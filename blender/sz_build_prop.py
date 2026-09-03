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
        from types import SimpleNamespace

        errors = []
        for module_name in ("Sollumz", "sollumz", "bl_ext.user_default.sollumz"):
            try:
                props = importlib.import_module(f"{module_name}.sollumz_properties")
                shaders = importlib.import_module(f"{module_name}.ydr.shader_materials")
                return SimpleNamespace(
                    module=module_name,
                    SollumType=props.SollumType,
                    LODLevel=props.LODLevel,
                    ArchetypeType=props.ArchetypeType,
                    AssetType=props.AssetType,
                    create_shader=shaders.create_shader,
                    mesh_helper=importlib.import_module(f"{module_name}.tools.meshhelper"),
                    MaterialType=props.MaterialType,
                    apply_flag_preset=importlib.import_module(
                        f"{module_name}.tools.boundhelper").apply_flag_preset,
                    flag_preset_names=[],
                    create_collision_material=importlib.import_module(
                        f"{module_name}.ybn.collision_materials"
                    ).create_collision_material_from_index,
                    collision_material_names=[
                        m.name for m in importlib.import_module(
                            f"{module_name}.ybn.collision_materials").collisionmats
                    ],
                )
            except ImportError as exc:
                errors.append(f"  {module_name}: {exc}")
        raise ImportError("Sollumz nicht gefunden:\n" + "\n".join(errors))


try:
    _sz = import_sollumz()
except ImportError as exc:
    raise SystemExit(
        f"{exc}\n\nAdd-on installieren und aktivieren, dann erneut versuchen."
    ) from exc

SollumType = _sz.SollumType
LODLevel = _sz.LODLevel
ArchetypeType = _sz.ArchetypeType
AssetType = _sz.AssetType
create_shader = _sz.create_shader
SOLLUMZ_MODULE = _sz.module
MESH = _sz.mesh_helper
apply_flag_preset = _sz.apply_flag_preset
FLAG_PRESETS = _sz.flag_preset_names
MaterialType = _sz.MaterialType
create_collision_material = _sz.create_collision_material
COLLISION_MATERIALS = _sz.collision_material_names


LOD_ENUM = {
    "high": LODLevel.HIGH,
    "medium": LODLevel.MEDIUM,
    "low": LODLevel.LOW,
    "verylow": LODLevel.VERYLOW,
}

# Achsenkonvertierung beim Import.
#
# Blenders OBJ-Importer nimmt standardmaessig an, dass die Datei Y-up ist
# (forward_axis="NEGATIVE_Z", up_axis="Y") - das ist fuer OBJ die uebliche
# Konvention und stimmt fuer Meshy-, Tripo- und Rodin-Ausgaben. Fuer eine in
# Blender-Konvention (Z-up) geschriebene Datei ist es falsch, und der Prop
# landet um 90 Grad gedreht im Spiel, ohne dass irgendeine Pruefung anschlaegt.
#
# Deshalb wird die Annahme hier explizit gemacht statt stillschweigend
# uebernommen.
OBJ_AXES = {
    "y": {"forward_axis": "NEGATIVE_Z", "up_axis": "Y"},
    "z": {"forward_axis": "Y", "up_axis": "Z"},
}

# glTF ist per Spezifikation Y-up, der Importer konvertiert immer korrekt.
# FBX, PLY und STL tragen die Information nicht verlaesslich - dort greift
# nur der Hinweis im Log.
IMPORTERS = {
    ".glb": lambda p, up: bpy.ops.import_scene.gltf(filepath=p),
    ".gltf": lambda p, up: bpy.ops.import_scene.gltf(filepath=p),
    ".obj": lambda p, up: bpy.ops.wm.obj_import(filepath=p, **OBJ_AXES[up]),
    ".fbx": lambda p, up: bpy.ops.import_scene.fbx(filepath=p),
    ".ply": lambda p, up: bpy.ops.wm.ply_import(filepath=p),
    ".stl": lambda p, up: bpy.ops.wm.stl_import(filepath=p),
}

