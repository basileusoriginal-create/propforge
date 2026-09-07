"""Texturen einbetten oder in eine gemeinsame .ytd auslagern."""
import argparse
import json
from types import SimpleNamespace

import pytest

from propforge import cli, config as pf_config, verify as pf_verify, workspace
from propforge.config import CollisionSettings, PipelineConfig, PropSpec, TextureSet, YtypSettings
from propforge.inspect import ArchetypeInfo, DrawableInfo, TextureInfo, YtypInfo
from propforge.validate import Level


def make_spec(**kwargs) -> PropSpec:
    base = dict(
        name="pf_crate",
        mesh="pf_crate.glb",
        textures=TextureSet(diffuse="d.png"),
        collision=CollisionSettings(),
    )
    base.update(kwargs)
    return PropSpec(**base)


def codes(findings, level=None):
    return {f.code for f in findings if level is None or f.level is level}


# --- Die Entscheidung selbst -------------------------------------------------

class TestEmbedOrDictionary:
    def test_without_ytd_textures_are_embedded(self):
        spec = make_spec()
        assert spec.embed_textures()
        assert spec.texture_dictionary() == ""

    def test_ytd_name_switches_to_external_textures(self):
        spec = make_spec(ytd="pack_props")
        assert not spec.embed_textures()
        assert spec.texture_dictionary() == "pack_props"

    def test_explicit_ytyp_override_wins(self):
        """Ein Verweis auf ein fremdes Woerterbuch bleibt moeglich.

        Der Fall dahinter: eine Vanilla-txd mitbenutzen, statt eine eigene zu
        bauen. Wer das ausdruecklich hinschreibt, meint es auch.
        """
        spec = make_spec(ytd="pack_props", ytyp=YtypSettings(texture_dictionary="vanilla_txd"))
        assert spec.texture_dictionary() == "vanilla_txd"

    def test_override_can_force_empty(self):
        spec = make_spec(ytyp=YtypSettings(texture_dictionary=""))
        assert spec.texture_dictionary() == ""

    @pytest.mark.parametrize("raw,expected", [
        ("Pack Props", "pack_props"),
        ("  PACK  ", "pack"),
        ("", None),
        ("   ", None),
        (None, None),
    ])
    def test_names_are_normalised(self, raw, expected):
        """Grossbuchstaben und Leerzeichen sind der stille Totalausfall.

        RAGE sucht das Woerterbuch ueber einen Hash des kleingeschriebenen
        Namens. 'Pack Props' laedt deshalb nie - ohne Fehlermeldung.
        """
        assert pf_config.normalize_ytd_name(raw) == expected


class TestJobHandover:
    def test_job_dict_carries_the_decision(self, tmp_path):
        job = make_spec(ytd="pack_props").to_job(tmp_path)
        assert job["ytd"] == "pack_props"
        assert job["embed_textures"] is False
        assert job["ytyp"]["texture_dictionary"] == "pack_props"

    def test_embedded_job_names_no_dictionary(self, tmp_path):
        job = make_spec().to_job(tmp_path)
        assert job["ytd"] is None
        assert job["embed_textures"] is True
        assert job["ytyp"]["texture_dictionary"] == ""

    def test_shared_dictionary_lives_beside_the_props(self, tmp_path):
        """Ein gemeinsames Woerterbuch gehoert keinem einzelnen Prop.

        Laege es im Ordner eines der Props, waere die Zuordnung eine Luege -
        und beim Aufraeumen eines fehlgeschlagenen Props waere es mit weg.
        """
        job = make_spec(ytd="pack_props").to_job(tmp_path)
        assert job["ytd_dir"].endswith("_ytd")
        assert job["ytd_dir"] != job["output_dir"]

    def test_sidecar_survives_the_round_trip(self, tmp_path):
        mesh = tmp_path / "pf_crate.glb"
        mesh.write_bytes(b"x")
        workspace.Job(name="pf_crate", mesh=mesh, ytd="Pack Props").write()
        job = workspace.read_job(mesh)
        assert job.ytd == "pack_props"
        assert job.to_spec().texture_dictionary() == "pack_props"


class TestConfigFile:
    def test_ytd_from_toml(self, tmp_path):
        (tmp_path / "pf_crate.glb").write_bytes(b"x")
        (tmp_path / "d.png").write_bytes(b"x")
        toml = tmp_path / "pipeline.toml"
        toml.write_text(
            '[pipeline]\nresource_name = "test"\nauthor = "t"\nworkdir = "out"\n'
            '[[prop]]\nname = "pf_crate"\nmesh = "pf_crate.glb"\nytd = "Pack Props"\n'
            '[prop.textures]\ndiffuse = "d.png"\n',
            encoding="utf-8")
        spec = pf_config.PipelineConfig.load(toml).props[0]
        assert spec.ytd == "pack_props"
        assert not spec.embed_textures()


