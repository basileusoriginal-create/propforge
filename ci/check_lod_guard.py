"""Real Blender regression: a tiny textured box and thin contact legs survive."""
import bpy
import json
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "blender"))
import sz_build_prop as build

def validate(source):
    source.data.calc_loop_triangles()
    from propforge.lod_guard import protected_vertices
    from mathutils.kdtree import KDTree
    mesh = source.data
    protected = protected_vertices([tuple(v.co) for v in mesh.vertices],
                                   [tuple(e.vertices) for e in mesh.edges],
                                   [tuple(t.vertices) for t in mesh.loop_triangles])
    results = {}
    for name, ratio in (("high", 1.), ("medium", .5), ("low", .22), ("verylow", .08)):
        lod = build.decimate_to_ratio(source, ratio, name)
        lod.calc_loop_triangles()
        assert len(lod.loop_triangles) > 0
        assert all(t.area > 1e-12 for t in lod.loop_triangles)
        assert all(n.vector.length > 1e-8 for n in lod.corner_normals)
        tree = KDTree(len(lod.vertices))
        for v in lod.vertices: tree.insert(v.co, v.index)
        tree.balance()
        assert all(tree.find(mesh.vertices[i].co)[2] <= .0001 for i in protected)
        results[name] = len(lod.loop_triangles)
        bpy.data.meshes.remove(lod)
    return results

build.reset_scene()
bpy.ops.mesh.primitive_cube_add(size=1.0)
tiny = bpy.context.object
small = validate(tiny)
assert set(small.values()) == {12}
build.reset_scene()
bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, radius=.5, location=(0,0,1.0))
body = bpy.context.object
objects = [body]
for x in (-.2, .2):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x,0,.25))
    leg = bpy.context.object
    leg.scale = (.04,.04,.5)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    objects.append(leg)
bpy.ops.object.select_all(action="DESELECT")
for obj in objects: obj.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
thin = validate(body)
assert thin["medium"] < thin["high"]
print("LOD_GUARD_PASSED=" + json.dumps({"tiny": small, "thin": thin}))
