"""Letzte Stufe: fertige Assets zu einer FiveM-Resource buendeln.

FiveM streamt alles automatisch, was in einem `stream/`-Ordner liegt.
Zwei Ausnahmen brauchen einen expliziten Eintrag im fxmanifest:
ytyp-Dateien ueber `data_file 'DLC_ITYP_REQUEST'`, ymaps ueber `this_is_a_map`.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

FX_VERSION = "cerulean"
GAME = "gta5"

# Endungen, die FiveM aus stream/ selbst aufsammelt.
STREAM_SUFFIXES = {".ydr", ".ydd", ".yft", ".ytd", ".ybn", ".ycd", ".ymap", ".ytyp"}


@dataclass
class ResourceReport:
    root: Path
    streamed: list[Path]
    ytyps: list[Path]
    ymaps: list[Path]

    def summary(self) -> str:
        lines = [f"Resource: {self.root.name}  ({len(self.streamed)} Streaming-Dateien)"]
        by_suffix: dict[str, int] = {}
        for p in self.streamed:
            by_suffix[p.suffix] = by_suffix.get(p.suffix, 0) + 1
        for suffix, count in sorted(by_suffix.items()):
            lines.append(f"  {suffix:<7} {count}")
        return "\n".join(lines)


def render_manifest(resource_name: str, author: str, ytyps: list[str], ymaps: list[str]) -> str:
    lines = [
        f"fx_version '{FX_VERSION}'",
        f"game '{GAME}'",
        "",
        f"name '{resource_name}'",
        f"author '{author}'",
        "version '1.0.0'",
        "description 'Generiert mit PropForge'",
        "",
    ]

    if ymaps:
        lines += ["this_is_a_map 'yes'", ""]

    if ytyps:
        lines.append("-- Archetype-Definitionen muessen explizit registriert werden,")
        lines.append("-- sonst findet das Spiel die Props trotz vorhandener .ydr nicht.")
        for name in sorted(ytyps):
            lines.append(f"data_file 'DLC_ITYP_REQUEST' 'stream/{name}'")
        lines.append("")

    lines += [
        "files {",
        "    'stream/**.ytyp',",
        "}",
        "",
    ]
    return "\n".join(lines)


def build_resource(
    build_dir: Path,
    out_root: Path,
    resource_name: str,
    author: str,
    clean: bool = True,
) -> ResourceReport:
    """Sammelt alle Build-Artefakte in eine installierbare FiveM-Resource."""
    build_dir = Path(build_dir)
    resource_root = Path(out_root) / resource_name
    stream_dir = resource_root / "stream"

    if clean and resource_root.exists():
        shutil.rmtree(resource_root)
    stream_dir.mkdir(parents=True, exist_ok=True)

    streamed: list[Path] = []
    ytyps: list[Path] = []
    ymaps: list[Path] = []

    for src in sorted(build_dir.rglob("*")):
        if not src.is_file() or src.suffix.lower() not in STREAM_SUFFIXES:
            continue
        dst = stream_dir / src.name
        if dst.exists():
            raise FileExistsError(
                f"Namenskollision beim Packen: '{src.name}' existiert bereits in stream/. "
                "Streaming-Dateinamen muessen serverweit eindeutig sein."
            )
        shutil.copy2(src, dst)
        streamed.append(dst)
        if src.suffix.lower() == ".ytyp":
            ytyps.append(dst)
        elif src.suffix.lower() == ".ymap":
            ymaps.append(dst)

    manifest = render_manifest(
        resource_name,
        author,
        [p.name for p in ytyps],
        [p.name for p in ymaps],
    )
    (resource_root / "fxmanifest.lua").write_text(manifest, encoding="utf-8")

    return ResourceReport(resource_root, streamed, ytyps, ymaps)
