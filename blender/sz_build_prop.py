"""Blender-Stufe der Prop-Pipeline. Laeuft headless.

Aufruf:
    blender --background --python blender/sz_build_prop.py -- --job job.json

Erwartet ein installiertes und aktiviertes Sollumz (>= 2.9-dev, Blender >= 4.2).
Die verwendete API ist gegen den Sollumz-Quellcode geprueft:

  obj.sollum_type                    -> SollumType-Enum
  obj.sz_lods.get_lod(LODLevel.X)    -> LODLevelProps, Feld .mesh
  obj.drawable_properties.lod_dist_* -> Sichtweiten des Drawables
  bpy.ops.sollumz.converttodrawable  -> erzeugt Drawable + optional Kollision
  bpy.ops.sollumz.export_assets      -> Export, mit direct_export=True headless
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

# --- Sollumz-Importe -------------------------------------------------------
# Die Liste der moeglichen Sollumz-Modulnamen liegt in propforge.sollumz_env,
# damit Umgebungspruefung und Build-Stufe nicht auseinanderlaufen koennen.
# Das Modul ist bewusst abhaengigkeitsfrei, damit es auch aus Blenders Python
# importierbar ist.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from propforge.sollumz_env import import_sollumz
except ImportError:  # Notfallpfad, falls das Repo-Layout nicht mitgereicht wurde
    def import_sollumz():
        import importlib

        errors = []
        for module_name in ("Sollumz", "sollumz", "bl_ext.user_default.sollumz"):
            try:
                props = importlib.import_module(f"{module_name}.sollumz_properties")
                shaders = importlib.import_module(f"{module_name}.ydr.shader_materials")
                return props.SollumType, props.LODLevel, shaders.create_shader, module_name
            except ImportError as exc:
                errors.append(f"  {module_name}: {exc}")
        raise ImportError("Sollumz nicht gefunden:\n" + "\n".join(errors))


try:
    SollumType, LODLevel, create_shader, SOLLUMZ_MODULE = import_sollumz()
except ImportError as exc:
    raise SystemExit(
        f"{exc}\n\nAdd-on installieren und aktivieren, dann erneut versuchen."
    ) from exc


LOD_ENUM = {
    "high": LODLevel.HIGH,
    "medium": LODLevel.MEDIUM,
    "low": LODLevel.LOW,
    "verylow": LODLevel.VERYLOW,
}

IMPORTERS = {
    ".glb": lambda p: bpy.ops.import_scene.gltf(filepath=p),
    ".gltf": lambda p: bpy.ops.import_scene.gltf(filepath=p),
    ".obj": lambda p: bpy.ops.wm.obj_import(filepath=p),
    ".fbx": lambda p: bpy.ops.import_scene.fbx(filepath=p),
    ".ply": lambda p: bpy.ops.wm.ply_import(filepath=p),
    ".stl": lambda p: bpy.ops.wm.stl_import(filepath=p),
}


def log(msg: str) -> None:
    print(f"[propforge] {msg}", flush=True)


# --- Szene ------------------------------------------------------------------

def reset_scene() -> None:
    """Leert die Szene, ohne die Preferences anzufassen.

    Nicht read_factory_settings verwenden: das setzt auch die Einstellungen
    zurueck und kann dabei die aktivierten Add-ons mitnehmen - also Sollumz
    selbst. Sollumz' eigene Tests benutzen read_homefile, und das ist auch
    hier der richtige Aufruf.
    """
    bpy.ops.wm.read_homefile(use_empty=True)


def select_only(obj: bpy.types.Object) -> None:
    """Selektiert genau ein Objekt und macht es aktiv.

    Ueber `selected_objects` statt `view_layer.objects`: letzteres kann nach
    einem `bpy.data.objects.remove()` verwaiste Eintraege enthalten, die beim
    Iterieren als None auftauchen. `selected_objects` ist eine Momentaufnahme
    und damit die deutlich kleinere und stabilere Liste.
    """
    for other in tuple(bpy.context.selected_objects):
        if other is not None:
            other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


# --- Import und Aufraeumen --------------------------------------------------

def import_mesh(path: Path) -> bpy.types.Object:
    suffix = path.suffix.lower()
    if suffix not in IMPORTERS:
        raise SystemExit(f"Nicht unterstuetztes Meshformat: {suffix}")

    before = set(bpy.data.objects)
    IMPORTERS[suffix](str(path))
    new_meshes = [o for o in set(bpy.data.objects) - before if o.type == "MESH"]
    if not new_meshes:
        raise SystemExit(f"Keine Mesh-Objekte in {path} gefunden.")

    if len(new_meshes) > 1:
        bpy.ops.object.select_all(action="DESELECT")
        for o in new_meshes:
            o.select_set(True)
        bpy.context.view_layer.objects.active = new_meshes[0]
        bpy.ops.object.join()

    obj = bpy.context.view_layer.objects.active
    obj.name = path.stem
    return obj


def cleanup_mesh(obj: bpy.types.Object) -> None:
    """Standard-Aufraeumen fuer generierte Meshes.

    AI-Generatoren liefern haeufig doppelte Vertices, inkonsistente Normalen
    und eine nicht angewandte Transformation. Alles drei bricht spaeter den
    Export oder fuehrt zu falscher Beleuchtung im Spiel.
    """
    select_only(obj)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=0.0001)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.mesh.quads_convert_to_tris(quad_method="BEAUTY", ngon_method="BEAUTY")
    bpy.ops.object.mode_set(mode="OBJECT")

    bpy.ops.object.shade_smooth()


def tri_count(obj: bpy.types.Object) -> int:
    """Zaehlt Dreiecke.

    `loop_triangles` ist leer, solange es nicht berechnet wurde - ohne den
    Aufruf haette die Budget-Pruefung stumm immer 0 gemeldet und nie gegriffen.
    """
    mesh = obj.data
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def ensure_uvs(obj: bpy.types.Object) -> bool:
    """Erzeugt notfalls ein Smart-UV-Projekt.

    Ein Drawable ohne UV-Layer exportiert zwar, zeigt im Spiel aber nur
    Texturmatsch. Besser ein automatisches Unwrap als gar keines - fuer
    verkaufsfertige Assets bleibt das trotzdem ein Handarbeitsschritt.
    """
    if obj.data.uv_layers:
        return False
    log(f"'{obj.name}' hat keine UV-Map - erzeuge Smart UV Project (bitte nachpruefen).")
    select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")
    return True


# --- LODs -------------------------------------------------------------------

def _bake_decimate(obj: bpy.types.Object, ratio: float, name: str) -> bpy.types.Mesh:
    """Backt einen Decimate-Modifier in einen neuen Mesh-Datenblock.

    Bewusst ohne Operatoren: `modifier_apply` braucht die richtige Selektion,
    den richtigen Modus und einen gueltigen Kontext, und jeder dieser drei
    Punkte ist im Hintergrundmodus eine Fehlerquelle. Der Weg ueber den
    Depsgraph wertet den Modifier direkt aus und ist vom Kontext unabhaengig.
    """
    tmp = obj.copy()
    tmp.data = obj.data.copy()
    bpy.context.collection.objects.link(tmp)

    try:
        mod = tmp.modifiers.new(name="lod_decimate", type="DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.ratio = ratio
        # Symmetrie aus: sie kann bei asymmetrischen Props die Silhouette kippen.
        mod.use_symmetry = False

        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = tmp.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(
            evaluated, preserve_all_data_layers=True, depsgraph=depsgraph
        )
        mesh.name = name
    finally:
        # Hilfsobjekt immer entfernen, auch wenn die Auswertung scheitert -
        # sonst landet es in der exportierten Hierarchie.
        bpy.data.objects.remove(tmp, do_unlink=True)

    return mesh


def decimate_to_ratio(obj: bpy.types.Object, ratio: float, name: str) -> bpy.types.Mesh:
    """Erzeugt eine reduzierte Kopie des Meshes als eigenen Datenblock."""
    if ratio >= 1.0:
        mesh = obj.data.copy()
        mesh.name = name
        return mesh
    return _bake_decimate(obj, ratio, name)


def clamp_to_budget(obj: bpy.types.Object, max_tris: int) -> None:
    """Reduziert LOD0, falls das generierte Mesh ueber dem Budget liegt."""
    current = tri_count(obj)
    if current <= max_tris:
        return

    ratio = max_tris / current
    log(f"LOD0 hat {current} Tris, Budget ist {max_tris} - reduziere auf Faktor {ratio:.3f}.")

    reduced = _bake_decimate(obj, ratio, f"{obj.data.name}_budget")
    old = obj.data
    obj.data = reduced
    if old.users == 0:
        bpy.data.meshes.remove(old)


# --- Material ---------------------------------------------------------------

def build_material(job: dict, mesh_obj: bpy.types.Object) -> bpy.types.Material:
    """Erzeugt ein Sollumz-Shadermaterial und haengt die DDS-Texturen ein."""
    shader_name = job["shader"]
    mat = create_shader(shader_name)
    mat.name = f"{job['name']}_mat"

    texture_dir = Path(job["texture_dir"])
    # Rollen-Suffix -> Samplername im Sollumz-Nodetree
    mapping = {
        "_d": "DiffuseSampler",
        "_n": "BumpSampler",
        "_s": "SpecSampler",
    }

    attached = 0
    for suffix, sampler in mapping.items():
        dds = texture_dir / f"{job['name']}{suffix}.dds"
        if not dds.is_file():
            continue
        node = mat.node_tree.nodes.get(sampler)
        if node is None:
            log(f"Shader '{shader_name}' hat keinen {sampler} - '{dds.name}' wird uebersprungen.")
            continue
        node.image = bpy.data.images.load(str(dds), check_existing=True)
        # sollumz_texture_name NICHT setzen: die Property hat nur einen Getter.
        # Sollumz leitet den Namen aus dem Dateipfad ab (Basisname ohne Endung,
        # kleingeschrieben). Es reicht also, die DDS unter dem gewuenschten
        # Namen zu laden - was die Texturstufe ohnehin tut.
        # Eingebettet: die Textur wandert in die .ydr statt in eine separate .ytd.
        node.texture_properties.embedded = True
        attached += 1
        log(f"  {sampler:<15} <- {dds.name} (Texturname: {node.sollumz_texture_name})")

    if attached == 0:
        log(f"Warnung: keine Textur an '{shader_name}' gebunden - liegen die DDS in {texture_dir}?")

    mesh_obj.data.materials.clear()
    mesh_obj.data.materials.append(mat)
    return mat


# --- Drawable ---------------------------------------------------------------

def configure_conversion(job: dict) -> None:
    scene = bpy.context.scene
    collision = job["collision"]
    scene.auto_create_embedded_col = bool(collision.get("enabled", True))
    scene.create_seperate_drawables = True
    scene.center_drawable_to_selection = False
    scene.sz_default_flag_preset_name = collision.get("flag_preset", "Default")


def find_drawable_root(candidates: set[bpy.types.Object]) -> bpy.types.Object:
    for obj in bpy.data.objects:
        if obj in candidates:
            continue
        if getattr(obj, "sollum_type", None) == SollumType.DRAWABLE:
            return obj
    raise SystemExit("Konvertierung lieferte kein Drawable - Sollumz-Version pruefen.")


def find_drawable_model(drawable: bpy.types.Object) -> bpy.types.Object:
    for child in drawable.children_recursive:
        if child.sollum_type == SollumType.DRAWABLE_MODEL:
            return child
    raise SystemExit(f"Kein Drawable Model unter '{drawable.name}' gefunden.")


def assign_lods(model_obj: bpy.types.Object, lod_meshes: dict[str, bpy.types.Mesh]) -> None:
    """Haengt die vorbereiteten LOD-Meshes in die Sollumz-LOD-Slots.

    Reihenfolge ist wichtig: erst die aktive Stufe setzen, damit Sollumz
    obj.data korrekt fuehrt, dann die uebrigen Stufen als mesh_ref ablegen.
    """
    lods = model_obj.sz_lods
    lods.active_lod_level = LODLevel.HIGH

    if "high" in lod_meshes:
        lods.get_lod(LODLevel.HIGH).mesh = lod_meshes["high"]

    for key in ("medium", "low", "verylow"):
        if key in lod_meshes:
            lods.get_lod(LOD_ENUM[key]).mesh = lod_meshes[key]

    lods.set_highest_lod_active()


def retarget_collision(
    drawable: bpy.types.Object,
    lod_meshes: dict[str, bpy.types.Mesh],
    collision: dict,
) -> None:
    """Baut die Kollision auf einer guenstigeren LOD-Stufe neu auf.

    `sollumz.converttodrawable` erzeugt die eingebettete Kollision immer aus
    dem LOD0-Mesh. Fuer einen Prop mit 10.000 Dreiecken bedeutet das 10.000
    Kollisionsdreiecke - deutlich mehr, als die Physik braucht. Hier wird die
    Bound-Geometrie nachtraeglich auf die konfigurierte LOD-Stufe umgehaengt.
    """
    if not collision.get("enabled", True):
        return

    source_lod = collision.get("source_lod", "low")
    mesh = lod_meshes.get(source_lod)
    if mesh is None:
        log(f"Kollisions-LOD '{source_lod}' nicht vorhanden - behalte LOD0-Kollision.")
        return

    bound_objs = [
        child for child in drawable.children_recursive
        if child.type == "MESH" and getattr(child, "sollum_type", "").startswith("sollumz_bound")
    ]
    if not bound_objs:
        log("Keine Bound-Geometrie gefunden - Kollision unveraendert.")
        return

    for bound in bound_objs:
        bound.data = mesh.copy()
        bound.data.name = f"{drawable.name}_col"

    kind = collision.get("kind", "bvh")
    if kind == "hull":
        apply_convex_hull(bound_objs)
    elif kind == "box":
        log("Kollisionstyp 'box' ist noch nicht implementiert - es bleibt bei BVH-Geometrie.")

    total = sum(len(b.data.polygons) for b in bound_objs)
    log(f"Kollision aus LOD '{source_lod}' ({kind}): {total} Faces")


def apply_convex_hull(bound_objs: list[bpy.types.Object]) -> None:
    """Ersetzt die Bound-Geometrie durch ihre konvexe Huelle.

    Fuer runde oder organische Props (Faesser, Felsen, Tonnen) ist die Huelle
    deutlich guenstiger als exakte Dreieckskollision und im Spiel kaum vom
    Original zu unterscheiden.
    """
    for bound in bound_objs:
        select_only(bound)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.convex_hull()
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.quads_convert_to_tris(quad_method="BEAUTY", ngon_method="BEAUTY")
        bpy.ops.object.mode_set(mode="OBJECT")


def apply_lod_distances(drawable: bpy.types.Object, distances: dict) -> None:
    props = drawable.drawable_properties
    props.lod_dist_high = float(distances.get("high", 60.0))
    props.lod_dist_med = float(distances.get("medium", 120.0))
    props.lod_dist_low = float(distances.get("low", 250.0))
    props.lod_dist_vlow = float(distances.get("verylow", 500.0))


# --- Export -----------------------------------------------------------------

# Vollstaendige Export-Settings. Sollumz' eigene Testsuite uebergibt diese
# zusammen mit use_custom_settings=True direkt als Operator-Argumente, statt die
# Add-on-Preferences zu veraendern. Das ist der stabile Weg: die Einstellungen
# des Nutzers bleiben unangetastet und der Aufruf ist reproduzierbar.
EXPORT_SETTINGS = {
    "limit_to_selected": True,
    "exclude_skeleton": False,
    "ymap_exclude_entities": False,
    "ymap_box_occluders": False,
    "ymap_model_occluders": False,
    "ymap_car_generators": False,
    "apply_transforms": False,
    "mesh_domain": "FACE_CORNER",
    "export_ytyps": False,
    "export_ytyps_include": "ALL",
    "export_ymaps": False,
    "export_ymaps_include": "ALL",
    "export_ytds": False,
    "export_ytds_include": "ALL",
}


def export(drawable: bpy.types.Object, out_dir: Path, fmt: str, version: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    select_only(drawable)
    for child in drawable.children_recursive:
        child.select_set(True)

    result = bpy.ops.sollumz.export_assets(
        directory=str(out_dir),
        direct_export=True,
        use_custom_settings=True,
        target_formats={fmt},
        target_versions={version},
        **EXPORT_SETTINGS,
    )
    if result != {"FINISHED"}:
        raise RuntimeError(f"Export lieferte {result} statt FINISHED.")

    # FINISHED heisst bei Sollumz nicht, dass etwas geschrieben wurde: bricht
    # der Export intern ab (etwa weil ein Material fehlt), landet das als
    # Warnung im Log und der Operator meldet trotzdem Erfolg. Deshalb wird
    # hier gegen das Dateisystem geprueft.
    written = sorted(
        p for p in out_dir.iterdir()
        if p.is_file() and p.name.startswith(drawable.name) and ".ydr" in p.name
    )
    if not written:
        existing = [p.name for p in out_dir.iterdir() if p.is_file()] or ["(nichts)"]
        raise RuntimeError(
            f"Der Export hat keine Datei fuer '{drawable.name}' erzeugt. "
            f"Im Zielverzeichnis liegt: {', '.join(existing)}. "
            "Die Ursache steht als WARNING in der Sollumz-Ausgabe weiter oben."
        )

    for path in written:
        log(f"  geschrieben: {path.name} ({path.stat().st_size} Bytes)")


def ensure_lod_materials(
    lod_meshes: dict[str, bpy.types.Mesh],
    source: bpy.types.Object,
) -> None:
    """Stellt sicher, dass jede LOD-Stufe das Shadermaterial traegt.

    Sollumz bricht den Export ab, wenn ein Drawable Model kein Sollumz-Material
    hat - und zwar mit einer Warnung im Log, nicht mit einer Exception. Ohne
    diese Pruefung wuerde der Build als erfolgreich gelten und nur keine Datei
    erzeugen.
    """
    if not source.data.materials:
        raise RuntimeError(
            "Das Quell-Mesh hat kein Material - build_material ist nicht gelaufen "
            "oder der Shader konnte nicht angelegt werden."
        )

    material = source.data.materials[0]
    for lod_key, mesh in lod_meshes.items():
        if mesh.materials:
            continue
        log(f"  LOD {lod_key}: Material fehlte, wird nachgetragen.")
        mesh.materials.append(material)


# --- Vorschaubilder ----------------------------------------------------------

def extract_lod_geometry(
    name: str,
    lod_meshes: dict[str, bpy.types.Mesh],
    out_dir: Path,
) -> list[dict]:
    """Schreibt die reine Geometrie jeder LOD-Stufe als JSON.

    Gezeichnet wird bewusst NICHT hier. Blenders Render-Engines brauchen einen
    OpenGL-Kontext, den --background nicht hat: Workbench scheiterte unter Linux
    an libEGL.so.1 und liess Blender unter Windows mit einer Access Violation
    abstuerzen.

    Also liefert diese Stufe nur Vertices und Dreiecke, und das Bild entsteht in
    propforge/preview.py mit einem kleinen Software-Rasterizer. Das ist
    deterministisch, braucht keine Grafikschicht - und ist ausserhalb von Blender
    testbar, was fuer diese Pipeline der wichtigere Punkt ist.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stats: list[dict] = []

    for lod_key, mesh in lod_meshes.items():
        mesh.calc_loop_triangles()

        vertices = [[round(c, 5) for c in v.co] for v in mesh.vertices]
        triangles = [list(tri.vertices) for tri in mesh.loop_triangles]

        target = out_dir / f"{name}_{lod_key}.json"
        target.write_text(
            json.dumps({"vertices": vertices, "triangles": triangles}),
            encoding="utf-8",
        )

        stats.append({
            "lod": lod_key,
            "triangles": len(triangles),
            "vertices": len(vertices),
            "geometry": target.name,
        })
        log(f"  Vorschau {lod_key}: {len(triangles)} Dreiecke -> {target.name}")

    return stats


