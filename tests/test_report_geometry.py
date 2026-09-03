"""Tests fuer den Aufbau-Bericht.

Dieses Skript ist bewusst beschreibend statt pruefend: es gibt aus, was in der
Datei steht, nicht was dort stehen sollte. Getestet wird deshalb, dass es
nichts verschluckt und nichts erfindet - besonders die Vertex-Semantik und
Sampler, die auf nicht vorhandene Texturen zeigen.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("report_geometry", ROOT / "ci" / "report_geometry.py")
report_geometry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report_geometry)


GEOMETRY = """
      <Item>
        <ShaderIndex value="0" />
        <VertexBuffer>
          <Flags value="0" />
          <Layout type="GTAV1"><Position /><Normal /><Colour0 /><TexCoord0 /><Tangent /></Layout>
          <Data>1 2 3
4 5 6</Data>
        </VertexBuffer>
        <IndexBuffer><Data>0 1 2</Data></IndexBuffer>
      </Item>"""


def make_ydr(tmp_path, name="pf_crate", sampler_target="pf_crate_d", embedded="pf_crate_d",
             geometry=GEOMETRY):
    tex = (f"<Item><Name>{embedded}</Name><Format>D3DFMT_DXT1</Format>"
           '<Width value="512" /><Height value="512" /></Item>') if embedded else ""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Drawable>
  <Name>{name}</Name>
  <ShaderGroup>
    <TextureDictionary>{tex}</TextureDictionary>
    <Shaders>
      <Item>
        <FileName>normal_spec.sps</FileName>
        <Parameters>
          <Item name="DiffuseSampler" type="Texture"><Name>{sampler_target}</Name></Item>
        </Parameters>
      </Item>
    </Shaders>
  </ShaderGroup>
  <DrawableModelsHigh><Item><Geometries>{geometry}</Geometries></Item></DrawableModelsHigh>
</Drawable>"""
    path = tmp_path / f"{name}.ydr.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def body(tmp_path, **kwargs):
    return "\n".join(report_geometry.report(make_ydr(tmp_path, **kwargs)))


class TestReport:
    def test_lists_top_level_blocks(self, tmp_path):
        assert "Bloecke: Name, ShaderGroup, DrawableModelsHigh" in body(tmp_path)

    def test_names_embedded_textures(self, tmp_path):
        assert "eingebettete Texturen: pf_crate_d" in body(tmp_path)

    def test_reports_no_embedded_textures(self, tmp_path):
        assert "eingebettete Texturen: (keine)" in body(tmp_path, embedded="")

    def test_shows_vertex_semantics_in_one_line(self, tmp_path):
        # Die Vertex-Semantik ist der interessanteste Teil des Aufbaus. Sie
        # darf nicht der Tiefenbegrenzung zum Opfer fallen.
        assert "Layout(type): Position, Normal, Colour0, TexCoord0, Tangent" in body(tmp_path)

    def test_counts_bulk_data_instead_of_printing_it(self, tmp_path):
        out = body(tmp_path)
        assert "Data [2 Zeilen / 6 Werte]" in out
        assert "4 5 6" not in out

    def test_flags_sampler_pointing_nowhere(self, tmp_path):
        # Genau dieser Fall ist im Spiel unsichtbar und in der Datei gueltig.
        out = body(tmp_path, sampler_target="fehlt_im_woerterbuch")
        assert "nicht im Woerterbuch!" in out

    def test_matching_sampler_not_flagged(self, tmp_path):
        assert "nicht im Woerterbuch" not in body(tmp_path)

    def test_counts_models_and_geometries(self, tmp_path):
        assert "DrawableModelsHigh: 1 Modell(e), 1 Geometrie(n)" in body(tmp_path)

    def test_empty_lod_container_reported(self, tmp_path):
        out = body(tmp_path, geometry="")
        assert "0 Geometrie(n)" in out


class TestMain:
    def test_emits_one_notice_per_prop(self, tmp_path, capsys):
        make_ydr(tmp_path, name="pf_a")
        make_ydr(tmp_path, name="pf_b")
        report_geometry.main(["report_geometry.py", str(tmp_path), "Geometrie"])
        out = capsys.readouterr().out
        assert out.count("::notice") == 2

    def test_notice_has_no_raw_newlines(self, tmp_path, capsys):
        # Unescaped Zeilenumbrueche zerreissen die Annotation in Fragmente.
        make_ydr(tmp_path)
        report_geometry.main(["report_geometry.py", str(tmp_path), "Geometrie"])
        out = capsys.readouterr().out.rstrip("\n")
        assert "\n" not in out
        assert "%0A" in out

    def test_missing_directory_is_not_fatal(self, tmp_path, capsys):
        assert report_geometry.main(["x", str(tmp_path / "nope"), "G"]) == 0
        assert "Keine .ydr.xml" in capsys.readouterr().out

    def test_broken_xml_is_reported_not_raised(self, tmp_path, capsys):
        (tmp_path / "kaputt.ydr.xml").write_text("<Drawable><Name>x")
        assert report_geometry.main(["x", str(tmp_path), "G"]) == 0
        assert "nicht lesbar" in capsys.readouterr().out
