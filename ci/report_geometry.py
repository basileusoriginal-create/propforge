"""Meldet den inneren Aufbau eines exportierten Drawables als Annotation.

Warum das noetig ist: `verify` prueft, was die Konfiguration versprochen hat -
Shader, LOD-Stufen, Sichtweiten, Sampler. Es sagt nichts darueber, wie die
Geometrie im Inneren aussieht. Genau da liegt aber der Fehler, wenn eine
formal einwandfreie Datei nichts anzeigt: eine fehlende Vertex-Semantik, ein
leerer Vertexpuffer, ein Sampler, der auf eine Textur zeigt, die im
eingebetteten Woerterbuch fehlt.

Bewusst *beschreibend* statt pruefend: das Skript weiss nicht, wie die
Elemente heissen, sondern gibt aus, was tatsaechlich in der Datei steht. Das
Format kommt aus szio und ist nirgends dokumentiert - Vermutungen darueber
haben in diesem Projekt schon genug gekostet. Erst wenn die echten Namen
bekannt sind, lohnt sich eine Pruefung darauf.

Aufruf:

    python ci/report_geometry.py ci/out/build "Geometrie (Linux)"
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

# GitHub kappt Annotations bei rund 4 KB.
MAX_CHARS = 3500

# Elemente, deren Textinhalt Nutzdaten sind. Sie werden nicht ausgegeben,
# sondern gezaehlt - sonst besteht die Annotation aus Zahlenkolonnen.
BULK = ("data", "vertices", "indices", "indexbuffer", "vertexbuffer")


def token_count(node: ET.Element) -> int:
    return len((node.text or "").split())


def line_count(node: ET.Element) -> int:
    return len([l for l in (node.text or "").splitlines() if l.strip()])


def describe(node: ET.Element, depth: int = 0, max_depth: int = 3) -> list[str]:
    """Beschreibt einen Teilbaum: Tag, Attribute, Datenmenge."""
    pad = "  " * depth
    # Attributwerte mitnehmen, solange sie kurz sind - "Bounds(type=Composite)"
    # sagt etwas, "Bounds(type)" nicht. Lange Zahlentripel bleiben draussen.
    full = ", ".join(f"{k}={v}" for k, v in node.attrib.items())
    attrs = full if len(full) <= 60 else ", ".join(node.attrib)
    head = f"{pad}{node.tag}" + (f"({attrs})" if attrs else "")

    text = (node.text or "").strip()
    if text and node.tag.lower() in BULK:
        head += f" [{line_count(node)} Zeilen / {token_count(node)} Werte]"
    elif text:
        head += f" = {text[:40]}"

    # Reine Namenslisten - allen voran die Vertex-Semantik - in eine Zeile.
    # Sie sind der interessanteste Teil des Aufbaus und duerfen nicht der
    # Tiefenbegrenzung zum Opfer fallen.
    if len(node) and all(len(c) == 0 and not (c.text or "").strip() for c in node):
        return [head + ": " + ", ".join(c.tag for c in node)]

    lines = [head]
    if depth < max_depth:
        for child in node:
            lines.extend(describe(child, depth + 1, max_depth))
    elif len(node):
        lines.append(f"{pad}  ... {len(node)} Kinder")
    return lines


def first(node: ET.Element, *names: str) -> ET.Element | None:
    """Erstes direktes Kind mit einem dieser Namen, Schreibweise egal."""
    wanted = {n.lower() for n in names}
    for child in node:
        if child.tag.lower() in wanted:
            return child
    return None


def lod_containers(root: ET.Element) -> list[tuple[str, ET.Element]]:
    return [
        (child.tag, child)
        for child in root
        if child.tag.lower().startswith("drawablemodels")
    ]


def report(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    lines = [f"{path.name}:"]

    # Die Bloecke auf oberster Ebene. Hier faellt auf, wenn etwas fehlt, das
    # ein Drawable braucht - oder etwas dasteht, das ein statischer Prop nicht
    # haben sollte (ein Skelett zum Beispiel).
    lines.append("  Bloecke: " + ", ".join(child.tag for child in root))

    # Shader und ihre Texturparameter - inklusive der Frage, ob die
    # referenzierte Textur im eingebetteten Woerterbuch ueberhaupt vorkommt.
    embedded: list[str] = []
    group = first(root, "ShaderGroup")
    if group is not None:
        txd = first(group, "TextureDictionary")
        for item in (txd or []):
            name = first(item, "Name")
            embedded.append((name.text or "").strip() if name is not None else "?")
        lines.append(f"  eingebettete Texturen: {', '.join(embedded) or '(keine)'}")

        shaders = first(group, "Shaders")
        for item in (shaders or []):
            fn = first(item, "FileName")
            lines.append(f"  Shader: {(fn.text or '').strip() if fn is not None else '?'}")
            params = first(item, "Parameters")
            for p in (params or []):
                if p.attrib.get("type") != "Texture":
                    continue
                tex = first(p, "Name")
                tex_name = (tex.text or "").strip() if tex is not None else ""
                mark = "" if tex_name in embedded else "  <- nicht im Woerterbuch!"
                lines.append(f"    {p.attrib.get('name', '?')} -> {tex_name or '(leer)'}{mark}")

    # Huellkoerper des Drawables. Sie entscheiden, ob das Spiel den Prop
    # ueberhaupt zeichnet: ist die Huelle zu klein oder falsch platziert,
    # wird das Objekt weggecullt, obwohl die Geometrie einwandfrei ist.
    for tag in ("BoundingSphereCenter", "BoundingSphereRadius",
                "BoundingBoxMin", "BoundingBoxMax"):
        node = first(root, tag)
        if node is None:
            continue
        value = ", ".join(f"{k}={v}" for k, v in node.attrib.items()) or (node.text or "").strip()
        lines.append(f"  {tag}: {value}")

    # Kollision. Die Flags sind der interessante Teil: ein Bound mit Flags 0
    # liegt vollstaendig in der Datei und kollidiert trotzdem mit nichts.
    bounds = first(root, "Bounds")
    if bounds is None:
        lines.append("  Bounds: (keine)")
    else:
        lines.append("  Bounds:")
        lines.extend("  " + l for l in describe(bounds, depth=1, max_depth=2))

        # Kinder und Flags gezielt statt per Tiefendump: die Flags liegen an
        # den Kind-Bounds, und ein vollstaendiger Baum bis dorthin sprengt die
        # Annotation. Beides zusammen entscheidet, ob die Kollision wirkt:
        # ohne Kinder ist das Composite eine leere Huelle, ohne Flags
        # kollidiert der Bound mit nichts.
        children = first(bounds, "Children")
        items = list(children) if children is not None else []
        lines.append(f"  Kind-Bounds: {len(items)}"
                     + (f" ({', '.join(i.attrib.get('type', '?') for i in items)})" if items else ""))
        for item in items:
            flags = [c for c in item.iter() if c.tag.lower().startswith("compositeflags")]
            for flag in flags:
                value = (flag.text or "").strip() or flag.attrib.get("value", "")
                lines.append(f"    {flag.tag}: {value or '(leer)'}")
            if not flags:
                lines.append("    (keine CompositeFlags gefunden)")

    # Aufbau der ersten Geometrie der hoechsten Stufe. Dort steht, welche
    # Vertex-Semantiken die Datei traegt und wie viele Werte drinstehen.
    for tag, container in lod_containers(root):
        models = list(container)
        if not models:
            continue
        geoms = first(models[0], "Geometries")
        items = list(geoms) if geoms is not None else []
        lines.append(f"  {tag}: {len(models)} Modell(e), {len(items)} Geometrie(n)")
        if items and tag.lower().endswith("high"):
            lines.append("  Aufbau der ersten Geometrie:")
            lines.extend("  " + l for l in describe(items[0], depth=1))

    return lines


def encode(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def main(argv: list[str]) -> int:
    build_dir = Path(argv[1]) if len(argv) > 1 else Path("ci/out/build")
    title = argv[2] if len(argv) > 2 else "Geometrie"

    files = sorted(build_dir.rglob("*.ydr.xml"))
    if not files:
        print(f"::notice title={title}::Keine .ydr.xml unter {build_dir} - "
              "der Aufbau laesst sich nur aus CWXML lesen.")
        return 0

    # Eine Annotation je Prop: zusammen waeren sie laengst abgeschnitten.
    for path in files:
        try:
            body = "\n".join(report(path))
        except ET.ParseError as exc:
            body = f"{path.name} ist nicht lesbar: {exc}"
        if len(body) > MAX_CHARS:
            body = body[:MAX_CHARS] + "\n[...gekuerzt...]"
        print(f"::notice title={title}: {path.name}::{encode(body)}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
