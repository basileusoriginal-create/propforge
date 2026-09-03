"""GLB-Assets einlesen und fuer die Pipeline aufbereiten.

Ein reales glTF-Asset kommt anders daher, als die Konfiguration es erwartet:

1. **Die Texturen stecken in der Datei.** GLB bettet sie als PNG-Bloecke ein,
   die Pipeline erwartet Dateipfade.
2. **Metallic und Roughness teilen sich eine Textur.** Die glTF-Spezifikation
   packt Roughness in den Gruen- und Metallic in den Blaukanal desselben
   Bildes. Die Pipeline erwartet zwei getrennte Karten.
3. **Der Ursprung liegt selten im Objekt.** Ein Asset mit Mittelpunkt bei
   (1.07, -0.60, 0.16) steht im Spiel einen Meter neben der Stelle, an die man
   es setzt.

Das gilt nicht nur fuer Marktplatz-Assets: Meshy, Tripo und Rodin liefern
ebenfalls GLB mit gepackter metallicRoughness. Diese Stufe ist damit der
Eingang fuer so ziemlich jede generierte Geometrie.

Bewusst ohne glTF-Bibliothek: das Format ist ein JSON-Kopf plus ein
Binaerblock, und was hier gebraucht wird, sind Positionen, Indizes und drei
Bilder. Eine Abhaengigkeit dafuer waere mehr Risiko als Gewinn.
"""

from __future__ import annotations

import io
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

GLB_MAGIC = b"glTF"
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

# glTF-Komponententypen -> numpy-Dtype
COMPONENT_TYPES = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}

TYPE_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

# Sehr grosse Texturen sind bei Marktplatz-Assets normal; Pillow warnt sonst
# vor einer Dekompressionsbombe und bricht ab.
Image.MAX_IMAGE_PIXELS = None


class IngestError(RuntimeError):
    pass


@dataclass
class AssetInfo:
    name: str
    triangles: int
    vertices: int
    dimensions: tuple[float, float, float]
    center: tuple[float, float, float]
    has_uvs: bool
    double_sided: bool
    materials: int
    textures: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def is_centered(self) -> bool:
        return all(abs(c) < 0.05 for c in self.center)

    def summary(self) -> str:
        x, y, z = self.dimensions
        lines = [
            f"{self.name}",
            f"  {self.triangles} Dreiecke, {self.vertices} Vertices",
            f"  Abmessungen (Z-up)  B{x:.2f} x T{y:.2f} x H{z:.2f} m",
            f"  Mittelpunkt         ({self.center[0]:.2f}, {self.center[1]:.2f}, "
            f"{self.center[2]:.2f}) - {'zentriert' if self.is_centered else 'versetzt'}",
            f"  UV-Layer            {'vorhanden' if self.has_uvs else 'FEHLT'}",
            f"  Materialien         {self.materials}",
        ]
        for role, path in self.textures.items():
            lines.append(f"  {role:<18}  {path}")
        for note in self.notes:
            lines.append(f"  Hinweis: {note}")
        return "\n".join(lines)


def read_glb(path: str | Path) -> tuple[dict, bytes]:
    """Zerlegt eine GLB-Datei in ihren JSON-Kopf und den Binaerblock."""
    raw = Path(path).read_bytes()
    if len(raw) < 12 or raw[:4] != GLB_MAGIC:
        raise IngestError(f"{path} ist keine GLB-Datei (Magic fehlt).")

    _, version, total = struct.unpack("<4sII", raw[:12])
    if version != 2:
        raise IngestError(f"glTF-Version {version} wird nicht unterstuetzt, erwartet 2.")

    chunks: dict[int, bytes] = {}
    offset = 12
    while offset < min(total, len(raw)):
        chunk_len, chunk_type = struct.unpack("<II", raw[offset:offset + 8])
        chunks[chunk_type] = raw[offset + 8:offset + 8 + chunk_len]
        offset += 8 + chunk_len

    if CHUNK_JSON not in chunks:
        raise IngestError("GLB enthaelt keinen JSON-Block.")

    return json.loads(chunks[CHUNK_JSON]), chunks.get(CHUNK_BIN, b"")


def read_accessor(gltf: dict, binary: bytes, index: int) -> np.ndarray:
    """Liest einen Accessor als numpy-Array."""
    accessor = gltf["accessors"][index]
    view = gltf["bufferViews"][accessor["bufferView"]]

    dtype = COMPONENT_TYPES[accessor["componentType"]]
    columns = TYPE_COUNTS[accessor["type"]]
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    itemsize = np.dtype(dtype).itemsize
    end = start + accessor["count"] * columns * itemsize

    values = np.frombuffer(binary[start:end], dtype=dtype)
    return values.reshape(accessor["count"], columns)


def gltf_to_zup(vertices: np.ndarray) -> np.ndarray:
    """glTF ist per Spezifikation Y-up, GTA und Blender sind Z-up."""
    return np.stack([vertices[:, 0], -vertices[:, 2], vertices[:, 1]], axis=1)


