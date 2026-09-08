"""Read and verify actual GEN8 binaries in the installed Blender/szio context.

CWXML here is decoded FROM a native file for inspection, never rebuilt from
the source. Complete texture mip blocks are checked directly in the binary.
"""
from __future__ import annotations
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from .native_textures import check_files, require
from . import placement
from .inspect import LOD_ELEMENTS, LOD_DIST_ELEMENTS


def files_in(root: Path, suffix: str):
    return sorted(p for p in root.rglob("*" + suffix) if p.is_file()
                  and not any(part.startswith(".") for part in p.relative_to(root).parts))


def read_native(path, out):
    from szio.gta5 import AssetFormat, AssetTarget, AssetVersion, save_asset, try_load_asset
    loaded = try_load_asset(path, return_target=True)
    require(loaded is not None, f"Native Datei nicht lesbar: {path}")
    asset, target = loaded
    require(target == AssetTarget(AssetFormat.NATIVE, AssetVersion.GEN8), f"Nicht GEN8/NATIVE: {path}")
    save_asset(asset, [AssetTarget(AssetFormat.CWXML, AssetVersion.GEN8)], out, path.stem)
    xml = out / (path.name + ".xml")
    require(xml.is_file(), f"Keine native Ruecklesung: {path}")
    return asset, ET.parse(xml).getroot()


def _bounds(points):
    return {"min": points.min(axis=0).tolist(), "max": points.max(axis=0).tolist()}


def _close_bounds(actual, wanted, label, tolerance=0.00015):
    require(all(abs(actual[k][i] - wanted[k][i]) <= tolerance
                for k in ("min", "max") for i in range(3)), f"Bounds weichen ab: {label}")


def drawable_geometry(xml, receipt):
    import numpy as np
    job = receipt["job"]
    lods = {}
    shaders = xml.findall("ShaderGroup/Shaders/Item")
    require(len(shaders) == 1 and shaders[0].findtext("FileName") == job["shader"], "Erwartet ein Atlas-Shadermaterial")
    samplers = {p.get("name").lower(): p.findtext("Name") for p in shaders[0].findall("Parameters/Item")
                if p.get("type") == "Texture"}
    expected_samplers = dict(zip(("diffusesampler", "bumpsampler", "specsampler"),
                                (Path(job["texture_files"][s]).stem.lower() for s in ("_d", "_n", "_s"))))
    require(samplers == expected_samplers, f"Sampler-Verweise weichen ab: {job['name']}")
    for key, tag in LOD_ELEMENTS.items():
        geometries = xml.findall(f"{tag}/Item/Geometries/Item")
        require(len(geometries) == 1, f"{key}: erwartet eine Atlas-Geometrie")
        geo = geometries[0]
        layout = [n.tag for n in geo.find("VertexBuffer/Layout")]
        require(layout == ["Position", "Normal", "Colour0", "TexCoord0", "Tangent"], f"{key}: ungueltige Vertex-Attribute {layout}")
        values = np.fromstring(geo.findtext("VertexBuffer/Data"), sep=" ")
        require(len(values) > 0 and len(values) % 16 == 0, f"{key}: Vertexpuffer leer/defekt")
        data = values.reshape(-1, 16)
        indices = np.fromstring(geo.findtext("IndexBuffer/Data"), sep=" ", dtype=int)
        require(len(indices) > 0 and len(indices) % 3 == 0, f"{key}: Indexpuffer leer/defekt")
        tris = indices.reshape(-1, 3)
        require(tris.min() >= 0 and tris.max() < len(data), f"{key}: Indizes ausserhalb des Vertexpuffers")
        require(np.isfinite(data).all(), f"{key}: nicht endliche Vertexdaten")
        require(np.allclose(np.linalg.norm(data[:, 3:6], axis=1), 1, atol=.001), f"{key}: ungueltige Normalen")
        require(np.all(data[:, 6:10] == 255), f"{key}: Atlas-Vertexfarben weichen ab")
        positions = data[:, :3]
        areas = np.linalg.norm(np.cross(positions[tris[:, 1]] - positions[tris[:, 0]],
                                        positions[tris[:, 2]] - positions[tris[:, 0]]), axis=1) / 2
        require(np.all(areas > 1e-12), f"{key}: degenerierte Dreiecke")
        expected = receipt["lods"][key]
        require(len(tris) == expected["triangles"], f"{key}: native Dreieckszahl weicht vom Build ab")
        box = _bounds(positions)
        _close_bounds(box, expected["bounds"], key)
        distance = float(xml.find(LOD_DIST_ELEMENTS[key]).get("value"))
        require(abs(distance - job["lod_distances"][key]) < .01, f"{key}: falsche LOD-Distanz")
        lods[key] = {"triangles": len(tris), "bounds": box, "distance": distance, "attributes": layout}
    collision = job["collision"]
    bounds = xml.findall("Bounds/Children/Item")
    if collision.get("enabled", True):
        require(bool(bounds), "Eingebettete Kollision leer")
        collision_count = 0
        for bound in bounds:
            require(bound.get("type") in ("GeometryBVH", "Geometry"), "Nicht gepruefter Kollisionstyp")
            polygons = bound.findall("Polygons/Triangle")
            require(bool(polygons), "Kollisionsgeometrie leer")
            vertices = np.fromstring((bound.findtext("Vertices") or "").replace(",", " "), sep=" ").reshape(-1, 3)
            require(len(vertices) > 0 and np.isfinite(vertices).all(), "Kollisionsvertices leer/ungueltig")
            require(bool(bound.findtext("CompositeFlags1")) and bool(bound.findtext("CompositeFlags2")), "Kollisionsflags leer")
            material_types = [int(n.get("value")) for n in bound.findall("Materials/Item/Type")]
            from .sollumz_env import import_sollumz
            material_index = import_sollumz().collision_material_names.index(collision.get("material", "DEFAULT"))
            require(material_types and all(n == material_index for n in material_types), "Kollisionsmaterial weicht ab")
            for triangle in polygons:
                require(all(0 <= int(triangle.get(k)) < len(vertices) for k in ("v1", "v2", "v3")), "Kollisionsindex ausserhalb der Geometrie")
            collision_count += len(polygons)
    else:
        require(not bounds, "Unerwartete Kollision")
        collision_count = 0
    return {"lods": lods, "samplers": samplers, "collision_triangles": collision_count}