FORMATS_IGNORING_SOURCE_UP = {".glb", ".gltf", ".fbx", ".ply", ".stl"}


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

def import_mesh(path: Path, source_up: str = "y") -> bpy.types.Object:
    suffix = path.suffix.lower()
    if suffix not in IMPORTERS:
        raise SystemExit(f"Nicht unterstuetztes Meshformat: {suffix}")
    if source_up not in OBJ_AXES:
        raise SystemExit(f"Unbekannte Quellorientierung: {source_up}")

    if suffix in FORMATS_IGNORING_SOURCE_UP and source_up != "y":
        log(f"Hinweis: '{suffix}' bringt seine Orientierung selbst mit, "
            f"source_up='{source_up}' bleibt hier ohne Wirkung.")

    before = set(bpy.data.objects)
    IMPORTERS[suffix](str(path), source_up)
    created = set(bpy.data.objects) - before
    new_meshes = [o for o in created if o.type == "MESH"]
    if not new_meshes:
        raise SystemExit(f"Keine Mesh-Objekte in {path} gefunden.")

    # Nicht auf context.active_object verlassen. Der glTF-Importer legt die
    # Knotenhierarchie als Empties an und laesst haeufig eines davon aktiv --
    # ein Empty kennt keinen Edit-Modus, und das Aufraeumen scheiterte dann mit
    # 'enum "EDIT" not found in ("OBJECT")'.
    target = sorted(new_meshes, key=lambda o: len(o.data.vertices), reverse=True)[0]

    if len(new_meshes) > 1:
        for other in tuple(bpy.context.selected_objects):
            if other is not None:
                other.select_set(False)
        for mesh_obj in new_meshes:
            mesh_obj.select_set(True)
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.join()
        log(f"{len(new_meshes)} Mesh-Objekte zusammengefuehrt.")

    # Die Elternkette mitsamt ihrer Transformation aufloesen. glTF haengt das
    # Mesh unter Empties, die die Y-up-nach-Z-up-Drehung tragen. Ein spaeteres
    # transform_apply wirkt nur auf das Objekt selbst, nicht auf die Eltern --
    # der Prop kaeme gedreht in den Export.
    if target.parent is not None:
        world = target.matrix_world.copy()
        target.parent = None
        target.matrix_world = world
        log("Elternobjekt geloest, Welttransformation uebernommen.")

    # Uebrig gebliebene Empties entfernen, damit sie nicht in der
    # Sollumz-Hierarchie landen.
    for leftover in created:
        if leftover is not target and leftover.name in bpy.data.objects:
            bpy.data.objects.remove(leftover, do_unlink=True)

    target.name = path.stem
    bpy.context.view_layer.objects.active = target
    return target


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


def apply_centering(obj: bpy.types.Object, mode: str) -> None:
    """Legt den Ursprung an eine definierte Stelle des Objekts.

    Assets aus Marktplaetzen und Generatoren sind selten am Ursprung
    modelliert. Der Versatz faellt beim Bauen nicht auf -- die Datei ist
    korrekt --, aber im Spiel steht der Prop dann neben der Setzposition.

    "base" ist der Standardfall fuer Props, die auf dem Boden stehen: in X und
    Y zentriert, Unterkante auf Z=0.
    """
    if mode == "none":
        return

    from mathutils import Vector

    coords = [v.co for v in obj.data.vertices]
    if not coords:
        return

    lo = Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
    hi = Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))
    center = (lo + hi) / 2.0

    offset = Vector((-center.x, -center.y, -center.z))
    if mode == "xy":
        offset.z = 0.0
    elif mode == "base":
        offset.z = -lo.z
    elif mode != "all":
        log(f"Unbekannter center-Modus '{mode}' - Ursprung bleibt unveraendert.")
        return

    for vertex in obj.data.vertices:
        vertex.co += offset

    log(f"Ursprung ausgerichtet ({mode}): verschoben um "
        f"({offset.x:.3f}, {offset.y:.3f}, {offset.z:.3f})")


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


