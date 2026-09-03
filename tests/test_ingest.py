"""Tests fuer die GLB-Eingangsstufe.

Anlass war ein echtes Marktplatz-Asset. Es brachte drei Dinge mit, die kein
synthetischer Testfall gezeigt hatte: eingebettete Texturen, eine gepackte
metallicRoughness-Karte und einen Ursprung ausserhalb des Objekts.
"""

import json
import struct

import numpy as np
import pytest
from PIL import Image

from propforge import ingest


def build_glb(with_textures=True, double_sided=False, offset=(0.0, 0.0, 0.0)):
    """Baut eine minimale, gueltige GLB-Datei im Speicher."""
    positions = np.array([
        [0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1],
    ], dtype=np.float32) + np.array(offset, dtype=np.float32)
    indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
    uvs = np.zeros((4, 2), dtype=np.float32)

    payload = bytearray()

    def add(array):
        while len(payload) % 4:
            payload.append(0)
        start = len(payload)
        payload.extend(array.tobytes())
        return {"buffer": 0, "byteOffset": start, "byteLength": array.nbytes}

    views = [add(positions), add(indices), add(uvs)]

    images, textures = [], []
    if with_textures:
        for color in ((200, 100, 50), (0, 128, 255), (128, 128, 255)):
            import io
            buf = io.BytesIO()
            Image.new("RGB", (8, 8), color).save(buf, format="PNG")
            blob = buf.getvalue()
            while len(payload) % 4:
                payload.append(0)
            views.append({"buffer": 0, "byteOffset": len(payload), "byteLength": len(blob)})
            payload.extend(blob)
            images.append({"bufferView": len(views) - 1, "mimeType": "image/png"})
            textures.append({"source": len(images) - 1})

    material = {"name": "m", "doubleSided": double_sided}
    if with_textures:
        material["pbrMetallicRoughness"] = {
            "baseColorTexture": {"index": 0},
            "metallicRoughnessTexture": {"index": 1},
        }
        material["normalTexture"] = {"index": 2}

    gltf = {
        "asset": {"version": "2.0"},
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5125, "count": 6, "type": "SCALAR"},
            {"bufferView": 2, "componentType": 5126, "count": 4, "type": "VEC2"},
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": len(payload)}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "TEXCOORD_0": 2},
            "indices": 1, "material": 0, "mode": 4,
        }]}],
        "materials": [material],
        "images": images,
        "textures": textures,
    }

    js = json.dumps(gltf).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    bn = bytes(payload) + b"\x00" * ((4 - len(payload) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bn)
    return (struct.pack("<4sII", b"glTF", 2, total)
            + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(bn), 0x004E4942) + bn)


@pytest.fixture
def glb(tmp_path):
    path = tmp_path / "a.glb"
    path.write_bytes(build_glb())
    return path


class TestReadGlb:
    def test_parses_chunks(self, glb):
        gltf, binary = ingest.read_glb(glb)
        assert gltf["asset"]["version"] == "2.0"
        assert len(binary) > 0

    def test_rejects_non_glb(self, tmp_path):
        bad = tmp_path / "b.glb"
        bad.write_bytes(b"not a glb file at all")
        with pytest.raises(ingest.IngestError, match="keine GLB"):
            ingest.read_glb(bad)

    def test_rejects_wrong_version(self, tmp_path):
        bad = tmp_path / "c.glb"
        bad.write_bytes(struct.pack("<4sII", b"glTF", 1, 12))
        with pytest.raises(ingest.IngestError, match="Version"):
            ingest.read_glb(bad)


class TestGeometry:
    def test_reads_positions_and_faces(self, glb):
        gltf, binary = ingest.read_glb(glb)
        vertices, faces, has_uvs = ingest.geometry(gltf, binary)
        assert vertices.shape == (4, 3)
        assert faces.shape == (2, 3)
        assert has_uvs

    def test_converts_to_z_up(self):
        # glTF ist Y-up. Ein Punkt, der dort nach oben zeigt, muss danach in Z liegen.
        result = ingest.gltf_to_zup(np.array([[0.0, 1.0, 0.0]]))
        assert np.allclose(result[0], [0.0, 0.0, 1.0])


