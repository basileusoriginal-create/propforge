"""Tests fuer die Kollisionsmaterialien.

Das Material ist kein Kosmetikfeld: ohne eines verwirft der Export die
Kollision und man laeuft durch den Prop. Entsprechend muss der Name stimmen,
bevor Blender ueberhaupt startet - und der Vorschlag beim Import muss etwas
taugen, damit niemand aus Bequemlichkeit DEFAULT stehen laesst.
"""

import pytest

from propforge import collision_materials as cm
from propforge import validate as pf_validate
from propforge.config import CollisionSettings, PipelineConfig, PropSpec, TextureSet
from propforge.validate import Level


def make_spec(**overrides):
    base = dict(
        name="pf_crate",
        mesh="crate.glb",
        textures=TextureSet(diffuse="d.png"),
    )
    base.update(overrides)
    return PropSpec(**base)


def codes(findings, level=None):
    return {f.code for f in findings if level is None or f.level is level}


class TestList:
    def test_names_are_unique(self):
        names = [m.name for m in cm.MATERIALS]
        assert len(names) == len(set(names))

    def test_every_material_has_a_usage_note(self):
        # Der ganze Zweck der Liste. Ein leerer Eintrag waere eine Luecke,
        # die beim Nachschlagen genau dann auffaellt, wenn man sie braucht.
        empty = [m.name for m in cm.MATERIALS if not m.usage.strip()]
        assert empty == []

    def test_by_name_covers_everything(self):
        assert len(cm.BY_NAME) == len(cm.MATERIALS)

    def test_default_exists(self):
        assert cm.DEFAULT_MATERIAL in cm.BY_NAME

    def test_keywords_point_at_real_materials(self):
        # Ein Stichwort, das auf ein nicht existierendes Material zeigt,
        # produziert einen Vorschlag, den die Pruefung sofort ablehnt.
        broken = [(k, v) for k, v in cm.KEYWORDS if v not in cm.BY_NAME]
        assert broken == []


class TestSuggest:
    @pytest.mark.parametrize("name,expected", [
        ("pf_desk", "WOOD_SOLID_MEDIUM"),
        ("office_table_oak", "WOOD_SOLID_MEDIUM"),
        ("rusty_dumpster_01", "METAL_HOLLOW_LARGE"),
        ("street_cone", "PLASTIC_HOLLOW"),
        ("shop_window", "GLASS_SHOOT_THROUGH"),
        ("stone_bench", "WOOD_SOLID_MEDIUM"),
    ])
    def test_guesses_from_name(self, name, expected):
        assert cm.suggest(name)[0] == expected

    def test_longer_keyword_wins(self):
        # "cardboard" ist spezifischer als "board" - ohne Laengenregel
        # entschiede die Reihenfolge in der Tabelle.
        material, keyword = cm.suggest("cardboard_box_stack")
        assert material == "CARDBOARD_BOX"
        assert keyword in {"cardboard", "carton"}

    def test_no_hint_gives_default_and_says_so(self):
        material, keyword = cm.suggest("zzz_object_17")
        assert material == cm.DEFAULT_MATERIAL
        assert keyword is None

    def test_uses_all_hints(self):
        assert cm.suggest("prop_a", "wooden_chair.glb")[0] == "WOOD_SOLID_SMALL"

    def test_is_case_insensitive(self):
        assert cm.suggest("PF_DESK_LARGE")[0] == "WOOD_SOLID_MEDIUM"


class TestSearchAndReference:
    def test_search_finds_by_name(self):
        assert any(m.name == "WOOD_SOLID_MEDIUM" for m in cm.search("wood_solid"))

    def test_search_finds_by_description(self):
        assert any(m.name == "MARBLE" for m in cm.search("marmor"))

    def test_search_is_case_insensitive(self):
        assert cm.search("HOLZ") == cm.search("holz")

    def test_reference_lists_every_material(self):
        text = cm.render_reference()
        for m in cm.MATERIALS:
            assert m.name in text

    def test_reference_groups_by_category(self):
        text = cm.render_reference()
        for category in cm.categories():
            assert category.upper() in text


class TestValidation:
    def _config(self, spec):
        from pathlib import Path
        return PipelineConfig(resource_name="r", author="a", workdir=Path("."), props=[spec])

    def test_known_material_passes(self):
        spec = make_spec(collision=CollisionSettings(material="WOOD_SOLID_MEDIUM"))
        assert "collision_material_unknown" not in codes(pf_validate.validate_prop(spec))

    def test_unknown_material_is_an_error(self):
        # Muss vor Blender auffallen: sonst laufen Texturaufbereitung und
        # Import umsonst, bevor der Fehler zuschlaegt.
        spec = make_spec(collision=CollisionSettings(material="HOLZ"))
        found = pf_validate.validate_prop(spec)
        assert "collision_material_unknown" in codes(found, Level.ERROR)

    def test_error_suggests_alternatives(self):
        spec = make_spec(collision=CollisionSettings(material="WOOD_MASSIV"))
        message = " ".join(f.message for f in pf_validate.validate_prop(spec))
        assert "WOOD_SOLID_MEDIUM" in message

    def test_ped_material_warns(self):
        spec = make_spec(collision=CollisionSettings(material="HEAD"))
        found = pf_validate.validate_prop(spec)
        assert "collision_material_unsuitable" in codes(found, Level.WARNING)

    def test_material_not_checked_when_collision_off(self):
        spec = make_spec(collision=CollisionSettings(enabled=False, material="QUATSCH"))
        assert "collision_material_unknown" not in codes(pf_validate.validate_prop(spec))