# --- Pruefung ----------------------------------------------------------------

def ytyp_info(texture_dictionary: str) -> YtypInfo:
    info = YtypInfo(name="pf_crate_ityp")
    info.archetypes.append(ArchetypeInfo(
        name="pf_crate", asset_name="pf_crate", asset_type="ASSET_TYPE_DRAWABLE",
        lod_dist=500.0, flags=32, texture_dictionary=texture_dictionary,
        physics_dictionary="pf_crate"))
    return info


class TestVerify:
    def test_missing_dictionary_reference_is_an_error(self):
        """Ausgelagerte Texturen ohne Verweis: der Prop waere im Spiel weiss."""
        spec = make_spec(ytd="pack_props")
        found = pf_verify.verify_ytyp(spec, ytyp_info(""), None)
        assert "archetype_texture_dictionary" in codes(found, Level.ERROR)

    def test_wrong_dictionary_name_is_an_error(self):
        spec = make_spec(ytd="pack_props")
        found = pf_verify.verify_ytyp(spec, ytyp_info("anderes_pack"), None)
        assert "archetype_texture_dictionary" in codes(found, Level.ERROR)

    def test_correct_reference_passes(self):
        spec = make_spec(ytd="pack_props")
        found = pf_verify.verify_ytyp(spec, ytyp_info("pack_props"), None)
        assert "archetype_texture_dictionary" not in codes(found)

    def test_superfluous_reference_is_only_a_warning(self):
        """Eingebettet und trotzdem ein Verweis: ueberfluessig, nicht kaputt.

        Das Spiel findet die Texturen in der .ydr. Der Verweis geht ins Leere,
        aber nichts geht dabei verloren - deshalb keine Eskalation.
        """
        found = pf_verify.verify_ytyp(make_spec(), ytyp_info("irgendwas"), None)
        assert "archetype_texture_dictionary" in codes(found, Level.WARNING)

    def test_textures_in_both_places_is_an_error(self):
        spec = make_spec(ytd="pack_props")
        drawable = DrawableInfo(
            name="pf_crate",
            textures=[TextureInfo("pf_crate_d", "D3DFMT_DXT1", 512, 512)])
        found = pf_verify.verify_ytyp(spec, ytyp_info("pack_props"), drawable)
        assert "textures_embedded_unexpectedly" in codes(found, Level.ERROR)

    def test_missing_ytd_file_is_found(self, tmp_path):
        """Der leiseste Fall: alles korrekt, nur das Woerterbuch fehlt."""
        build = tmp_path / "build"
        (build / "pf_crate").mkdir(parents=True)
        (build / "pf_crate" / "pf_crate.ydr").write_bytes(b"x" * 5000)
        (build / "pf_crate" / "pf_crate_ityp.ytyp").write_bytes(b"x" * 500)
        config = PipelineConfig(
            resource_name="test", author="t", workdir=tmp_path,
            props=[make_spec(ytd="pack_props")])
        assert "ytd_missing" in codes(pf_verify.verify(config, build), Level.ERROR)

    def test_present_ytd_file_passes(self, tmp_path):
        build = tmp_path / "build"
        (build / "pf_crate").mkdir(parents=True)
        (build / "pf_crate" / "pf_crate.ydr").write_bytes(b"x" * 5000)
        (build / "pf_crate" / "pf_crate_ityp.ytyp").write_bytes(b"x" * 500)
        (build / "_ytd").mkdir()
        (build / "_ytd" / "pack_props.ytd").write_bytes(b"x" * 2000)
        config = PipelineConfig(
            resource_name="test", author="t", workdir=tmp_path,
            props=[make_spec(ytd="pack_props")])
        assert "ytd_missing" not in codes(pf_verify.verify(config, build))

    def test_embedded_prop_is_not_asked_for_a_ytd(self, tmp_path):
        build = tmp_path / "build"
        (build / "pf_crate").mkdir(parents=True)
        (build / "pf_crate" / "pf_crate.ydr").write_bytes(b"x" * 5000)
        (build / "pf_crate" / "pf_crate_ityp.ytyp").write_bytes(b"x" * 500)
        config = PipelineConfig(
            resource_name="test", author="t", workdir=tmp_path,
            props=[make_spec()])
        assert "ytd_missing" not in codes(pf_verify.verify(config, build))


# --- Die Abfrage -------------------------------------------------------------

