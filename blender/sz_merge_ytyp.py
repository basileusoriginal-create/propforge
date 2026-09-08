"""Fasst mehrere .ytyp zu einer zusammen - auch die binaeren.

Aufruf:

    blender --background --python sz_merge_ytyp.py -- \
        --input a.ytyp b.ytyp --name pack_props --out ordner \
        --format NATIVE --version GEN8 --result bericht.json

Warum ueberhaupt Blender: die Binaerform einer .ytyp ist ein RSC7-Container,
den nur szio lesen kann - und szio wird als Sollumz-Abhaengigkeit in Blenders
Python installiert. Fuer CWXML gibt es den kuerzeren Weg ohne Blender in
`propforge/ytyp_merge.py`; dieses Skript ist der fuer alles andere.

Bewusst ohne bpy-Datenbloecke: die Archetypen wandern nicht durch die
Blender-Szene, sondern von szio-Asset zu szio-Asset. Der Umweg ueber Blenders
PropertyGroups wuerde jedes Archetyp-Feld einzeln hin- und herkopieren - und
jedes vergessene Feld waere ein stiller Datenverlust, der erst im Spiel
auffaellt.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def log(message: str) -> None:
    print(f"[merge-ytyp] {message}", flush=True)


def load_map_types(path: Path):
    """Liest eine .ytyp beliebigen Formats als szio-Asset."""
    from szio import VPath
    from szio.gta5 import AssetType, try_load_asset

    result = try_load_asset(VPath(path.resolve()), return_target=True)
    if result is None:
        raise RuntimeError(
            f"'{path.name}' liess sich nicht lesen. Bei einer binaeren .ytyp "
            "heisst das fast immer, dass PyMateria fehlt - ohne das Paket kann "
            "Sollumz Binaerdateien weder lesen noch schreiben ('propforge "
            "doctor' zeigt es an)."
        )

    asset, target = result
    if asset.ASSET_TYPE is not AssetType.MAP_TYPES:
        raise RuntimeError(
            f"'{path.name}' ist keine .ytyp, sondern {asset.ASSET_TYPE.name}."
        )
    return asset, target


# Felder, die einen Archetyp inhaltlich ausmachen. Dieselbe Liste wie in
# propforge/ytyp_merge.py, nur in der szio-Schreibweise: beide Wege sollen bei
# denselben Eingaben dieselbe Entscheidung treffen.
IDENTITY_FIELDS = (
    "name", "asset_name", "asset_type", "lod_dist", "flags",
    "special_attribute", "hd_texture_dist", "texture_dictionary",
    "physics_dictionary", "bb_min", "bb_max", "bs_center", "bs_radius",
)


def _signature(archetype) -> tuple:
    """Der inhaltliche Fingerabdruck eines Archetyps.

    Fehlt eines der Felder, wird das gemeldet statt uebergangen. Ein
    getattr-Standardwert waere hier genau die falsche Vorsicht: zwei
    Archetypen, die sich in einem nicht mehr gelesenen Feld unterscheiden,
    saehen dann identisch aus - und der Merger wuerde stillschweigend einen
    von beiden wegwerfen. Lieber ein klarer Abbruch, wenn szio seine Felder
    umbenennt.
    """
    missing = [f for f in IDENTITY_FIELDS if not hasattr(archetype, f)]
    if missing:
        raise RuntimeError(
            f"Der Archetyp '{getattr(archetype, 'name', '?')}' hat die Felder "
            f"{', '.join(missing)} nicht. Vermutlich hat sich szio geaendert - "
            "der Vergleich waere ohne diese Felder nicht mehr aussagekraeftig."
        )
    return tuple(repr(getattr(archetype, f)) for f in IDENTITY_FIELDS)


def merge(paths: list[Path], name: str, out_dir: Path, fmt: str, version: str) -> dict:
    out_dir = out_dir.resolve()
    from szio.gta5 import (
        AssetFormat,
        AssetMapTypes,
        AssetTarget,
        AssetVersion,
        SaveOptions,
        save_asset,
    )

    archetypes = []
    seen: dict[str, tuple[Path, tuple]] = {}
    duplicates: list[str] = []
    sources: list[str] = []

    for path in paths:
        asset, _ = load_map_types(path)
        count = 0
        for archetype in asset.archetypes:
            key = archetype.name.lower()
            first = seen.get(key)
            signature = _signature(archetype)
            if first is not None:
                first_path, first_signature = first
                if first_signature == signature:
                    # Derselbe Prop zweimal gebaut. Welchen man nimmt, ist
                    # folgenlos - beide sagen dasselbe.
                    duplicates.append(archetype.name)
                    log(f"  {path.name}: '{archetype.name}' ist identisch mit "
                        f"dem aus {first_path.name} - einmal uebernommen.")
                    continue
                # Gleicher Name, andere Definition. Das darf nicht still
                # verschmelzen: im Spiel gewinnt der zuletzt geladene
                # Archetyp, und welcher das ist, entscheidet die
                # Ladereihenfolge.
                raise RuntimeError(
                    f"Zwei verschiedene Archetypen heissen '{archetype.name}':\n"
                    f"  {first_path.name}\n  {path.name}\n"
                    "Einen der beiden umbenennen - sonst zeigt im Spiel einer "
                    "der Props das Modell des anderen."
                )
            seen[key] = (path, signature)
            archetypes.append(archetype)
            count += 1
        sources.append(path.name)
        log(f"  {path.name}: {count} Archetyp(en)")

    if not archetypes:
        raise RuntimeError("Keine Archetypen gefunden - es gaebe nichts zusammenzufassen.")

    merged = AssetMapTypes(name=name, archetypes=archetypes)
    target = AssetTarget(AssetFormat[fmt], AssetVersion[version])

    out_dir.mkdir(parents=True, exist_ok=True)
    save_asset(
        merged,
        (target,),
        out_dir,
        name,
        SaveOptions(
            gen8_directory=out_dir / "gen8",
            gen9_directory=out_dir / "gen9",
            tool_metadata=("PropForge", "merge-ytyp"),
        ),
    )

    written = sorted(
        p for p in out_dir.iterdir()
        if p.is_file() and p.name.startswith(name) and ".ytyp" in p.name
    )
    if not written:
        existing = [p.name for p in out_dir.iterdir() if p.is_file()] or ["(nichts)"]
        raise RuntimeError(
            f"Es wurde keine Datei fuer '{name}' geschrieben. Im Zielordner "
            f"liegt: {', '.join(existing)}."
        )

    # Gegenprobe: die geschriebene Datei zurueckgelesen. Dass save_asset
    # zurueckkehrt, heisst nur, dass es keinen Fehler geworfen hat - nicht,
    # dass die Datei die Archetypen enthaelt. Eine Sammel-ytyp, in der ein
    # Prop fehlt, ist im Spiel nicht von einer kaputten Datei zu
    # unterscheiden: der Prop erscheint einfach nicht.
    expected = [a.name for a in archetypes]
    reread, _ = load_map_types(written[0])
    actual = [a.name for a in reread.archetypes]
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise RuntimeError(
            f"Die geschriebene {written[0].name} enthaelt {len(actual)} "
            f"Archetypen, erwartet waren {len(expected)}. "
            f"Fehlt: {missing or '-'}. Zuviel: {extra or '-'}."
        )

    for path in written:
        log(f"geschrieben: {path.name} ({path.stat().st_size} Bytes)")

    return {
        "name": name,
        "archetypes": expected,
        "duplicates": duplicates,
        "sources": sources,
        "files": [{"file": p.name, "bytes": p.stat().st_size} for p in written],
    }


def main(argv: list[str]) -> int:
    argv = argv[argv.index("--") + 1:] if "--" in argv else []

    parser = argparse.ArgumentParser(description="PropForge YTYP-Merger")
    parser.add_argument("--input", nargs="+", required=True, help="Die .ytyp-Dateien")
    parser.add_argument("--name", required=True, help="Name der Sammel-ytyp")
    parser.add_argument("--out", required=True, help="Zielordner")
    parser.add_argument("--format", default="NATIVE", choices=["NATIVE", "CWXML"])
    parser.add_argument("--version", default="GEN8", choices=["GEN8", "GEN9"])
    parser.add_argument("--result", help="Pfad fuer den Ergebnisbericht (JSON)")
    args = parser.parse_args(argv)

    # Sollumz muss aktiv sein, damit szio im Modulpfad liegt. Der Import unten
    # wuerde sonst mit einem nichtssagenden ModuleNotFoundError scheitern.
    try:
        import szio  # noqa: F401
    except ImportError:
        log("FEHLER: szio ist nicht verfuegbar. Ist Sollumz in dieser "
            "Blender-Installation aktiviert? 'propforge doctor' prueft das.")
        return 2

    paths = [Path(p) for p in args.input]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        log(f"FEHLER: nicht gefunden: {', '.join(p.name for p in missing)}")
        return 2

    try:
        report = merge(paths, args.name, Path(args.out), args.format, args.version)
    except Exception as exc:  # noqa: BLE001
        import traceback

        log(f"FEHLER: {exc}")
        for line in traceback.format_exc().splitlines():
            log(f"  {line}")
        return 1

    # Der Bericht ist die belastbare Quelle, nicht der Exit-Code: Blender gibt
    # den im Hintergrundmodus nicht zuverlaessig weiter. Derselbe Grund wie
    # beim Prop-Build.
    if args.result:
        result_path = Path(args.result)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"Ergebnisbericht: {result_path}")

    log(f"Fertig: {len(report['archetypes'])} Archetypen in {args.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
