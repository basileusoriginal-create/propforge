"""A failed native readback must leave an earlier dictionary untouched."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("writes_file", [True, False])
def test_failed_export_preserves_previous_ytd(tmp_path, writes_file):
    source = Path(__file__).resolve().parents[1] / "blender/sz_build_prop.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in
                 {"manifest_for", "merge_with_manifest", "build_texture_dictionary", "_build_texture_dictionary"}]
    dds = tmp_path / "pf_a_d.dds"
    dds.write_bytes(b"dds")
    dictionary = tmp_path / "pack.ytd"
    dictionary.write_bytes(b"known good")
    manifest = tmp_path / "pack.textures.json"
    original = json.dumps({"name": "pack", "props": ["pf_a"], "textures": {dds.stem: str(dds)}})
    manifest.write_text(original)
    def export(**kwargs):
        if writes_file:
            (Path(kwargs["directory"]) / "pack.ytd").write_bytes(b"bad export")
        return {"FINISHED"}
    def reject(*args):
        raise RuntimeError("readback failed")
    fake = SimpleNamespace(
        context=SimpleNamespace(scene=SimpleNamespace(sz_txds=SimpleNamespace(
            new_texture_dictionary=lambda **kw: SimpleNamespace(new_texture=lambda image: None)))),
        data=SimpleNamespace(images=SimpleNamespace(load=lambda *a, **kw: object())),
        ops=SimpleNamespace(sollumz=SimpleNamespace(export_assets=export)))
    namespace = dict(Path=Path, json=json, MANIFEST_SUFFIX=".textures.json", bpy=fake,
                     log=lambda *a: None, reset_scene=lambda: None, EXPORT_SETTINGS={},
                     check_texture_dictionary=reject)
    exec(compile(tree, str(source), "exec"), namespace)
    with pytest.raises(RuntimeError):
        namespace["build_texture_dictionary"]("pack", [dds], tmp_path, "NATIVE", "GEN8", ["pf_a"])
    assert dictionary.read_bytes() == b"known good"
    assert manifest.read_text() == original
    assert not list(tmp_path.glob(".ytd-stage-*"))
