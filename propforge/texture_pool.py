"""Content-addressed DDS names shared by material samplers and dictionaries."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

SUFFIXES = ("_d", "_n", "_s")


def prepare_job(job: dict) -> dict[str, str]:
    """Keep embedded names compatible; deduplicate complete DDS bytes for YTDs."""
    source_dir = Path(job["texture_dir"])
    sources = {suffix: source_dir / f"{job['name']}{suffix}.dds" for suffix in SUFFIXES}
    missing = [p.name for p in sources.values() if not p.is_file()]
    if missing:
        raise RuntimeError("DDS vor Materialaufbau fehlen: " + ", ".join(missing))
    if not job.get("ytd"):
        return {suffix: str(path) for suffix, path in sources.items()}
    pool = source_dir.parent / "_shared"
    pool.mkdir(parents=True, exist_ok=True)
    result = {}
    for suffix, source in sources.items():
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        target = pool / f"pftex_{digest}.dds"
        if target.exists():
            if target.read_bytes() != data:
                raise RuntimeError(f"Beschaedigte gemeinsame DDS: {target}")
        else:
            shutil.copy2(source, target)
        result[suffix] = str(target)
    return result
