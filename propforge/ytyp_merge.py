"""Mehrere .ytyp zu einer zusammenfassen.

Warum ueberhaupt: PropForge schreibt pro Prop eine eigene .ytyp. Das ist beim
Bauen richtig - faellt ein Prop aus, ist nur seine Datei betroffen -, aber ein
Pack mit sechzig Props hat dann sechzig Archetyp-Dateien, sechzig Zeilen
`DLC_ITYP_REQUEST` im Manifest und sechzig Gelegenheiten, eine davon zu
vergessen. Fuer die Auslieferung ist eine Sammel-ytyp die richtige Form.

Das Zusammenfassen selbst ist unspektakulaer: eine .ytyp ist eine Liste von
Archetypen mit einem Namen aussen herum. Die Arbeit steckt in dem, was dabei
schiefgehen kann.

Der teure Fall ist der Namenskonflikt. Zwei Archetypen mit gleichem Namen sind
kein Fehler, den irgendetwas meldet - das Spiel nimmt einen davon, und welchen,
haengt an der Ladereihenfolge. Ein Prop zeigt dann im Spiel das Modell eines
anderen. Deshalb bricht der Merger bei Namensgleichheit ab, statt still zu
entscheiden - ausser die beiden Archetypen sind Feld fuer Feld identisch, dann
ist es dieselbe Definition zweimal und die Wahl ist folgenlos.

Dieses Modul arbeitet auf CWXML (.ytyp.xml). Die Binaerform geht denselben Weg
ueber Blender und Sollumz, benutzt aber dieselbe Entscheidungslogik hier -
damit beide Wege bei denselben Eingaben dasselbe tun.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# Felder, die einen Archetyp inhaltlich ausmachen. Zwei Archetypen mit gleichem
# Namen gelten als dieselbe Definition, wenn sie hierin uebereinstimmen.
IDENTITY_FIELDS = (
    "name",
    "assetName",
    "assetType",
    "lodDist",
    "flags",
    "specialAttribute",
    "hdTextureDist",
    "textureDictionary",
    "physicsDictionary",
    "bbMin",
    "bbMax",
    "bsCentre",
    "bsRadius",
)


class MergeError(Exception):
    """Das Zusammenfassen wuerde ein Ergebnis erzeugen, dem nicht zu trauen ist."""


@dataclass
class ArchetypeEntry:
    """Ein Archetyp mit dem Wissen, woher er kommt."""

    name: str
    source: Path
    element: ET.Element

    def signature(self) -> tuple:
        return tuple(_field_text(self.element, f) for f in IDENTITY_FIELDS)


@dataclass
class MergePlan:
    """Was beim Zusammenfassen herauskommen wuerde - vor dem Schreiben."""

    name: str
    entries: list[ArchetypeEntry] = field(default_factory=list)
    sources: list[Path] = field(default_factory=list)
    # Archetypen, die mehrfach vorkamen und identisch waren. Kein Fehler, aber
    # erwaehnenswert: meistens heisst es, dass derselbe Prop zweimal gebaut
    # wurde.
    duplicates: list[str] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def archetype_names(self) -> list[str]:
        return [e.name for e in self.entries]


def _field_text(element: ET.Element, tag: str) -> str:
    """Liest ein Feld als Text - egal ob als Inhalt oder als Attribut notiert.

    CodeWalker schreibt Zahlen als `<lodDist value="60" />` und Zeichenketten
    als `<name>pf_tisch</name>`. Beim Vergleich zaehlt beides gleich.
    """
    for child in element:
        if child.tag.lower() != tag.lower():
            continue
        if child.attrib:
            return "|".join(f"{k}={v}" for k, v in sorted(child.attrib.items()))
        return (child.text or "").strip()
    return ""


def _archetypes_container(root: ET.Element) -> ET.Element | None:
    for child in root:
        if child.tag.lower() == "archetypes":
            return child
    return None


def read_archetypes(path: Path) -> list[ArchetypeEntry]:
    """Liest die Archetypen einer .ytyp.xml."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise MergeError(f"{path.name} ist kein gueltiges XML: {exc}") from exc

    if root.tag.lower() != "cmaptypes":
        raise MergeError(
            f"{path.name}: Wurzelelement ist '{root.tag}', erwartet 'CMapTypes'. "
            "Das ist keine .ytyp."
        )

    container = _archetypes_container(root)
    if container is None:
        return []

    entries = []
    for item in container:
        name = _field_text(item, "name")
        if not name:
            raise MergeError(
                f"{path.name}: ein Archetyp ohne <name>. Eine namenlose "
                "Definition ist im Spiel nicht referenzierbar."
            )
        entries.append(ArchetypeEntry(name=name, source=path, element=item))
    return entries


