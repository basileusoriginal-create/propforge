"""Kommandozeile der Prop-Pipeline.

    propforge validate  pipeline.toml     Preflight ohne Blender
    propforge textures  pipeline.toml     PBR -> DDS
    propforge jobs      pipeline.toml     Job-JSON fuer die Blender-Stufe
    propforge build     pipeline.toml     Blender headless aufrufen
    propforge verify    pipeline.toml     Export gegen die Konfiguration pruefen
    propforge pack      pipeline.toml     FiveM-Resource bauen
    propforge run       pipeline.toml     alles nacheinander
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import doctor as pf_doctor
from . import ingest as pf_ingest
from . import inspect as pf_inspect
from . import packaging, preview as pf_preview, textures, validate
from . import verify as pf_verify
from .config import PipelineConfig
from .validate import Level


def _load(path: str) -> PipelineConfig:
    return PipelineConfig.load(path)


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


def cmd_ingest(args: argparse.Namespace) -> int:
    """Bereitet ein GLB fuer die Pipeline auf."""
    source = Path(args.source)
    out_dir = Path(args.out)
    name = args.name or source.stem.lower().replace("-", "_").replace(" ", "_")

    info, _, _ = pf_ingest.inspect(source, name)
    gltf, binary = pf_ingest.read_glb(source)
    written = pf_ingest.extract_textures(gltf, binary, out_dir, name)

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

    snippet = pf_ingest.config_snippet(info, mesh_target, out_dir)
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
    p = sub.add_parser("ingest", help="GLB einlesen: Texturen entpacken, Konfiguration erzeugen")
    p.add_argument("source", help="Pfad zur .glb-Datei")
    p.add_argument("--out", default="assets", help="Zielverzeichnis")
    p.add_argument("--name", help="Prop-Name (Standard: Dateiname)")
    p.add_argument("--max-texture", type=int, default=2048,
                   help="Texturen auf diese Kantenlaenge begrenzen")
    p.set_defaults(func=cmd_ingest)

    # doctor braucht keine Konfiguration - es prueft nur die Umgebung.
    p = sub.add_parser("doctor", help="Umgebung pruefen (Blender, Sollumz, szio, texconv)")
    p.add_argument("--blender", help="Pfad zur Blender-Binary")
    p.add_argument("--texconv", help="Pfad zu texconv.exe")
    p.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
