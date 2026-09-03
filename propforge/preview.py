"""Kontaktbogen aus den LOD-Renderings.

Die einzelnen PNGs sind schon nuetzlich, aber nebeneinander gelegt beantworten
sie die eigentliche Frage: haelt LOD3 noch die Silhouette von LOD0, oder ist der
Prop in der Distanz nur noch ein Klumpen? Decimate ist blind fuer duenne
Strukturen - Gelaender, Antennen, Griffe verschwinden zuerst.

Diese Stufe laeuft ausserhalb von Blender und ist damit lokal testbar.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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
    solid: Path | None
    wire: Path | None


def _font(size: int) -> ImageFont.ImageFont:
    """Laedt eine skalierbare Schrift, faellt notfalls auf die Bitmapschrift zurueck.

    Die Bitmapschrift ist winzig, aber ein Kontaktbogen ohne Beschriftung waere
    schlechter als einer mit kleiner Beschriftung.
    """
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


def collect(render_dir: Path, name: str, stats: list[dict]) -> list[LodPreview]:
    """Verbindet die Statistik aus dem Build mit den tatsaechlichen Dateien."""
    render_dir = Path(render_dir)
    previews: list[LodPreview] = []

    by_lod = {entry["lod"]: entry for entry in stats}
    for lod in LOD_ORDER:
        entry = by_lod.get(lod)
        if entry is None:
            continue
        images = entry.get("images", {})
        solid = render_dir / images["solid"] if images.get("solid") else None
        wire = render_dir / images["wire"] if images.get("wire") else None
        previews.append(
            LodPreview(
                lod=lod,
                triangles=int(entry.get("triangles", 0)),
                solid=solid if solid and solid.is_file() else None,
                wire=wire if wire and wire.is_file() else None,
            )
        )
    return previews


def build_sheet(previews: list[LodPreview], name: str, out_path: Path, cell: int = 320) -> Path:
    """Legt die Stufen nebeneinander: obere Reihe massiv, untere als Drahtgitter."""
    if not previews:
        raise ValueError("Keine Vorschaubilder vorhanden.")

    has_wire = any(p.wire for p in previews)
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

        for row, (image_path, caption) in enumerate(
            [(preview.solid, "massiv"), (preview.wire, "Drahtgitter")][:rows]
        ):
            y = HEADER_HEIGHT + PADDING + row * (cell + LABEL_HEIGHT + PADDING)
            box = (x, y, x + cell, y + cell)

            if image_path is not None:
                with Image.open(image_path) as img:
                    img = img.convert("RGBA")
                    img.thumbnail((cell, cell), Image.LANCZOS)
                    offset = (
                        x + (cell - img.width) // 2,
                        y + (cell - img.height) // 2,
                    )
                    sheet.paste(img, offset, img)
            else:
                draw.rectangle(box, outline=MUTED)
                draw.text((x + 12, y + cell // 2), "kein Bild", fill=MUTED, font=small_font)

            if row == 0:
                share = preview.triangles / reference * 100.0
                draw.text(
                    (x, y + cell + 6),
                    preview.lod.upper(),
                    fill=ACCENT,
                    font=label_font,
                )
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
        previews = collect(render_root / name, name, stats)
        if not previews:
            continue
        sheets.append(build_sheet(previews, name, out_dir / f"{name}_lods.png"))

    return sheets
