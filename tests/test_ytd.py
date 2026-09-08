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

    def _pack(self, tmp_path, textures, props=("pf_crate",)):
        build = tmp_path / "build"
        (build / "pf_crate").mkdir(parents=True)
        (build / "pf_crate" / "pf_crate.ydr").write_bytes(b"x" * 5000)
        (build / "pf_crate" / "pf_crate_ityp.ytyp").write_bytes(b"x" * 500)
        (build / "_ytd").mkdir()
        (build / "_ytd" / "pack_props.ytd").write_bytes(b"x" * 2000)
        if textures is not None:
            (build / "_ytd" / "pack_props.textures.json").write_text(json.dumps({
                "name": "pack_props", "props": list(props),
                "textures": {t: f"/irgendwo/{t}.dds" for t in textures},
            }), encoding="utf-8")
        return build

    def test_present_ytd_file_passes(self, tmp_path):
        build = self._pack(tmp_path, ["pf_crate_d", "pf_crate_n"])
        config = PipelineConfig(
            resource_name="test", author="t", workdir=tmp_path,
            props=[make_spec(ytd="pack_props")])
        assert not codes(pf_verify.verify(config, build), Level.ERROR)

    def test_ytd_without_this_props_textures_is_an_error(self, tmp_path):
        """Der Fall, den ein zweiter Lauf ohne Begleitliste erzeugen wuerde.

        Heute fuenf Props ins Woerterbuch, morgen fuenf weitere: die .ytd wird
        jedes Mal komplett neu geschrieben. Sie ist dann da, hat eine
        plausible Groesse - und die Props von gestern sind im Spiel weiss.
        """
        build = self._pack(tmp_path, ["pf_barrel_d"], props=["pf_barrel"])
        config = PipelineConfig(
            resource_name="test", author="t", workdir=tmp_path,
            props=[make_spec(ytd="pack_props")])
        assert "ytd_without_prop_textures" in codes(pf_verify.verify(config, build), Level.ERROR)

    def test_missing_manifest_is_a_warning(self, tmp_path):
        build = self._pack(tmp_path, None)
        config = PipelineConfig(
            resource_name="test", author="t", workdir=tmp_path,
            props=[make_spec(ytd="pack_props")])
        assert "ytd_manifest_missing" in codes(pf_verify.verify(config, build), Level.WARNING)

    def test_embedded_prop_is_not_asked_for_a_ytd(self, tmp_path):
        build = tmp_path / "build"
        (build / "pf_crate").mkdir(parents=True)
        (build / "pf_crate" / "pf_crate.ydr").write_bytes(b"x" * 5000)
        (build / "pf_crate" / "pf_crate_ityp.ytyp").write_bytes(b"x" * 500)
        config = PipelineConfig(
            resource_name="test", author="t", workdir=tmp_path,
            props=[make_spec()])
        assert "ytd_missing" not in codes(pf_verify.verify(config, build))


# --- Gruppierung und Fortschreibung -----------------------------------------
#
# Die Blender-Stufe laesst sich hier nicht ausfuehren (kein bpy), aber die
# beiden Entscheidungen, um die es geht, brauchen kein Blender: welche
# Texturen in welches Woerterbuch gehoeren, und was beim zweiten Lauf mit den
# Texturen des ersten passiert. Beides wird direkt aus dem Skript importiert.

def load_build_module():
    import importlib.util
    from pathlib import Path as _P

    path = _P(__file__).resolve().parent.parent / "blender" / "sz_build_prop.py"
    source = path.read_text(encoding="utf-8")
    # bpy und die Sollumz-Importe stehen im Kopf und sind hier nicht
    # verfuegbar. Statt sie zu faelschen wird nur der Teil ausgefuehrt, der
    # ohne sie auskommt - die reinen Entscheidungsfunktionen.
    marker = "MANIFEST_SUFFIX = "
    start = source.index(marker)
    end = source.index("def build_texture_dictionary(")
    namespace = {"json": json, "Path": __import__("pathlib").Path}
    exec(compile(source[start:end], str(path), "exec"), namespace)

    start = source.index("def collect_texture_dictionaries(")
    end = source.index("def _written(")
    namespace["texture_files"] = lambda job: [
        __import__("pathlib").Path(job["texture_dir"]) / f"{job['name']}{s}.dds"
        for s in ("_d", "_n", "_s")]
    exec(compile(source[start:end], str(path), "exec"), namespace)
    return namespace


