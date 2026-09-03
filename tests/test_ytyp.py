"""Tests fuer die Archetyp-Definition (.ytyp).

Warum das eine eigene Datei ist: die .ytyp entscheidet, ob der Prop im Spiel
ueberhaupt existiert. Eine .ydr ohne passenden Archetyp ist Geometrie, die
niemand referenzieren kann - und der Fehler ist stumm: alle Dateien sind
gueltig, der Export meldet Erfolg, im Spiel passiert nichts.

Die XML-Fixture bildet die CodeWalker-Struktur einer ytyp nach. Sie benutzt
die Feldnamen des Spiels (camelCase: lodDist, assetName), nicht die
PascalCase-Namen der .ydr - das ist der Unterschied, der beim Parsen leicht
untergeht.
"""

import pytest

from propforge import inspect as pf_inspect
from propforge import verify as pf_verify
from propforge.config import (
    CollisionSettings,
    LodSettings,
    PipelineConfig,
    PropSpec,
    TextureSet,
    YtypSettings,
)
from propforge.validate import Level


def make_ytyp_xml(
    ytyp_name="pf_crate_ityp",
    archetypes=(("pf_crate", "pf_crate", "ASSET_TYPE_DRAWABLE", 500, 32, "", "pf_crate"),),
):
    items = "".join(
        f"""
    <Item type="CBaseArchetypeDef">
      <lodDist value="{lod_dist}.00000000" />
      <flags value="{flags}" />
      <specialAttribute value="0" />
      <bbMin x="-0.5" y="-0.5" z="0.0" />
      <bbMax x="0.5" y="0.5" z="1.0" />
      <bsCentre x="0.0" y="0.0" z="0.5" />
      <bsRadius value="0.87" />
      <hdTextureDist value="100.00000000" />
      <name>{name}</name>
      {f"<textureDictionary>{txd}</textureDictionary>" if txd else "<textureDictionary />"}
      <clipDictionary />
      <drawableDictionary />
      {f"<physicsDictionary>{phys}</physicsDictionary>" if phys else "<physicsDictionary />"}
      <assetType>{asset_type}</assetType>
      <assetName>{asset_name}</assetName>
      <extensions />
    </Item>"""
        for name, asset_name, asset_type, lod_dist, flags, txd, phys in archetypes
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<CMapTypes>
  <extensions />
  <archetypes>{items}
  </archetypes>
  <name>{ytyp_name}</name>
  <dependencies />
  <compositeEntityTypes />
</CMapTypes>"""


def write_ytyp(directory, **kwargs):
    name = kwargs.get("ytyp_name", "pf_crate_ityp")
    path = directory / f"{name}.ytyp.xml"
    path.write_text(make_ytyp_xml(**kwargs), encoding="utf-8")
    return path


def make_spec(**overrides):
    base = dict(
        name="pf_crate",
        mesh="crate.glb",
        textures=TextureSet(diffuse="d.png", normal="n.png", roughness="r.png"),
    )
    base.update(overrides)
    return PropSpec(**base)


def codes(findings, level=None):
    return {f.code for f in findings if level is None or f.level is level}


class TestParseYtyp:
    def test_reads_ytyp_name_not_archetype_name(self, tmp_path):
        info = pf_inspect.parse_ytyp(write_ytyp(tmp_path))
        # Der Name der ytyp steht als direktes Kind der Wurzel - der gleich
        # lautende Tag innerhalb eines Archetyps darf ihn nicht ueberschreiben.
        assert info.name == "pf_crate_ityp"

    def test_reads_archetype_fields(self, tmp_path):
        info = pf_inspect.parse_ytyp(write_ytyp(tmp_path))
        assert len(info.archetypes) == 1
        a = info.archetypes[0]
        assert a.name == "pf_crate"
        assert a.asset_name == "pf_crate"
        assert a.asset_type == "ASSET_TYPE_DRAWABLE"
        assert a.lod_dist == 500.0
        assert a.flags == 32
        assert a.physics_dictionary == "pf_crate"
        assert a.texture_dictionary == ""

    def test_reads_multiple_archetypes(self, tmp_path):
        path = write_ytyp(tmp_path, archetypes=(
            ("a", "a", "ASSET_TYPE_DRAWABLE", 500, 32, "", "a"),
            ("b", "b", "ASSET_TYPE_DRAWABLE", 300, 32, "", ""),
        ))
        info = pf_inspect.parse_ytyp(path)
        assert [a.name for a in info.archetypes] == ["a", "b"]
        assert info.archetypes[1].lod_dist == 300.0

    def test_tag_case_is_irrelevant(self, tmp_path):
        # Sollte szio je PascalCase schreiben, darf der Parser nicht umkippen.
        xml = make_ytyp_xml().replace("lodDist", "LodDist").replace("assetName", "AssetName")
        path = tmp_path / "pf_crate_ityp.ytyp.xml"
        path.write_text(xml, encoding="utf-8")
        info = pf_inspect.parse_ytyp(path)
        assert info.archetypes[0].lod_dist == 500.0
        assert info.archetypes[0].asset_name == "pf_crate"

    def test_rejects_wrong_root(self, tmp_path):
        bad = tmp_path / "bad.ytyp.xml"
        bad.write_text("<Drawable><Name>x</Name></Drawable>")
        with pytest.raises(pf_inspect.InspectError, match="CMapTypes"):
            pf_inspect.parse_ytyp(bad)

    def test_rejects_broken_xml(self, tmp_path):
        bad = tmp_path / "bad.ytyp.xml"
        bad.write_text("<CMapTypes><name>x")
        with pytest.raises(pf_inspect.InspectError, match="gueltiges XML"):
            pf_inspect.parse_ytyp(bad)

    def test_summary_names_archetype(self, tmp_path):
        info = pf_inspect.parse_ytyp(write_ytyp(tmp_path))
        assert "pf_crate" in info.summary()

    def test_find_ytyps(self, tmp_path):
        nested = tmp_path / "build" / "pf_crate"
        nested.mkdir(parents=True)
        write_ytyp(nested)
        assert len(pf_inspect.find_ytyps(tmp_path)) == 1


class TestYtypSettings:
    def test_default_name_is_derived(self):
        assert make_spec().ytyp_name() == "pf_crate_ityp"

    def test_explicit_name_wins(self):
        spec = make_spec(ytyp=YtypSettings(name="meine_props"))
        assert spec.ytyp_name() == "meine_props"

    def test_lod_dist_derived_from_furthest_lod(self):
        # Ohne Ableitung stuende hier Sollumz' Vorgabe 200 - der Prop wuerde
        # ausblenden, obwohl noch LOD-Geometrie fuer 500 m exportiert wurde.
        spec = make_spec(lods=LodSettings(distances={
            "high": 60.0, "medium": 120.0, "low": 250.0, "verylow": 800.0}))
        assert spec.archetype_lod_dist() == 800.0

    def test_explicit_lod_dist_wins(self):
        spec = make_spec(ytyp=YtypSettings(lod_dist=123.0))
        assert spec.archetype_lod_dist() == 123.0

    def test_job_carries_ytyp_block(self, tmp_path):
        job = make_spec().to_job(tmp_path)
        assert job["ytyp"]["enabled"] is True
        assert job["ytyp"]["name"] == "pf_crate_ityp"
        assert job["ytyp"]["lod_dist"] == 500.0
        assert job["ytyp"]["flags"] == 32

    def test_config_parses_ytyp_section(self):
        from propforge.config import PipelineConfig as PC

        raw = {
            "pipeline": {"resource_name": "r"},
            "prop": [{
                "name": "pf_crate",
                "mesh": "c.glb",
                "textures": {"diffuse": "d.png"},
                "ytyp": {"name": "custom", "flags": 0, "lod_dist": 42.0,
                         "hd_texture_dist": 5.0, "texture_dictionary": "shared_txd"},
            }],
        }
        spec = PC.from_dict(raw).props[0]
        assert spec.ytyp_name() == "custom"
        assert spec.ytyp.flags == 0
        assert spec.archetype_lod_dist() == 42.0
        assert spec.ytyp.hd_texture_dist == 5.0
        assert spec.ytyp.texture_dictionary == "shared_txd"

    def test_ytyp_can_be_disabled(self):
        from propforge.config import PipelineConfig as PC

        raw = {
            "pipeline": {"resource_name": "r"},
            "prop": [{"name": "p", "mesh": "c.glb", "textures": {"diffuse": "d.png"},
                      "ytyp": {"enabled": False}}],
        }
        assert PC.from_dict(raw).props[0].ytyp.enabled is False


class TestVerifyYtyp:
    def _info(self, tmp_path, **kwargs):
        return pf_inspect.parse_ytyp(write_ytyp(tmp_path, **kwargs))

    def test_matching_ytyp_is_clean(self, tmp_path):
        assert pf_verify.verify_ytyp(make_spec(), self._info(tmp_path), None) == []

    def test_missing_archetype_flagged(self, tmp_path):
        info = self._info(tmp_path, archetypes=(
            ("etwas_anderes", "etwas_anderes", "ASSET_TYPE_DRAWABLE", 500, 32, "", ""),))
        assert "archetype_missing" in codes(pf_verify.verify_ytyp(make_spec(), info, None))

    def test_asset_name_mismatch_flagged(self, tmp_path):
        # Der teuerste stille Fehler: die Datei ist gueltig, der Verweis zeigt
        # aber auf eine .ydr, die es nicht gibt.
        info = self._info(tmp_path, archetypes=(
            ("pf_crate", "pf_kiste", "ASSET_TYPE_DRAWABLE", 500, 32, "", "pf_crate"),))
        assert "archetype_asset_mismatch" in codes(pf_verify.verify_ytyp(make_spec(), info, None))

    def test_wrong_asset_type_flagged(self, tmp_path):
        info = self._info(tmp_path, archetypes=(
            ("pf_crate", "pf_crate", "ASSET_TYPE_ASSETLESS", 500, 32, "", "pf_crate"),))
        assert "archetype_asset_type" in codes(pf_verify.verify_ytyp(make_spec(), info, None))

    def test_wrong_lod_dist_flagged(self, tmp_path):
        info = self._info(tmp_path, archetypes=(
            ("pf_crate", "pf_crate", "ASSET_TYPE_DRAWABLE", 200, 32, "", "pf_crate"),))
        found = codes(pf_verify.verify_ytyp(make_spec(), info, None))
        assert "archetype_lod_dist" in found
        assert "archetype_lod_dist_below_lods" in found

    def test_flags_mismatch_warns(self, tmp_path):
        info = self._info(tmp_path, archetypes=(
            ("pf_crate", "pf_crate", "ASSET_TYPE_DRAWABLE", 500, 0, "", "pf_crate"),))
        found = pf_verify.verify_ytyp(make_spec(), info, None)
        assert "archetype_flags" in codes(found, Level.WARNING)

    def test_missing_physics_dictionary_flagged(self, tmp_path):
        # Kollision ist eingebettet, aber nicht referenziert: der Prop haette
        # im Spiel keine Kollision, ohne dass eine Datei fehlt.
        info = self._info(tmp_path, archetypes=(
            ("pf_crate", "pf_crate", "ASSET_TYPE_DRAWABLE", 500, 32, "", ""),))
        assert "archetype_physics_dictionary" in codes(
            pf_verify.verify_ytyp(make_spec(), info, None))

    def test_physics_dictionary_without_collision_warns(self, tmp_path):
        spec = make_spec(collision=CollisionSettings(enabled=False))
        found = pf_verify.verify_ytyp(spec, self._info(tmp_path), None)
        assert "archetype_physics_unexpected" in codes(found, Level.WARNING)

    def test_texture_dictionary_set_despite_embedded_warns(self, tmp_path):
        from propforge.inspect import DrawableInfo, TextureInfo

        drawable = DrawableInfo(
            name="pf_crate",
            textures=[TextureInfo("pf_crate_d", "D3DFMT_DXT1", 1024, 1024)],
        )
        info = self._info(tmp_path, archetypes=(
            ("pf_crate", "pf_crate", "ASSET_TYPE_DRAWABLE", 500, 32, "pf_crate", "pf_crate"),))
        found = pf_verify.verify_ytyp(make_spec(), info, drawable)
        assert "archetype_texture_dictionary" in codes(found, Level.WARNING)

    def test_explicit_texture_dictionary_not_second_guessed(self, tmp_path):
        from propforge.inspect import DrawableInfo, TextureInfo

        drawable = DrawableInfo(
            name="pf_crate",
            textures=[TextureInfo("pf_crate_d", "D3DFMT_DXT1", 1024, 1024)],
        )
        spec = make_spec(ytyp=YtypSettings(texture_dictionary="shared_txd"))
        info = self._info(tmp_path, archetypes=(
            ("pf_crate", "pf_crate", "ASSET_TYPE_DRAWABLE", 500, 32, "shared_txd", "pf_crate"),))
        assert "archetype_texture_dictionary" not in codes(
            pf_verify.verify_ytyp(spec, info, drawable))


class TestVerifyPipelineYtyp:
    def _config(self, workdir, **kwargs):
        return PipelineConfig(
            resource_name="r", author="a", workdir=workdir,
            props=[make_spec(**kwargs)], export_format="CWXML",
        )

    def test_missing_ytyp_flagged(self, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        found = pf_verify.verify(self._config(tmp_path), build)
        assert "ytyp_missing" in codes(found, Level.ERROR)

    def test_binary_ytyp_reported_as_info(self, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        (build / "pf_crate_ityp.ytyp").write_bytes(b"binary")
        found = pf_verify.verify(self._config(tmp_path), build)
        assert "binary_ytyp_not_inspectable" in codes(found, Level.INFO)
        assert "ytyp_missing" not in codes(found)

    def test_disabled_ytyp_is_not_demanded(self, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        config = self._config(tmp_path, ytyp=YtypSettings(enabled=False))
        assert "ytyp_missing" not in codes(pf_verify.verify(config, build))

    def test_ytyp_found_in_nested_dir(self, tmp_path):
        nested = tmp_path / "build" / "pf_crate"
        nested.mkdir(parents=True)
        write_ytyp(nested)
        found = pf_verify.verify(self._config(tmp_path), tmp_path / "build")
        assert "ytyp_missing" not in codes(found)
        assert "archetype_missing" not in codes(found)
