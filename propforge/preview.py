"""Kontaktbogen aus den LOD-Geometrien.

Die Blender-Stufe liefert nur Vertices und Dreiecke; gezeichnet wird hier mit
dem Software-Rasterizer aus `raster.py`. Nebeneinandergelegt beantworten die
Stufen die Frage, die kein Test beantwortet: haelt LOD3 noch die Silhouette von
LOD0, oder ist der Prop in der Distanz nur noch ein Klumpen? Decimate ist blind
fuer duenne Strukturen - Gelaender, Antennen, Griffe verschwinden zuerst.

Der gesamte Ablauf laeuft ausserhalb von Blender und ist damit lokal testbar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .raster import Geometry, compute_bounds, render_solid, render_wire

LOD_ORDER = ("high", "medium", "low", "verylow")

BACKGROUND = (24, 24, 28)
FOREGROUND = (232, 232, 236)
MUTED = (150, 150, 160)
ACCENT = (255, 176, 80)

PADDING = 16
LABEL_HEIGHT = 46
HEADER_HEIGHT = 40


@dataclass
class LodPreview:
    lod: str
    triangles: int
    solid: Image.Image | None = None
    wire: Image.Image | None = None


def _font(size: int) -> ImageFont.ImageFont:
    """Laedt eine skalierbare Schrift, faellt notfalls auf die Bitmapschrift zurueck."""
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def load_geometries(render_dir: Path, stats: list[dict]) -> dict[str, Geometry]:
    """Liest die von Blender geschriebenen Geometriedateien."""
    render_dir = Path(render_dir)
    geometries: dict[str, Geometry] = {}

    for entry in stats:
        lod = entry.get("lod")
        filename = entry.get("geometry")
        if not lod or not filename:
            continue
        path = render_dir / filename
        if not path.is_file():
            continue
        geometries[lod] = Geometry.from_dict(json.loads(path.read_text(encoding="utf-8")))

    return geometries


def render_previews(
    render_dir: Path,
    stats: list[dict],
    size: int = 512,
    out_dir: Path | None = None,
) -> list[LodPreview]:
    """Rastert jede LOD-Stufe massiv und als Drahtgitter.

    Alle Stufen teilen sich die Bounding-Box der hoechsten Stufe. Wuerde jede
    Stufe fuer sich eingepasst, kaschierte der Massstabssprung genau den
    Silhouettenverlust, den man sehen will.
    """
    geometries = load_geometries(render_dir, stats)
    if not geometries:
        return []

    by_lod = {entry["lod"]: entry for entry in stats if "lod" in entry}
    reference_key = next((l for l in LOD_ORDER if l in geometries), None)
    if reference_key is None:
        return []
    bounds = compute_bounds(geometries[reference_key])

    previews: list[LodPreview] = []
    for lod in LOD_ORDER:
        geometry = geometries.get(lod)
        if geometry is None:
            continue

        solid = render_solid(geometry, size, bounds)
        wire = render_wire(geometry, size, bounds)

        if out_dir is not None:
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            solid.save(out_dir / f"{lod}_solid.png")
            wire.save(out_dir / f"{lod}_wire.png")

        previews.append(
            LodPreview(
                lod=lod,
                triangles=int(by_lod.get(lod, {}).get("triangles", geometry.triangle_count)),
                solid=solid,
                wire=wire,
            )
        )

    return previews


def build_sheet(previews: list[LodPreview], name: str, out_path: Path, cell: int = 320) -> Path:
    """Legt die Stufen nebeneinander: obere Reihe massiv, untere als Drahtgitter."""
    if not previews:
        raise ValueError("Keine Vorschaubilder vorhanden.")

    has_wire = any(p.wire is not None for p in previews)
    rows = 2 if has_wire else 1

    width = PADDING + len(previews) * (cell + PADDING)
    height = HEADER_HEIGHT + PADDING + rows * (cell + LABEL_HEIGHT + PADDING)

    sheet = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)

    title_font = _font(20)
    label_font = _font(16)
    small_font = _font(13)

    draw.text((PADDING, PADDING - 4), name, fill=FOREGROUND, font=title_font)

    reference = previews[0].triangles or 1

    for column, preview in enumerate(previews):
        x = PADDING + column * (cell + PADDING)

        for row, (image, caption) in enumerate(
            [(preview.solid, "massiv"), (preview.wire, "Drahtgitter")][:rows]
        ):
            y = HEADER_HEIGHT + PADDING + row * (cell + LABEL_HEIGHT + PADDING)

            if image is not None:
                thumb = image.copy()
                thumb.thumbnail((cell, cell), Image.LANCZOS)
                sheet.paste(
                    thumb,
                    (x + (cell - thumb.width) // 2, y + (cell - thumb.height) // 2),
                    thumb,
                )
            else:
                draw.rectangle((x, y, x + cell, y + cell), outline=MUTED)
                draw.text((x + 12, y + cell // 2), "kein Bild", fill=MUTED, font=small_font)

            if row == 0:
                share = preview.triangles / reference * 100.0
                draw.text((x, y + cell + 6), preview.lod.upper(), fill=ACCENT, font=label_font)
                draw.text(
                    (x, y + cell + 26),
                    f"{preview.triangles} Dreiecke  ({share:.0f} %)",
                    fill=MUTED,
                    font=small_font,
                )
            elif column == 0:
                # Zeilenbeschriftung nur einmal - viermal "Drahtgitter"
                # nebeneinander ist Rauschen, kein Informationsgewinn.
                draw.text((x, y + cell + 6), caption, fill=MUTED, font=small_font)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def build_all(render_root: Path, result: dict, out_dir: Path) -> list[Path]:
    """Erzeugt einen Kontaktbogen je Prop aus dem Build-Ergebnisbericht."""
    render_root = Path(render_root)
    out_dir = Path(out_dir)
    sheets: list[Path] = []

    for prop in result.get("props", []):
        name = prop.get("name")
        stats = prop.get("previews") or []
        if not name or not stats:
            continue

        previews = render_previews(
            render_root / name, stats, out_dir=out_dir / name
        )
        if not previews:
            continue
        sheets.append(build_sheet(previews, name, out_dir / f"{name}_lods.png"))

    return sheets