def verify(build_dir: Path, qa_dir: Path):
    build_dir, qa_dir = Path(build_dir).resolve(), Path(qa_dir).resolve()
    require(qa_dir != build_dir and build_dir not in qa_dir.parents,
            "Native Pruefberichte gehoeren ausserhalb des Build-Ordners")
    qa_dir.mkdir(parents=True, exist_ok=True)
    paths = [p for suffix in (".ydr", ".ytd", ".ytyp") for p in files_in(build_dir, suffix)]
    require(bool(paths), "Keine nativen Dateien gefunden")
    require(bool(files_in(build_dir, ".ydr")), "Keine nativen Drawables gefunden")
    require(len({p.name.lower() for p in paths}) == len(paths), "Doppelte native Dateinamen")
    decoded = {}
    for path in paths:
        decoded[path.name] = read_native(path, qa_dir)
    dictionaries = {}
    for path in files_in(build_dir, ".ytd"):
        manifest_path = path.with_suffix(".textures.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sources = {name: (manifest_path.parent / value).resolve() for name, value in manifest["textures"].items()}
        require(set(decoded[path.name][0].textures) == set(sources), f"{path.name}: Texturverzeichnis unvollstaendig")
        dictionaries[path.stem] = check_files(path, sources)
    archetypes = {}
    for path in files_in(build_dir, ".ytyp"):
        for item in decoded[path.name][1].findall("archetypes/Item"):
            name = item.findtext("name")
            require(name not in archetypes, f"Archetyp doppelt registriert: {name}")
            archetypes[name] = item
    props = {}
    for path in files_in(build_dir, ".ydr"):
        receipt_path = path.with_suffix(".build.json")
        require(receipt_path.is_file(), f"{path.name}: Build-Beleg fehlt; Alt-Asset fuer dieses Pack neu bauen")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        require(receipt.get("version") == 1, f"{path.name}: unbekannter Build-Beleg")
        job = receipt["job"]
        for name, expected_hash in receipt["files"].items():
            source = path.parent / name
            require(source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() == expected_hash,
                    f"Build-Beleg passt nicht zu {name}")
        native_asset, xml = decoded[path.name]
        geometry = drawable_geometry(xml, receipt)
        box = placement.read(path)
        require(box is not None, f"Standhoehen-Beleg fehlt: {path.name}")
        _close_bounds(box, geometry["lods"]["high"]["bounds"], path.name)
        require(path.stem in archetypes, f"Archetyp fehlt: {path.stem}")
        archetype = archetypes[path.stem]
        require(archetype.findtext("assetName") == path.stem, f"Archetyp verweist auf anderes Drawable: {path.stem}")
        require((archetype.findtext("textureDictionary") or "") == job["ytyp"]["texture_dictionary"], "Archetyp-Texturwoerterbuch weicht ab")
        for key, field in (("lod_dist", "lodDist"), ("hd_texture_dist", "hdTextureDist"), ("flags", "flags")):
            require(abs(float(archetype.find(field).get("value")) - float(job["ytyp"][key])) < .001, f"Archetyp {field} weicht ab")
        for field in ("bbMin", "bbMax", "bsCentre"):
            require(all(math.isfinite(float(archetype.find(field).get(axis))) for axis in ("x", "y", "z")), "Archetyp-Bounds ungueltig")
        require(float(archetype.find("bsRadius").get("value")) > 0, "Archetyp-Radius ungueltig")
        embedded = xml.findall("ShaderGroup/TextureDictionary/Item")
        if job.get("ytd"):
            require(not embedded, "YTD-Prop enthaelt unerwartet eingebettete Texturen")
            require(job["ytd"] in dictionaries, f"YTD fehlt: {job['ytd']}")
            texture_names = {t["name"] for t in dictionaries[job["ytd"]]["textures"]}
            require(set(geometry["samplers"].values()) <= texture_names, "Sampler nicht in YTD")
        else:
            sources = {Path(p).stem: Path(p) for p in job["texture_files"].values()}
            require({i.findtext("Name") for i in embedded} == set(sources), "Eingebettete Texturen unvollstaendig")
            geometry["embedded_textures"] = check_files(path, sources)
        geometry["toolchain"] = receipt["toolchain"]
        geometry["placement_bounds"] = box
        props[path.stem] = geometry
    require(set(props) == set(archetypes), "YTYP-/YDR-Bestand ist nicht deckungsgleich")
    result = {"status": "passed", "version": 1,
              "method": "GEN8 binary readback via szio plus direct native DDS mip payload comparison",
              "props": props, "dictionaries": dictionaries,
              "files": {p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size} for p in paths},
              "manual_checks": ["Materialwirkung", "LOD-Uebergaenge im Spiel", "begehbare Kollision", "Streaming unter konkreter Last"]}
    (qa_dir / "native_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