def prepare_inbox(tmp_path, monkeypatch, count=1):
    w = workspace.Workspace.load(tmp_path)
    w.ensure()
    for index in range(count):
        (w.inbox / f"pf_prop{index}.glb").write_bytes(b"test input")
    monkeypatch.setattr(cli.pf_ingest, "inspect", lambda *a: (
        SimpleNamespace(center=(0, 0, 0), is_centered=True, triangles=900), None, None))
    monkeypatch.setattr(cli.pf_ingest, "read_glb", lambda *a: ({}, b""))
    monkeypatch.setattr(cli.pf_ingest, "extract_textures", lambda *a: {})
    monkeypatch.setattr(cli.pf_ingest, "suggest_profile", lambda *a: "standard")
    for name in ("cmd_validate", "cmd_textures", "cmd_build", "cmd_verify", "cmd_pack"):
        monkeypatch.setattr(cli, name, lambda args: 0)
    return w


def convert(tmp_path, **overrides):
    args = dict(root=tmp_path, blender="blender", texconv=None, format="NATIVE",
                no_ask=True, ytd=None, embed=False)
    args.update(overrides)
    return cli.cmd_convert(argparse.Namespace(**args))


class TestAsking:
    def test_answer_lands_in_the_sidecar(self, tmp_path, monkeypatch):
        w = prepare_inbox(tmp_path, monkeypatch)
        monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
        monkeypatch.setattr(cli, "_ask_profile", lambda d: "standard")
        monkeypatch.setattr(cli, "_ask_material", lambda n: "DEFAULT")
        monkeypatch.setattr(cli, "_ask_ytd", lambda n, d=None: "pack_props")

        assert convert(tmp_path, no_ask=False) == 0
        sidecar = workspace.sidecar_for(w.done / "pf_prop0.glb")
        assert json.loads(sidecar.read_text())["ytd"] == "pack_props"

    def test_embedded_answer_writes_no_key(self, tmp_path, monkeypatch):
        w = prepare_inbox(tmp_path, monkeypatch)
        monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
        monkeypatch.setattr(cli, "_ask_profile", lambda d: "standard")
        monkeypatch.setattr(cli, "_ask_material", lambda n: "DEFAULT")
        monkeypatch.setattr(cli, "_ask_ytd", lambda n, d=None: None)

        assert convert(tmp_path, no_ask=False) == 0
        sidecar = workspace.sidecar_for(w.done / "pf_prop0.glb")
        assert "ytd" not in json.loads(sidecar.read_text())

    def test_previous_answer_becomes_the_next_default(self, tmp_path, monkeypatch):
        """Wer ein Pack einliest, meint beim zweiten Prop meist dasselbe."""
        prepare_inbox(tmp_path, monkeypatch, count=3)
        monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
        monkeypatch.setattr(cli, "_ask_profile", lambda d: "standard")
        monkeypatch.setattr(cli, "_ask_material", lambda n: "DEFAULT")
        defaults = []
        monkeypatch.setattr(cli, "_ask_ytd",
                            lambda n, d=None: (defaults.append(d), "pack_props")[1])

        assert convert(tmp_path, no_ask=False) == 0
        assert defaults == [None, "pack_props", "pack_props"]

    def test_flag_applies_to_the_whole_run_without_asking(self, tmp_path, monkeypatch):
        w = prepare_inbox(tmp_path, monkeypatch, count=3)
        monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
        monkeypatch.setattr(cli, "_ask_profile", lambda d: "standard")
        monkeypatch.setattr(cli, "_ask_material", lambda n: "DEFAULT")
        def never(*a, **k):
            raise AssertionError("Gefragt, obwohl --ytd gesetzt war.")
        monkeypatch.setattr(cli, "_ask_ytd", never)

        assert convert(tmp_path, no_ask=False, ytd="Pack Props") == 0
        for index in range(3):
            sidecar = workspace.sidecar_for(w.done / f"pf_prop{index}.glb")
            assert json.loads(sidecar.read_text())["ytd"] == "pack_props"

    def test_contradicting_flags_are_refused(self, tmp_path, monkeypatch):
        prepare_inbox(tmp_path, monkeypatch)
        assert convert(tmp_path, ytd="pack", embed=True) == 2

    def test_script_mode_embeds_by_default(self, tmp_path, monkeypatch):
        """Ohne Terminal wird nicht gefragt - und nicht heimlich ausgelagert.

        Eingebettet ist die Wahl, die fuer sich allein funktioniert: eine
        Datei, kein Verweis, der ins Leere gehen kann.
        """
        w = prepare_inbox(tmp_path, monkeypatch)
        assert convert(tmp_path) == 0
        sidecar = workspace.sidecar_for(w.done / "pf_prop0.glb")
        assert json.loads(sidecar.read_text()).get("ytd") is None
