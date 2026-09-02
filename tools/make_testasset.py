"""Erzeugt ein synthetisches Test-Asset fuer CI und Rauchtests.

Bewusst ohne Abhaengigkeiten ausser Pillow: das OBJ wird direkt geschrieben,
die Texturen prozedural erzeugt. So liegen keine Binaerdateien im Repo und die
CI kann die komplette Kette ohne externen Generator durchlaufen.

Die Geometrie ist eine UV-Kugel mit ausreichend Dreiecken, damit die
Decimate-Stufe messbar etwas zu tun hat.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path


def uv_sphere(segments: int = 48, rings: int = 24, radius: float = 0.5):
    """Baut eine UV-Kugel mit Positionen, UV-Koordinaten und Dreiecken."""
    positions: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []

    for ring in range(rings + 1):
        v = ring / rings
        phi = v * math.pi
        for seg in range(segments + 1):
            u = seg / segments
            theta = u * 2.0 * math.pi
            positions.append((
                radius * math.sin(phi) * math.cos(theta),
                radius * math.sin(phi) * math.sin(theta),
                radius * math.cos(phi),
            ))
            uvs.append((u, 1.0 - v))

    faces: list[tuple[int, int, int]] = []
    stride = segments + 1
    for ring in range(rings):
        for seg in range(segments):
            a = ring * stride + seg
            b = a + stride
            # Pole erzeugen entartete Dreiecke - die werden uebersprungen.
            if ring != 0:
                faces.append((a + 1, b + 1, a + 2))
            if ring != rings - 1:
                faces.append((a + 2, b + 1, b + 2))
    return positions, uvs, faces


def write_obj(path: Path, positions, uvs, faces) -> None:
    lines = ["# PropForge Testasset", "o pf_testprop"]
    lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in positions]
    lines += [f"vt {u:.6f} {v:.6f}" for u, v in uvs]
    lines += [f"f {a}/{a} {b}/{b} {c}/{c}" for a, b, c in faces]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_textures(out_dir: Path, name: str, size: int = 512) -> None:
    from PIL import Image

    # Diffuse: Schachbrett, damit UV-Fehler sofort sichtbar werden.
    diffuse = Image.new("RGB", (size, size))
    px = diffuse.load()
    tile = size // 8
    for y in range(size):
        for x in range(size):
            dark = ((x // tile) + (y // tile)) % 2 == 0
            px[x, y] = (70, 70, 78) if dark else (185, 175, 160)
    diffuse.save(out_dir / f"{name}_albedo.png")

    # Flache Normalmap in OpenGL-Konvention (Y+) - genau das, was
    # AI-Generatoren liefern und was die Pipeline nach DirectX drehen muss.
    Image.new("RGB", (size, size), color=(128, 128, 255)).save(out_dir / f"{name}_normal.png")

    # Roughness-Verlauf: links glatt, rechts rau.
    rough = Image.new("L", (size, size))
    rpx = rough.load()
    for y in range(size):
        for x in range(size):
            rpx[x, y] = int(255 * x / (size - 1))
    rough.save(out_dir / f"{name}_roughness.png")

    Image.new("L", (size, size), color=0).save(out_dir / f"{name}_metallic.png")


def main() -> int:
    parser = argparse.ArgumentParser(description="Testasset fuer PropForge erzeugen")
    parser.add_argument("--out", default="assets", help="Zielverzeichnis")
    parser.add_argument("--name", default="pf_testprop")
    parser.add_argument("--segments", type=int, default=48)
    parser.add_argument("--rings", type=int, default=24)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    positions, uvs, faces = uv_sphere(args.segments, args.rings)
    write_obj(out / f"{args.name}.obj", positions, uvs, faces)
    write_textures(out, args.name)

    print(f"{args.name}.obj: {len(positions)} Vertices, {len(faces)} Dreiecke -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
