"""Meldet als GitHub-Annotation, was der Lauf tatsaechlich gebaut hat.

Fehler werden schon als ::error:: gemeldet. Aber ein *erfolgreicher* Lauf ist
von aussen stumm: Schritt-Logs sind nur eingeloggt lesbar, und ein Bild sagt
nicht, wie gross das Objekt ist oder wie viele Dreiecke jede Stufe hat.

Genau diese Zahlen entscheiden aber Fragen wie "steht der Prop aufrecht?".
Also werden sie mit ::notice:: ausgegeben - das rendert GitHub oeffentlich.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def describe(prop: dict) -> list[str]:
    lines = [f"{prop.get('name', '?')}:"]

    dims = prop.get("dimensions")
    if dims:
        x, y, z = dims.get("x", 0), dims.get("y", 0), dims.get("z", 0)
        lines.append(f"  Abmessungen B{x:.3f} x T{y:.3f} x H{z:.3f} m")
        # Die hoechste Achse benennen: liegt ein Prop auf der Seite, faellt es
        # hier auf, auch ohne Bild.
        tallest = max((("X", x), ("Y", y), ("Z", z)), key=lambda p: p[1])
        lines.append(f"  laengste Achse: {tallest[0]} ({tallest[1]:.3f} m)")

    for entry in prop.get("previews", []):
        lines.append(
            f"  LOD {entry.get('lod', '?'):<8} "
            f"{entry.get('triangles', 0):>6} Dreiecke, "
            f"{entry.get('vertices', 0):>6} Vertices"
        )
    return lines


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path("ci/out/build_result.json")
    title = argv[2] if len(argv) > 2 else "PropForge"

    if not path.is_file():
        print(f"::notice title={title}::Kein Ergebnisbericht unter {path}.")
        return 0

    result = json.loads(path.read_text(encoding="utf-8"))
    lines: list[str] = [
        f"Gebaut: {len(result.get('succeeded', []))}/{result.get('total', 0)}"
    ]
    for prop in result.get("props", []):
        lines.extend(describe(prop))

    body = "\n".join(lines).replace("%", "%25").replace("\n", "%0A")
    print(f"::notice title={title}::{body}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
