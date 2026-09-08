"""Read-only GEN8 texture payload check against the prepared DDS files.

This narrow diagnostic checks the raw native headers AND every compressed
mip block, because szio 1.3.0.dev9 truncates sub-4x4 mips on DDS readback.
Layout reference (read 2026-09-07): CodeWalker.Core/GameFiles/Resources/Texture.cs
and GameFiles/RpfFile.cs at https://github.com/dexyfex/CodeWalker.
It does not write or convert any native asset.
"""
import hashlib
import json
import math
import struct
import sys
import zlib
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from propforge.native_textures import check_files, page_size


def check(ydr, texture_dir, texture_prefix=None):
    prefix = texture_prefix or ydr.stem
    return check_files(ydr, {prefix + '_' + role: texture_dir / (prefix + '_' + role + '.dds')
                             for role in ('d', 'n', 's')})

if __name__ == "__main__":
    ydr, texture_dir, report = map(Path, sys.argv[1:])
    result = check(ydr, texture_dir)
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
