"""Tests fuer die Auswertung exportierter CWXML-Assets.

Die XML-Fixtures bilden die reale CodeWalker-Struktur nach: Drawable-Wurzel,
LodDist*-Werte, ShaderGroup mit Texture-Parametern, DrawableModels*-Container
und Bounds.
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


def make_ydr_xml(
    name="pf_crate",
    shader="normal_spec.sps",
    lods=("high", "medium", "low", "verylow"),
    distances=(60, 120, 250, 500),
    samplers=("DiffuseSampler", "BumpSampler", "SpecSampler"),
    textures=(("pf_crate_d", "D3DFMT_DXT1", 1024, 1024),),
    bounds="GeometryBVH",
    geometries_per_lod=1,
    bound_children=1,
    semantics=("Position", "Normal", "Colour0", "TexCoord0", "Tangent"),
    vertices=12,
    indices=18,
):
    dist_high, dist_med, dist_low, dist_vlow = distances
    param_xml = "".join(
        f'<Item name="{s}" type="Texture"><Name>{name}_d</Name></Item>' for s in samplers
    )
    tex_xml = "".join(
        f"<Item><Name>{n}</Name><Format>{f}</Format>"
        f'<Width value="{w}" /><Height value="{h}" /></Item>'
        for n, f, w, h in textures
    )
    element_for = {
        "high": "DrawableModelsHigh",
        "medium": "DrawableModelsMedium",
        "low": "DrawableModelsLow",
        "verylow": "DrawableModelsVeryLow",
    }
    layout = "".join(f"<{s} />" for s in semantics) if semantics else ""
    vertex_rows = "\n".join("0 0 0" for _ in range(vertices))
    index_values = " ".join("0" for _ in range(indices))
    geo = "".join(
        '<Item><ShaderIndex value="0" />'
        f'<VertexBuffer><Layout type="GTAV1">{layout}</Layout>'
        f"<Data>{vertex_rows}</Data></VertexBuffer>"
        f"<IndexBuffer><Data>{index_values}</Data></IndexBuffer></Item>"
        for _ in range(geometries_per_lod)
    )
    lod_xml = "".join(
        f"<{element_for[l]}><Item><Geometries>{geo}</Geometries></Item></{element_for[l]}>"
        for l in lods
    )
    if bounds:
        kids = "".join(f'<Item type="{bounds}"><Margin value="0.04" /></Item>'
                       for _ in range(bound_children))
        bounds_xml = (f'<Bounds type="Composite"><Margin value="0.04" />'
                      f"<Children>{kids}</Children></Bounds>")
    else:
        bounds_xml = ""

    return f"""<?xml version='1.0' encoding='UTF-8'?>
<Drawable>
  <Name>{name}</Name>
  <LodDistHigh value="{dist_high}" />
  <LodDistMed value="{dist_med}" />
  <LodDistLow value="{dist_low}" />
  <LodDistVlow value="{dist_vlow}" />
  <ShaderGroup>
    <TextureDictionary>{tex_xml}</TextureDictionary>
    <Shaders>
      <Item>
        <FileName>{shader}</FileName>
        <Parameters>{param_xml}</Parameters>
      </Item>
    </Shaders>
  </ShaderGroup>
  {lod_xml}
  {bounds_xml}
