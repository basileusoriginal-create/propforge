import json

import pytest

from propforge import packaging, placement


def test_pack_reads_each_drawable_metadata_across_build_runs(tmp_path):
    build = tmp_path / "build"
    for name, bottom in (("pf_base", 0.0), ("pf_centre", -0.375), ("pf_offset", 2.0)):
        folder = build / name
        folder.mkdir(parents=True)
        drawable = folder / f"{name}.ydr"
        drawable.write_bytes(name.encode())
        placement.write(drawable, [-1, -.5, bottom], [1, .5, bottom+.75])
    # No build_result.json dependency: earlier runs must keep their bounds.
    resource = packaging.build_resource(build, tmp_path / "out", "pack", "test")
    lua = (resource.root / "client.lua").read_text()
    assert '["pf_centre"] = { min = {-1.0,-0.5,-0.375}' in lua
    assert '["pf_offset"] = { min = {-1.0,-0.5,2.0}' in lua
    assert {p.suffix for p in resource.streamed} == {".ydr"}
    assert not list(resource.root.rglob("*.json"))


@pytest.mark.parametrize("change", ["drawable", "hash", "version", "nonfinite", "reversed"])
def test_rejects_stale_or_invalid_bounds(tmp_path, change):
    drawable = tmp_path / "pf_a.ydr"
    drawable.write_bytes(b"first")
    path = placement.write(drawable, [-1,-1,0], [1,1,1])
    data = json.loads(path.read_text())
    if change == "drawable": data["drawable"] = "other.ydr"
    elif change == "hash": drawable.write_bytes(b"rebuilt")
    elif change == "version": data["version"] = 2
    elif change == "nonfinite": data["bounds"]["min"][2] = float("nan")
    elif change == "reversed": data["bounds"]["min"][2] = 2
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError): placement.read(drawable)


def test_legacy_drawable_remains_distinguishable(tmp_path):
    drawable = tmp_path / "pf_a.ydr"
    drawable.write_bytes(b"old")
    assert placement.read(drawable) is None


def test_invalid_bounds_do_not_remove_previous_resource(tmp_path):
    build = tmp_path / "build"
    build.mkdir()
    drawable = build / "pf_a.ydr"
    drawable.write_bytes(b"first")
    placement.write(drawable, [-1,-1,0], [1,1,1])
    resource = packaging.build_resource(build, tmp_path / "out", "pack", "test")
    previous = (resource.root / "client.lua").read_bytes()
    drawable.write_bytes(b"changed without matching bounds")
    with pytest.raises(ValueError, match="passen nicht"):
        packaging.build_resource(build, tmp_path / "out", "pack", "test")
    assert (resource.root / "client.lua").read_bytes() == previous
    assert (resource.root / "stream/pf_a.ydr").read_bytes() == b"first"