def split_metallic_roughness(image: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Trennt die gepackte glTF-Textur in Roughness und Metallic.

    Die Spezifikation legt fest: Gruenkanal ist Roughness, Blaukanal ist
    Metallic. Der Rotkanal ist frei (manche Werkzeuge legen dort Occlusion ab).

    Ohne diese Trennung wuerde die Pipeline die kombinierte Textur als
    Roughness lesen und der Specular-Wert waere um den Metallanteil verfaelscht.
    """
    rgb = image.convert("RGB")
    _, green, blue = rgb.split()
    return green, blue


def extract_textures(gltf: dict, binary: bytes, out_dir: Path, name: str) -> dict[str, Path]:
    """Schreibt die eingebetteten Texturen als einzelne Dateien.

    Rueckgabe sind die Rollen, die die Pipeline-Konfiguration erwartet.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not gltf.get("materials"):
        return {}

    material = gltf["materials"][0]
    pbr = material.get("pbrMetallicRoughness", {})
    written: dict[str, Path] = {}

    def load_texture(texture_index: int) -> Image.Image | None:
        try:
            source = gltf["textures"][texture_index]["source"]
            image_def = gltf["images"][source]
            view = gltf["bufferViews"][image_def["bufferView"]]
        except (KeyError, IndexError):
            return None
        start = view.get("byteOffset", 0)
        blob = binary[start:start + view["byteLength"]]
        return Image.open(io.BytesIO(blob))

    if "baseColorTexture" in pbr:
        image = load_texture(pbr["baseColorTexture"]["index"])
        if image is not None:
            path = out_dir / f"{name}_albedo.png"
            image.save(path)
            written["diffuse"] = path

    if "metallicRoughnessTexture" in pbr:
        image = load_texture(pbr["metallicRoughnessTexture"]["index"])
        if image is not None:
            roughness, metallic = split_metallic_roughness(image)
            rough_path = out_dir / f"{name}_roughness.png"
            metal_path = out_dir / f"{name}_metallic.png"
            roughness.save(rough_path)
            metallic.save(metal_path)
            written["roughness"] = rough_path
            written["metallic"] = metal_path

    if "normalTexture" in material:
        image = load_texture(material["normalTexture"]["index"])
        if image is not None:
            path = out_dir / f"{name}_normal.png"
            image.save(path)
            written["normal"] = path

    return written


def geometry(gltf: dict, binary: bytes) -> tuple[np.ndarray, np.ndarray, bool]:
    """Sammelt Positionen und Dreiecke aller Primitive."""
    if not gltf.get("meshes"):
        raise IngestError("Die Datei enthaelt kein Mesh.")

    all_vertices: list[np.ndarray] = []
    all_faces: list[np.ndarray] = []
    has_uvs = True
    offset = 0

    for mesh in gltf["meshes"]:
        for primitive in mesh.get("primitives", []):
            if primitive.get("mode", 4) != 4:
                continue  # nur Dreiecke
            attributes = primitive["attributes"]
            if "POSITION" not in attributes:
                continue
            vertices = read_accessor(gltf, binary, attributes["POSITION"]).astype(float)
            if "TEXCOORD_0" not in attributes:
                has_uvs = False

            if "indices" in primitive:
                faces = read_accessor(gltf, binary, primitive["indices"]).reshape(-1, 3)
            else:
                faces = np.arange(len(vertices)).reshape(-1, 3)

            all_vertices.append(vertices)
            all_faces.append(faces.astype(int) + offset)
            offset += len(vertices)

    if not all_vertices:
        raise IngestError("Kein Dreiecks-Primitive gefunden.")

    return np.vstack(all_vertices), np.vstack(all_faces), has_uvs


def inspect(path: str | Path, name: str) -> tuple[AssetInfo, np.ndarray, np.ndarray]:
    """Liest ein GLB und beschreibt, was die Pipeline damit vorfindet."""
    gltf, binary = read_glb(path)
    vertices, faces, has_uvs = geometry(gltf, binary)
    vertices_zup = gltf_to_zup(vertices)

    lo, hi = vertices_zup.min(axis=0), vertices_zup.max(axis=0)
    dimensions = tuple(float(v) for v in (hi - lo))
    center = tuple(float(v) for v in (lo + hi) / 2)

    material = (gltf.get("materials") or [{}])[0]
    info = AssetInfo(
        name=name,
        triangles=len(faces),
        vertices=len(vertices),
        dimensions=dimensions,
        center=center,
        has_uvs=has_uvs,
        double_sided=bool(material.get("doubleSided")),
        materials=len(gltf.get("materials", [])),
    )

    if not has_uvs:
        info.notes.append(
            "Kein UV-Layer - die Blender-Stufe legt ein Smart-UV-Projekt an, "
            "das fuer verkaufsfertige Assets nachgearbeitet werden sollte."
        )
    if info.materials > 1:
        info.notes.append(
            f"{info.materials} Materialien. Die Pipeline baut einen Shader je Prop - "
            "die Materialien muessen vorher zusammengefuehrt werden."
        )
    if material.get("doubleSided"):
        info.notes.append(
            "doubleSided ist gesetzt. GTA zeichnet Rueckseiten nicht - "
            "duenne Flaechen ohne Dicke sind im Spiel von hinten unsichtbar."
        )
    if not info.is_centered:
        info.notes.append(
            "Der Ursprung liegt ausserhalb des Objekts. Ohne Zentrierung steht "
            "der Prop im Spiel versetzt zur Setzposition (center = \"base\")."
        )

    return info, vertices_zup, faces


def write_slim_glb(gltf: dict, binary: bytes, target: Path) -> Path:
    """Schreibt eine GLB nur mit Geometrie, ohne eingebettete Texturen.

    Die Bilder sind nach dem Entpacken doppelt vorhanden - einmal als PNG
    daneben, einmal im Binaerblock. Bei 2048er Karten sind das schnell 13 MB,
    von denen die Pipeline kein Byte benutzt: sie baut ihr eigenes
    Sollumz-Material aus den entpackten Dateien.

    Behalten werden nur die BufferViews, auf die Accessoren zeigen.
    """
    keep: dict[int, int] = {}
    new_views: list[dict] = []
    payload = bytearray()

    for accessor in gltf.get("accessors", []):
        index = accessor.get("bufferView")
        if index is None or index in keep:
            continue
        view = gltf["bufferViews"][index]
        start = view.get("byteOffset", 0)
        blob = binary[start:start + view["byteLength"]]

        # glTF verlangt 4-Byte-Ausrichtung der BufferViews.
        while len(payload) % 4:
            payload.append(0)

        rebuilt = {"buffer": 0, "byteOffset": len(payload), "byteLength": len(blob)}
        if "byteStride" in view:
            rebuilt["byteStride"] = view["byteStride"]
        if "target" in view:
            rebuilt["target"] = view["target"]

        keep[index] = len(new_views)
        new_views.append(rebuilt)
        payload.extend(blob)

    slim = {k: v for k, v in gltf.items() if k not in ("images", "textures", "samplers")}
    slim["bufferViews"] = new_views
    slim["buffers"] = [{"byteLength": len(payload)}]
    slim["accessors"] = [
        {**a, "bufferView": keep[a["bufferView"]]} if a.get("bufferView") in keep else a
        for a in gltf.get("accessors", [])
    ]
    # Materialverweise auf Texturen zeigen ins Leere, sobald die Bilder fehlen.
    slim["materials"] = [
        {k: v for k, v in m.items()
         if k not in ("normalTexture", "occlusionTexture", "emissiveTexture")}
        | ({"pbrMetallicRoughness": {
                k: v for k, v in m.get("pbrMetallicRoughness", {}).items()
                if not k.endswith("Texture")}}
           if "pbrMetallicRoughness" in m else {})
        for m in gltf.get("materials", [])
    ]

    json_chunk = json.dumps(slim, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    bin_chunk = bytes(payload) + b"\x00" * ((4 - len(payload) % 4) % 4)

    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    with open(target, "wb") as fh:
        fh.write(struct.pack("<4sII", GLB_MAGIC, 2, total))
        fh.write(struct.pack("<II", len(json_chunk), CHUNK_JSON))
        fh.write(json_chunk)
        fh.write(struct.pack("<II", len(bin_chunk), CHUNK_BIN))
        fh.write(bin_chunk)
    return target


def _relative(path: Path, texture_dir: Path) -> Path:
    try:
        return Path(path).relative_to(Path(texture_dir).parent)
    except ValueError:
        return Path(path)


def config_snippet(info: AssetInfo, mesh_path: Path, texture_dir: Path) -> str:
    """Erzeugt den [[prop]]-Block fuer die pipeline.toml.

    Pfade sind relativ zum Elternverzeichnis des Asset-Ordners - dort liegt die
    Konfiguration, und dorthin gehoert der Block.
    """
    lines = [
        "[[prop]]",
        f'name = "{info.name}"',
        f'mesh = "{_relative(mesh_path, texture_dir).as_posix()}"',
        '# glTF ist per Spezifikation Y-up.',
        'source_up = "y"',
        f"max_tris = {max(2000, info.triangles)}",
    ]
    if not info.is_centered:
        lines.append('# Ursprung lag ausserhalb des Objekts.')
        lines.append('center = "base"')
    lines.append("")
    lines.append("[prop.textures]")
    base = Path(texture_dir).parent
    for role, path in info.textures.items():
        candidate = Path(path)
        try:
            candidate = candidate.relative_to(base)
        except ValueError:
            pass
        lines.append(f'{role} = "{candidate.as_posix()}"')
    return "\n".join(lines) + "\n"