# --- Sollumz-Namenskonvention -----------------------------------------------

def align_mesh_attributes(mesh: bpy.types.Mesh, label: str = "") -> None:
    """Bringt UV-Maps und Farb-Attribute auf die Namen, die Sollumz erwartet.

    Das ist kein Schoenheitsschritt, sondern der Unterschied zwischen einem
    sichtbaren und einem unsichtbaren Prop.

    Sollumz sucht die Vertexdaten unter festen Namen: die erste UV-Map heisst
    ``UVMap 0`` (mit Leerzeichen), das erste Farb-Attribut ``Color 1``. Heisst
    die UV-Map wie bei Blender ueblich ``UVMap``, findet der Vertexpuffer-Bauer
    sie nicht und ueberspringt sie stillschweigend - die exportierte Geometrie
    hat dann kein ``TexCoord0``, obwohl der Shader es deklariert. Sollumz
    schreibt dazu eine Warnung ins Log und exportiert trotzdem.

    Normalerweise erledigt das der Operator ``sollumz.createshadermaterial``
    ueber ``post_create_shader_update_object``. Diese Pipeline ruft
    ``create_shader`` direkt auf und haengt das Material selbst an - damit
    fiel dieser Schritt unter den Tisch. Hier wird dieselbe Reihenfolge
    nachgezogen: erst umbenennen, was da ist, dann ergaenzen, was fehlt.

    Welche Indizes ueberhaupt gebraucht werden, leitet Sollumz aus dem Shader
    des Materials ab. Deshalb muss das Material am Mesh haengen, bevor das
    hier laeuft.
    """
    MESH.mesh_rename_uv_maps_by_order(mesh)
    MESH.mesh_rename_color_attrs_by_order(mesh)
    MESH.mesh_add_missing_uv_maps(mesh)
    added_colors = MESH.mesh_add_missing_color_attrs(mesh)

    # Neu angelegte Farb-Attribute ausdruecklich auf Weiss setzen.
    #
    # Blenders Vorgabewert fuer ein frisches BYTE_COLOR-Attribut ist nicht
    # dokumentiert und je nach Version verschieden. Schwarz waere hier fatal:
    # die Vertexfarbe geht multiplikativ in die Beleuchtung ein, der Prop
    # waere im Spiel pechschwarz. Weiss ist neutral.
    for index in added_colors:
        name = MESH.get_color_attr_name(index)
        attr = mesh.color_attributes.get(name)
        if attr is None:
            continue
        attr.data.foreach_set("color_srgb", [1.0] * (len(attr.data) * 4))
        log(f"  {label}Farb-Attribut '{name}' angelegt und auf Weiss gesetzt.")


def check_mesh_attributes(mesh: bpy.types.Mesh, label: str = "") -> None:
    """Prueft nach, ob wirklich alles da ist, was der Shader braucht.

    Sollumz meldet fehlende Attribute nur als Warnung im Log und exportiert
    weiter. Genau so entsteht eine formal einwandfreie Datei, die im Spiel
    nichts anzeigt. Hier wird daraus ein Abbruch.
    """
    problems = []

    for index in sorted(MESH.get_mesh_used_texcoords_indices(mesh)):
        name = MESH.get_uv_map_name(index)
        if name not in mesh.uv_layers:
            problems.append(f"UV-Map '{name}' fehlt")

    for index in sorted(MESH.get_mesh_used_colors_indices(mesh)):
        name = MESH.get_color_attr_name(index)
        attr = mesh.color_attributes.get(name)
        if attr is None:
            problems.append(f"Farb-Attribut '{name}' fehlt")
        elif attr.domain != "CORNER" or attr.data_type != "BYTE_COLOR":
            problems.append(
                f"Farb-Attribut '{name}' hat Format {attr.domain}/{attr.data_type}, "
                "gebraucht wird CORNER/BYTE_COLOR")

    if problems:
        raise RuntimeError(
            f"{label}Das Mesh '{mesh.name}' erfuellt die Sollumz-Namenskonvention nicht: "
            + "; ".join(problems)
            + ". Der Export waere formal in Ordnung und im Spiel unsichtbar."
        )

    log(f"  {label}Vertexdaten: "
        f"UV {', '.join(l.name for l in mesh.uv_layers) or '-'} | "
        f"Farben {', '.join(a.name for a in mesh.color_attributes) or '-'}")


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

    bound_objs = find_bound_meshes(drawable)
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


