"""Tests fuer die Ordner-Routine.

Der Sinn dieser Stufe ist, dass niemand mehr eine Konfigurationsdatei von
Hand pflegt. Entsprechend wird geprueft, dass die Konfiguration vollstaendig
aus den Begleitdateien entsteht - und dass ein fehlgeschlagenes Asset im
Eingang liegen bleibt statt im Archiv zu verschwinden.
"""

import json

import pytest

from propforge import workspace as ws
from propforge.config import PROFILES


def glb(folder, name="pf_flasche"):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.glb"
    path.write_bytes(b"glTF\x02\x00\x00\x00")
    return path


class TestWorkspace:
    def test_defaults_without_config_file(self, tmp_path):
        w = ws.Workspace.load(tmp_path)
        assert w.inbox.name == "eingang"
        assert w.done.name == "fertig"
        assert w.out.name == "ausgabe"

    def test_config_file_overrides_paths(self, tmp_path):
        (tmp_path / ws.WORKSPACE_FILE).write_text(
            '[workspace]\ninbox = "rein"\nout = "raus"\nresource_name = "meins"\n')
        w = ws.Workspace.load(tmp_path)
        assert w.inbox == (tmp_path / "rein").resolve()
        assert w.out == (tmp_path / "raus").resolve()
        assert w.resource_name == "meins"

    def test_ensure_creates_folders(self, tmp_path):
        w = ws.Workspace.load(tmp_path)
        w.ensure()
        assert w.inbox.is_dir() and w.done.is_dir() and w.out.is_dir()

    def test_meshes_are_sorted_and_filtered(self, tmp_path):
        w = ws.Workspace.load(tmp_path)
        w.ensure()
        glb(w.inbox, "b_zweit")
        glb(w.inbox, "a_erst")
        (w.inbox / "notiz.txt").write_text("kein Mesh")
        assert [m.stem for m in w.meshes()] == ["a_erst", "b_zweit"]

    def test_empty_inbox_is_not_an_error(self, tmp_path):
        assert ws.Workspace.load(tmp_path).meshes() == []


class TestJobs:
    def test_mesh_without_sidecar_still_counts(self, tmp_path):
        # Wer ein GLB einfach hineinkopiert, soll nicht erst JSON schreiben.
        w = ws.Workspace.load(tmp_path)
        w.ensure()
        glb(w.inbox)
        job = w.jobs()[0]
        assert job.name == "pf_flasche"
        assert job.profile == "standard"
        assert job.material == "DEFAULT"

    def test_sidecar_is_read(self, tmp_path):
        w = ws.Workspace.load(tmp_path)
        w.ensure()
        mesh = glb(w.inbox)
        ws.sidecar_for(mesh).write_text(json.dumps(
            {"name": "pf_bier", "profile": "clutter",
             "material": "glass_shoot_through", "prompt": "eine Flasche"}))
        job = w.jobs()[0]
        assert job.name == "pf_bier"
        assert job.profile == "clutter"
        assert job.material == "GLASS_SHOOT_THROUGH"
        assert job.prompt == "eine Flasche"

    def test_sidecar_name_matches_mesh(self, tmp_path):
        assert ws.sidecar_for(tmp_path / "pf_x.glb").name == "pf_x.job.json"

    def test_broken_sidecar_is_reported(self, tmp_path):
        w = ws.Workspace.load(tmp_path)
        w.ensure()
        mesh = glb(w.inbox)
        ws.sidecar_for(mesh).write_text("{kaputt")
        with pytest.raises(ValueError, match="gueltiges JSON"):
            w.jobs()

    def test_write_then_read_round_trip(self, tmp_path):
        mesh = glb(tmp_path)
        ws.Job(name="pf_x", mesh=mesh, profile="detailed",
               material="METAL_SOLID_MEDIUM", ytd="meinpack").write()
        job = ws.read_job(mesh)
        assert (job.profile, job.material, job.ytd) == (
            "detailed", "METAL_SOLID_MEDIUM", "meinpack")

    def test_created_timestamp_is_set(self, tmp_path):
        mesh = glb(tmp_path)
        ws.Job(name="pf_x", mesh=mesh).write()
        assert ws.read_job(mesh).created


class TestConfigFromJobs:
    def test_profile_drives_the_budget(self, tmp_path):
        w = ws.Workspace.load(tmp_path)
        job = ws.Job(name="pf_x", mesh=tmp_path / "a.glb", profile="clutter",
                     textures={"diffuse": "d.png"})
        spec = w.to_config([job]).props[0]
        assert spec.max_tris == PROFILES["clutter"].max_tris
        assert spec.texture_size == PROFILES["clutter"].texture_size
        assert spec.lods.distances == PROFILES["clutter"].distances

    def test_material_reaches_the_spec(self, tmp_path):
        w = ws.Workspace.load(tmp_path)
        job = ws.Job(name="pf_x", mesh=tmp_path / "a.glb",
                     material="WOOD_SOLID_MEDIUM", textures={"diffuse": "d.png"})
        assert w.to_config([job]).props[0].collision.material == "WOOD_SOLID_MEDIUM"

    def test_unknown_profile_falls_back(self, tmp_path):
        w = ws.Workspace.load(tmp_path)
        job = ws.Job(name="pf_x", mesh=tmp_path / "a.glb", profile="quatsch")
        assert w.to_config([job]).props[0].profile == "standard"

    def test_workdir_is_the_output_folder(self, tmp_path):
        w = ws.Workspace.load(tmp_path)
        assert w.to_config([]).workdir == w.out

    def test_textures_are_carried_over(self, tmp_path):
        w = ws.Workspace.load(tmp_path)
        job = ws.Job(name="pf_x", mesh=tmp_path / "a.glb",
                     textures={"diffuse": "d.png", "normal": "n.png"})
        spec = w.to_config([job]).props[0]
        assert spec.textures.diffuse.endswith("d.png")
        assert spec.textures.normal.endswith("n.png")


class TestArchive:
    def test_moves_mesh_and_sidecar(self, tmp_path):
        w = ws.Workspace.load(tmp_path)
        w.ensure()
        mesh = glb(w.inbox)
        job = ws.Job(name="pf_flasche", mesh=mesh)
        job.write()
        w.archive(job)
        assert not mesh.exists()
        assert (w.done / "pf_flasche.glb").is_file()
        assert (w.done / "pf_flasche.job.json").is_file()

    def test_second_run_does_not_overwrite(self, tmp_path):
        # Zwei Assets gleichen Namens duerfen sich im Archiv nicht
        # gegenseitig ausloeschen.
        w = ws.Workspace.load(tmp_path)
        w.ensure()
        for _ in range(2):
            mesh = glb(w.inbox)
            w.archive(ws.Job(name="pf_flasche", mesh=mesh))
        assert (w.done / "pf_flasche.glb").is_file()
        assert (w.done / "pf_flasche_2.glb").is_file()

    def test_missing_sidecar_is_fine(self, tmp_path):
        w = ws.Workspace.load(tmp_path)
        w.ensure()
        mesh = glb(w.inbox)
        w.archive(ws.Job(name="pf_flasche", mesh=mesh))
        assert (w.done / "pf_flasche.glb").is_file()
