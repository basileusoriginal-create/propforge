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


def page_size(flags):
    groups = ((27, 1, 0), (26, 1, 1), (25, 1, 2), (24, 1, 3),
              (17, 127, 4), (11, 63, 5), (7, 15, 6), (5, 3, 7), (4, 1, 8))
    return (0x200 << (flags & 15)) * sum(((flags >> s) & m) << n for s, m, n in groups)


def check(ydr, texture_dir):
    binary = ydr.read_bytes()
    assert binary[:4] == b"RSC7", "Not a native RSC7 file"
    data = zlib.decompress(binary[16:], -15)
    system_size = page_size(struct.unpack_from("<I", binary, 8)[0])
    graphics_size = page_size(struct.unpack_from("<I", binary, 12)[0])
    assert len(data) == system_size + graphics_size
    result = []
    for suffix, fmt in (("d", b"DXT1"), ("n", b"DXT5"), ("s", b"DXT1")):
        name = ydr.stem + "_" + suffix
        source = (texture_dir / (name + ".dds")).read_bytes()
        assert source[:4] == b"DDS " and source[84:88] == fmt
        height, width = struct.unpack_from("<II", source, 12)
        levels = struct.unpack_from("<I", source, 28)[0]
        assert levels == int(math.log2(max(width, height))) + 1
        block_bytes = 16 if fmt == b"DXT5" else 8
        mip_bytes = [max(1, (max(1, width >> i) + 3) // 4) *
                     max(1, (max(1, height >> i) + 3) // 4) * block_bytes for i in range(levels)]
        assert len(source) == 128 + sum(mip_bytes)
        candidates = []
        search = 0
        while (name_at := data.find(name.encode() + b"\0", search, system_size)) >= 0:
            search = name_at + 1
            pointer = struct.pack("<Q", 0x50000000 + name_at)
            ref_start = 0
            while (ref := data.find(pointer, ref_start, system_size)) >= 0:
                ref_start = ref + 1
                offset = ref - 0x28
                if offset < 0 or offset + 144 > system_size:
                    continue
                w, h = struct.unpack_from("<HH", data, offset + 0x50)
                if (w, h) == (width, height) and data[offset + 0x58:offset + 0x5c] == fmt:
                    candidates.append(offset)
        assert len(candidates) == 1, f"Expected one GEN8 texture header for {name}"
        offset = candidates[0]
        assert data[offset + 0x5d] == levels
        gpu_pointer = struct.unpack_from("<Q", data, offset + 0x70)[0]
        assert 0x60000000 <= gpu_pointer < 0x60000000 + graphics_size
        payload_start = system_size + gpu_pointer - 0x60000000
        payload = data[payload_start:payload_start + sum(mip_bytes)]
        assert payload == source[128:], f"Native mip blocks differ for {name}"
        result.append({"name": name, "width": width, "height": height, "format": fmt.decode(),
                       "levels": levels, "mip_block_bytes": mip_bytes,
                       "all_mip_blocks_identical": True, "payload_bytes": len(payload),
                       "native_header_offset": offset, "native_data_pointer": hex(gpu_pointer),
                       "dds_sha256": hashlib.sha256(source).hexdigest()})
    return {"ydr_sha256": hashlib.sha256(binary).hexdigest(),
            "system_bytes": system_size, "graphics_bytes": graphics_size,
            "status": "passed", "textures": result}


if __name__ == "__main__":
    ydr, texture_dir, report = map(Path, sys.argv[1:])
    result = check(ydr, texture_dir)
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