def find_bound_meshes(drawable: bpy.types.Object) -> list[bpy.types.Object]:
    """Alle Mesh-Objekte der eingebetteten Kollision."""
    return [
        child for child in drawable.children_recursive
        if child.type == "MESH" and getattr(child, "sollum_type", "").startswith("sollumz_bound")
    ]


def apply_collision_material(bound_objs: list[bpy.types.Object], material_name: str) -> None:
    """Gibt der Kollisionsgeometrie ein Kollisionsmaterial.

    Ohne das faellt die Kollision beim Export ersatzlos weg. Sollumz prueft
    vor dem Schreiben jedes Bound-Meshes (``ybn/ybnexport.py``):

        if obj.type == "MESH" and not validate_collision_materials(obj, ...):
            return None

    und ``validate_collision_materials`` lehnt zwei Faelle ab: ein Mesh ohne
    Kollisionsmaterial - und ein Mesh mit einem *Nicht*-Kollisionsmaterial.
    Beides trifft hier zu: die Kollision entsteht als Kopie des Rendermeshes
    und bringt dessen Shadermaterial mit.

    Das ``return None`` verwirft den Bound. Uebrig bleibt ein Bound Composite
    ohne Kinder - eine gueltige, leere Huelle. Die Datei enthaelt einen
    Kollisionsblock, und man laeuft trotzdem hindurch.

    Sollumz weist Kollisionsmaterialien nirgends automatisch zu; in der
    Oberflaeche ist das ein eigener Knopf. Wer die Kollision wie hier
    programmgesteuert erzeugt, muss den Schritt selbst gehen.
    """
    try:
        index = COLLISION_MATERIALS.index(material_name)
    except ValueError:
        raise RuntimeError(
            f"Kollisionsmaterial '{material_name}' ist unbekannt. "
            f"Verfuegbar sind {len(COLLISION_MATERIALS)} Materialien, darunter: "
            + ", ".join(COLLISION_MATERIALS[:12]) + " ..."
        ) from None

    for bound in bound_objs:
        material = create_collision_material(index)
        # Ersetzen, nicht ergaenzen: das mitkopierte Shadermaterial ist
        # genau das, was die Pruefung ablehnt.
        bound.data.materials.clear()
        bound.data.materials.append(material)

    # Nachsehen statt hoffen - der Export wuerde den Bound sonst stumm
    # verwerfen.
    for bound in bound_objs:
        mats = list(bound.data.materials)
        wrong = [m.name for m in mats if m.sollum_type != MaterialType.COLLISION]
        if not mats or wrong:
            raise RuntimeError(
                f"'{bound.name}' traegt nach dem Setzen kein reines "
                f"Kollisionsmaterial (gefunden: {[m.name for m in mats] or 'keins'}). "
                "Der Export wuerde die Kollision verwerfen und eine leere Huelle "
                "schreiben."
            )

    log(f"  Kollisionsmaterial '{material_name}' (Index {index}) auf "
        f"{len(bound_objs)} Bound-Mesh(es).")


def active_flags(group) -> list[str]:
    """Namen der gesetzten Flags einer BoundFlags-Gruppe.

    ``BoundFlags`` ist eine schlichte PropertyGroup aus BoolProperties und hat
    - anders als die Archetyp-Flags - KEIN ``total``-Feld. Sollumz zaehlt
    dafuer selbst die Annotationen durch (``ybn/gta5/presets/flag.py``), und
    genau das passiert hier auch.
    """
    names = list(type(group).__annotations__.keys())
    return [name for name in names if getattr(group, name, False)]