class TestProfiles:
    """Die Groessenklassen. Die Zahlen stammen aus den FiveM-Leitfaeden und
    den ueblichen Polycount-Baendern - nicht aus dem Bauch."""

    def _prop(self, **extra):
        raw = {
            "pipeline": {"resource_name": "r"},
            "prop": [{"name": "pf_x", "mesh": "m.glb",
                      "textures": {"diffuse": "d.png"}, **extra}],
        }
        return PipelineConfig.from_dict(raw).props[0]

    def test_default_is_standard(self):
        spec = self._prop()
        assert spec.profile == "standard"
        assert spec.max_tris == 4000
        assert spec.texture_size == 512

    def test_clutter_is_smaller_in_every_dimension(self):
        clutter, standard = self._prop(profile="clutter"), self._prop()
        assert clutter.max_tris < standard.max_tris
        assert clutter.texture_size < standard.texture_size
        # Was klein ist, muss nicht weit gerendert werden.
        assert clutter.lods.distances["verylow"] < standard.lods.distances["verylow"]

    def test_explicit_value_beats_profile(self):
        spec = self._prop(profile="clutter", texture_size=1024)
        assert spec.texture_size == 1024
        assert spec.max_tris == 1500

    def test_unknown_profile_is_rejected_by_name(self):
        from propforge.config import ConfigError

        with pytest.raises(ConfigError, match="clutter"):
            self._prop(profile="riesig")

    def test_profiles_are_ordered_by_budget(self):
        from propforge.config import PROFILES

        order = [PROFILES[n].max_tris for n in ("clutter", "standard", "detailed", "hero")]
        assert order == sorted(order)

    def test_every_profile_has_all_four_distances(self):
        from propforge.config import LOD_LEVELS, PROFILES

        for profile in PROFILES.values():
            assert set(profile.distances) == set(LOD_LEVELS)
            values = [profile.distances[l] for l in LOD_LEVELS]
            assert values == sorted(values), profile.name

    def test_over_budget_warns(self):
        from propforge import validate as v

        found = v.validate_prop(self._prop(profile="clutter", max_tris=9000))
        assert "budget_tris" in {f.code for f in found}

    def test_within_budget_is_quiet(self):
        from propforge import validate as v

        found = {f.code for f in v.validate_prop(self._prop())}
        assert "budget_tris" not in found and "budget_texture" not in found


class TestTextureMemory:
    def test_matches_published_figures(self):
        # Gegenprobe an den veroeffentlichten Werten: 1024er DXT1 mit
        # Mipmaps rund 0,7 MiB, 2048er rund 2,7 MiB.
        from propforge.config import texture_memory

        assert 0.6 < texture_memory(1024, 1) / 1024 / 1024 < 0.75
        assert 2.5 < texture_memory(2048, 1) / 1024 / 1024 < 2.9

    # Die Vergleiche laufen ueber ein Verhaeltnis, nicht ueber Gleichheit:
    # das Ergebnis wird auf ganze Bytes abgeschnitten, und exakte Gleichheit
    # scheitert dann an einem einzelnen Byte. Geprueft gehoert die Aussage,
    # nicht die Rundung.
    def test_alpha_costs_double(self):
        from propforge.config import texture_memory

        assert texture_memory(512, 1, with_alpha=1) / texture_memory(512, 1) == pytest.approx(2.0, rel=1e-4)

    def test_scales_with_role_count(self):
        from propforge.config import texture_memory

        assert texture_memory(512, 3) / texture_memory(512, 1) == pytest.approx(3.0, rel=1e-4)

    def test_large_texture_set_warns(self):
        from propforge import validate as v
        from propforge.config import PipelineConfig as PC

        raw = {"pipeline": {"resource_name": "r"},
               "prop": [{"name": "pf_x", "mesh": "m.glb", "profile": "hero",
                         "texture_size": 2048,
                         "textures": {"diffuse": "d.png", "normal": "n.png",
                                      "roughness": "r.png"}}]}
        found = {f.code for f in v.validate_prop(PC.from_dict(raw).props[0])}
        assert "texture_memory" in found


class TestConfigMerge:
    def _config(self, prop_extra: dict):
        raw = {
            "pipeline": {"resource_name": "r"},
            "defaults": {"collision": {"kind": "hull", "source_lod": "medium"}},
            "prop": [{
                "name": "pf_crate", "mesh": "c.glb",
                "textures": {"diffuse": "d.png"},
                **prop_extra,
            }],
        }
        return PipelineConfig.from_dict(raw).props[0]

    def test_prop_table_does_not_wipe_defaults(self):
        # Wer nur das Material setzt, darf nicht lautlos die konfigurierte
        # Kollisionsart verlieren. Genau das ist beim Tisch passiert.
        spec = self._config({"collision": {"material": "WOOD_SOLID_MEDIUM"}})
        assert spec.collision.material == "WOOD_SOLID_MEDIUM"
        assert spec.collision.kind == "hull"
        assert spec.collision.source_lod == "medium"

    def test_prop_value_wins_over_default(self):
        spec = self._config({"collision": {"kind": "bvh"}})
        assert spec.collision.kind == "bvh"
        assert spec.collision.source_lod == "medium"

    def test_defaults_alone_still_apply(self):
        spec = self._config({})
        assert spec.collision.kind == "hull"

    def test_material_is_normalised_to_upper_case(self):
        spec = self._config({"collision": {"material": "wood_solid_medium"}})
        assert spec.collision.material == "WOOD_SOLID_MEDIUM"
