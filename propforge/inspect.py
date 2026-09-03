"""Auswertung exportierter CodeWalker-XML-Assets.

Der Zweck: verifizieren, ohne GTA V zu starten. Ein `.ydr.xml` ist reiner Text
und enthaelt alles, was die Pipeline versprochen hat - LOD-Stufen, Sichtweiten,
Shader, Texturen, Kollision. Damit laesst sich automatisiert pruefen, ob der
Build wirklich das gebaut hat, was in der Konfiguration stand.

Das ersetzt keinen Blick ins Spiel, faengt aber die gesamte Klasse von Fehlern
ab, bei denen der Export stillschweigend etwas weglaesst.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

# CWXML nennt die LOD-Container abweichend von der Sollumz-Enum.
LOD_ELEMENTS = {
    "high": "DrawableModelsHigh",
    "medium": "DrawableModelsMedium",
    "low": "DrawableModelsLow",
    "verylow": "DrawableModelsVeryLow",
}

LOD_DIST_ELEMENTS = {
    "high": "LodDistHigh",
    "medium": "LodDistMed",
    "low": "LodDistLow",
    "verylow": "LodDistVlow",
}


class InspectError(RuntimeError):
    pass


@dataclass
class LodInfo:
    level: str
    models: int
    geometries: int
    distance: float
    # Vertex-Semantiken, die der Puffer tatsaechlich traegt - z.B.
    # {"Position", "Normal", "Colour0", "TexCoord0", "Tangent"}.
    #
    # Das ist die Stelle, an der ein unsichtbarer Prop auffaellt: fehlt
    # TexCoord0, hat das Modell keine Texturkoordinaten, egal wie viele
    # Texturen eingebettet sind.
    semantics: set[str] = field(default_factory=set)
    vertices: int = 0
    indices: int = 0


@dataclass
class TextureInfo:
    name: str
    fmt: str
    width: int
    height: int

    @property
    def is_power_of_two(self) -> bool:
        return all(n > 0 and (n & (n - 1)) == 0 for n in (self.width, self.height))


@dataclass
class DrawableInfo:
    name: str
    shaders: list[str] = field(default_factory=list)
    samplers: dict[str, str] = field(default_factory=dict)
    textures: list[TextureInfo] = field(default_factory=list)
    lods: dict[str, LodInfo] = field(default_factory=dict)
    bounds: list[str] = field(default_factory=list)
    # Anzahl der Kinder in den Bound Composites. Ein Composite ohne Kinder
    # ist eine leere Huelle: die Datei enthaelt einen Kollisionsblock, das
    # Spiel findet darin aber nichts, woran man anstossen koennte.
    bound_children: int = 0

    @property
    def has_collision(self) -> bool:
        return bool(self.bounds)

    def summary(self) -> str:
        lines = [f"{self.name}"]
        lines.append(f"  Shader      {', '.join(self.shaders) or '-'}")
        for lod in ("high", "medium", "low", "verylow"):
            info = self.lods.get(lod)
            if info is None:
                continue
            lines.append(
                f"  LOD {lod:<8} {info.models} Modell(e), "
                f"{info.geometries} Geometrie(n), Sichtweite {info.distance:g} m"
            )
            lines.append(
                f"  {'':<12} {info.vertices} Vertices, {info.indices} Indizes, "
                f"Semantik: {', '.join(sorted(info.semantics)) or '-'}"
            )
        if self.textures:
            for t in self.textures:
                flag = "" if t.is_power_of_two else "  <- keine Zweierpotenz!"
                lines.append(f"  Textur      {t.name} {t.width}x{t.height} {t.fmt}{flag}")
        else:
            lines.append("  Textur      keine eingebettet")
        lines.append(
            f"  Kollision   {', '.join(self.bounds) if self.bounds else 'keine'}"
            + (f" ({self.bound_children} Kind-Bound(s))" if self.bounds else ""))
        return "\n".join(lines)


def _value(root: ET.Element, tag: str, default: float = 0.0) -> float:
    node = root.find(tag)
    if node is None:
        return default
    try:
        return float(node.attrib.get("value", default))
    except (TypeError, ValueError):
        return default


def _find(node: ET.Element, tag: str) -> ET.Element | None:
    """Erster Nachfahre mit diesem Tag, Gross-/Kleinschreibung egal."""
    wanted = tag.lower()
    for child in node.iter():
        if child is not node and child.tag.lower() == wanted:
            return child
    return None


def _rows(node: ET.Element | None) -> int:
    if node is None:
        return 0
    return len([line for line in (node.text or "").splitlines() if line.strip()])


def _values(node: ET.Element | None) -> int:
    if node is None:
        return 0
    return len((node.text or "").split())


def read_geometry(item: ET.Element) -> tuple[set[str], int, int]:
    """Semantiken, Vertex- und Indexanzahl einer Geometrie.

    Aufbau laut echtem Export (nicht geraten - aus der CI-Ausgabe abgelesen):

        <VertexBuffer>
          <Layout type="GTAV1"><Position /><Normal /><Colour0 /> ... </Layout>
          <Data>eine Zeile je Vertex</Data>
        </VertexBuffer>
        <IndexBuffer><Data>alle Indizes</Data></IndexBuffer>
    """
    vertex_buffer = _find(item, "VertexBuffer")
    index_buffer = _find(item, "IndexBuffer")

    semantics: set[str] = set()
    vertices = 0
    if vertex_buffer is not None:
        layout = _find(vertex_buffer, "Layout")
        if layout is not None:
            semantics = {child.tag for child in layout}
        vertices = _rows(_find(vertex_buffer, "Data"))

    indices = _values(_find(index_buffer, "Data")) if index_buffer is not None else 0
    return semantics, vertices, indices


def parse_drawable(path: str | Path) -> DrawableInfo:
    """Liest ein `.ydr.xml` und extrahiert die pruefbaren Eigenschaften."""
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise InspectError(f"{path.name} ist kein gueltiges XML: {exc}") from exc

    if root.tag != "Drawable":
        raise InspectError(f"{path.name}: Wurzelelement ist '{root.tag}', erwartet 'Drawable'.")

    name_node = root.find("Name")
    info = DrawableInfo(name=(name_node.text or "").strip() if name_node is not None else path.stem)

    # --- Shader und ihre Textur-Parameter ---
    for shader in root.findall("./ShaderGroup/Shaders/Item"):
        filename = shader.find("FileName")
        if filename is not None and filename.text:
            info.shaders.append(filename.text.strip())
        for param in shader.findall("./Parameters/Item"):
            if param.attrib.get("type") != "Texture":
                continue
            sampler = param.attrib.get("name", "")
            tex_name = param.find("Name")
            if sampler and tex_name is not None and tex_name.text:
                info.samplers[sampler] = tex_name.text.strip()

    # --- Eingebettete Texturen ---
    for item in root.findall("./ShaderGroup/TextureDictionary/Item"):
        tex_name = item.find("Name")
        fmt = item.find("Format")
        info.textures.append(
            TextureInfo(
                name=(tex_name.text or "").strip() if tex_name is not None else "?",
                fmt=(fmt.text or "").strip() if fmt is not None else "?",
                width=int(_value(item, "Width")),
                height=int(_value(item, "Height")),
            )
        )

    # --- LOD-Stufen ---
    for level, element in LOD_ELEMENTS.items():
        container = root.find(element)
        if container is None:
            continue
        models = container.findall("Item")
        if not models:
            continue
        items = [g for m in models for g in m.findall("./Geometries/Item")]

        semantics: set[str] = set()
        vertices = indices = 0
        for item in items:
            geo_semantics, geo_vertices, geo_indices = read_geometry(item)
            # Vereinigung, nicht Schnittmenge: eine Geometrie ohne TexCoord0
            # faellt so nicht auf. Genau dafuer gibt es die Pruefung in
            # verify, die zusaetzlich jede Geometrie einzeln betrachtet.
            semantics |= geo_semantics
            vertices += geo_vertices
            indices += geo_indices

        info.lods[level] = LodInfo(
            level=level,
            models=len(models),
            geometries=len(items),
            distance=_value(root, LOD_DIST_ELEMENTS[level], 9998.0),
            semantics=semantics,
            vertices=vertices,
            indices=indices,
        )

    # --- Kollision ---
    #
    # Nicht nur zaehlen, ob ein Bounds-Block da ist. Ein Bound Composite ohne
    # Kinder ist eine gueltige, leere Huelle - die Datei sieht vollstaendig
    # aus, und im Spiel laeuft man hindurch. Genau so ist es passiert:
    # Sollumz verwirft ein Bound-Mesh ohne Kollisionsmaterial und schreibt
    # das Composite trotzdem.
    for bounds in root.iter("Bounds"):
        info.bounds.append(bounds.attrib.get("type", "?"))
        if bounds.attrib.get("type", "").lower() != "composite":
            continue
        children = _child(bounds, "Children")
        info.bound_children += len(list(children)) if children is not None else 0

    return info


def find_drawables(build_dir: str | Path) -> list[Path]:
    return sorted(Path(build_dir).rglob("*.ydr.xml"))


# --- Archetypen (.ytyp.xml) --------------------------------------------------
#
# Anders als die .ydr traegt die .ytyp die Feldnamen des Spiels selbst
# (camelCase: lodDist, assetName, textureDictionary). Weil diese Stufe nicht
# gegen eine echte Datei entwickelt werden konnte, sucht der Parser die Felder
# gross-/kleinschreibungsunabhaengig und an beliebiger Tiefe. Lieber
# nachsichtig lesen als am ersten Schreibweisenunterschied scheitern.


@dataclass
class ArchetypeInfo:
    name: str
    asset_name: str
    asset_type: str
    lod_dist: float
    flags: int
    texture_dictionary: str
    physics_dictionary: str


@dataclass
class YtypInfo:
    name: str
    archetypes: list[ArchetypeInfo] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"{self.name} ({len(self.archetypes)} Archetyp(en))"]
        for a in self.archetypes:
            lines.append(
                f"  {a.name:<20} asset={a.asset_name} typ={a.asset_type} "
                f"lodDist={a.lod_dist:g} flags={a.flags}"
            )
            lines.append(
                f"  {'':<20} txd='{a.texture_dictionary}' "
                f"physics='{a.physics_dictionary}'"
            )
        return "\n".join(lines)


def _child(node: ET.Element, tag: str) -> ET.Element | None:
    """Direktes Kind, Gross-/Kleinschreibung egal."""
    wanted = tag.lower()
    for child in node:
        if child.tag.lower() == wanted:
            return child
    return None


def _text(node: ET.Element, tag: str, default: str = "") -> str:
    """Feldwert - egal ob als Elementtext oder als value-Attribut geschrieben."""
    found = _child(node, tag)
    if found is None:
        return default
    if found.text and found.text.strip():
        return found.text.strip()
    return found.attrib.get("value", default)


def _number(node: ET.Element, tag: str, default: float = 0.0) -> float:
    try:
        return float(_text(node, tag, str(default)))
    except ValueError:
        return default


def parse_ytyp(path: str | Path) -> YtypInfo:
    """Liest eine `.ytyp.xml` und extrahiert die Archetypen."""
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise InspectError(f"{path.name} ist kein gueltiges XML: {exc}") from exc

    if root.tag.lower() != "cmaptypes":
        raise InspectError(
            f"{path.name}: Wurzelelement ist '{root.tag}', erwartet 'CMapTypes'."
        )

    container = _child(root, "archetypes")
    items = list(container) if container is not None else []

    info = YtypInfo(name=_text(root, "name", path.name.split(".")[0]))
    for item in items:
        info.archetypes.append(
            ArchetypeInfo(
                name=_text(item, "name"),
                asset_name=_text(item, "assetName"),
                asset_type=_text(item, "assetType"),
                lod_dist=_number(item, "lodDist"),
                flags=int(_number(item, "flags")),
                texture_dictionary=_text(item, "textureDictionary"),
                physics_dictionary=_text(item, "physicsDictionary"),
            )
        )

    return info


def find_ytyps(build_dir: str | Path) -> list[Path]:
    return sorted(Path(build_dir).rglob("*.ytyp.xml"))
