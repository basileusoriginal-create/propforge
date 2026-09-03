"""Vergleicht unsere Materialliste mit der von Sollumz.

Unsere Liste ist eine Beschreibung, keine Quelle der Wahrheit: der
Materialindex kommt zur Laufzeit aus Sollumz. Beschreibung und Wirklichkeit
duerfen aber nicht auseinanderlaufen - sonst schlaegt die Abfrage beim Import
ein Material vor, das es nicht gibt, oder die Preflight-Pruefung lehnt ein
gueltiges ab.

Sollumz wird in der CI ohnehin ausgecheckt, also wird hier direkt seine
Quelldatei gelesen - ohne Blender, ohne Import.

    python ci/check_collision_materials.py _sollumz
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from propforge.collision_materials import MATERIALS  # noqa: E402

PATTERN = re.compile(r'CollisionMaterialDef\(\s*"([A-Z0-9_]+)"')


def sollumz_names(sollumz_root: Path) -> list[str]:
    source = sollumz_root / "ybn" / "collision_materials.py"
    if not source.is_file():
        raise FileNotFoundError(f"Sollumz-Quelle nicht gefunden: {source}")
    return PATTERN.findall(source.read_text(encoding="utf-8"))


def encode(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("_sollumz")

    try:
        theirs = sollumz_names(root)
    except FileNotFoundError as exc:
        print(f"::notice title=Kollisionsmaterialien::{exc}")
        return 0

    ours = [m.name for m in MATERIALS]
    missing = sorted(set(theirs) - set(ours))
    extra = sorted(set(ours) - set(theirs))
    duplicates = sorted({n for n in ours if ours.count(n) > 1})

    if not (missing or extra or duplicates):
        print(f"::notice title=Kollisionsmaterialien::"
              f"{len(ours)} Materialien, deckungsgleich mit Sollumz.")
        return 0

    body = []
    if missing:
        body.append(f"In Sollumz, bei uns nicht beschrieben: {', '.join(missing)}")
    if extra:
        body.append(f"Bei uns beschrieben, in Sollumz nicht (mehr) vorhanden: {', '.join(extra)}")
    if duplicates:
        body.append(f"Doppelt in unserer Liste: {', '.join(duplicates)}")

    # Warnung, kein Fehler: eine neue Sollumz-Version darf den Build nicht
    # kippen. Sichtbar muss die Abweichung trotzdem sein.
    print(f"::warning title=Kollisionsmaterialien weichen ab::{encode(chr(10).join(body))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