# --- Ablauf -----------------------------------------------------------------

def build(job: dict, fmt: str, version: str, render_dir: str | None = None) -> dict:
    name = job["name"]
    log(f"=== {name} ===")

    reset_scene()

    source = import_mesh(Path(job["mesh"]))
    cleanup_mesh(source)
    ensure_uvs(source)
    clamp_to_budget(source, int(job["max_tris"]))
    log(f"LOD0: {tri_count(source)} Dreiecke")

    # Material VOR den LOD-Kopien anlegen. Mesh-Datenblöcke tragen ihre
    # Materialliste mit, wenn sie kopiert werden - andersherum bekommen die
    # LOD-Meshes keins, und Sollumz bricht den Export mit
    # "has no Sollumz materials! Aborting..." ab. Genau so ist es passiert.
    build_material(job, source)

    # LOD-Meshes vor der Drawable-Konvertierung erzeugen, damit die
    # Decimate-Hilfsobjekte die Sollumz-Hierarchie nicht verschmutzen.
    lod_meshes: dict[str, bpy.types.Mesh] = {}
    for lod_key, ratio in job["lod_ratios"].items():
        mesh = decimate_to_ratio(source, float(ratio), f"{name}_{lod_key}")
        lod_meshes[lod_key] = mesh
        log(f"  LOD {lod_key:<8} ratio {float(ratio):.2f} -> {len(mesh.polygons)} Faces")

    ensure_lod_materials(lod_meshes, source)

    configure_conversion(job)
    before = set(bpy.data.objects)
    select_only(source)
    bpy.ops.sollumz.converttodrawable()

    drawable = find_drawable_root(before - {source})
    drawable.name = name
    model = find_drawable_model(drawable)

    assign_lods(model, lod_meshes)
    retarget_collision(drawable, lod_meshes, job["collision"])
    apply_lod_distances(drawable, job["lod_distances"])

    out_dir = Path(job["output_dir"])
    export(drawable, out_dir, fmt, version)
    log(f"Export nach {out_dir}")

    previews: list[dict] = []
    if render_dir is not None:
        previews = extract_lod_geometry(name, lod_meshes, Path(render_dir) / name)

    return {"name": name, "previews": previews}


