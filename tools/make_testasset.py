"""Erzeugt ein synthetisches Test-Asset fuer CI und Rauchtests.

Bewusst ohne Abhaengigkeiten ausser Pillow: das OBJ wird direkt geschrieben,
die Texturen prozedural erzeugt. So liegen keine Binaerdateien im Repo und die
CI kann die komplette Kette ohne externen Generator durchlaufen.

Zwei Formen:

  sphere   UV-Kugel - der gutmuetige Fall, gleichmaessige Kruemmung
  torture  Gestell aus Sockel, duennen Streben, Gelaender und Kleinteil -
           der Fall, an dem sich LOD-Reduktion tatsaechlich entscheidet
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

    # Alle Indizes in diesem Modul sind 0-basiert. Erst write_obj rechnet auf
    # die 1-basierte OBJ-Konvention um - an genau einer Stelle.
    faces: list[tuple[int, int, int]] = []
    stride = segments + 1
    for ring in range(rings):
        for seg in range(segments):
            a = ring * stride + seg
            b = a + stride
            # Pole erzeugen entartete Dreiecke - die werden uebersprungen.
            if ring != 0:
                faces.append((a, b, a + 1))
            if ring != rings - 1:
                faces.append((a + 1, b, b + 1))
    return positions, uvs, faces


class MeshBuilder:
    """Sammelt Teilgeometrien zu einem Mesh.

    UVs entstehen per Boxprojektion - grob, aber gueltig. Es geht hier um
    LOD-Verhalten, nicht um Texturqualitaet.
    """

    def __init__(self) -> None:
        self.positions: list[tuple[float, float, float]] = []
        self.uvs: list[tuple[float, float]] = []
        self.faces: list[tuple[int, int, int]] = []

    def add(self, positions, faces) -> None:
        offset = len(self.positions)
        self.positions.extend(positions)
        for x, y, z in positions:
            # Boxprojektion auf die dominante Achse.
            ax, ay = (x, y) if abs(z) > max(abs(x), abs(y)) else (
                (y, z) if abs(x) > abs(y) else (x, z)
            )
            self.uvs.append((ax * 0.5 + 0.5, ay * 0.5 + 0.5))
        for a, b, c in faces:
            self.faces.append((a + offset, b + offset, c + offset))


def box(cx, cy, cz, sx, sy, sz):
    """Achsenparalleler Quader."""
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    positions = [
        (cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz),
        (cx + hx, cy + hy, cz - hz), (cx - hx, cy + hy, cz - hz),
        (cx - hx, cy - hy, cz + hz), (cx + hx, cy - hy, cz + hz),
        (cx + hx, cy + hy, cz + hz), (cx - hx, cy + hy, cz + hz),
    ]
    faces = [
        (0, 2, 1), (0, 3, 2),  # unten
        (4, 5, 6), (4, 6, 7),  # oben
        (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 0, 4), (3, 4, 7),
    ]
    return positions, faces


def cylinder(cx, cy, cz, radius, height, segments=10, axis="z"):
    """Zylinder entlang einer Achse - fuer duenne Streben und Gelaender."""
    positions = []
    for level in (0.0, 1.0):
        for seg in range(segments):
            angle = 2 * math.pi * seg / segments
            u, v = radius * math.cos(angle), radius * math.sin(angle)
            offset = (level - 0.5) * height
            if axis == "z":
                positions.append((cx + u, cy + v, cz + offset))
            elif axis == "x":
                positions.append((cx + offset, cy + u, cz + v))
            else:
                positions.append((cx + u, cy + offset, cz + v))

    faces = []
    for seg in range(segments):
        nxt = (seg + 1) % segments
        a, b = seg, nxt
        c, d = seg + segments, nxt + segments
        faces.append((a, b, c))
        faces.append((b, d, c))
    # Deckel als Faecher
    for seg in range(1, segments - 1):
        faces.append((0, seg, seg + 1))
        faces.append((segments, segments + seg + 1, segments + seg))
    return positions, faces


def torture_rig():
    """Testobjekt, das die LOD-Kette absichtlich unter Druck setzt.

    Eine Kugel ist der leichteste Fall: gleichmaessige Kruemmung, keine duennen
    Teile, keine scharfen Kanten. Dieses Objekt mischt bewusst Groessenordnungen:

      - massiver Sockel (haelt jede Reduktion aus)
      - vier duenne Streben (verschwinden als erstes)
      - ein waagerechtes Gelaender, noch duenner
      - eine kleine Kugel als Detail nahe der Aufloesungsgrenze
      - eine scharfkantige Platte

    Genau solche Mischungen zerlegt Decimate: es entfernt dort, wo der Fehler
    lokal am kleinsten ist - und das ist bei duennen Streben irrefuehrend
    guenstig, weil ihr Verschwinden geometrisch wenig, optisch aber sehr viel
    kostet.
    """
    mesh = MeshBuilder()

    mesh.add(*box(0, 0, -0.42, 0.9, 0.6, 0.16))          # Sockel
    mesh.add(*box(0, 0, 0.34, 0.66, 0.02, 0.30))          # scharfkantige Platte

    for sx in (-0.36, 0.36):
        for sy in (-0.22, 0.22):
            mesh.add(*cylinder(sx, sy, 0.0, 0.022, 0.70, segments=32))  # Streben

    mesh.add(*cylinder(0.0, -0.22, 0.30, 0.012, 0.72, segments=24, axis="x"))  # Gelaender
    mesh.add(*cylinder(0.0, 0.22, 0.30, 0.012, 0.72, segments=24, axis="x"))

    detail, detail_faces = uv_sphere(28, 18, radius=0.05)[0::2]
    detail = [(x, y, z + 0.58) for x, y, z in detail]
    mesh.add(detail, detail_faces)

    return mesh.positions, mesh.uvs, mesh.faces


def write_obj(path: Path, positions, uvs, faces) -> None:
    """Schreibt ein OBJ.

    OBJ zaehlt Indizes ab 1, dieses Modul intern ab 0. Die Umrechnung passiert
    ausschliesslich hier -- vorher stand sie an zwei Stellen unterschiedlich,
    wodurch das Gestell mit einem Versatz von einem Vertex in die Datei ging.
    Jedes Dreieck verband dann die falschen Ecken. Im Speicher war die
    Geometrie korrekt, nur die Datei war es nicht -- und Blender liest die Datei.
    """
    if faces and min(min(f) for f in faces) < 0:
        raise ValueError("Negativer Vertexindex - die Eingabe ist nicht 0-basiert.")
    if faces and max(max(f) for f in faces) >= len(positions):
        raise ValueError("Vertexindex zeigt hinter das Ende der Vertexliste.")

    lines = ["# PropForge Testasset", "o pf_testprop"]
    lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in positions]
    lines += [f"vt {u:.6f} {v:.6f}" for u, v in uvs]
    lines += [
        f"f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}" for a, b, c in faces
    ]
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
    parser.add_argument("--shape", default="sphere", choices=["sphere", "torture"])
    parser.add_argument("--segments", type=int, default=48)
    parser.add_argument("--rings", type=int, default=24)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.shape == "torture":
        positions, uvs, faces = torture_rig()
    else:
        positions, uvs, faces = uv_sphere(args.segments, args.rings)

    write_obj(out / f"{args.name}.obj", positions, uvs, faces)
    write_textures(out, args.name)

    print(f"{args.name}.obj ({args.shape}): {len(positions)} Vertices, "
          f"{len(faces)} Dreiecke -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
