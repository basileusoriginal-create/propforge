import numpy as np
import pytest
from PIL import Image

from propforge import textures
from propforge.config import PropSpec, TextureSet


class TestPowerOfTwo:
    @pytest.mark.parametrize(
        "value,expected",
        [(1000, 1024), (1025, 1024), (700, 512), (1500, 2048), (3000, 2048), (1, 16), (512, 512)],
    )
    def test_nearest(self, value, expected):
        assert textures.nearest_power_of_two(value) == expected

    def test_respects_maximum(self):
        assert textures.nearest_power_of_two(4000, maximum=512) == 512

    def test_resizes_non_square(self):
        img = Image.new("RGB", (1000, 300))
        out = textures.to_power_of_two(img)
        assert out.size == (1024, 256)

    def test_leaves_valid_untouched(self):
        img = Image.new("RGB", (512, 128))
        assert textures.to_power_of_two(img) is img


class TestSpecular:
    def test_inverts_roughness(self):
        # Vollstaendig rau -> matt -> Specular nahe 0
        rough = Image.new("L", (8, 8), color=255)
        spec = textures.build_specular(rough, None, (8, 8))
        assert np.asarray(spec.convert("L")).max() == 0

        # Vollstaendig glatt -> Specular maximal
        smooth = Image.new("L", (8, 8), color=0)
        spec = textures.build_specular(smooth, None, (8, 8))
        assert np.asarray(spec.convert("L")).min() == 255

    def test_metallic_lifts_dull_surfaces(self):
        rough = Image.new("L", (8, 8), color=255)  # spec waere 0
        metal = Image.new("L", (8, 8), color=255)
        spec = textures.build_specular(rough, metal, (8, 8))
        # Metall darf nicht bei 0 landen, sonst wirkt es im Spiel wie Plastik
        assert np.asarray(spec.convert("L")).mean() == pytest.approx(255 * 0.6, abs=2)

    def test_dielectric_unchanged_by_metallic_channel(self):
        rough = Image.new("L", (8, 8), color=64)
        no_metal = Image.new("L", (8, 8), color=0)
        without = np.asarray(textures.build_specular(rough, None, (8, 8)).convert("L"))
        with_zero = np.asarray(textures.build_specular(rough, no_metal, (8, 8)).convert("L"))
        assert np.array_equal(without, with_zero)

    def test_requires_at_least_one_input(self):
        with pytest.raises(textures.TextureError):
            textures.build_specular(None, None, (8, 8))

    def test_resizes_to_target(self):
        rough = Image.new("L", (16, 16), color=128)
        assert textures.build_specular(rough, None, (64, 32)).size == (64, 32)


class TestNormalMap:
    def test_flips_green_channel(self):
        img = Image.new("RGB", (4, 4), color=(128, 200, 255))
        out = np.asarray(textures.convert_normal_map(img, flip_green=True))
        assert out[0, 0, 0] == 128           # rot unveraendert
        assert out[0, 0, 1] == 255 - 200     # gruen invertiert
        assert out[0, 0, 2] == 255           # blau unveraendert

    def test_noop_when_disabled(self):
        img = Image.new("RGB", (4, 4), color=(128, 200, 255))
        out = np.asarray(textures.convert_normal_map(img, flip_green=False))
        assert tuple(out[0, 0]) == (128, 200, 255)

    def test_double_flip_is_identity(self):
        img = Image.new("RGB", (4, 4), color=(10, 77, 200))
        once = textures.convert_normal_map(img, True)
        twice = textures.convert_normal_map(once, True)
        assert np.array_equal(np.asarray(img), np.asarray(twice))


class TestAlphaDetection:
    def test_opaque_alpha_is_ignored(self):
        img = Image.new("RGBA", (8, 8), color=(255, 0, 0, 255))
        assert textures.has_meaningful_alpha(img) is False

    def test_real_transparency_detected(self):
        img = Image.new("RGBA", (8, 8), color=(255, 0, 0, 255))
        img.putpixel((0, 0), (255, 0, 0, 0))
        assert textures.has_meaningful_alpha(img) is True

    def test_rgb_has_no_alpha(self):
        assert textures.has_meaningful_alpha(Image.new("RGB", (8, 8))) is False


class TestPrepare:
    def _spec(self, tmp_path, **kwargs):
        Image.new("RGB", (900, 900), color=(120, 120, 120)).save(tmp_path / "d.png")
        Image.new("RGB", (900, 900), color=(128, 128, 255)).save(tmp_path / "n.png")
        Image.new("L", (900, 900), color=200).save(tmp_path / "r.png")
        return PropSpec(
            name="pf_test",
            mesh=str(tmp_path / "m.glb"),
            textures=TextureSet(
                diffuse=str(tmp_path / "d.png"),
                normal=str(tmp_path / "n.png"),
                roughness=str(tmp_path / "r.png"),
            ),
            texture_size=512,
            **kwargs,
        )

    def test_produces_three_maps_at_target_size(self, tmp_path):
        out = tmp_path / "out"
        prepared = textures.prepare(self._spec(tmp_path), out)
        roles = {p.role for p in prepared}
        assert roles == {"diffuse", "normal", "specular"}
        for p in prepared:
            with Image.open(p.path) as img:
                assert img.size == (512, 512)

    def test_diffuse_without_alpha_uses_dxt1(self, tmp_path):
        prepared = textures.prepare(self._spec(tmp_path), tmp_path / "out")
        diffuse = next(p for p in prepared if p.role == "diffuse")
        assert diffuse.dds_format == textures.DDS_FORMATS["diffuse"]

    def test_normal_always_uses_dxt5(self, tmp_path):
        prepared = textures.prepare(self._spec(tmp_path), tmp_path / "out")
        normal = next(p for p in prepared if p.role == "normal")
        assert normal.dds_format == "BC3_UNORM"

    def test_transparent_diffuse_switches_to_dxt5(self, tmp_path):
        img = Image.new("RGBA", (512, 512), color=(255, 0, 0, 255))
        img.putpixel((0, 0), (255, 0, 0, 0))
        img.save(tmp_path / "cutout.png")
        spec = self._spec(tmp_path)
        spec.textures.diffuse = str(tmp_path / "cutout.png")
        prepared = textures.prepare(spec, tmp_path / "out")
        diffuse = next(p for p in prepared if p.role == "diffuse")
        assert diffuse.dds_format == "BC3_UNORM"

    def test_compress_without_texconv_raises(self, tmp_path):
        prepared = textures.prepare(self._spec(tmp_path), tmp_path / "out")
        with pytest.raises(textures.TextureError, match="texconv"):
            textures.compress(prepared, tmp_path / "dds", texconv=None)
