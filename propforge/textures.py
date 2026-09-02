"""Texturstufe: PBR-Output eines AI-Generators -> GTA-taugliche DDS.

Zwei getrennte Schritte:

1. Aufbereitung in Pillow (plattformunabhaengig, hier testbar):
   Zweierpotenz-Resize, Specular aus Roughness/Metallic, Normalmap-Konvention.
2. Kompression via `texconv` (DirectXTex, Windows) zu DXT1/DXT5/BC7 mit Mipmaps.

Schritt 1 ist der inhaltlich interessante Teil: AI-Generatoren liefern das
metallic/roughness-Workflow-Paar, GTA V erwartet aber eine einzelne
Specular-Map und eine DirectX-Normalmap.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .config import VALID_TEXTURE_SIZES, PropSpec

# DDS-Formate nach Verwendungszweck.
# GTA V liest BC1/BC3 zuverlaessig; BC7 nur auf modernen Builds.
DDS_FORMATS = {
    "diffuse": "BC1_UNORM",       # kein Alpha noetig -> DXT1, halber Speicher
    "diffuse_alpha": "BC3_UNORM",  # mit Alpha -> DXT5
    "normal": "BC3_UNORM",         # Normalmaps brauchen DXT5, DXT1 zerstoert sie
    "specular": "BC1_UNORM",
}


class TextureError(RuntimeError):
    pass


@dataclass
class PreparedTexture:
    role: str          # "diffuse" | "normal" | "specular"
    path: Path         # aufbereitete PNG-Zwischendatei
    dds_format: str
    sampler: str       # Sollumz-Samplername im Shader-Nodetree


def nearest_power_of_two(value: int, maximum: int = 2048) -> int:
    """Naechstliegende Zweierpotenz, nach oben durch `maximum` begrenzt.

    Der Abstand wird logarithmisch gemessen, nicht linear. Bei Bildgroessen
    zaehlt das Verhaeltnis: 1500 px liegt naeher an 2048 (Faktor 1,37) als an
    1024 (Faktor 1,46), obwohl der lineare Abstand das Gegenteil nahelegt.
    Linear gerundet wuerde man hier unnoetig Detail wegwerfen.
    """
    if value <= VALID_TEXTURE_SIZES[0]:
        return VALID_TEXTURE_SIZES[0]
    candidates = [s for s in VALID_TEXTURE_SIZES if s <= maximum]
    if not candidates:
        raise TextureError(f"Kein gueltiges Texturformat unterhalb von {maximum}.")
    return min(candidates, key=lambda s: (abs(math.log2(s) - math.log2(value)), s))


def to_power_of_two(img: Image.Image, maximum: int = 2048) -> Image.Image:
    """Skaliert ein Bild auf Zweierpotenz-Kantenlaengen.

    Breite und Hoehe werden unabhaengig behandelt - GTA erlaubt auch
    nicht-quadratische Texturen wie 512x128.
    """
    target_w = nearest_power_of_two(img.width, maximum)
    target_h = nearest_power_of_two(img.height, maximum)
    if (target_w, target_h) == img.size:
        return img
    return img.resize((target_w, target_h), Image.LANCZOS)


def build_specular(
    roughness: Image.Image | None,
    metallic: Image.Image | None,
    size: tuple[int, int],
) -> Image.Image:
    """Leitet eine GTA-Specular-Map aus Roughness und Metallic ab.

    GTA Vs `normal_spec.sps` erwartet im SpecSampler eine Graustufen-Map, bei
    der hell = glaenzend bedeutet. Der metallic/roughness-Workflow der
    AI-Generatoren dreht die Bedeutung um, deshalb wird invertiert.
    Metallic hebt die Intensitaet zusaetzlich an, weil Metallflaechen in GTA
    deutlich staerker spiegeln als Dielektrika.
    """
    if roughness is None and metallic is None:
        raise TextureError("Weder Roughness noch Metallic vorhanden - Specular nicht ableitbar.")

    if roughness is not None:
        rough = np.asarray(roughness.convert("L").resize(size, Image.LANCZOS), dtype=np.float32) / 255.0
        spec = 1.0 - rough
    else:
        spec = np.full((size[1], size[0]), 0.5, dtype=np.float32)

    if metallic is not None:
        metal = np.asarray(metallic.convert("L").resize(size, Image.LANCZOS), dtype=np.float32) / 255.0
        # Metallflaechen auf mindestens 60 % Specular anheben; dielektrische
        # Bereiche (metal == 0) bleiben exakt unveraendert.
        boosted = np.maximum(spec, 0.6)
        spec = spec * (1.0 - metal) + boosted * metal
        spec = np.clip(spec, 0.0, 1.0)

    return Image.fromarray((spec * 255.0).round().astype(np.uint8), mode="L").convert("RGB")


def convert_normal_map(img: Image.Image, flip_green: bool) -> Image.Image:
    """Konvertiert zwischen OpenGL- und DirectX-Normalmap-Konvention.

    AI-Generatoren geben ueberwiegend OpenGL (Y+) aus, RAGE erwartet DirectX
    (Y-). Der Unterschied aeussert sich in Beleuchtung, die "nach innen"
    statt nach aussen woelbt - ein Fehler, den man im Spiel erst spaet sieht.
    """
    rgb = img.convert("RGB")
    if not flip_green:
        return rgb
    arr = np.asarray(rgb, dtype=np.uint8).copy()
    arr[:, :, 1] = 255 - arr[:, :, 1]
    return Image.fromarray(arr, mode="RGB")


def has_meaningful_alpha(img: Image.Image, threshold: int = 250) -> bool:
    """True, wenn der Alphakanal tatsaechlich Transparenz enthaelt.

    Viele Generatoren haengen einen vollflaechig opaken Alphakanal an. Den zu
    behalten wuerde die Textur unnoetig von DXT1 auf DXT5 heben - doppelter
    VRAM-Verbrauch ohne Gegenwert.
    """
    if img.mode not in ("RGBA", "LA", "PA"):
        return False
    alpha = np.asarray(img.convert("RGBA"))[:, :, 3]
    return bool((alpha < threshold).any())


def prepare(spec: PropSpec, out_dir: Path) -> list[PreparedTexture]:
    """Bereitet alle Texturen eines Props auf und legt PNG-Zwischendateien ab."""
    out_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[PreparedTexture] = []

    diffuse_src = Image.open(spec.textures.diffuse)
    diffuse = to_power_of_two(diffuse_src, spec.texture_size)
    alpha = has_meaningful_alpha(diffuse_src)
    diffuse_out = out_dir / f"{spec.name}_d.png"
    (diffuse if alpha else diffuse.convert("RGB")).save(diffuse_out)
    prepared.append(
        PreparedTexture(
            role="diffuse",
            path=diffuse_out,
            dds_format=DDS_FORMATS["diffuse_alpha"] if alpha else DDS_FORMATS["diffuse"],
            sampler="DiffuseSampler",
        )
    )

    target_size = diffuse.size

    if spec.textures.normal:
        normal = to_power_of_two(Image.open(spec.textures.normal), spec.texture_size)
        normal = normal.resize(target_size, Image.LANCZOS)
        normal = convert_normal_map(normal, spec.flip_normal_green)
        normal_out = out_dir / f"{spec.name}_n.png"
        normal.save(normal_out)
        prepared.append(
            PreparedTexture("normal", normal_out, DDS_FORMATS["normal"], "BumpSampler")
        )

    spec_img: Image.Image | None = None
    if spec.textures.specular:
        spec_img = to_power_of_two(Image.open(spec.textures.specular), spec.texture_size)
        spec_img = spec_img.convert("RGB").resize(target_size, Image.LANCZOS)
    elif spec.textures.roughness or spec.textures.metallic:
        spec_img = build_specular(
            Image.open(spec.textures.roughness) if spec.textures.roughness else None,
            Image.open(spec.textures.metallic) if spec.textures.metallic else None,
            target_size,
        )

    if spec_img is not None:
        spec_out = out_dir / f"{spec.name}_s.png"
        spec_img.save(spec_out)
        prepared.append(
            PreparedTexture("specular", spec_out, DDS_FORMATS["specular"], "SpecSampler")
        )

    return prepared


def find_texconv() -> str | None:
    return shutil.which("texconv") or shutil.which("texconv.exe")


def compress(prepared: list[PreparedTexture], out_dir: Path, texconv: str | None = None) -> list[Path]:
    """Komprimiert die aufbereiteten PNGs zu DDS mit vollstaendiger Mipmap-Kette.

    `-m 0` erzeugt alle Mipmap-Stufen; ohne Mipmaps flimmern Props in der
    Distanz sichtbar.
    """
    exe = texconv or find_texconv()
    if exe is None:
        raise TextureError(
            "texconv nicht gefunden. DirectXTex installieren "
            "(https://github.com/microsoft/DirectXTex/releases) und in den PATH legen."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []

    for tex in prepared:
        cmd = [
            exe,
            "-f", tex.dds_format,
            "-m", "0",
            "-y",
            "-nologo",
            "-o", str(out_dir),
            str(tex.path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise TextureError(f"texconv fehlgeschlagen fuer {tex.path.name}:\n{proc.stderr}")
        results.append(out_dir / f"{tex.path.stem}.dds")

    return results
