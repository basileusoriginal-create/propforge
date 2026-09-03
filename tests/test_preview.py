import pytest
from PIL import Image

from propforge import preview


def make_render(dir_path, name, lod, mode, color=(200, 120, 60), size=(512, 512)):
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{name}_{lod}_{mode}.png"
    Image.new("RGBA", size, color + (255,)).save(path)
    return path


def stats_for(lods, triangles, with_wire=True):
    return [
        {
            "lod": lod,
            "triangles": tris,
            "images": (
                {"solid": f"pf_x_{lod}_solid.png", "wire": f"pf_x_{lod}_wire.png"}
                if with_wire
                else {"solid": f"pf_x_{lod}_solid.png"}
            ),
        }
        for lod, tris in zip(lods, triangles)
    ]


class TestCollect:
    def test_orders_by_lod_not_by_input(self, tmp_path):
        # Die Reihenfolge im Bericht ist nicht garantiert, die Darstellung
        # muss aber immer von hoch nach niedrig laufen.
        for lod in ("verylow", "high", "low", "medium"):
            make_render(tmp_path, "pf_x", lod, "solid")
            make_render(tmp_path, "pf_x", lod, "wire")
        stats = stats_for(["verylow", "high", "low", "medium"], [80, 1000, 220, 80])
        result = preview.collect(tmp_path, "pf_x", stats)
        assert [p.lod for p in result] == ["high", "medium", "low", "verylow"]

    def test_missing_file_becomes_none(self, tmp_path):
        make_render(tmp_path, "pf_x", "high", "solid")
        stats = stats_for(["high"], [1000])
        result = preview.collect(tmp_path, "pf_x", stats)
        assert result[0].solid is not None
        assert result[0].wire is None

    def test_keeps_triangle_counts(self, tmp_path):
        make_render(tmp_path, "pf_x", "high", "solid")
        stats = stats_for(["high"], [1234])
        assert preview.collect(tmp_path, "pf_x", stats)[0].triangles == 1234

    def test_ignores_unknown_lod_names(self, tmp_path):
        stats = [{"lod": "ultra", "triangles": 5, "images": {}}]
        assert preview.collect(tmp_path, "pf_x", stats) == []


class TestBuildSheet:
    def _previews(self, tmp_path, with_wire=True):
        lods = ["high", "medium", "low", "verylow"]
        tris = [2000, 1000, 440, 160]
        for lod in lods:
            make_render(tmp_path, "pf_x", lod, "solid")
            if with_wire:
                make_render(tmp_path, "pf_x", lod, "wire")
        return preview.collect(tmp_path, "pf_x", stats_for(lods, tris, with_wire))

    def test_creates_image(self, tmp_path):
        previews = self._previews(tmp_path)
        out = preview.build_sheet(previews, "pf_x", tmp_path / "sheet.png")
        assert out.is_file()
        with Image.open(out) as img:
            assert img.width > img.height  # vier Spalten, zwei Reihen

    def test_width_scales_with_lod_count(self, tmp_path):
        four = self._previews(tmp_path)
        wide = preview.build_sheet(four, "pf_x", tmp_path / "a.png", cell=100)
        narrow = preview.build_sheet(four[:2], "pf_x", tmp_path / "b.png", cell=100)
        with Image.open(wide) as w, Image.open(narrow) as n:
            assert w.width > n.width

    def test_single_row_without_wireframes(self, tmp_path):
        with_wire = self._previews(tmp_path / "a")
        without = self._previews(tmp_path / "b", with_wire=False)
        tall = preview.build_sheet(with_wire, "pf_x", tmp_path / "tall.png", cell=100)
        flat = preview.build_sheet(without, "pf_x", tmp_path / "flat.png", cell=100)
        with Image.open(tall) as t, Image.open(flat) as f:
            assert t.height > f.height

    def test_empty_input_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="Keine Vorschaubilder"):
            preview.build_sheet([], "pf_x", tmp_path / "x.png")

    def test_handles_missing_image_gracefully(self, tmp_path):
        # Ein fehlendes Rendering darf den Kontaktbogen nicht verhindern -
        # die uebrigen Stufen sind trotzdem aussagekraeftig.
        make_render(tmp_path, "pf_x", "high", "solid")
        stats = stats_for(["high", "medium"], [100, 50])
        previews = preview.collect(tmp_path, "pf_x", stats)
        out = preview.build_sheet(previews, "pf_x", tmp_path / "sheet.png")
        assert out.is_file()

    def test_creates_parent_directory(self, tmp_path):
        previews = self._previews(tmp_path)
        out = preview.build_sheet(previews, "pf_x", tmp_path / "neu" / "tief" / "s.png")
        assert out.is_file()


class TestBuildAll:
    def test_one_sheet_per_prop(self, tmp_path):
        root = tmp_path / "renders"
        for name in ("pf_a", "pf_b"):
            d = root / name
            for lod in ("high", "low"):
                d.mkdir(parents=True, exist_ok=True)
                Image.new("RGBA", (64, 64)).save(d / f"{name}_{lod}_solid.png")
        result = {
            "props": [
                {
                    "name": name,
                    "previews": [
                        {"lod": lod, "triangles": 100,
                         "images": {"solid": f"{name}_{lod}_solid.png"}}
                        for lod in ("high", "low")
                    ],
                }
                for name in ("pf_a", "pf_b")
            ]
        }
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
        font = preview._font(16)
        assert font is not None
