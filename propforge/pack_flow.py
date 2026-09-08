"""Complete packs through the existing YTYP merger, verifier and packager."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from . import packaging, placement
from .native_verify import files_in


def _reset_child(parent: Path, name: str) -> Path:
    path = parent / name
    if path.resolve().parent != parent.resolve() or path.is_symlink():
        raise ValueError(f"Unsicherer Pack-Arbeitsordner: {path}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def assemble(config, blender, merge_command):
    if config.export_format != "NATIVE" or config.export_version != "GEN8":
        raise ValueError("Der vollstaendige Pack-Vertrag unterstuetzt NATIVE/GEN8.")
    build = config.workdir / "build"
    source = _reset_child(config.workdir, "pack_inputs")
    ytyps = files_in(build, ".ytyp")
    if not ytyps:
        raise ValueError("Keine Archetypen fuer das Pack vorhanden.")
    for path in ytyps:
        target = source / path.name
        if target.exists():
            raise ValueError(f"YTYP-Dateiname doppelt: {path.name}")
        shutil.copy2(path, target)
    merged = config.workdir / "merged"
    code = merge_command(argparse.Namespace(source=str(source), name=config.resource_name,
                         out=str(merged), blender=blender, format="NATIVE", version="GEN8",
                         dry_run=False, quiet=True))
    if code:
        raise RuntimeError("Sammel-YTYP konnte nicht geprueft erstellt werden.")
    staging = _reset_child(config.workdir, "pack_content")
    sources = files_in(build, ".ydr") + files_in(build, ".ytd") + [merged / (config.resource_name + ".ytyp")]
    names = []
    for path in sources:
        target = staging / path.name
        if target.exists():
            raise ValueError(f"Pack-Dateiname doppelt: {path.name}")
        shutil.copy2(path, target)
        if path.suffix == ".ydr":
            if placement.read(path) is None:
                raise ValueError(f"Standhoehe nicht geprueft: {path.name}")
            shutil.copy2(path.with_suffix(".placement.json"), target.with_suffix(".placement.json"))
            shutil.copy2(path.with_suffix(".build.json"), target.with_suffix(".build.json"))
            names.append(path.stem)
    report = packaging.build_resource(staging, config.workdir / "resources", config.resource_name,
                                      config.author, spawn_helper=config.spawn_helper, prop_names=names)
    hashes = {}
    for source in sources:
        exported = report.root / "stream" / source.name
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if hashlib.sha256(exported.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Pack-Kopie weicht vom geprueften Build ab: {exported}")
        hashes[source.name] = {"sha256": digest, "bytes": exported.stat().st_size}
    result = {"version": 1, "resource": config.resource_name, "props": sorted(names),
              "files": hashes, "native_verification": "native_check/native_result.json",
              "merge_verification": "merged/merge_result.json",
              "ingame": "pending", "source_and_stream_bytes_identical": True}
    (config.workdir / "pack_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(report.summary())
    return report