def main(argv: list[str]) -> int:
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(description="PropForge Blender-Stufe")
    parser.add_argument("--job", required=True, help="Pfad zur Job-JSON (ein Prop oder Liste)")
    parser.add_argument("--format", default="NATIVE", choices=["NATIVE", "CWXML"])
    parser.add_argument("--version", default="GEN8", choices=["GEN8", "GEN9"])
    parser.add_argument("--result", help="Pfad fuer den Ergebnisbericht (JSON)")
    parser.add_argument("--render", help="Verzeichnis fuer LOD-Vorschaubilder (optional)")
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.job).read_text(encoding="utf-8"))
    jobs = payload if isinstance(payload, list) else [payload]

    succeeded: list[str] = []
    failures: list[dict] = []
    previews: list[dict] = []

    for job in jobs:
        name = job.get("name", "?")
        try:
            info = build(job, args.format, args.version, args.render)
            succeeded.append(name)
            previews.append(info)
        except Exception as exc:  # noqa: BLE001 - ein kaputter Prop darf den Batch nicht stoppen
            import traceback

            trace = traceback.format_exc()
            # Vollstaendiger Traceback, nicht nur str(exc): bei Blender-Operatoren
            # steht die eigentliche Ursache fast immer in der Aufrufkette, nicht
            # in der Fehlermeldung selbst.
            log(f"FEHLER bei '{name}':")
            for line in trace.splitlines():
                log(f"  {line}")
            failures.append({"name": name, "error": str(exc), "traceback": trace})

    log(f"Fertig: {len(succeeded)}/{len(jobs)} Props gebaut.")

    # Ergebnisbericht schreiben. Der Exit-Code allein reicht nicht: Blender
    # gibt ihn im Hintergrundmodus nicht zuverlaessig weiter, wodurch ein
    # fehlgeschlagener Build als Erfolg durchgeht und die naechste Stufe
    # auf nicht existierenden Dateien arbeitet. Genau das ist passiert.
    if args.result:
        result_path = Path(args.result)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "total": len(jobs),
                    "succeeded": succeeded,
                    "failed": failures,
                    "props": previews,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        log(f"Ergebnisbericht: {result_path}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(list(sys.argv)))