def find_ytyps(folder: Path) -> list[Path]:
    """Alle .ytyp.xml eines Ordners, in stabiler Reihenfolge.

    Nicht rekursiv: ein Ordner voller ytyps ist die Ansage, ein Baum darunter
    waere Raten. Wer mehr will, gibt die Dateien einzeln an.
    """
    return sorted(p for p in Path(folder).iterdir()
                  if p.is_file() and p.name.lower().endswith(".ytyp.xml"))


def plan_merge(paths: list[Path], name: str) -> MergePlan:
    """Entscheidet, was in die Sammel-ytyp kommt - ohne etwas zu schreiben.

    Getrennt vom Schreiben, damit dieselbe Entscheidung auch die
    Blender-Variante fuer Binaerdateien treffen kann und `--dry-run` nicht
    einen zweiten, womoeglich abweichenden Codeweg braucht.
    """
    plan = MergePlan(name=name)
    seen: dict[str, ArchetypeEntry] = {}

    for path in paths:
        entries = read_archetypes(path)
        if not entries:
            plan.skipped.append((path, "enthaelt keine Archetypen"))
            continue
        plan.sources.append(path)

        for entry in entries:
            key = entry.name.lower()
            previous = seen.get(key)
            if previous is None:
                seen[key] = entry
                plan.entries.append(entry)
                continue

            if previous.signature() == entry.signature():
                plan.duplicates.append(entry.name)
                continue

            raise MergeError(
                f"Zwei verschiedene Archetypen heissen '{entry.name}':\n"
                f"  {previous.source.name}\n"
                f"  {entry.source.name}\n"
                "Im Spiel gewinnt der zuletzt geladene - welcher das ist, "
                "haengt an der Ladereihenfolge. Einen der beiden umbenennen."
            )

    return plan


def render(plan: MergePlan) -> str:
    """Schreibt den Plan als CWXML."""
    root = ET.Element("CMapTypes")
    ET.SubElement(root, "extensions")
    archetypes = ET.SubElement(root, "archetypes")
    for entry in plan.entries:
        archetypes.append(entry.element)
    ET.SubElement(root, "name").text = plan.name
    ET.SubElement(root, "dependencies")
    ET.SubElement(root, "compositeEntityTypes")

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode") + "\n"


def merge(paths: list[Path], name: str, out_path: Path) -> MergePlan:
    """Fasst die .ytyp.xml zusammen und schreibt das Ergebnis."""
    plan = plan_merge(paths, name)
    if not plan.entries:
        raise MergeError(
            "Keine Archetypen gefunden - es gaebe nichts zusammenzufassen.")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(plan), encoding="utf-8")

    # Und die Gegenprobe: die geschriebene Datei zurueckgelesen muss genau die
    # Archetypen enthalten, die geplant waren. Eine Sammel-ytyp, in der ein
    # Prop fehlt, ist im Spiel nicht von einer kaputten Datei zu unterscheiden -
    # der Prop erscheint einfach nicht.
    written = [e.name for e in read_archetypes(out_path)]
    if written != plan.archetype_names:
        raise MergeError(
            f"Die geschriebene Datei enthaelt {len(written)} Archetypen, "
            f"geplant waren {len(plan.entries)}. Unterschied: "
            f"{sorted(set(plan.archetype_names) ^ set(written))}"
        )

    return plan
