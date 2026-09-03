import pytest

from propforge import packaging


@pytest.fixture
def build_dir(tmp_path):
    d = tmp_path / "build"
    (d / "pf_crate").mkdir(parents=True)
    (d / "pf_drum").mkdir(parents=True)
    (d / "pf_crate" / "pf_crate.ydr").write_bytes(b"ydr")
    (d / "pf_crate" / "pf_crate.ybn").write_bytes(b"ybn")
    (d / "pf_drum" / "pf_drum.ydr").write_bytes(b"ydr")
    (d / "pf_crate" / "props.ytyp").write_bytes(b"ytyp")
    (d / "pf_crate" / "notes.txt").write_text("ignoriere mich")
    return d


class TestBuildResource:
    def test_collects_only_streamable_files(self, build_dir, tmp_path):
        report = packaging.build_resource(build_dir, tmp_path / "res", "pf_pack", "Nick")
        names = {p.name for p in report.streamed}
        assert names == {"pf_crate.ydr", "pf_crate.ybn", "pf_drum.ydr", "props.ytyp"}
        assert not (report.root / "stream" / "notes.txt").exists()

    def test_flattens_into_single_stream_folder(self, build_dir, tmp_path):
        report = packaging.build_resource(build_dir, tmp_path / "res", "pf_pack", "Nick")
        assert all(p.parent.name == "stream" for p in report.streamed)

    def test_writes_manifest(self, build_dir, tmp_path):
        report = packaging.build_resource(build_dir, tmp_path / "res", "pf_pack", "Nick")
        manifest = (report.root / "fxmanifest.lua").read_text()
        assert "fx_version 'cerulean'" in manifest
        assert "game 'gta5'" in manifest
        assert "author 'Nick'" in manifest

    def test_ytyp_registered_as_data_file(self, build_dir, tmp_path):
        report = packaging.build_resource(build_dir, tmp_path / "res", "pf_pack", "Nick")
        manifest = (report.root / "fxmanifest.lua").read_text()
        assert "data_file 'DLC_ITYP_REQUEST' 'stream/props.ytyp'" in manifest

    def test_no_map_flag_without_ymap(self, build_dir, tmp_path):
        report = packaging.build_resource(build_dir, tmp_path / "res", "pf_pack", "Nick")
        assert "this_is_a_map" not in (report.root / "fxmanifest.lua").read_text()

    def test_map_flag_when_ymap_present(self, build_dir, tmp_path):
        (build_dir / "pf_crate" / "scene.ymap").write_bytes(b"ymap")
        report = packaging.build_resource(build_dir, tmp_path / "res", "pf_pack", "Nick")
        assert "this_is_a_map 'yes'" in (report.root / "fxmanifest.lua").read_text()

    def test_name_collision_raises(self, build_dir, tmp_path):
        # Streaming-Namen sind serverweit global - eine Kollision muss auffallen,
        # bevor sie auf dem Server ein anderes Asset ueberschreibt.
        (build_dir / "pf_drum" / "pf_crate.ydr").write_bytes(b"dup")
        with pytest.raises(FileExistsError, match="Namenskollision"):
            packaging.build_resource(build_dir, tmp_path / "res", "pf_pack", "Nick")

    def test_rebuild_is_clean(self, build_dir, tmp_path):
        out = tmp_path / "res"
        packaging.build_resource(build_dir, out, "pf_pack", "Nick")
        stale = out / "pf_pack" / "stream" / "old_asset.ydr"
        stale.write_bytes(b"alt")
        packaging.build_resource(build_dir, out, "pf_pack", "Nick")
        assert not stale.exists()

    def test_summary_counts_by_suffix(self, build_dir, tmp_path):
        report = packaging.build_resource(build_dir, tmp_path / "res", "pf_pack", "Nick")
        summary = report.summary()
        assert ".ydr" in summary and "2" in summary


class TestManifestRendering:
    def test_multiple_ytyps_sorted(self):
        manifest = packaging.render_manifest("r", "a", ["b.ytyp", "a.ytyp"], [])
        assert manifest.index("'stream/a.ytyp'") < manifest.index("'stream/b.ytyp'")

    def test_empty_pack_still_valid(self):
        manifest = packaging.render_manifest("r", "a", [], [])
        assert "fx_version" in manifest
        assert "data_file" not in manifest

    def test_client_script_only_with_helper(self):
        assert "client_script" not in packaging.render_manifest("r", "a", [], [])
        assert "client_script 'client.lua'" in packaging.render_manifest(
            "r", "a", [], [], spawn_helper=True)


class TestSpawnHelper:
    def test_lists_prop_names(self):
        lua = packaging.render_spawn_helper(["pf_drum", "pf_crate"])
        assert 'local PROPS = { "pf_crate", "pf_drum" }' in lua

    def test_registers_both_commands(self):
        lua = packaging.render_spawn_helper(["pf_crate"])
        assert 'RegisterCommand("pfspawn"' in lua
        assert 'RegisterCommand("pfdelete"' in lua

    def test_distinguishes_the_two_failure_modes(self):
        # Der ganze Sinn des Helfers: "Modell laedt nicht" und "Modell laedt,
        # ist aber unsichtbar" haben verschiedene Ursachen und muessen
        # verschieden gemeldet werden.
        lua = packaging.render_spawn_helper(["pf_crate"])
        assert "Archetyp nicht" in lua
        assert "Modell das Problem" in lua

    def test_no_leftover_format_placeholders(self):
        # Das Lua-Template geht durch %-Formatierung. Ein vergessenes %% waere
        # ein Syntaxfehler, der erst auf dem Server auffiele.
        lua = packaging.render_spawn_helper(["pf_crate"])
        assert "%(props)s" not in lua
        assert "%%" not in lua

    def test_written_into_resource(self, build_dir, tmp_path):
        report = packaging.build_resource(build_dir, tmp_path / "res", "pf_pack", "Nick")
        lua = (report.root / "client.lua").read_text()
        assert "pf_crate" in lua and "pf_drum" in lua
        assert "client_script 'client.lua'" in (report.root / "fxmanifest.lua").read_text()

    def test_can_be_switched_off(self, build_dir, tmp_path):
        report = packaging.build_resource(
            build_dir, tmp_path / "res", "pf_pack", "Nick", spawn_helper=False)
        assert not (report.root / "client.lua").exists()
        assert "client_script" not in (report.root / "fxmanifest.lua").read_text()

    def test_no_helper_without_drawables(self, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        (build / "props.ytyp").write_bytes(b"ytyp")
        report = packaging.build_resource(build, tmp_path / "res", "pf_pack", "Nick")
        assert not (report.root / "client.lua").exists()
