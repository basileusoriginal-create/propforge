"""Integrationstests fuer den DDS-Schritt.

Diese Tests rufen den tatsaechlich installierten Konverter auf und lesen den
DDS-Header zurueck. Sie sind der Grund, warum zwei stille Fehler aufgefallen
sind: ImageMagick erzeugte bei "dds:mipmaps=true" genau eine Mipmap-Stufe und
degradierte dxt5 ohne Alphakanal kommentarlos auf dxt1. Beides sieht man einer
erfolgreich beendeten Kommandozeile nicht an.

Ohne Konverter im PATH werden die Tests uebersprungen.
"""

import struct

from PIL import Image

from propforge import textures
from propforge.config import PropSpec, TextureSet

DDS_MAGIC = b"DDS "


def read_dds_header(path):
    """Liest Magic, Groesse, Mipmap-Anzahl und FourCC aus einer DDS-Datei."""
    data = path.read_bytes()
    height, width = struct.unpack("<II", data[12:20])
    mipmaps = struct.unpack("<I", data[28:32])[0]
    return {
        "magic": data[:4],
        "width": width,
        "height": height,
        "mipmaps": mipmaps,
        "fourcc": data[84:88].decode("ascii", "replace"),
        "size": len(data),
    }


def converter_available() -> bool:
    return textures.find_dds_converter() is not None


class TestMipLevels:
    def test_square(self):
        assert textures.mip_levels(512, 512) == 10
        assert textures.mip_levels(1024, 1024) == 11
        assert textures.mip_levels(1, 1) == 1

    def test_uses_longer_edge(self):
        # Die Kette laeuft bis 1x1, also zaehlt die laengere Kante.
        assert textures.mip_levels(512, 128) == 10


class TestImageMagickFormatMapping:
    def test_known_formats_mapped(self):
        assert textures.IMAGEMAGICK_COMPRESSION["BC1_UNORM"] == "dxt1"
        assert textures.IMAGEMAGICK_COMPRESSION["BC3_UNORM"] == "dxt5"

    def test_bc7_not_supported(self):
        assert "BC7_UNORM" not in textures.IMAGEMAGICK_COMPRESSION


def _spec(tmp_path):
    Image.new("RGB", (256, 256), color=(120, 90, 60)).save(tmp_path / "d.png")
    Image.new("RGB", (256, 256), color=(128, 128, 255)).save(tmp_path / "n.png")
    Image.new("L", (256, 256), color=180).save(tmp_path / "r.png")
    return PropSpec(
        name="pf_dds",
        mesh=str(tmp_path / "m.obj"),
        textures=TextureSet(
            diffuse=str(tmp_path / "d.png"),
            normal=str(tmp_path / "n.png"),
            roughness=str(tmp_path / "r.png"),
        ),
        texture_size=256,
    )


class TestRealConversion:
    def test_writes_valid_dds(self, tmp_path):
        if not converter_available():
            return
        out = tmp_path / "out"
        prepared = textures.prepare(_spec(tmp_path), out)
        written = textures.compress(prepared, out)
        assert len(written) == 3
        for path in written:
            header = read_dds_header(path)
            assert header["magic"] == DDS_MAGIC, f"{path.name} ist keine DDS-Datei"
            assert header["width"] == 256 and header["height"] == 256

    def test_full_mipmap_chain(self, tmp_path):
        if not converter_available():
            return
        out = tmp_path / "out"
        prepared = textures.prepare(_spec(tmp_path), out)
        written = textures.compress(prepared, out)
        for path in written:
            header = read_dds_header(path)
            # 256x256 -> 9 Stufen. Eine einzelne Stufe bedeutet: keine Mipmaps,
            # und der Prop flimmert in der Distanz.
            assert header["mipmaps"] == 9, f"{path.name} hat {header['mipmaps']} Stufen statt 9"

    def test_normal_map_keeps_dxt5(self, tmp_path):
        if not converter_available():
            return
        out = tmp_path / "out"
        prepared = textures.prepare(_spec(tmp_path), out)
        written = textures.compress(prepared, out)
        normal = next(p for p in written if p.stem.endswith("_n"))
        header = read_dds_header(normal)
        # DXT1 waere hier ein stiller Qualitaetsverlust: die Normalmap
        # bekaeme nur 5-6-5 Bit und wuerde im Spiel sichtbar bandieren.
        assert header["fourcc"] == "DXT5", f"Normalmap kam als {header['fourcc']} heraus"

    def test_diffuse_without_alpha_stays_dxt1(self, tmp_path):
        if not converter_available():
            return
        out = tmp_path / "out"
        prepared = textures.prepare(_spec(tmp_path), out)
        written = textures.compress(prepared, out)
        diffuse = next(p for p in written if p.stem.endswith("_d"))
        # Ohne Transparenz waere DXT5 doppelter Speicher ohne Gegenwert.
        assert read_dds_header(diffuse)["fourcc"] == "DXT1"
