"""Kommandozeile der Prop-Pipeline.

    propforge validate  pipeline.toml     Preflight ohne Blender
    propforge textures  pipeline.toml     PBR -> DDS
    propforge jobs      pipeline.toml     Job-JSON fuer die Blender-Stufe
    propforge build     pipeline.toml     Blender headless aufrufen
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
from . import inspect as pf_inspect
from . import packaging, textures, validate
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
    exe = args.texconv or textures.find_texconv()
    total = 0
    for prop in config.props:
        work = config.workdir / "textures" / prop.name
        prepared = textures.prepare(prop, work)
        print(f"{prop.name}: {len(prepared)} Texturen aufbereitet -> {work}")
        for tex in prepared:
            print(f"    {tex.role:<9} {tex.dds_format:<11} {tex.path.name}")
        if exe:
            written = textures.compress(prepared, work, exe)
            total += len(written)
        else:
            print("    (texconv fehlt - DDS-Schritt uebersprungen)")
    if total:
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
    cmd = [
        blender, "--background",
        "--python", str(script), "--",
        "--job", str(jobs_file),
        "--format", config.export_format,
        "--version", config.export_version,
    ]
    print("$ " + " ".join(cmd))
    return subprocess.run(cmd).returncode


def cmd_pack(args: argparse.Namespace) -> int:
    config = _load(args.config)
    report = packaging.build_resource(
        build_dir=config.workdir / "build",
        out_root=config.workdir / "resources",
        resource_name=config.resource_name,
        author=config.author,
    )
    print(report.summary())
    print(f"\nResource: {report.root}")
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

    print("--- Abgleich mit der Konfiguration ---")
    return _report(pf_verify.verify(config, build_dir))


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

    # doctor braucht keine Konfiguration - es prueft nur die Umgebung.
    p = sub.add_parser("doctor", help="Umgebung pruefen (Blender, Sollumz, szio, texconv)")
    p.add_argument("--blender", help="Pfad zur Blender-Binary")
    p.add_argument("--texconv", help="Pfad zu texconv.exe")
    p.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