</Drawable>"""


def write_ydr(tmp_path, **kwargs):
    name = kwargs.get("name", "pf_crate")
    path = tmp_path / f"{name}.ydr.xml"
    path.write_text(make_ydr_xml(**kwargs), encoding="utf-8")
    return path


class TestParseDrawable:
    def test_reads_name_and_shader(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path))
        assert info.name == "pf_crate"
        assert info.shaders == ["normal_spec.sps"]

    def test_reads_all_four_lods(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path))
        assert set(info.lods) == {"high", "medium", "low", "verylow"}
        assert info.lods["high"].distance == 60
        assert info.lods["verylow"].distance == 500

    def test_counts_geometries(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path, geometries_per_lod=3))
        assert info.lods["high"].geometries == 3

    def test_reads_vertex_semantics(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path))
        assert info.lods["high"].semantics == {
            "Position", "Normal", "Colour0", "TexCoord0", "Tangent"}

    def test_counts_vertices_and_indices(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path, vertices=30, indices=45))
        assert info.lods["high"].vertices == 30
        assert info.lods["high"].indices == 45

    def test_sums_over_multiple_geometries(self, tmp_path):
        info = pf_inspect.parse_drawable(
            write_ydr(tmp_path, geometries_per_lod=3, vertices=10, indices=12))
        assert info.lods["high"].vertices == 30
        assert info.lods["high"].indices == 36

    def test_summary_shows_semantics(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path))
        assert "TexCoord0" in info.summary()

    def test_reads_samplers(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path))
        assert set(info.samplers) == {"DiffuseSampler", "BumpSampler", "SpecSampler"}

    def test_detects_collision(self, tmp_path):
        assert pf_inspect.parse_drawable(write_ydr(tmp_path)).has_collision is True
        assert pf_inspect.parse_drawable(write_ydr(tmp_path, bounds=None)).has_collision is False

    def test_counts_bound_children(self, tmp_path):
        assert pf_inspect.parse_drawable(write_ydr(tmp_path)).bound_children == 1
        assert pf_inspect.parse_drawable(
            write_ydr(tmp_path, bound_children=0)).bound_children == 0

    def test_texture_power_of_two_flag(self, tmp_path):
        info = pf_inspect.parse_drawable(
            write_ydr(tmp_path, textures=(("t", "D3DFMT_DXT1", 1000, 1024),))
        )
        assert info.textures[0].is_power_of_two is False

    def test_rejects_wrong_root(self, tmp_path):
        bad = tmp_path / "bad.ydr.xml"
        bad.write_text("<Fragment><Name>x</Name></Fragment>")
        with pytest.raises(pf_inspect.InspectError, match="Drawable"):
            pf_inspect.parse_drawable(bad)

    def test_rejects_broken_xml(self, tmp_path):
        bad = tmp_path / "bad.ydr.xml"
        bad.write_text("<Drawable><Name>x")
        with pytest.raises(pf_inspect.InspectError, match="gueltiges XML"):
            pf_inspect.parse_drawable(bad)

    def test_summary_mentions_missing_pot(self, tmp_path):
        info = pf_inspect.parse_drawable(
            write_ydr(tmp_path, textures=(("t", "D3DFMT_DXT1", 1000, 1024),))
        )
        assert "Zweierpotenz" in info.summary()


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


class TestVerifyDrawable:
    def test_matching_export_is_clean(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path))
        assert pf_verify.verify_drawable(make_spec(), info) == []

    def test_wrong_shader_flagged(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path, shader="default.sps"))
        assert "shader_mismatch" in codes(pf_verify.verify_drawable(make_spec(), info))

    def test_missing_lod_flagged(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path, lods=("high", "medium")))
        assert "lod_missing_in_export" in codes(pf_verify.verify_drawable(make_spec(), info))

    def test_wrong_distance_flagged(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path, distances=(60, 120, 250, 999)))
        found = pf_verify.verify_drawable(make_spec(), info)
        assert "lod_distance_mismatch" in codes(found, Level.ERROR)

    def test_small_distance_drift_tolerated(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path, distances=(60.2, 120, 250, 500)))
        assert "lod_distance_mismatch" not in codes(pf_verify.verify_drawable(make_spec(), info))

    def test_empty_geometry_flagged(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path, geometries_per_lod=0))
        # Ohne Items faellt der LOD ganz weg - das muss ebenfalls auffallen
        found = codes(pf_verify.verify_drawable(make_spec(), info))
        assert "lod_missing_in_export" in found or "lod_empty_geometry" in found

    def test_unbound_sampler_flagged(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path, samplers=("DiffuseSampler",)))
        assert "sampler_not_bound" in codes(pf_verify.verify_drawable(make_spec(), info))

    def test_empty_composite_flagged(self, tmp_path):
        # Composite vorhanden, aber ohne Kinder: gueltige Datei, im Spiel
        # laeuft man hindurch. Genau dieser Fall ist uns durchgerutscht.
        info = pf_inspect.parse_drawable(write_ydr(tmp_path, bound_children=0))
        found = pf_verify.verify_drawable(make_spec(), info)
        assert "collision_composite_empty" in codes(found, Level.ERROR)

    def test_populated_composite_not_flagged(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path))
        assert "collision_composite_empty" not in codes(
            pf_verify.verify_drawable(make_spec(), info))

    def test_missing_collision_flagged(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path, bounds=None))
        assert "collision_missing" in codes(pf_verify.verify_drawable(make_spec(), info))

    def test_collision_not_expected(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path))
        spec = make_spec(collision=CollisionSettings(enabled=False))
        assert "collision_unexpected" in codes(pf_verify.verify_drawable(spec, info), Level.WARNING)

    def test_non_pot_texture_flagged(self, tmp_path):
        info = pf_inspect.parse_drawable(
            write_ydr(tmp_path, textures=(("t", "D3DFMT_DXT1", 1000, 1024),))
        )
        assert "texture_not_pot" in codes(pf_verify.verify_drawable(make_spec(), info))

    def test_missing_texcoord_is_an_error(self, tmp_path):
        # Der Fehler, der uns einen halben Tag gekostet hat: Geometrie
        # vollstaendig, LODs korrekt, Texturen eingebettet, Sampler belegt -
        # und trotzdem kein einziges Pixel Textur, weil die UV-Koordinaten
        # nicht im Vertexpuffer stehen.
        info = pf_inspect.parse_drawable(write_ydr(
            tmp_path, semantics=("Position", "Normal", "Tangent")))
        found = pf_verify.verify_drawable(make_spec(), info)
        assert "vertex_texcoord_missing" in codes(found, Level.ERROR)

    def test_missing_colour_warns(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(
            tmp_path, semantics=("Position", "Normal", "TexCoord0", "Tangent")))
        found = pf_verify.verify_drawable(make_spec(), info)
        assert "vertex_colour_missing" in codes(found, Level.WARNING)
        assert "vertex_texcoord_missing" not in codes(found)

    def test_texcoord_not_demanded_without_textures(self, tmp_path):
        # Ohne gebundene Textur braucht es auch keine Texturkoordinaten.
        info = pf_inspect.parse_drawable(write_ydr(
            tmp_path, samplers=(), semantics=("Position", "Normal", "Colour0")))
        assert "vertex_texcoord_missing" not in codes(
            pf_verify.verify_drawable(make_spec(), info))

    def test_empty_vertex_buffer_is_an_error(self, tmp_path):
        info = pf_inspect.parse_drawable(write_ydr(tmp_path, vertices=0, indices=0))
        assert "geometry_empty" in codes(pf_verify.verify_drawable(make_spec(), info), Level.ERROR)

    def test_lod_not_reduced_warns(self, tmp_path):
        xml = make_ydr_xml(geometries_per_lod=1)
        # LOD low kuenstlich aufblaehen
        xml = xml.replace(
            "<DrawableModelsLow><Item><Geometries><Item>",
            "<DrawableModelsLow><Item><Geometries><Item/><Item/><Item/><Item>",
        )
        path = tmp_path / "pf_crate.ydr.xml"
        path.write_text(xml, encoding="utf-8")
        info = pf_inspect.parse_drawable(path)
        assert "lod_not_reduced" in codes(pf_verify.verify_drawable(make_spec(), info), Level.WARNING)


class TestVerifyPipeline:
    def _config(self, workdir, **kwargs):
        # Die ytyp wird in tests/test_ytyp.py geprueft. Hier stoert ihre
        # Abwesenheit nur, deshalb ist sie abgeschaltet.
        kwargs.setdefault("ytyp", YtypSettings(enabled=False))
        return PipelineConfig(
            resource_name="r", author="a", workdir=workdir,
            props=[make_spec(**kwargs)], export_format="CWXML",
        )

    def test_finds_export_in_nested_dir(self, tmp_path):
        build = tmp_path / "build" / "pf_crate"
        build.mkdir(parents=True)
        write_ydr(build)
        found = pf_verify.verify(self._config(tmp_path), tmp_path / "build")
        # Die Fixture ist naturgemaess winzig, deshalb schlaegt die
        # Groessenpruefung an. Inhaltlich muss der Export sauber sein.
        assert codes(found) == {"drawable_suspiciously_small"}

    def test_small_drawable_flagged(self, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        write_ydr(build)
        found = pf_verify.verify(self._config(tmp_path), build)
        assert "drawable_suspiciously_small" in codes(found, Level.WARNING)

    def test_implausibly_large_drawable_is_an_error(self, tmp_path):
        # Ein halbes Gigabyte fuer einen Prop heisst nicht "detailliert",
        # sondern "der Schreiber ist entgleist". Sowas darf nicht gepackt
        # werden, also ist es ein Fehler und keine Warnung.
        build = tmp_path / "build"
        build.mkdir()
        path = write_ydr(build)
        with path.open("r+b") as fh:
            fh.seek(pf_verify.MAX_DRAWABLE_BYTES + 1)
            fh.write(b"\0")
        found = pf_verify.verify(self._config(tmp_path), build)
        assert "drawable_implausibly_large" in codes(found, Level.ERROR)

    def test_large_drawable_not_flagged(self, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        path = write_ydr(build)
        # Auffuellen bis ueber die Schwelle - ohne das XML zu zerstoeren.
        padding = " " * (pf_verify.MIN_DRAWABLE_BYTES + 1)
        path.write_text(path.read_text() + f"<!--{padding}-->", encoding="utf-8")
        assert "drawable_suspiciously_small" not in codes(
            pf_verify.verify(self._config(tmp_path), build))

    def test_missing_export_flagged(self, tmp_path):
        (tmp_path / "build").mkdir()
        assert "export_missing" in codes(pf_verify.verify(self._config(tmp_path), tmp_path / "build"))

    def test_binary_export_reported_as_info(self, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        (build / "pf_crate.ydr").write_bytes(b"binary")
        found = pf_verify.verify(self._config(tmp_path), build)
        assert "binary_export_not_inspectable" in codes(found, Level.INFO)

    def test_missing_build_dir(self, tmp_path):
        assert "build_dir_missing" in codes(pf_verify.verify(self._config(tmp_path), tmp_path / "nope"))
