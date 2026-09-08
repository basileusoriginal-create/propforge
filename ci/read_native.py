"""Diagnostic readback of already built binaries; never builds source geometry.

Run inside the configured Blender Python context:
  blender --background --python ci/read_native.py -- <build_dir> <qa_dir>
The XML is a diagnostic representation decoded from the native files and is
kept outside build/stream. It is not a second export of the Blender source.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

from szio.gta5 import AssetFormat, AssetTarget, AssetVersion, save_asset, try_load_asset
import pymateria.gta5.gen8 as pmg8

args = sys.argv[sys.argv.index("--") + 1:]
build_dir, qa_dir = (Path(arg).resolve() for arg in args)
qa_dir.mkdir(parents=True, exist_ok=True)
report = {"method": "szio/PyMateria native readback to diagnostic CWXML", "files": []}
for path in sorted(build_dir.rglob("*")):
    if path.suffix not in (".ydr", ".ytyp", ".ytd"):
        continue
    raw_textures = []
    if path.suffix == ".ydr":
        # szio's DDS extraction intentionally pops the sub-4x4 mips from
        # its in-memory copy. Count the original native mips before that.
        raw = pmg8.Drawable.import_rsc(path).result
        dictionary = raw.shader_group.texture_dictionary
        for texture in (dictionary.textures.values() if dictionary else ()):
            raw_textures.append({
                "name": texture.name, "width": texture.width, "height": texture.height,
                "format": str(texture.format), "mip_count": len(texture.mips),
                "mip_layer_shapes": [[list(layer.shape) for layer in mip.layers] for mip in texture.mips],
            })
    loaded = try_load_asset(path, return_target=True)
    if loaded is None:
        raise RuntimeError(f"Native file was not readable: {path}")
    asset, target = loaded
    if target != AssetTarget(AssetFormat.NATIVE, AssetVersion.GEN8):
        raise RuntimeError(f"Unexpected native target: {target}")
    save_asset(asset, [AssetTarget(AssetFormat.CWXML, AssetVersion.GEN8)], qa_dir, path.stem)
    embedded = []
    group = getattr(asset, "shader_group", None)
    for texture in (group.embedded_textures.values() if group else ()):
        if texture.data is None:
            raise RuntimeError(f"Embedded texture has no data: {texture.name}")
        with texture.data.open() as stream:
            data = stream.read()
        if data[:4] != b"DDS ":
            raise RuntimeError(f"Texture readback is not DDS: {texture.name}")
        texture_dir = qa_dir / path.stem
        texture_dir.mkdir(exist_ok=True)
        (texture_dir / (texture.name + ".dds")).write_bytes(data)
        height, width = struct.unpack_from("<II", data, 12)
        embedded.append({
            "name": texture.name, "width": width, "height": height,
            "mipmaps": struct.unpack_from("<I", data, 28)[0],
            "fourcc": data[84:88].decode("ascii"), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    report["files"].append({
        "path": str(path.resolve()), "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "target": str(target), "asset_type": str(asset.ASSET_TYPE),
        "embedded_dds": embedded,
        "direct_pymateria_textures": raw_textures,
        "dictionary_textures": sorted(asset.textures) if path.suffix == ".ytd" else [],
    })
if not report["files"]:
    raise RuntimeError("No native files found")
(qa_dir / "readback.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
