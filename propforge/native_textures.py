"""Validate GEN8 native DDS headers and every compressed mip block.

The existing diagnostic is now reusable by normal conversion. This reader is
deliberately restricted to classic GEN8 BC1/BC3 atlas data. It never writes a
native file. Layout: CodeWalker Texture.cs/RpfFile.cs (reviewed 2026-09-07).
"""
from __future__ import annotations
import hashlib
import math
import struct
import zlib
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def page_size(flags):
    groups = ((27, 1, 0), (26, 1, 1), (25, 1, 2), (24, 1, 3),
              (17, 127, 4), (11, 63, 5), (7, 15, 6), (5, 3, 7), (4, 1, 8))
    return (0x200 << (flags & 15)) * sum(((flags >> s) & m) << n for s, m, n in groups)


def check_dds(source: bytes):
    require(len(source) >= 128 and source[:4] == b"DDS ", "DDS-Header fehlt")
    fmt = source[84:88]
    require(fmt in (b"DXT1", b"DXT5"), f"Atlas-Format nicht unterstuetzt: {fmt!r}")
    height, width = struct.unpack_from("<II", source, 12)
    require(all(16 <= n <= 2048 and (n & (n - 1)) == 0 for n in (width, height)),
            f"Atlas-Regel: POT-Kanten zwischen 16 und 2048, erhalten {width}x{height}")
    levels = struct.unpack_from("<I", source, 28)[0]
    require(levels == int(math.log2(max(width, height))) + 1, "DDS-Mipkette unvollstaendig")
    block_bytes = 16 if fmt == b"DXT5" else 8
    mip_bytes = [max(1, (max(1, width >> i) + 3) // 4) *
                 max(1, (max(1, height >> i) + 3) // 4) * block_bytes for i in range(levels)]
    require(len(source) == 128 + sum(mip_bytes), "DDS-Nutzdatenlaenge passt nicht zur Mipkette")
    return width, height, fmt, levels, mip_bytes


def check_files(native: Path, sources: dict[str, Path]):
    binary = Path(native).read_bytes()
    require(len(binary) >= 16 and binary[:4] == b"RSC7", "Native RSC7-Datei fehlt")
    data = zlib.decompress(binary[16:], -15)
    system_size = page_size(struct.unpack_from("<I", binary, 8)[0])
    graphics_size = page_size(struct.unpack_from("<I", binary, 12)[0])
    require(len(data) == system_size + graphics_size, "Native Seitengroessen unplausibel")
    result = []
    for name, path in sorted(sources.items()):
        source = Path(path).read_bytes()
        width, height, fmt, levels, mip_bytes = check_dds(source)
        candidates = set()
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
                    candidates.add(offset)
        require(len(candidates) == 1, f"Erwartet genau einen GEN8-Texturheader fuer {name}")
        offset = candidates.pop()
        require(data[offset + 0x5d] == levels, f"Native Mip-Anzahl falsch: {name}")
        gpu_pointer = struct.unpack_from("<Q", data, offset + 0x70)[0]
        require(0x60000000 <= gpu_pointer < 0x60000000 + graphics_size, f"Texturzeiger ausserhalb der Grafikseiten: {name}")
        start = system_size + gpu_pointer - 0x60000000
        require(start + sum(mip_bytes) <= len(data), f"Native Texturdaten abgeschnitten: {name}")
        payload = data[start:start + sum(mip_bytes)]
        require(payload == source[128:], f"Native Mip-Bloecke weichen von DDS ab: {name}")
        result.append({"name": name, "width": width, "height": height, "format": fmt.decode(),
                       "levels": levels, "mip_block_bytes": mip_bytes,
                       "all_mip_blocks_identical": True, "payload_bytes": len(payload),
                       "native_header_offset": offset, "native_data_pointer": hex(gpu_pointer),
                       "dds_sha256": hashlib.sha256(source).hexdigest()})
    return {"ydr_sha256": hashlib.sha256(binary).hexdigest(),
            "system_bytes": system_size, "graphics_bytes": graphics_size,
            "status": "passed", "textures": result}
