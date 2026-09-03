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