BUILD = load_build_module()


def job(name, ytd, texture_dir="/t"):
    return {"name": name, "ytd": ytd, "texture_dir": f"{texture_dir}/{name}",
            "output_dir": f"/build/{name}", "ytd_dir": "/build/_ytd"}


class TestGrouping:
    def test_one_dictionary_per_name_not_per_prop(self):
        """Genau der Punkt: gleiche Namen ueberschreiben sich NICHT.

        Zehn Props mit demselben ytd-Namen ergeben ein Woerterbuch mit allen
        Texturen - nicht zehn, von denen neun verlorengehen.
        """
        jobs = [job(f"pf_prop{i}", "pack_props") for i in range(10)]
        groups = BUILD["collect_texture_dictionaries"](jobs, {j["name"] for j in jobs})
        assert list(groups) == ["pack_props"]
        _, files, props = groups["pack_props"]
        assert len(props) == 10
        assert len(files) == 30

    def test_different_names_stay_apart(self):
        jobs = [job("pf_a", "pack_eins"), job("pf_b", "pack_zwei")]
        groups = BUILD["collect_texture_dictionaries"](jobs, {"pf_a", "pf_b"})
        assert sorted(groups) == ["pack_eins", "pack_zwei"]

    def test_embedded_props_form_no_group(self):
        groups = BUILD["collect_texture_dictionaries"](
            [job("pf_a", None)], {"pf_a"})
        assert groups == {}

    def test_failed_props_are_left_out(self):
        """Sonst enthielte das Woerterbuch Texturen zu einem Prop, den es nicht gibt."""
        jobs = [job("pf_a", "pack"), job("pf_b", "pack")]
        groups = BUILD["collect_texture_dictionaries"](jobs, {"pf_a"})
        assert groups["pack"][2] == ["pf_a"]


