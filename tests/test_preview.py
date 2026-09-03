import json
import math

import pytest
from PIL import Image

from propforge import preview


def sphere_dict(segments: int, rings: int) -> dict:
    vertices = []
    for ring in range(rings + 1):
        phi = math.pi * ring / rings
        for seg in range(segments):
            theta = 2 * math.pi * seg / segments
            vertices.append([
                math.sin(phi) * math.cos(theta),
                math.sin(phi) * math.sin(theta),
                math.cos(phi),
            ])
    triangles = []
    for ring in range(rings):
        for seg in range(segments):
            a = ring * segments + seg
            b = ring * segments + (seg + 1) % segments
            triangles.append([a, b, a + segments])
            triangles.append([b, b + segments, a + segments])
    return {"vertices": vertices, "triangles": triangles}


LOD_RESOLUTION = {"high": (24, 16), "medium": (16, 10), "low": (10, 6), "verylow": (6, 4)}


def write_geometry(render_dir, name, lods=("high", "medium", "low", "verylow")):
    render_dir.mkdir(parents=True, exist_ok=True)
    stats = []
    for lod in lods:
        data = sphere_dict(*LOD_RESOLUTION[lod])
        filename = f"{name}_{lod}.json"
        (render_dir / filename).write_text(json.dumps(data))
        stats.append({
            "lod": lod,
            "triangles": len(data["triangles"]),
            "vertices": len(data["vertices"]),
            "geometry": filename,
        })
    return stats


class TestLoadGeometries:
    def test_loads_all_levels(self, tmp_path):
        stats = write_geometry(tmp_path, "pf_x")
        geometries = preview.load_geometries(tmp_path, stats)
        assert set(geometries) == {"high", "medium", "low", "verylow"}

    def test_skips_missing_files(self, tmp_path):
        stats = write_geometry(tmp_path, "pf_x", lods=("high",))
        stats.append({"lod": "low", "triangles": 5, "geometry": "fehlt.json"})
        assert set(preview.load_geometries(tmp_path, stats)) == {"high"}

    def test_skips_entries_without_geometry(self, tmp_path):
        assert preview.load_geometries(tmp_path, [{"lod": "high", "triangles": 5}]) == {}


class TestRenderPreviews:
    def test_orders_high_to_low(self, tmp_path):
        stats = write_geometry(tmp_path, "pf_x")
        stats.reverse()  # Reihenfolge im Bericht ist nicht garantiert
        previews = preview.render_previews(tmp_path, stats, size=96)
        assert [p.lod for p in previews] == ["high", "medium", "low", "verylow"]

    def test_produces_both_passes(self, tmp_path):
        stats = write_geometry(tmp_path, "pf_x", lods=("high",))
        result = preview.render_previews(tmp_path, stats, size=96)
        assert result[0].solid is not None
        assert result[0].wire is not None

    def test_triangle_counts_kept(self, tmp_path):
        stats = write_geometry(tmp_path, "pf_x", lods=("high",))
        expected = stats[0]["triangles"]
        assert preview.render_previews(tmp_path, stats, size=64)[0].triangles == expected

    def test_writes_images_when_out_dir_given(self, tmp_path):
        stats = write_geometry(tmp_path / "geo", "pf_x", lods=("high", "low"))
        out = tmp_path / "png"
        preview.render_previews(tmp_path / "geo", stats, size=64, out_dir=out)
        assert (out / "high_solid.png").is_file()
        assert (out / "low_wire.png").is_file()

    def test_no_geometry_returns_empty(self, tmp_path):
        assert preview.render_previews(tmp_path, [], size=64) == []

    def test_shared_scale_across_levels(self, tmp_path):
        # Alle Stufen muessen denselben Massstab haben, sonst kaschiert der
        # Zoom genau den Silhouettenverlust, den man sehen will.
        import numpy as np

        stats = write_geometry(tmp_path, "pf_x")
        previews = preview.render_previews(tmp_path, stats, size=128)
        widths = []
        for p in previews:
            alpha = np.asarray(p.solid)[:, :, 3]
            columns = np.where(alpha.any(axis=0))[0]
            widths.append(columns.max() - columns.min())
        # Die reduzierte Kugel ist etwas kleiner, aber nicht drastisch -
        # ein Massstabsfehler wuerde sich als Faktor zeigen.
        assert max(widths) - min(widths) < max(widths) * 0.25


class TestBuildSheet:
    def _previews(self, tmp_path, lods=("high", "medium", "low", "verylow")):
        stats = write_geometry(tmp_path, "pf_x", lods=lods)
        return preview.render_previews(tmp_path, stats, size=128)

    def test_creates_image(self, tmp_path):
        out = preview.build_sheet(self._previews(tmp_path), "pf_x", tmp_path / "s.png")
        assert out.is_file()
        with Image.open(out) as img:
            assert img.width > img.height

    def test_width_scales_with_level_count(self, tmp_path):
        four = self._previews(tmp_path / "a")
        two = self._previews(tmp_path / "b", lods=("high", "low"))
        wide = preview.build_sheet(four, "pf_x", tmp_path / "w.png", cell=80)
        narrow = preview.build_sheet(two, "pf_x", tmp_path / "n.png", cell=80)
        with Image.open(wide) as w, Image.open(narrow) as n:
            assert w.width > n.width

    def test_empty_input_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="Keine Vorschaubilder"):
            preview.build_sheet([], "pf_x", tmp_path / "x.png")

    def test_creates_parent_directory(self, tmp_path):
        previews = self._previews(tmp_path)
        out = preview.build_sheet(previews, "pf_x", tmp_path / "neu" / "tief" / "s.png")
        assert out.is_file()


class TestBuildAll:
    def _result(self, root, names):
        props = []
        for name in names:
            stats = write_geometry(root / name, name, lods=("high", "low"))
            props.append({"name": name, "previews": stats})
        return {"props": props}

    def test_one_sheet_per_prop(self, tmp_path):
        root = tmp_path / "renders"
        result = self._result(root, ["pf_a", "pf_b"])
        sheets = preview.build_all(root, result, tmp_path / "out")
        assert len(sheets) == 2
        assert all(s.is_file() for s in sheets)

    def test_skips_props_without_previews(self, tmp_path):
        result = {"props": [{"name": "pf_a", "previews": []}]}
        assert preview.build_all(tmp_path, result, tmp_path / "out") == []

    def test_empty_result_is_fine(self, tmp_path):
        assert preview.build_all(tmp_path, {}, tmp_path / "out") == []


class TestFont:
    def test_returns_usable_font(self):
        assert preview._font(16) is not None
