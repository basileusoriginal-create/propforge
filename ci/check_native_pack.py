"""Audit the desk-copy pack diagnostic after ci/read_native.py, not a converter.

Usage: python ci/check_native_pack.py <diagnostic-root>
Checks actual GEN8 DDS blocks and geometry decoded FROM the binaries.
The expected dimensions/material/triangle counts belong to the desk fixture.
"""
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci.check_native_textures import check
from propforge import ytyp_merge

root = Path(sys.argv[1]).resolve()
out = root / "work/ausgabe"
qa = root / "native_readback"
manifest = json.loads((out / "build/_ytd/pf_pack_textures.textures.json").read_text())
names = manifest["props"]
assert names == ["pf_pack_desk_a", "pf_pack_desk_b", "pf_pack_desk_c"]
ytd = out / "build/_ytd/pf_pack_textures.ytd"
reread = json.loads((qa / "readback.json").read_text())
txd = next(f for f in reread["files"] if f["asset_type"].endswith("TEXTURE_DICTIONARY"))
assert txd["dictionary_textures"] == sorted(manifest["textures"])
report = {"status": "passed", "method": "native GEN8 readback plus exact compressed DDS block comparison", "props": {}}
for name in names:
    xml = ET.parse(qa / (name + ".ydr.xml")).getroot()
    assert not xml.findall("ShaderGroup/TextureDictionary/Item")
    assert xml.findtext("ShaderGroup/Shaders/Item/FileName") == "normal_spec.sps"
    samplers = {n.get("name"): n.findtext("Name") for n in xml.findall("ShaderGroup/Shaders/Item/Parameters/Item") if n.get("type") == "Texture"}
    assert samplers == {"diffusesampler": name+"_d", "bumpsampler": name+"_n", "specsampler": name+"_s"}
    assert set(samplers.values()) <= set(manifest["textures"])
    lods = {}
    for tag, expected in zip(("High", "Medium", "Low", "VeryLow"), (2628, 1314, 578, 210)):
        geos = xml.findall(f"DrawableModels{tag}/Item/Geometries/Item")
        assert len(geos) == 1
        geo = geos[0]
        layout = [n.tag for n in geo.find("VertexBuffer/Layout")]
        assert layout == ["Position", "Normal", "Colour0", "TexCoord0", "Tangent"]
        data = np.fromstring(geo.findtext("VertexBuffer/Data"), sep=" ").reshape(-1,16)
        tris = np.fromstring(geo.findtext("IndexBuffer/Data"), sep=" ", dtype=int).reshape(-1,3)
        assert len(tris) == expected and tris.min() >= 0 and tris.max() < len(data)
        assert np.isfinite(data).all() and np.all(data[:,6:10] == 255)
        assert np.allclose(np.linalg.norm(data[:,3:6],axis=1),1,atol=.001)
        extent = np.ptp(data[:,:3],axis=0)
        if tag == "High":
            assert np.allclose(extent, (1.6,.800079,.75),atol=.0001)
            assert abs(data[:,2].min()) < .00001
        lods[tag] = {"triangles":len(tris), "dimensions_m":extent.tolist(), "attributes":layout}
    bound = xml.find("Bounds/Children/Item")
    assert bound.get("type") == "GeometryBVH"
    coll_tris = bound.findall("Polygons/Triangle")
    assert len(coll_tris) == 578
    assert [int(t.get("value")) for t in bound.findall("Materials/Item/Type")] == [70]
    assert bound.findtext("CompositeFlags1") and bound.findtext("CompositeFlags2")
    individual = ytyp_merge.read_archetypes(qa / (name+"_ityp.ytyp.xml"))[0]
    assert individual.element.findtext("textureDictionary") == "pf_pack_textures"
    assert individual.element.findtext("assetName") == name
    textures = check(ytd, out/"textures"/name, texture_prefix=name)
    assert all(t["levels"] == 10 and (t["width"],t["height"]) == (512,512) for t in textures["textures"])
    job = json.loads((root/"work/fertig"/(name+".job.json")).read_text())
    normal = np.array(Image.open(job["textures"]["normal"]).convert("RGB"))
    normal[:,:,1] = 255-normal[:,:,1]
    assert np.array_equal(normal,np.array(Image.open(out/"textures"/name/(name+"_n.png"))))
    report["props"][name] = {"lods":lods,"collision_triangles":len(coll_tris),"samplers":samplers,
                           "normal_green_flipped_once":True,"textures":textures}
merged = ytyp_merge.read_archetypes(root/"merged_readback/pf_pack_validation.ytyp.xml")
assert sorted(a.name for a in merged) == names
for entry in merged:
    original = ytyp_merge.read_archetypes(qa/(entry.name+"_ityp.ytyp.xml"))[0]
    assert entry.signature() == original.signature()
first = check(root/"run1_ytd/pf_pack_textures.ytd", out/"textures/pf_pack_desk_a", "pf_pack_desk_a")
assert [t["dds_sha256"] for t in first["textures"]] == [t["dds_sha256"] for t in report["props"][names[0]]["textures"]["textures"]]
report["run1_payload_preserved"] = True
report["shared_ytyp_fields_preserved"] = True
report["dictionary_texture_count"] = len(manifest["textures"])
hashes = [t["dds_sha256"] for p in report["props"].values() for t in p["textures"]["textures"]]
report["unique_dds_payloads"] = len(set(hashes))
report["content_deduplication"] = False
before = json.loads((root/"source_hashes_before.json").read_text(encoding="utf-8-sig"))
assert all(hashlib.sha256(Path(i["Path"]).read_bytes()).hexdigest().upper() == i["Hash"] for i in before)
report["source_files_unchanged"] = True
report["ingame"] = "pending"
(root/"native_pack_verification.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps({k:v for k,v in report.items() if k != "props"},indent=2))