def apply_collision_flags(drawable: bpy.types.Object, preset_name: str) -> None:
    """Setzt die Kollisionsflags und prueft, dass sie auch angekommen sind.

    Ohne Flags kollidiert ein Bound mit nichts. Die Datei ist vollstaendig,
    die Kollisionsgeometrie liegt drin, jede Pruefung ist zufrieden - und im
    Spiel laeuft man hindurch.

    Der Weg dorthin ist derselbe wie bei den UV-Namen: Sollumz nimmt den
    Preset-Namen als Zeichenkette entgegen, sucht ihn und gibt bei
    Nichtfinden schlicht ``False`` zurueck. Der Aufrufer im Add-on wertet das
    nicht aus. Ein Tippfehler oder ein veralteter Name - etwa "Default"
    statt "General (Default)" - bleibt damit folgenlos sichtbar und fatal
    wirksam.

    Deshalb wird hier der Rueckgabewert ausgewertet UND anschliessend
    nachgesehen, ob wirklich Flags gesetzt sind.
    """
    bounds = [
        child for child in drawable.children_recursive
        if getattr(child, "sollum_type", "") in (
            SollumType.BOUND_GEOMETRYBVH, SollumType.BOUND_GEOMETRY)
    ]
    if not bounds:
        log("Keine Bound-Container gefunden - keine Flags zu setzen.")
        return

    known = ", ".join(FLAG_PRESETS) if FLAG_PRESETS else "(Liste nicht lesbar)"

    for bound in bounds:
        if not apply_flag_preset(bound, preset_name):
            raise RuntimeError(
                f"Das Kollisions-Preset '{preset_name}' gibt es nicht. "
                f"Verfuegbar: {known}. Ohne Preset haette die Kollision keine "
                "gesetzten Flags und wuerde mit nichts kollidieren - man liefe "
                "durch den Prop hindurch, ohne dass eine Datei fehlt."
            )

        set1 = active_flags(bound.composite_flags1)
        set2 = active_flags(bound.composite_flags2)
        if not set1 and not set2:
            raise RuntimeError(
                f"Preset '{preset_name}' wurde angewandt, an '{bound.name}' ist "
                "aber kein einziges Flag gesetzt. Damit kollidiert der Bound "
                "mit nichts."
            )
        log(f"  Kollisionsflags '{preset_name}' auf '{bound.name}': "
            f"{len(set1)}+{len(set2)} gesetzt "
            f"({', '.join(set1[:4])}{' ...' if len(set1) > 4 else ''} | "
            f"{', '.join(set2[:4])}{' ...' if len(set2) > 4 else ''})")


def apply_lod_distances(drawable: bpy.types.Object, distances: dict) -> None:
    props = drawable.drawable_properties
    props.lod_dist_high = float(distances.get("high", 60.0))
    props.lod_dist_med = float(distances.get("medium", 120.0))
    props.lod_dist_low = float(distances.get("low", 250.0))
    props.lod_dist_vlow = float(distances.get("verylow", 500.0))


# --- Archetyp (.ytyp) --------------------------------------------------------

def has_embedded_texture(drawable: bpy.types.Object) -> bool:
    """Traegt irgendein Material des Drawables eine eingebettete Textur?"""
    for child in [drawable, *drawable.children_recursive]:
        data = getattr(child, "data", None)
        materials = getattr(data, "materials", None) or ()
        for mat in materials:
            tree = getattr(mat, "node_tree", None)
            if tree is None:
                continue
            for node in tree.nodes:
                if not isinstance(node, bpy.types.ShaderNodeTexImage):
                    continue
                # texture_properties wird von Sollumz an den Node gehaengt.
                # Ohne aktives Add-on gibt es die Property nicht - dann ist
                # ohnehin nichts eingebettet.
                props = getattr(node, "texture_properties", None)
                if props is not None and getattr(props, "embedded", False):
                    return True
    return False


