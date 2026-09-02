import pytest
from PIL import Image

from propforge import validate
from propforge.config import (
    CollisionSettings,
    LodSettings,
    PipelineConfig,
    PropSpec,
    TextureSet,
)


@pytest.fixture
def assets(tmp_path):
    mesh = tmp_path / "prop.glb"
    mesh.write_bytes(b"glTF fake")
    Image.new("RGB", (1024, 1024)).save(tmp_path / "d.png")
    Image.new("RGB", (1024, 1024)).save(tmp_path / "n.png")
    Image.new("L", (1024, 1024)).save(tmp_path / "r.png")
    return tmp_path


def make_spec(assets, **overrides) -> PropSpec:
    base = dict(
        name="pf_crate",
        mesh=str(assets / "prop.glb"),
        textures=TextureSet(
            diffuse=str(assets / "d.png"),
            normal=str(assets / "n.png"),
            roughness=str(assets / "r.png"),
        ),
    )
    base.update(overrides)
    return PropSpec(**base)


def codes(findings, level=None):
    return {f.code for f in findings if level is None or f.level is level}


class TestNames:
    def test_valid_name_passes(self, assets):
        assert "name_invalid" not in codes(validate.validate_prop(make_spec(assets)))

    @pytest.mark.parametrize("name", ["PF_Crate", "pf crate", "9crate", "pf", "pf-crate", "pf.crate"])
    def test_invalid_names_rejected(self, assets, name):
        assert "name_invalid" in codes(validate.validate_prop(make_spec(assets, name=name)))

    def test_duplicate_names_flagged(self, assets):
        config = PipelineConfig(
            resource_name="r", author="a", workdir=assets,
            props=[make_spec(assets), make_spec(assets)],
        )
        assert "name_duplicate" in codes(validate.validate(config))


class TestFiles:
    def test_missing_mesh(self, assets):
        spec = make_spec(assets, mesh=str(assets / "nope.glb"))
        assert "mesh_missing" in codes(validate.validate_prop(spec))

    def test_unsupported_mesh_format(self, assets):
        bad = assets / "prop.blend"
        bad.write_bytes(b"x")
        spec = make_spec(assets, mesh=str(bad))
        assert "mesh_format" in codes(validate.validate_prop(spec))

    def test_missing_texture(self, assets):
        spec = make_spec(assets)
        spec.textures.diffuse = str(assets / "gone.png")
        assert "texture_missing" in codes(validate.validate_prop(spec))


class TestShaderSamplerMatching:
    def test_normal_spec_without_normal_map_errors(self, assets):
        spec = make_spec(assets)
        spec.textures.normal = None
        found = codes(validate.validate_prop(spec), validate.Level.ERROR)
        assert "sampler_missing" in found

    def test_roughness_satisfies_spec_sampler(self, assets):
        # Specular wird aus Roughness abgeleitet, muss also nicht direkt vorliegen.
        spec = make_spec(assets)
        assert "sampler_missing" not in codes(validate.validate_prop(spec))

    def test_default_shader_needs_only_diffuse(self, assets):
        spec = make_spec(assets, shader="default.sps")
        spec.textures.normal = None
        spec.textures.roughness = None
        assert "sampler_missing" not in codes(validate.validate_prop(spec))

    def test_unknown_shader_warns(self, assets):
        spec = make_spec(assets, shader="vehicle_paint1.sps")
        assert "shader_unknown" in codes(validate.validate_prop(spec), validate.Level.WARNING)


class TestLods:
    def test_ascending_ratios_rejected(self, assets):
        lods = LodSettings(ratios={"high": 0.2, "medium": 0.8})
        assert "lod_ratio_order" in codes(validate.validate_prop(make_spec(assets, lods=lods)))

    def test_descending_distances_rejected(self, assets):
        lods = LodSettings(
            ratios={"high": 1.0, "medium": 0.5},
            distances={"high": 300.0, "medium": 100.0},
        )
        assert "lod_dist_order" in codes(validate.validate_prop(make_spec(assets, lods=lods)))

    def test_ratio_out_of_range(self, assets):
        lods = LodSettings(ratios={"high": 1.5})
        assert "lod_ratio_range" in codes(validate.validate_prop(make_spec(assets, lods=lods)))

    def test_missing_high_lod(self, assets):
        lods = LodSettings(ratios={"medium": 0.5}, distances={"medium": 100.0})
        assert "lod_no_high" in codes(validate.validate_prop(make_spec(assets, lods=lods)))

    def test_defaults_are_valid(self, assets):
        assert not validate.has_errors(validate.validate_prop(make_spec(assets)))


class TestCollision:
    def test_source_lod_must_exist(self, assets):
        spec = make_spec(assets, collision=CollisionSettings(source_lod="veryhigh"))
        assert "collision_source_lod" in codes(validate.validate_prop(spec))

    def test_unknown_kind(self, assets):
        spec = make_spec(assets, collision=CollisionSettings(kind="sphere"))
        assert "collision_kind" in codes(validate.validate_prop(spec))

    def test_disabled_collision_warns_only(self, assets):
        spec = make_spec(assets, collision=CollisionSettings(enabled=False))
        findings = validate.validate_prop(spec)
        assert "collision_disabled" in codes(findings, validate.Level.WARNING)
        assert not validate.has_errors(findings)


class TestTextureSize:
    def test_non_power_of_two_rejected(self, assets):
        assert "texture_size_invalid" in codes(validate.validate_prop(make_spec(assets, texture_size=1000)))

    def test_oversized_source_warns(self, assets):
        Image.new("RGB", (4096, 4096)).save(assets / "huge.png")
        spec = make_spec(assets, texture_size=512)
        spec.textures.diffuse = str(assets / "huge.png")
        assert "texture_oversized" in codes(validate.validate_prop(spec), validate.Level.WARNING)


class TestPipelineLevel:
    def test_bad_export_format(self, assets):
        config = PipelineConfig(
            resource_name="r", author="a", workdir=assets,
            props=[make_spec(assets)], export_format="BINARY",
        )
        assert "export_format" in codes(validate.validate(config), validate.Level.ERROR)

    def test_native_export_emits_pymateria_note(self, assets):
        config = PipelineConfig(
            resource_name="r", author="a", workdir=assets,
            props=[make_spec(assets)], export_format="NATIVE",
        )
        assert "native_requires_pymateria" in codes(validate.validate(config), validate.Level.INFO)

    def test_clean_config_has_no_errors(self, assets):
        config = PipelineConfig(
            resource_name="r", author="a", workdir=assets,
            props=[make_spec(assets)], export_format="CWXML",
        )
        assert not validate.has_errors(validate.validate(config))