class TestManifest:
    def test_second_run_keeps_the_first_runs_textures(self, tmp_path):
        """Der Fehler, den es ohne die Begleitliste gaebe.

        Eine .ytd wird bei jedem Lauf komplett neu geschrieben. Ohne diese
        Fortschreibung waeren die Props des ersten Laufs danach im Spiel
        weiss - ohne fehlende Datei und ohne Meldung.
        """
        first = tmp_path / "pf_tisch_d.dds"
        first.write_bytes(b"x")
        manifest = tmp_path / "pack.textures.json"
        manifest.write_text(json.dumps({
            "name": "pack", "props": ["pf_tisch"],
            "textures": {"pf_tisch_d": str(first)},
        }), encoding="utf-8")

        second = tmp_path / "pf_stuhl_d.dds"
        second.write_bytes(b"x")
        known, props, gone = BUILD["merge_with_manifest"](manifest, [second], ["pf_stuhl"])

        assert sorted(known) == ["pf_stuhl_d", "pf_tisch_d"]
        assert props == ["pf_stuhl", "pf_tisch"]
        assert gone == []

    def test_deleted_textures_stop_before_replacing_dictionary(self, tmp_path):
        manifest = tmp_path / "pack.textures.json"
        manifest.write_text(json.dumps({
            "name": "pack", "props": ["pf_alt"],
            "textures": {"pf_alt_d": str(tmp_path / "weg.dds")},
        }), encoding="utf-8")
        neu = tmp_path / "pf_neu_d.dds"
        neu.write_bytes(b"x")

        with pytest.raises(RuntimeError, match="pf_alt_d"):
            BUILD["merge_with_manifest"](manifest, [neu], ["pf_neu"])

    def test_existing_dictionary_requires_manifest(self, tmp_path):
        (tmp_path / "pack.ytd").write_bytes(b"previous dictionary")
        with pytest.raises(RuntimeError, match="fehlt neben bestehender YTD"):
            BUILD["merge_with_manifest"](tmp_path / "pack.textures.json", [], [])

    @pytest.mark.parametrize("data", [{}, [], {"textures": [], "props": []}])
    def test_invalid_manifest_schema_is_rejected(self, tmp_path, data):
        path = tmp_path / "pack.textures.json"
        path.write_text(json.dumps(data))
        with pytest.raises(RuntimeError, match="ungueltige Begleitliste"):
            BUILD["merge_with_manifest"](path, [], [])

    def test_rebuilt_texture_wins_over_the_listed_path(self, tmp_path):
        """Neu gebaut heisst neu: der aktuelle Lauf ueberschreibt den Eintrag."""
        alt = tmp_path / "alt" / "pf_tisch_d.dds"
        alt.parent.mkdir()
        alt.write_bytes(b"x")
        neu = tmp_path / "neu" / "pf_tisch_d.dds"
        neu.parent.mkdir()
        neu.write_bytes(b"y")
        manifest = tmp_path / "pack.textures.json"
        manifest.write_text(json.dumps({
            "name": "pack", "props": ["pf_tisch"], "textures": {"pf_tisch_d": str(alt)},
        }), encoding="utf-8")

        known, _, _ = BUILD["merge_with_manifest"](manifest, [neu], ["pf_tisch"])
        assert known["pf_tisch_d"] == neu

    def test_no_manifest_yet_is_the_normal_first_run(self, tmp_path):
        dds = tmp_path / "pf_tisch_d.dds"
        dds.write_bytes(b"x")
        known, props, gone = BUILD["merge_with_manifest"](
            tmp_path / "fehlt.json", [dds], ["pf_tisch"])
        assert sorted(known) == ["pf_tisch_d"]
        assert props == ["pf_tisch"]
        assert gone == []

    def test_broken_manifest_stops_the_run(self, tmp_path):
        """Kaputte Liste heisst: unbekannt, was frueher drin war.

        Stillschweigend neu anzufangen wuerde alle frueheren Props weiss
        machen. Lieber laut abbrechen.
        """
        manifest = tmp_path / "pack.textures.json"
        manifest.write_text("{kaputt", encoding="utf-8")
        with pytest.raises(RuntimeError, match="kein gueltiges JSON"):
            BUILD["merge_with_manifest"](manifest, [], [])


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
    @pytest.mark.parametrize("textures", [{}, {"diffuse": "existing.png"}])
    @pytest.mark.parametrize("flags,old,expected", [
        ({"ytd": "Pack Props"}, None, "pack_props"),
        ({"embed": True}, "old_pack", None),
    ])
    def test_flags_override_existing_handoffs(self, tmp_path, monkeypatch, textures, flags, old, expected):
        w = prepare_inbox(tmp_path, monkeypatch)
        mesh = w.inbox / "pf_prop0.glb"
        workspace.Job(name=mesh.stem, mesh=mesh, profile="detailed", center="none",
                      ytd=old, textures=textures).write()
        monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
        def never(*a, **k):
            raise AssertionError("Existing handoff must not prompt")
        for name in ("_ask_profile", "_ask_material", "_ask_ytd"):
            monkeypatch.setattr(cli, name, never)
        def check(args):
            assert args.config.props[0].ytd == expected
            return 0
        monkeypatch.setattr(cli, "cmd_build", check)
        assert convert(tmp_path, no_ask=False, **flags) == 0
        saved = json.loads(workspace.sidecar_for(w.done / mesh.name).read_text())
        assert saved.get("ytd") == expected
        assert saved["profile"] == "detailed"
        assert saved["center"] == "none"

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
