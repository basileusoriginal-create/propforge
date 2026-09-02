"""Installiert Sollumz' Abhaengigkeiten. Laeuft in Blenders Python.

    blender --background --python ci/install_deps.py

Sollumz bringt die Installation selbst mit, inklusive gepinnter Versionen und
Hash-Pruefung - das ist der richtige Weg, statt szio von Hand in Blenders
Python zu pippen.

`online_access_override=True` ist noetig, weil Blender im Hintergrundmodus
keinen Online-Zugriff meldet und die Installation sonst kommentarlos nichts
tut.

Optionale Abhaengigkeiten (PyMateria) werden nur angefordert, wenn sie auf der
Plattform ueberhaupt verfuegbar sind - unter Linux gibt es sie nicht.
"""

import sys
from pathlib import Path

# Blender legt bei "--python skript.py" das Projektverzeichnis nicht in den
# sys.path - der Import von propforge muss also selbst dafuer sorgen.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    try:
        from propforge.sollumz_env import MODULE_CANDIDATES
    except ImportError:
        MODULE_CANDIDATES = ("Sollumz", "sollumz", "bl_ext.user_default.sollumz")

    dependencies = None
    for name in MODULE_CANDIDATES:
        try:
            module = __import__(f"{name}.dependencies", fromlist=["dependencies"])
            dependencies = module
            print(f"SOLLUMZ_MODULE={name}")
            break
        except ImportError:
            continue

    if dependencies is None:
        print("SOLLUMZ_NOT_FOUND: " + ", ".join(MODULE_CANDIDATES))
        return 1

    optional: set[str] = set()
    if sys.platform == "win32":
        optional.add("pymateria")

    ok = dependencies.install_dependencies(
        online_access_override=True,
        optional_dependencies_to_install=optional,
    )
    print("DEPS_INSTALLED" if ok else "DEPS_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