class TestMetallicRoughnessSplit:
    def test_green_is_roughness_blue_is_metallic(self):
        # Die glTF-Spezifikation legt die Kanalbelegung fest. Ohne Trennung
        # wuerde die kombinierte Textur als Roughness gelesen und der
        # Specular-Wert waere um den Metallanteil verfaelscht.
        image = Image.new("RGB", (4, 4), (10, 200, 60))
        roughness, metallic = ingest.split_metallic_roughness(image)
        assert np.asarray(roughness).max() == 200
        assert np.asarray(metallic).max() == 60

    def test_output_is_grayscale(self):
        roughness, metallic = ingest.split_metallic_roughness(
            Image.new("RGB", (4, 4), (1, 2, 3))
        )
        assert roughness.mode == "L" and metallic.mode == "L"


class TestExtractTextures:
    def test_writes_four_maps(self, glb, tmp_path):
        gltf, binary = ingest.read_glb(glb)
        written = ingest.extract_textures(gltf, binary, tmp_path / "out", "pf_x")
        assert set(written) == {"diffuse", "roughness", "metallic", "normal"}
        assert all(p.is_file() for p in written.values())

    def test_handles_material_without_textures(self, tmp_path):
        path = tmp_path / "n.glb"
        path.write_bytes(build_glb(with_textures=False))
        gltf, binary = ingest.read_glb(path)
        assert ingest.extract_textures(gltf, binary, tmp_path / "o", "pf_x") == {}


class TestInspect:
    def test_reports_geometry(self, glb):
        info, _, _ = ingest.inspect(glb, "pf_x")
        assert info.triangles == 2
        assert info.vertices == 4
        assert info.has_uvs

    def test_detects_offset_origin(self, tmp_path):
        path = tmp_path / "off.glb"
        path.write_bytes(build_glb(offset=(5.0, 0.0, 0.0)))
        info, _, _ = ingest.inspect(path, "pf_x")
        assert not info.is_centered
        assert any("Ursprung" in n for n in info.notes)

    def test_centered_asset_has_no_note(self, tmp_path):
        path = tmp_path / "c.glb"
        path.write_bytes(build_glb(offset=(-0.5, -0.5, -0.5)))
        info, _, _ = ingest.inspect(path, "pf_x")
        assert info.is_centered

    def test_double_sided_is_flagged(self, tmp_path):
        path = tmp_path / "d.glb"
        path.write_bytes(build_glb(double_sided=True))
        info, _, _ = ingest.inspect(path, "pf_x")
        assert any("doubleSided" in n for n in info.notes)


class TestSlimGlb:
    def test_geometry_survives(self, glb, tmp_path):
        # Der Sinn der Uebung: kleiner werden, ohne Geometrie zu verlieren.
        gltf, binary = ingest.read_glb(glb)
        target = ingest.write_slim_glb(gltf, binary, tmp_path / "slim.glb")
        before, _, _ = ingest.inspect(glb, "a")
        after, _, _ = ingest.inspect(target, "b")
        assert (after.triangles, after.vertices) == (before.triangles, before.vertices)
        assert np.allclose(after.dimensions, before.dimensions)

    def test_textures_are_gone(self, glb, tmp_path):
        gltf, binary = ingest.read_glb(glb)
        target = ingest.write_slim_glb(gltf, binary, tmp_path / "slim.glb")
        slim_gltf, _ = ingest.read_glb(target)
        assert not slim_gltf.get("images")
        assert not slim_gltf.get("textures")

    def test_file_is_smaller(self, glb, tmp_path):
        gltf, binary = ingest.read_glb(glb)
        target = ingest.write_slim_glb(gltf, binary, tmp_path / "slim.glb")
        assert target.stat().st_size < glb.stat().st_size


class TestConfigSnippet:
    def test_contains_essentials(self, glb, tmp_path):
        info, _, _ = ingest.inspect(glb, "pf_x")
        info.textures = {"diffuse": str(tmp_path / "assets" / "pf_x_albedo.png")}
        snippet = ingest.config_snippet(
            info, tmp_path / "assets" / "pf_x.glb", tmp_path / "assets"
        )
        assert 'name = "pf_x"' in snippet
        assert 'source_up = "y"' in snippet
        assert "[prop.textures]" in snippet
        assert 'assets/pf_x_albedo.png' in snippet

    def test_offset_asset_gets_centering(self, tmp_path):
        path = tmp_path / "off.glb"
        path.write_bytes(build_glb(offset=(5.0, 0.0, 0.0)))
        info, _, _ = ingest.inspect(path, "pf_x")
        snippet = ingest.config_snippet(info, tmp_path / "a" / "x.glb", tmp_path / "a")
        assert 'center = "base"' in snippet