def has_embedded_collision(drawable: bpy.types.Object) -> bool:
    return any(
        getattr(child, "sollum_type", None) == SollumType.BOUND_COMPOSITE
        for child in drawable.children_recursive
    )


def create_ytyp(drawable: bpy.types.Object, settings: dict) -> str:
    """Legt eine .ytyp mit genau einem Archetyp fuer dieses Drawable an.

    Ohne Archetyp-Definition findet das Spiel den Prop nicht: die .ydr allein
    ist nur Geometrie, erst der Archetyp gibt ihr einen Namen, unter dem sie
    spawnbar ist.

    Bewusst kein externes Werkzeug. Ein ytyp-Generator, der nur die fertige
    Datei sieht, muss raten, ob Kollision und Texturen eingebettet sind. Diese
    Stufe weiss es, weil sie beides selbst hineingebaut hat.

    Sollumz fuellt beim Setzen von ``archetype.asset`` einige Felder selbst -
    aber nicht alle: die Erkennung eingebetteter Texturen prueft dort auf
    ``DRAWABLE_GEOMETRY``, einen Typ, den das aktuelle Sollumz gar nicht mehr
    erzeugt. Deshalb wird hier jedes Feld selbst gesetzt und anschliessend
    protokolliert, was tatsaechlich drinsteht.
    """
    scene = bpy.context.scene
    name = drawable.name
    ytyp_name = settings.get("name") or f"{name}_ityp"

    ytyp = scene.ytyps.add()
    ytyp.name = ytyp_name
    scene.ytyp_index = len(scene.ytyps) - 1

    archetype = ytyp.new_archetype(ArchetypeType.BASE)
    archetype.name = name
    # Setzt asset_name, asset_type und (bei eingebetteter Kollision)
    # physics_dictionary automatisch. Wird unten trotzdem nachgezogen.
    archetype.asset = drawable
    archetype.asset_name = name
    archetype.asset_type = AssetType.DRAWABLE

    archetype.lod_dist = float(settings.get("lod_dist", 500.0))
    archetype.hd_texture_dist = float(settings.get("hd_texture_dist", 100.0))
    archetype.flags.total = str(int(settings.get("flags", 32)))

    # Eingebettete Kollision wird ueber den eigenen Namen referenziert.
    # Ohne Kollision bleibt das Feld leer, sonst sucht das Spiel eine .ybn,
    # die es nicht gibt.
    archetype.physics_dictionary = name if has_embedded_collision(drawable) else ""

    # Texturwoerterbuch: nur setzen, wenn die Texturen NICHT eingebettet sind.
    # Eingebettete Texturen liegen in der .ydr selbst; ein Verweis auf eine
    # nicht existierende .ytd waere ein Fehler ohne Nutzen.
    override = settings.get("texture_dictionary")
    if override is not None:
        archetype.texture_dictionary = str(override)
    elif has_embedded_texture(drawable):
        archetype.texture_dictionary = ""
    else:
        archetype.texture_dictionary = name

    log(f"YTYP '{ytyp_name}': Archetyp '{archetype.name}' "
        f"(asset={archetype.asset_name}, lodDist={archetype.lod_dist:g}, "
        f"flags={archetype.flags.total}, "
        f"physics='{archetype.physics_dictionary}', "
        f"txd='{archetype.texture_dictionary}')")

    return ytyp_name


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
    # SELECTED statt ALL: exportiert genau die ytyp, deren Index gesetzt ist.
    # ALL wuerde auch ytyps mitnehmen, die in einer Startup-Datei des Nutzers
    # stecken - im Batch waere das eine stille Fremddatei im Resource-Ordner.
    "export_ytyps_include": "SELECTED",
    "export_ymaps": False,
    "export_ymaps_include": "ALL",
    "export_ytds": False,
    "export_ytds_include": "ALL",
}


