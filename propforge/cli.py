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

    print(f"{len(jobs)} Asset(s) im Eingang:")
    for job in jobs:
        print(f"  {job.name:<28} {job.profile:<9} {job.material}")
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
        if info.center != (0.0, 0.0, 0.0) and not info.is_centered:
            job.center = "base"
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
    p.set_defaults(func=cmd_convert)

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
