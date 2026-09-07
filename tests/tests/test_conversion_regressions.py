"""Regressions observed with the local production handoff and Blender setup."""
import argparse
import json
import sys
from types import SimpleNamespace

import pytest

from propforge import cli, sollumz_env, workspace


def test_enabled_development_extension_wins_over_inactive_release(monkeypatch):
    addons = {"bl_ext.user_default.sollumz_dev": object()}
    monkeypatch.setitem(sys.modules, "bpy", SimpleNamespace(
        context=SimpleNamespace(preferences=SimpleNamespace(addons=addons))))
    assert sollumz_env.module_candidates() == ("bl_ext.user_default.sollumz_dev",)


def test_inactive_addon_is_not_accepted(monkeypatch):
    monkeypatch.setitem(sys.modules, "bpy", SimpleNamespace(
        context=SimpleNamespace(preferences=SimpleNamespace(addons={}))))
    with pytest.raises(ImportError, match="aktiviert"):
        sollumz_env.module_candidates()


@pytest.mark.parametrize("center", ["none", "xy", "all", "base"])
@pytest.mark.parametrize("fail_stage", [None, "cmd_build", "cmd_verify", "cmd_pack"])
def test_convert_preserves_origin_and_archives_only_after_success(
        tmp_path, monkeypatch, center, fail_stage):
    w = workspace.Workspace.load(tmp_path)
    w.ensure()
    mesh = w.inbox / "pf_wall.glb"
    mesh.write_bytes(b"test input")
    workspace.Job(name="pf_wall", mesh=mesh, center=center, profile="detailed").write()
    monkeypatch.setattr(cli.pf_ingest, "inspect", lambda *a: (
        SimpleNamespace(center=(4, 0, 2), is_centered=False), None, None))
    monkeypatch.setattr(cli.pf_ingest, "read_glb", lambda *a: ({}, b""))
    monkeypatch.setattr(cli.pf_ingest, "extract_textures", lambda *a: {"diffuse": w.inbox / "d.png"})
    stages = []
    def stage(name):
        def run(args):
            assert args.config.props[0].center == center
            assert args.config.props[0].profile == "detailed"
            assert mesh.exists()
            stages.append(name)
            return 1 if name == fail_stage else 0
        return run
    order = ["cmd_validate", "cmd_textures", "cmd_build", "cmd_verify", "cmd_pack"]
    for name in order:
        monkeypatch.setattr(cli, name, stage(name))
    code = cli.cmd_convert(argparse.Namespace(root=tmp_path, blender="blender", texconv=None, format="NATIVE"))
    assert code == (1 if fail_stage else 0)
    assert stages == (order[:order.index(fail_stage) + 1] if fail_stage else order)
    sidecar = workspace.sidecar_for(mesh if fail_stage else w.done / mesh.name)
    assert json.loads(sidecar.read_text())["center"] == center
    assert mesh.exists() == bool(fail_stage)