def _written(out_dir: Path, stem: str, marker: str) -> list[Path]:
    return sorted(
        p for p in out_dir.iterdir()
        if p.is_file() and p.name.startswith(stem) and marker in p.name
    )


def export(
    drawable: bpy.types.Object,
    out_dir: Path,
    fmt: str,
    version: str,
    ytyp_name: str | None = None,
) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)

    select_only(drawable)
    for child in drawable.children_recursive:
        child.select_set(True)

    settings = dict(EXPORT_SETTINGS)
    settings["export_ytyps"] = ytyp_name is not None

    result = bpy.ops.sollumz.export_assets(
        directory=str(out_dir),
        direct_export=True,
        use_custom_settings=True,
        target_formats={fmt},
        target_versions={version},
        **settings,
    )
    if result != {"FINISHED"}:
        raise RuntimeError(f"Export lieferte {result} statt FINISHED.")

    # FINISHED heisst bei Sollumz nicht, dass etwas geschrieben wurde: bricht
    # der Export intern ab (etwa weil ein Material fehlt), landet das als
    # Warnung im Log und der Operator meldet trotzdem Erfolg. Deshalb wird
    # hier gegen das Dateisystem geprueft.
    written = _written(out_dir, drawable.name, ".ydr")
    if not written:
        existing = [p.name for p in out_dir.iterdir() if p.is_file()] or ["(nichts)"]
        raise RuntimeError(
            f"Der Export hat keine Datei fuer '{drawable.name}' erzeugt. "
            f"Im Zielverzeichnis liegt: {', '.join(existing)}. "
            "Die Ursache steht als WARNING in der Sollumz-Ausgabe weiter oben."
        )

    # Dieselbe Pruefung fuer die ytyp. Sie laeuft im Export durch denselben
    # Zweig, der Fehler still ins Log schreibt.
    if ytyp_name is not None:
        ytyps = _written(out_dir, ytyp_name, ".ytyp")
        if not ytyps:
            existing = [p.name for p in out_dir.iterdir() if p.is_file()] or ["(nichts)"]
            raise RuntimeError(
                f"Der Export hat keine .ytyp fuer '{ytyp_name}' erzeugt. "
                f"Im Zielverzeichnis liegt: {', '.join(existing)}. "
                "Ohne Archetyp-Definition ist der Prop im Spiel nicht spawnbar."
            )
        written += ytyps

    for path in written:
        log(f"  geschrieben: {path.name} ({path.stat().st_size} Bytes)")

    # Die Dateigroessen wandern in den Ergebnisbericht.
    #
    # Grund: dass eine Datei existiert und die richtigen Metadaten hat, heisst
    # nicht, dass Geometrie drinsteht. Ein Drawable mit tausenden Dreiecken und
    # drei eingebetteten 1024er-Texturen ist megabytegross - eine leere Huelle
    # sind ein paar Kilobyte. Der Unterschied faellt sofort auf, ohne dass man
    # das Binaerformat parsen muss.
    return [{"file": p.name, "bytes": p.stat().st_size} for p in written]


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

    source = import_mesh(Path(job["mesh"]), job.get("source_up", "y"))
    cleanup_mesh(source)
    apply_centering(source, job.get("center", "none"))
    ensure_uvs(source)
    clamp_to_budget(source, int(job["max_tris"]))

    # Die Abmessungen protokollieren. Ein auf der Seite liegender Prop ist an
    # den Zahlen sofort erkennbar - und sonst an gar nichts, weil die
    # exportierte Datei formal einwandfrei ist.
    dims = source.dimensions
    dimensions = {"x": round(dims.x, 4), "y": round(dims.y, 4), "z": round(dims.z, 4)}
    log(f"LOD0: {tri_count(source)} Dreiecke, "
        f"Abmessungen B{dims.x:.2f} x T{dims.y:.2f} x H{dims.z:.2f} m")

    # Material VOR den LOD-Kopien anlegen. Mesh-Datenblöcke tragen ihre
    # Materialliste mit, wenn sie kopiert werden - andersherum bekommen die
    # LOD-Meshes keins, und Sollumz bricht den Export mit
    # "has no Sollumz materials! Aborting..." ab. Genau so ist es passiert.
    build_material(job, source)

    # Erst jetzt moeglich: welche UV-Maps und Farb-Attribute gebraucht werden,
    # steht im Shader des Materials. Und zwingend VOR den LOD-Kopien - die
    # erben die Attribute mit, andersherum muesste jede einzeln nachbessern.
    align_mesh_attributes(source.data)
    check_mesh_attributes(source.data, "LOD0: ")

    # LOD-Meshes vor der Drawable-Konvertierung erzeugen, damit die
    # Decimate-Hilfsobjekte die Sollumz-Hierarchie nicht verschmutzen.
    lod_meshes: dict[str, bpy.types.Mesh] = {}
    for lod_key, ratio in job["lod_ratios"].items():
        mesh = decimate_to_ratio(source, float(ratio), f"{name}_{lod_key}")
        lod_meshes[lod_key] = mesh
        log(f"  LOD {lod_key:<8} ratio {float(ratio):.2f} -> {len(mesh.polygons)} Faces")

    ensure_lod_materials(lod_meshes, source)

    # Und jede Stufe einzeln nachpruefen. Der Decimate-Modifikator soll
    # Attribute mitnehmen - "soll" ist in diesem Projekt aber kein Beleg,
    # und eine LOD-Stufe ohne UVs faellt sonst erst im Spiel auf, wenn man
    # weit genug weggeht.
    for lod_key, mesh in lod_meshes.items():
        align_mesh_attributes(mesh, f"LOD {lod_key}: ")
        check_mesh_attributes(mesh, f"LOD {lod_key}: ")

    configure_conversion(job)
    before = set(bpy.data.objects)
    select_only(source)
    bpy.ops.sollumz.converttodrawable()

    drawable = find_drawable_root(before - {source})
    drawable.name = name
    model = find_drawable_model(drawable)

    assign_lods(model, lod_meshes)
    retarget_collision(drawable, lod_meshes, job["collision"])
    if job["collision"].get("enabled", True):
        # Ausserhalb von retarget_collision: das steigt bei abgeschaltetem
        # oder fehlendem Ziel-LOD frueh aus, und die Kollision braucht
        # Material und Flags in JEDEM Fall - auch wenn sie aus LOD0 stammt.
        bound_meshes = find_bound_meshes(drawable)
        if not bound_meshes:
            raise RuntimeError(
                "Kollision ist aktiviert, aber die Konvertierung hat keine "
                "Bound-Geometrie erzeugt. Der Prop haette im Spiel keine "
                "Kollision, ohne dass eine Datei fehlt."
            )
        apply_collision_material(bound_meshes, job["collision"].get("material", "DEFAULT"))
        apply_collision_flags(drawable, job["collision"].get("flag_preset", "General (Default)"))
    apply_lod_distances(drawable, job["lod_distances"])

    # Erst nach der Kollision: create_ytyp liest am Drawable ab, ob Kollision
    # und Texturen eingebettet sind, und setzt die Archetyp-Felder danach.
    ytyp_settings = job.get("ytyp") or {}
    ytyp_name = None
    if ytyp_settings.get("enabled", True):
        ytyp_name = create_ytyp(drawable, ytyp_settings)

    out_dir = Path(job["output_dir"])
    files = export(drawable, out_dir, fmt, version, ytyp_name)
    log(f"Export nach {out_dir}")

    previews: list[dict] = []
    if render_dir is not None:
        previews = extract_lod_geometry(name, lod_meshes, Path(render_dir) / name)

    return {
        "name": name,
        "previews": previews,
        "dimensions": dimensions,
        "ytyp": ytyp_name,
        "files": files,
    }


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
