"""Kommandozeile der Prop-Pipeline.

    propforge validate  pipeline.toml     Preflight ohne Blender
    propforge textures  pipeline.toml     PBR -> DDS
    propforge jobs      pipeline.toml     Job-JSON fuer die Blender-Stufe
    propforge build     pipeline.toml     Blender headless aufrufen
    propforge verify    pipeline.toml     Export gegen die Konfiguration pruefen
    propforge pack      pipeline.toml     FiveM-Resource bauen
    propforge run       pipeline.toml     alles nacheinander
    propforge ingest    modell.glb        GLB einlesen, Konfiguration erzeugen
    propforge materials [begriff]         Kollisionsmaterialien nachschlagen
    propforge generate  "ein Holztisch"   Mesh erzeugen lassen und einlesen

Lokale Routine ueber Ordner (kein Bearbeiten von Konfigurationsdateien):

    propforge init                        Arbeitsordner anlegen
    propforge batch                       mehrere Assets erfragen und erzeugen
    propforge convert                     alles im Eingang zu GTA-Dateien machen

Fuer ein Pack:

    propforge convert --ytd pack_props    Texturen in eine gemeinsame .ytd
    propforge merge-ytyp <ordner>         alle .ytyp zu einer zusammenfassen
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import collision_materials as pf_materials
from . import doctor as pf_doctor
from . import generate as pf_generate
from . import ingest as pf_ingest
from . import inspect as pf_inspect
from . import packaging, preview as pf_preview, textures, validate
from . import verify as pf_verify
from . import workspace as pf_workspace
from . import ytyp_merge as pf_ytyp_merge
from . import config as pf_config
from .config import PipelineConfig
from .validate import Level


def _load(path_or_config) -> PipelineConfig:
    """Laedt aus einer Datei - oder reicht eine fertige Konfiguration durch.

    Damit koennen die Stufen unveraendert auch auf einer Konfiguration
    arbeiten, die aus den Begleitdateien im Arbeitsordner entstanden ist,
    statt aus einer pipeline.toml.
    """
    if isinstance(path_or_config, PipelineConfig):
        return path_or_config
    return PipelineConfig.load(path_or_config)


def _report(findings: list[validate.Finding]) -> int:
    if not findings:
        print("Preflight: keine Befunde.")
        return 0
    order = {Level.ERROR: 0, Level.WARNING: 1, Level.INFO: 2}
    for f in sorted(findings, key=lambda f: (order[f.level], f.prop or "", f.code)):
        print(f)
    errors = sum(1 for f in findings if f.level is Level.ERROR)
    warnings = sum(1 for f in findings if f.level is Level.WARNING)
    print(f"\n{errors} Fehler, {warnings} Warnungen.")
    return 1 if errors else 0


def cmd_validate(args: argparse.Namespace) -> int:
    return _report(validate.validate(_load(args.config)))


def cmd_textures(args: argparse.Namespace) -> int:
    config = _load(args.config)

    # find_dds_converter statt find_texconv: letzteres kennt nur das
    # Windows-Werkzeug. Der Aufrufer hier war nach der Umstellung auf den
    # plattformunabhaengigen Konverter versehentlich stehen geblieben - der
    # Linux-Lauf hat deshalb weiter stumm keine DDS erzeugt.
    converter = textures.find_dds_converter(args.texconv)
    if converter is None:
        print(
            "Kein DDS-Konverter gefunden. Ohne DDS bleiben die Shader-Sampler leer "
            "und der Prop erscheint im Spiel ohne Textur.\n"
            "Installiere texconv (DirectXTex) oder ImageMagick.",
            file=sys.stderr,
        )
        return 1

    kind, exe = converter
    print(f"DDS-Konverter: {kind} ({exe})\n")

    total = 0
    for prop in config.props:
        work = config.workdir / "textures" / prop.name
        prepared = textures.prepare(prop, work)
        print(f"{prop.name}: {len(prepared)} Texturen aufbereitet -> {work}")
        for tex in prepared:
            print(f"    {tex.role:<9} {tex.dds_format:<11} {tex.path.name}")
        written = textures.compress(prepared, work, args.texconv)
        for path in written:
            print(f"    -> {path.name} ({path.stat().st_size} Bytes)")
        total += len(written)

    print(f"\n{total} DDS-Dateien geschrieben.")
    return 0


def cmd_jobs(args: argparse.Namespace) -> int:
    config = _load(args.config)
    jobs = [p.to_job(config.workdir) for p in config.props]
    out = config.workdir / "jobs.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
    print(f"{len(jobs)} Jobs -> {out}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    config = _load(args.config)
    findings = validate.validate(config)
    if validate.has_errors(findings):
        print("Build abgebrochen - Preflight meldet Fehler:\n")
        return _report(findings)

    cmd_jobs(args)
    jobs_file = config.workdir / "jobs.json"

    blender = args.blender or shutil.which("blender") or shutil.which("blender.exe")
    if blender is None:
        print("Blender nicht gefunden. Mit --blender <pfad> angeben.", file=sys.stderr)
        return 2

    script = Path(__file__).resolve().parent.parent / "blender" / "sz_build_prop.py"
    # Kein --factory-startup: das deaktiviert saemtliche Add-ons, also auch
    # Sollumz, und haengt dessen site-packages (szio, PyMateria) nicht ein.
    # Der Build wuerde dann mit "Sollumz nicht gefunden" scheitern, obwohl
    # alles korrekt installiert ist.
    result_file = config.workdir / "build_result.json"
    if result_file.exists():
        result_file.unlink()

    cmd = [
        blender, "--background",
        "--python", str(script), "--",
        "--job", str(jobs_file),
        "--format", config.export_format,
        "--version", config.export_version,
        "--result", str(result_file),
        "--render", str(config.workdir / "renders"),
    ]
    print("$ " + " ".join(cmd))
    returncode = subprocess.run(cmd).returncode

    # Auf den Exit-Code allein ist kein Verlass: Blender gibt ihn im
    # Hintergrundmodus nicht zuverlaessig weiter. Ein fehlgeschlagener Build
    # kam dadurch als Erfolg zurueck und die naechste Stufe arbeitete auf
    # Dateien, die es nie gab. Der Ergebnisbericht ist die belastbare Quelle.
    if not result_file.exists():
        print(
            f"\nBlender hat keinen Ergebnisbericht geschrieben ({result_file}).\n"
            "Das heisst, das Skript ist vor dem Ende abgebrochen - der Grund steht "
            "weiter oben in der Blender-Ausgabe.",
            file=sys.stderr,
        )
        return returncode or 1

    result = json.loads(result_file.read_text(encoding="utf-8"))
    failed = result.get("failed", [])
    succeeded = result.get("succeeded", [])

    print(f"\nGebaut: {len(succeeded)}/{result.get('total', 0)}")
    for entry in result.get("texture_dictionaries", []):
        files = ", ".join(f"{f['file']} ({f['bytes']} Bytes)" for f in entry.get("files", []))
        props = entry.get("props", [])
        print(f"  Texturwoerterbuch {entry['name']}: {files}")
        print(f"    {len(entry.get('textures', []))} Texturen fuer "
              f"{len(props)} Prop(s): {', '.join(props) or '-'}")
    for failure in failed:
        print(f"  FEHLGESCHLAGEN {failure['name']}: {failure['error']}", file=sys.stderr)

    if not failed:
        try:
            sheets = pf_preview.build_all(
                config.workdir / "renders", result, config.workdir / "previews"
            )
            for sheet in sheets:
                print(f"  Vorschau: {sheet}")
        except Exception as exc:  # noqa: BLE001 - eine fehlende Vorschau darf den Build nicht kippen
            print(f"  Vorschau konnte nicht erzeugt werden: {exc}", file=sys.stderr)

    return 1 if failed else returncode


def cmd_pack(args: argparse.Namespace) -> int:
    config = _load(args.config)
    report = packaging.build_resource(
        build_dir=config.workdir / "build",
        out_root=config.workdir / "resources",
        resource_name=config.resource_name,
        author=config.author,
        spawn_helper=config.spawn_helper,
        prop_names=[p.name for p in config.props],
    )
    print(report.summary())
    print(f"\nResource: {report.root}")
    if config.spawn_helper:
        print("Im Spiel testen: Resource starten, dann /pfspawn "
              f"{config.props[0].name if config.props else ''}".rstrip())
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    config = _load(args.config)
    build_dir = config.workdir / "build"

    drawables = pf_inspect.find_drawables(build_dir)
    if drawables:
        print(f"{len(drawables)} Drawable(s) in {build_dir}:\n")
        for path in drawables:
            print(pf_inspect.parse_drawable(path).summary())
            print()

    ytyps = pf_inspect.find_ytyps(build_dir)
    if ytyps:
        print(f"{len(ytyps)} Archetyp-Definition(en):\n")
        for path in ytyps:
            print(pf_inspect.parse_ytyp(path).summary())
            print()

    print("--- Abgleich mit der Konfiguration ---")
    return _report(pf_verify.verify(config, build_dir))


def choose_collision_material(name: str, source: Path, preset: str | None) -> str:
    """Ermittelt das Kollisionsmaterial fuer einen Import.

    Reihenfolge: ausdrueckliche Angabe schlaegt Abfrage schlaegt Vorschlag.
    Ohne Terminal (CI, Skript) wird nicht gefragt, sondern der Vorschlag
    genommen und ausdruecklich gemeldet - eine Abfrage, die niemand
    beantworten kann, blockiert sonst den Lauf.
    """
    if preset:
        material = preset.upper()
        if material not in pf_materials.BY_NAME:
            raise SystemExit(
                f"Kollisionsmaterial '{material}' gibt es nicht. "
                "Liste: python -m propforge.cli materials")
        return material

    suggestion, keyword = pf_materials.suggest(name, source.stem)
    why = f" (wegen '{keyword}' im Namen)" if keyword else " (kein Hinweis im Namen)"

    if not sys.stdin.isatty():
        print(f"Kollisionsmaterial: {suggestion}{why} - nicht nachgefragt, "
              "kein Terminal. Mit --material anders setzen.")
        return suggestion

    print("\nKollisionsmaterial: bestimmt Schrittgeraeusche, Einschlaege und")
    print("Bruchverhalten. Alle Materialien: docs/kollisionsmaterialien.txt")
    print(f"Vorschlag: {suggestion}{why}")
    print("  [Enter] uebernehmen | <NAME> setzen | ? suchen")

    while True:
        answer = input("Material> ").strip()
        if not answer:
            return suggestion
        if answer.startswith("?"):
            term = answer.lstrip("? ").strip()
            hits = pf_materials.search(term) if term else list(pf_materials.MATERIALS)
            for m in hits[:25]:
                print(f"  {m.name:<28} {m.usage}")
            if len(hits) > 25:
                print(f"  ... und {len(hits) - 25} weitere")
            continue
        candidate = answer.upper()
        if candidate in pf_materials.BY_NAME:
            return candidate
        print(f"  '{candidate}' gibt es nicht. Mit '?{answer}' suchen.")


def cmd_materials(args: argparse.Namespace) -> int:
    """Listet die Kollisionsmaterialien oder schreibt sie als Textdatei."""
    if args.write:
        target = Path(args.write)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(pf_materials.render_reference(), encoding="utf-8")
        print(f"{len(pf_materials.MATERIALS)} Materialien -> {target}")
        return 0

    if args.suggest:
        material, keyword = pf_materials.suggest(args.suggest)
        why = f"wegen '{keyword}'" if keyword else "kein Hinweis im Namen, Standard"
        print(f"{material}  ({why})")
        return 0

    hits = pf_materials.search(args.search) if args.search else list(pf_materials.MATERIALS)
    if not hits:
        print(f"Nichts gefunden fuer '{args.search}'.")
        return 1
    category = None
    for m in hits:
        if m.category != category:
            category = m.category
            print(f"\n{category}")
        print(f"  {m.name:<28} {m.usage}")
    print(f"\n{len(hits)} von {len(pf_materials.MATERIALS)} Materialien.")
    return 0


# --- Lokale Routine ---------------------------------------------------------

def _ask(prompt: str, default: str | None = None) -> str:
    hint = f" [{default}]" if default else ""
    answer = input(f"{prompt}{hint}> ").strip()
    return answer or (default or "")


def _ask_profile(default: str) -> str:
    while True:
        answer = _ask("  Kategorie (" + " | ".join(pf_config.PROFILES) + ")", default).lower()
        if answer in pf_config.PROFILES:
            return answer
        print(f"  '{answer}' gibt es nicht.")


def _ask_material(name: str) -> str:
    suggestion, keyword = pf_materials.suggest(name)
    why = f", wegen '{keyword}'" if keyword else ""
    while True:
        answer = _ask(f"  Kollisionsmaterial ('?' sucht{why})", suggestion)
        if answer.startswith("?"):
            for m in pf_materials.search(answer.lstrip("? ").strip())[:20]:
                print(f"    {m.name:<28} {m.usage}")
            continue
        if answer.upper() in pf_materials.BY_NAME:
            return answer.upper()
        print(f"  '{answer}' gibt es nicht - mit '?{answer}' suchen.")


def _ask_ytd(name: str, default: str | None = None) -> str | None:
    """Eingebettete Texturen oder eine gemeinsame .ytd?

    Der Vorschlag ist bewusst 'eingebettet': fuer einen einzelnen Prop ist das
    die robustere Wahl - eine Datei, nichts kann getrennt voneinander verloren
    gehen. Lohnend wird die .ytd erst, wenn sich mehrere Props Texturen
    teilen; dann laedt das Spiel sie einmal statt pro Prop.
    """
    while True:
        answer = _ask(
            "  Texturen (e = eingebettet in die .ydr | Name = gemeinsame .ytd)",
            default or "e",
        )
        if answer.lower() in {"e", "eingebettet", "embedded"}:
            return None
        ytd = pf_config.normalize_ytd_name(answer)
        if not ytd:
            continue
        if ytd == name.lower():
            # Gleicher Name fuer Drawable und Woerterbuch geht technisch, aber
            # beide landen als '<name>.ydr' und '<name>.ytd' in stream/ und
            # sind dort nicht mehr auseinanderzuhalten, wenn etwas fehlt.
            print(f"  '{ytd}' ist schon der Propname - besser etwas wie "
                  f"'{ytd}_txd' oder ein Packname.")
            continue
        return ytd


def _collect_ytyps(source: Path) -> list[Path]:
    """Die .ytyp-Dateien hinter dem Argument - Ordner oder Einzeldatei."""
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise FileNotFoundError(f"'{source}' gibt es nicht.")
    return sorted(
        p for p in source.iterdir()
        if p.is_file() and (p.name.lower().endswith(".ytyp.xml")
                            or p.suffix.lower() == ".ytyp")
    )


def cmd_merge_ytyp(args: argparse.Namespace) -> int:
    """Fasst alle .ytyp eines Ordners zu einer zusammen.

    Fuer ein Pack ist eine Datei besser als sechzig: eine Zeile im Manifest
    statt sechzig, und keine Gelegenheit, eine davon zu vergessen.
    """
    source = Path(args.source)
    try:
        paths = _collect_ytyps(source)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not paths:
        print(f"Keine .ytyp in {source} gefunden.", file=sys.stderr)
        return 2

    name = pf_config.normalize_ytd_name(
        args.name or (source.stem if source.is_file() else source.name))
    out_dir = Path(args.out) if args.out else (
        source.parent if source.is_file() else source) / "merged"

    # Ein frueheres Ergebnis nicht wieder mit einsammeln. Bei der Vorgabe
    # (Unterordner 'merged') kann das nicht passieren, mit --out schon - und
    # zweimal laufen lassen ist genau das, was man tut, wenn ein Prop
    # dazugekommen ist.
    own = {(out_dir / f"{name}.ytyp.xml").resolve(), (out_dir / f"{name}.ytyp").resolve()}
    paths = [p for p in paths if p.resolve() not in own]
    if not paths:
        print(f"In {source} liegt nur das Ergebnis eines frueheren Laufs.",
              file=sys.stderr)
        return 2

    binary = [p for p in paths if not p.name.lower().endswith(".ytyp.xml")]
    print(f"{len(paths)} Datei(en) in {source}:")
    for path in paths:
        print(f"  {path.name}")
    print()

    # Der kurze Weg, wenn es ihn gibt: reines XML braucht kein Blender. Der
    # Unterschied ist keine Kosmetik - ohne Blender laeuft das hier in
    # Millisekunden und ist hier im Projekt vollstaendig getestet, waehrend
    # der Binaerweg auf szio in Blenders Python angewiesen ist.
    if not binary and args.format == "CWXML":
        out_path = out_dir / f"{name}.ytyp.xml"
        try:
            if args.dry_run:
                plan = pf_ytyp_merge.plan_merge(paths, name)
            else:
                plan = pf_ytyp_merge.merge(paths, name, out_path)
        except pf_ytyp_merge.MergeError as exc:
            print(f"Abgebrochen: {exc}", file=sys.stderr)
            return 1

        for archetype in plan.archetype_names:
            print(f"  + {archetype}")
        for duplicate in plan.duplicates:
            print(f"  = {duplicate} (identisch, einmal uebernommen)")
        for path, why in plan.skipped:
            print(f"  - {path.name}: {why}")
        if args.dry_run:
            print(f"\n{len(plan.entries)} Archetypen kaemen in '{name}.ytyp.xml'.")
            return 0
        print(f"\n{len(plan.entries)} Archetypen -> {out_path} "
              f"({out_path.stat().st_size} Bytes)")
        _print_manifest_hint(name, len(paths))
        return 0

    if args.dry_run:
        print("--dry-run gibt es nur fuer CWXML: eine binaere .ytyp laesst "
              "sich nur in Blender lesen, und dann ist das Zusammenfassen "
              "auch schon fast erledigt.", file=sys.stderr)
        return 2

    blender = args.blender or shutil.which("blender") or shutil.which("blender.exe")
    if blender is None:
        kind = "binaere .ytyp" if binary else f"Format {args.format}"
        print(f"Fuer {kind} wird Blender gebraucht (dort steckt szio). "
              "Mit --blender <pfad> angeben.", file=sys.stderr)
        return 2

    script = Path(__file__).resolve().parent.parent / "blender" / "sz_merge_ytyp.py"
    result_file = out_dir / "merge_result.json"
    if result_file.exists():
        result_file.unlink()

    cmd = [
        blender, "--background", "--python", str(script), "--",
        "--input", *[str(p) for p in paths],
        "--name", name,
        "--out", str(out_dir),
        "--format", args.format,
        "--version", args.version,
        "--result", str(result_file),
    ]
    print("$ " + " ".join(cmd))
    returncode = subprocess.run(cmd).returncode

    # Wie beim Build: der Exit-Code von Blender im Hintergrundmodus ist keine
    # verlaessliche Quelle. Der Bericht ist es.
    if not result_file.exists():
        print("\nBlender hat keinen Ergebnisbericht geschrieben - der Grund "
              "steht weiter oben in der Ausgabe.", file=sys.stderr)
        return returncode or 1

    report = json.loads(result_file.read_text(encoding="utf-8"))
    for archetype in report.get("archetypes", []):
        print(f"  + {archetype}")
    files = ", ".join(f"{f['file']} ({f['bytes']} Bytes)" for f in report.get("files", []))
    print(f"\n{len(report.get('archetypes', []))} Archetypen -> {files}")
    _print_manifest_hint(name, len(paths))
    return 0


def _print_manifest_hint(name: str, replaced: int) -> None:
    """Sagt, was jetzt noch im fxmanifest zu tun ist.

    Ohne diesen Hinweis waere die Zusammenfassung eine Falle: die alten .ytyp
    stehen weiter im Manifest, die neue nicht. Das Spiel laedt dann entweder
    beides (und meldet doppelte Archetypen) oder die Sammel-ytyp gar nicht -
    und der Prop erscheint einfach nicht.
    """
    print(f"\nIm fxmanifest.lua die {replaced} bisherigen Zeilen ersetzen durch:")
    print(f"    data_file 'DLC_ITYP_REQUEST' 'stream/{name}.ytyp'")
    print("Und die alten .ytyp aus stream/ entfernen - sonst laedt das Spiel "
          "dieselben Archetypen zweimal.")


def cmd_init(args: argparse.Namespace) -> int:
    """Legt die Arbeitsordner und die Vorlage an."""
    workspace = pf_workspace.Workspace.load(args.root)
    workspace.ensure()

    config = workspace.root / pf_workspace.WORKSPACE_FILE
    if config.exists():
        print(f"{config.name} existiert bereits - unveraendert gelassen.")
    else:
        config.write_text(workspace.render_config(), encoding="utf-8")
        print(f"Vorlage geschrieben: {config}")

    print(f"\n  Eingang  {workspace.inbox}")
    print(f"  Fertig   {workspace.done}")
    print(f"  Ausgabe  {workspace.out}")
    print("\nGLBs in den Eingang legen oder mit 'propforge batch' erzeugen,")
    print("dann 'propforge convert'.")
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    """Fragt mehrere Assets ab und erzeugt sie in einem Rutsch."""
    workspace = pf_workspace.Workspace.load(args.root)
    workspace.ensure()

    token = pf_generate.find_token(args.api_key)
    if not token:
        print("Kein API-Schluessel - siehe 'propforge generate --help'.", file=sys.stderr)
        return 2

    print("Was soll erzeugt werden? Leere Zeile beendet die Eingabe.\n")
    wishes: list[tuple[str, str, str]] = []
    while True:
        prompt = _ask(f"Asset {len(wishes) + 1}")
        if not prompt:
            break
        name = "pf_" + "".join(
            c for c in "_".join(prompt.lower().split()[:3]) if c.isalnum() or c == "_")
        profile = _ask_profile(args.profile or pf_config.DEFAULT_PROFILE)
        material = _ask_material(name)
        wishes.append((prompt, profile, material))
        print()

    if not wishes:
        print("Nichts angefordert.")
        return 0

    print(f"\n{len(wishes)} Asset(s) werden erzeugt. Abbruch mit Strg+C.\n")
    provider = pf_generate.TripoProvider(token=token)
    failed = 0

    for index, (prompt, profile_name, material) in enumerate(wishes, 1):
        profile = pf_config.PROFILES[profile_name]
        name = "pf_" + "".join(
            c for c in "_".join(prompt.lower().split()[:3]) if c.isalnum() or c == "_")
        target = workspace.inbox / f"{name}.glb"
        if target.exists():
            target = pf_workspace._free_name(target)

        print(f"[{index}/{len(wishes)}] {name}  ({profile_name}, {material})")
        request = pf_generate.GenerationRequest(
            prompt=prompt, name=name, face_limit=profile.max_tris,
            model_version=args.model)
        try:
            provider.run(
                request, target,
                on_progress=lambda s: print(f"      {s.status:<10} {s.progress:3d} %"),
                timeout=args.timeout,
            )
        except pf_generate.GenerationError as exc:
            print(f"      fehlgeschlagen: {exc}", file=sys.stderr)
            failed += 1
            continue

        pf_workspace.Job(
            name=target.stem, mesh=target, profile=profile_name,
            material=material, prompt=prompt,
            model=args.model or pf_generate.DEFAULT_MODEL,
        ).write()
        print(f"      -> {target.name} ({target.stat().st_size / 1024:.0f} KiB)")

    done = len(wishes) - failed
    print(f"\n{done}/{len(wishes)} erzeugt -> {workspace.inbox}")
    if done:
        print("Weiter mit: propforge convert")
    return 1 if failed else 0


def _guess_profile(mesh: Path) -> str:
    """Groessenklasse aus der Dreieckszahl schaetzen, wenn moeglich."""
    try:
        info, _, _ = pf_ingest.inspect(mesh, mesh.stem)
        return pf_ingest.suggest_profile(info.triangles)
    except Exception:  # noqa: BLE001 - ein unlesbares Mesh faellt spaeter auf
        return pf_config.DEFAULT_PROFILE


def cmd_convert(args: argparse.Namespace) -> int:
    """Wandelt alles im Eingang in GTA-Dateien um."""
    workspace = pf_workspace.Workspace.load(args.root)
    workspace.ensure()

    jobs = workspace.jobs()
    if not jobs:
        print(f"Der Eingang ist leer: {workspace.inbox}\n"
              "GLBs dorthin kopieren oder mit 'propforge batch' erzeugen.")
        return 0

    blender = args.blender or workspace.blender
    if not blender:
        print("Blender nicht gesetzt. Entweder --blender angeben oder in der "
              f"{pf_workspace.WORKSPACE_FILE} eintragen.", file=sys.stderr)
        return 2

    # Fehlende Angaben erfragen - aber nur, wenn jemand da ist, der
    # antworten kann. Im Skriptbetrieb wird geschaetzt und das ausdruecklich
    # gesagt, statt auf eine Eingabe zu warten, die nie kommt.
    interactive = sys.stdin.isatty() and not args.no_ask

    # Eine Vorgabe fuer den ganzen Lauf schlaegt die Nachfrage. Fuer ein Pack
    # ist das der eigentliche Fall: zehn GLBs in den Eingang, ein '--ytd
    # pack_name', fertig - statt zehnmal dieselbe Antwort zu tippen.
    forced_ytd: str | None = pf_config.normalize_ytd_name(getattr(args, "ytd", None))
    forced_embed = bool(getattr(args, "embed", False))
    if forced_ytd and forced_embed:
        print("--ytd und --embed schliessen sich aus.", file=sys.stderr)
        return 2

    # Beim Nachfragen die letzte Antwort als Vorschlag weiterreichen: wer
    # gerade ein Pack einliest, meint beim zweiten Prop fast immer dasselbe
    # Woerterbuch wie beim ersten.
    last_ytd: str | None = None
    for job in jobs:
        if pf_workspace.sidecar_for(job.mesh).is_file():
            continue

        guess = _guess_profile(job.mesh)
        material, keyword = pf_materials.suggest(job.name)
        if forced_ytd or forced_embed:
            job.ytd = forced_ytd
        if not interactive:
            job.profile, job.material = guess, material
            print(f"  {job.name}: keine Begleitdatei - geschaetzt: "
                  f"{guess} / {material}")
        else:
            print(f"\n{job.name} hat keine Begleitdatei:")
            job.profile = _ask_profile(guess)
            job.material = _ask_material(job.name)
            if not (forced_ytd or forced_embed):
                job.ytd = _ask_ytd(job.name, last_ytd)
                last_ytd = job.ytd
        job.write()

    print(f"\n{len(jobs)} Asset(s) im Eingang:")
    for job in jobs:
        print(f"  {job.name:<28} {job.profile:<9} {job.material:<22} "
              f"{'ytd:' + job.ytd if job.ytd else 'Texturen eingebettet'}")
    print()

    # Texturen aus den Meshes holen und die Begleitdaten vervollstaendigen.
    prepared: list[pf_workspace.Job] = []
    for job in jobs:
        if job.textures:
            prepared.append(job)
            continue
        try:
            info, _, _ = pf_ingest.inspect(job.mesh, job.name)
            gltf, binary = pf_ingest.read_glb(job.mesh)
            written = pf_ingest.extract_textures(gltf, binary, workspace.inbox, job.name)
        except Exception as exc:  # noqa: BLE001 - ein kaputtes Mesh darf den Stapel nicht stoppen
            print(f"  {job.name}: Texturen nicht lesbar ({exc})", file=sys.stderr)
            prepared.append(job)
            continue

        job.textures = {role: str(path) for role, path in written.items()}
        # Die Bounding-Box-Mitte ist NICHT der gewollte Ursprung. Ein Tisch
        # mit Ursprung auf der Standflaeche hat seine Box-Mitte auf halber
        # Hoehe - voellig korrekt. Die frueher hier stehende Zuweisung
        # ueberschrieb damit eine ausdrueckliche Wahl aus der Begleitdatei
        # ('none', 'xy', 'all') stillschweigend mit 'base'.
        job.write()
        prepared.append(job)

    config = _load(workspace.to_config(prepared, export_format=args.format))

    stage_args = argparse.Namespace(config=config, blender=blender, texconv=args.texconv)
    for step in (cmd_validate, cmd_textures, cmd_build, cmd_verify, cmd_pack):
        code = step(stage_args)
        if code:
            print("\nAbgebrochen - die Assets bleiben im Eingang liegen.", file=sys.stderr)
            return code

    # Erst jetzt archivieren: was nicht gebaut wurde, soll beim naechsten
    # Lauf wieder drankommen und nicht im Archiv verschwinden.
    for job in prepared:
        workspace.archive(job)

    print(f"\n{len(prepared)} Asset(s) fertig -> {workspace.out}")
    print(f"Verarbeitete Meshes liegen jetzt in {workspace.done}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """Laesst ein Mesh erzeugen und reicht es direkt an ingest weiter."""
    name = args.name or "pf_" + "_".join(args.prompt.lower().split()[:3])
    name = "".join(c for c in name if c.isalnum() or c == "_")

    # Budget schon beim Generator setzen statt hinterher wegzuschneiden.
    # Der Generator kennt die Form und weiss besser, wo Kanten entbehrlich
    # sind, als ein blinder Reduktionsalgorithmus.
    profile = pf_config.PROFILES.get(args.profile)
    if profile is None:
        print(f"Unbekanntes Profil '{args.profile}'. Moeglich: "
              + ", ".join(pf_config.PROFILES), file=sys.stderr)
        return 2
    face_limit = args.face_limit if args.face_limit is not None else profile.max_tris
    max_texture = args.max_texture if args.max_texture is not None else profile.texture_size

    print(f"Profil '{profile.name}': bis {profile.max_tris} Dreiecke, "
          f"{profile.texture_size} px Textur - {profile.usage}")

    request = pf_generate.GenerationRequest(
        prompt=args.prompt,
        name=name,
        face_limit=face_limit,
        pbr=not args.no_pbr,
        model_version=args.model,
    )

    if args.dry_run:
        print(pf_generate.describe_request(request))
        return 0

    token = pf_generate.find_token(args.api_key)
    if not token:
        print(
            "Kein API-Schluessel gefunden. Drei Wege, einer reicht:\n"
            "\n"
            "  1. Datei '.env' im Repo-Ordner anlegen, eine Zeile:\n"
            "       TRIPO_API_KEY=tsk_...\n"
            "     (steht in der .gitignore - landet also nicht im oeffentlichen Repo)\n"
            "  2. Dauerhaft in Windows setzen, danach ein NEUES Terminal oeffnen:\n"
            "       setx TRIPO_API_KEY \"tsk_...\"\n"
            "  3. Nur fuer diesen Aufruf:  --api-key tsk_...\n"
            "\n"
            "Schluessel: https://platform.tripo3d.ai - Pay-as-you-go, kein Abo.\n"
            "Ohne Schluessel zeigt --dry-run, was abgeschickt wuerde.",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out)
    target = out_dir / f"{name}_raw.glb"
    provider = pf_generate.TripoProvider(token=token)

    def progress(state: pf_generate.TaskState) -> None:
        print(f"  {state.status:<10} {state.progress:3d} %")

    print(f"Erzeuge '{args.prompt}' als {name} ...")
    try:
        provider.run(request, target, on_progress=progress, timeout=args.timeout)
    except pf_generate.GenerationError as exc:
        print(f"\nGenerierung fehlgeschlagen: {exc}", file=sys.stderr)
        return 1

    print(f"Mesh: {target} ({target.stat().st_size / 1024:.0f} KiB)\n")

    # Direkt weiter durch die vorhandene Eingangsstufe - der Generator liefert
    # dasselbe Format, das die Pipeline ohnehin erwartet.
    ingest_args = argparse.Namespace(
        source=str(target), out=args.out, name=name,
        # Das Profil muss mit: sonst schaetzt ingest die Groessenklasse neu
        # aus der Dreieckszahl und ueberschreibt die ausdrueckliche Wahl.
        # Wer 'clutter' verlangt hat, bekam so 'standard' in die Konfiguration.
        profile=profile.name,
        max_texture=max_texture, material=args.material,
    )
    return cmd_ingest(ingest_args)


def cmd_ingest(args: argparse.Namespace) -> int:
    """Bereitet ein GLB fuer die Pipeline auf."""
    source = Path(args.source)
    out_dir = Path(args.out)
    name = args.name or source.stem.lower().replace("-", "_").replace(" ", "_")

    info, _, _ = pf_ingest.inspect(source, name)
    gltf, binary = pf_ingest.read_glb(source)
    written = pf_ingest.extract_textures(gltf, binary, out_dir, name)

    # Texturgrenze aus dem Profil. Ohne Angabe wird die Groessenklasse aus
    # der Dreieckszahl geschaetzt - dasselbe, was auch im erzeugten
    # Konfigurationsblock steht.
    profile_name = getattr(args, "profile", None) or pf_ingest.suggest_profile(info.triangles)
    profile = pf_config.PROFILES.get(profile_name, pf_config.PROFILES[pf_config.DEFAULT_PROFILE])
    limit = getattr(args, "max_texture", None) or profile.texture_size
    print(f"Profil '{profile.name}' ({info.triangles} Dreiecke): "
          f"Texturen auf {limit} px begrenzt.")
    args.max_texture = limit

    if args.max_texture:
        from PIL import Image

        for path in written.values():
            with Image.open(path) as img:
                if max(img.size) > args.max_texture:
                    ratio = args.max_texture / max(img.size)
                    resized = img.resize(
                        (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                        Image.LANCZOS,
                    )
                    resized.save(path)

    info.textures = {role: str(path) for role, path in written.items()}
    print(info.summary())

    # Geometrie ohne die eingebetteten Texturen ablegen: die liegen jetzt
    # als PNG daneben, und die Pipeline baut ihr eigenes Material daraus.
    mesh_target = out_dir / f"{name}.glb"
    pf_ingest.write_slim_glb(gltf, binary, mesh_target)
    before = source.stat().st_size / 1024 / 1024
    after = mesh_target.stat().st_size / 1024 / 1024
    print(f"\nGeometrie: {before:.1f} MB -> {after:.1f} MB (Texturen ausgelagert)")

    material = choose_collision_material(name, source, args.material)
    snippet = pf_ingest.config_snippet(info, mesh_target, out_dir, material, profile.name)
    snippet_path = out_dir.parent / f"{name}.toml"
    snippet_path.write_text(snippet, encoding="utf-8")

    print(f"\nKonfigurationsblock -> {snippet_path}\n")
    print(snippet)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = pf_doctor.run(blender=args.blender, texconv=args.texconv)
    text, ok = pf_doctor.summarize(checks)
    print(text)
    return 0 if ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    for step in (cmd_validate, cmd_textures, cmd_build, cmd_verify, cmd_pack):
        code = step(args)
        if code:
            return code
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="propforge", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, fn, helptext in [
        ("validate", cmd_validate, "Preflight-Checks ohne Blender"),
        ("textures", cmd_textures, "PBR-Texturen zu DDS aufbereiten"),
        ("jobs", cmd_jobs, "Job-JSON fuer die Blender-Stufe schreiben"),
        ("build", cmd_build, "Blender headless aufrufen"),
        ("verify", cmd_verify, "Exportierte Assets gegen die Konfiguration pruefen"),
        ("pack", cmd_pack, "FiveM-Resource buendeln"),
        ("run", cmd_run, "Alle Stufen nacheinander"),
    ]:
        p = sub.add_parser(name, help=helptext)
        p.add_argument("config", help="Pfad zur pipeline.toml")
        p.add_argument("--blender", help="Pfad zur Blender-Binary")
        p.add_argument("--texconv", help="Pfad zu texconv.exe")
        p.set_defaults(func=fn)

    # ingest arbeitet auf einer Quelldatei, nicht auf einer Konfiguration.
    p = sub.add_parser("ingest", help="Fertiges GLB einlesen (ohne Generator)")
    p.add_argument("source", help="Pfad zur .glb-Datei")
    p.add_argument("--out", default="assets", help="Zielverzeichnis")
    p.add_argument("--name", help="Prop-Name (Standard: Dateiname)")
    p.add_argument("--profile", default=None,
                   help="Groessenklasse fuer die Texturgrenze: "
                        + ", ".join(pf_config.PROFILES) + " (Standard: aus der Dreieckszahl)")
    p.add_argument("--max-texture", type=int,
                   help="Texturen begrenzen (Standard: aus dem Profil)")
    p.add_argument("--material", help="Kollisionsmaterial; ohne Angabe wird gefragt")
    p.set_defaults(func=cmd_ingest)

    # generate haengt vor ingest: Prompt rein, fertiger Konfigurationsblock raus.
    p = sub.add_parser("generate", help="Mesh erzeugen lassen und einlesen")
    p.add_argument("prompt", help="Beschreibung des gewuenschten Objekts")
    p.add_argument("--name", help="Prop-Name (Standard: aus dem Prompt)")
    p.add_argument("--out", default="assets", help="Zielverzeichnis")
    p.add_argument("--profile", default=pf_config.DEFAULT_PROFILE,
                   help="Groessenklasse: " + ", ".join(pf_config.PROFILES))
    p.add_argument("--face-limit", type=int,
                   help="Dreiecksobergrenze (Standard: aus dem Profil)")
    p.add_argument("--no-pbr", action="store_true", help="ohne PBR-Texturen erzeugen")
    p.add_argument("--model", default=None,
                   help=f"Modellversion (Standard: {pf_generate.DEFAULT_MODEL}; "
                        f"{pf_generate.BETTER_MODEL} = bessere Texturen, teurer)")
    p.add_argument("--api-key", help="Statt der Umgebungsvariablen TRIPO_API_KEY")
    p.add_argument("--timeout", type=float, default=900.0, help="Wartezeit in Sekunden")
    p.add_argument("--max-texture", type=int,
                   help="Texturen begrenzen (Standard: aus dem Profil)")
    p.add_argument("--material", help="Kollisionsmaterial; ohne Angabe wird gefragt")
    p.add_argument("--dry-run", action="store_true",
                   help="nur zeigen, was abgeschickt wuerde")
    p.set_defaults(func=cmd_generate)

    # Lokale Routine: init / batch / convert.
    p = sub.add_parser("init", help="Arbeitsordner anlegen")
    p.add_argument("--root", default=".", help="Wurzel des Arbeitsordners")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("batch", help="Mehrere Assets erfragen und erzeugen")
    p.add_argument("--root", default=".", help="Wurzel des Arbeitsordners")
    p.add_argument("--profile", help="Vorgabe fuer die Kategorie-Abfrage")
    p.add_argument("--model", help=f"Modellversion (Standard: {pf_generate.DEFAULT_MODEL})")
    p.add_argument("--api-key", help="Statt der Umgebungsvariablen TRIPO_API_KEY")
    p.add_argument("--timeout", type=float, default=900.0, help="Wartezeit je Asset")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("convert", help="Alles im Eingang zu GTA-Dateien machen")
    p.add_argument("--root", default=".", help="Wurzel des Arbeitsordners")
    p.add_argument("--blender", help="Pfad zur Blender-Binary")
    p.add_argument("--texconv", help="Pfad zu texconv.exe")
    p.add_argument("--format", default="NATIVE", choices=["NATIVE", "CWXML"])
    p.add_argument("--no-ask", action="store_true",
                   help="nicht nachfragen, fehlende Angaben schaetzen")
    p.add_argument("--ytd", metavar="NAME",
                   help="Texturen in eine gemeinsame .ytd dieses Namens "
                        "statt in die .ydr (fuer den ganzen Lauf)")
    p.add_argument("--embed", action="store_true",
                   help="Texturen einbetten, ohne zu fragen")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("merge-ytyp", help="Mehrere .ytyp zu einer zusammenfassen")
    p.add_argument("source", help="Ordner mit .ytyp-Dateien (oder eine einzelne Datei)")
    p.add_argument("--name", help="Name der Sammel-ytyp (Vorgabe: Ordnername)")
    p.add_argument("--out", help="Zielordner (Vorgabe: neben den Quellen)")
    p.add_argument("--blender", help="Pfad zur Blender-Binary (fuer binaere .ytyp)")
    p.add_argument("--format", default="NATIVE", choices=["NATIVE", "CWXML"])
    p.add_argument("--version", default="GEN8", choices=["GEN8", "GEN9"])
    p.add_argument("--dry-run", action="store_true",
                   help="nur zeigen, was zusammengefasst wuerde")
    p.set_defaults(func=cmd_merge_ytyp)

    # materials braucht weder Konfiguration noch Quelldatei.
    p = sub.add_parser("materials", help="Kollisionsmaterialien nachschlagen")
    p.add_argument("search", nargs="?", help="Suchbegriff (Name, Kategorie, Beschreibung)")
    p.add_argument("--suggest", help="Material zu einem Prop-Namen vorschlagen")
    p.add_argument("--write", help="Liste als Textdatei schreiben")
    p.set_defaults(func=cmd_materials)

    # doctor braucht keine Konfiguration - es prueft nur die Umgebung.
    p = sub.add_parser("doctor", help="Umgebung pruefen (Blender, Sollumz, szio, texconv)")
    p.add_argument("--blender", help="Pfad zur Blender-Binary")
    p.add_argument("--texconv", help="Pfad zu texconv.exe")
    p.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
