from propforge.texture_pool import prepare_job, SUFFIXES
import pytest


def make_job(tmp_path, name, payloads, ytd="pack"):
    directory = tmp_path / "textures" / name
    directory.mkdir(parents=True)
    for suffix, data in zip(SUFFIXES, payloads):
        (directory / (name + suffix + ".dds")).write_bytes(data)
    return {"name": name, "texture_dir": str(directory), "ytd": ytd}


def test_same_dds_across_jobs_and_runs_share_sampler_name(tmp_path):
    first = prepare_job(make_job(tmp_path, "a", [b"diffuse", b"normal", b"specular"]))
    second = prepare_job(make_job(tmp_path, "b", [b"diffuse", b"other normal", b"specular"]))
    assert first["_d"] == second["_d"] and first["_s"] == second["_s"]
    assert first["_n"] != second["_n"]
    assert len(list((tmp_path / "textures/_shared").glob("*.dds"))) == 4


def test_missing_dds_stops_before_build(tmp_path):
    with pytest.raises(RuntimeError, match="DDS"):
        prepare_job(make_job(tmp_path, "a", [b"diffuse"]))


def test_embedded_paths_remain_compatible(tmp_path):
    files = prepare_job(make_job(tmp_path, "a", [b"d", b"n", b"s"], ytd=None))
    assert files["_d"].endswith("a_d.dds")


def test_corrupt_pool_entry_is_not_reused(tmp_path):
    from pathlib import Path
    job = make_job(tmp_path, "a", [b"d", b"n", b"s"])
    files = prepare_job(job)
    Path(files["_d"]).write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="Beschaedigte"):
        prepare_job(job)
