"""Wie Sollumz in einer Blender-Installation heissen kann - an einer Stelle.

Sollumz laesst sich auf drei Arten installieren, und der Modulname unterscheidet
sich je nach Weg:

  "Sollumz"                      klassisches Add-on, so installiert es die
                                 Sollumz-eigene CI und die meisten Anleitungen
  "sollumz"                      klassisches Add-on, kleingeschrieben entpackt
  "bl_ext.user_default.sollumz"  als Extension (Blender 4.2+)

Diese Liste wird sowohl von der Umgebungspruefung als auch von der
Blender-Stufe benutzt. Sie hier zu halten verhindert, dass die beiden
auseinanderlaufen - genau das ist einmal passiert und hat die CI rot gemacht,
weil die Pruefung 'Sollumz' nicht kannte, das Build-Skript aber schon.

Bewusst ohne Abhaengigkeiten: dieses Modul wird auch aus Blenders eigenem
Python importiert, wo Pillow und numpy nicht vorhanden sein muessen.
"""

from __future__ import annotations

MODULE_CANDIDATES = (
    "Sollumz",
    "sollumz",
    "bl_ext.user_default.sollumz",
)

OPTIONAL_DEPENDENCIES = ("pymateria",)
REQUIRED_DEPENDENCIES = ("szio",)


def probe_source() -> str:
    """Python-Quelltext, der in Blender laeuft und den Zustand ausgibt.

    Gibt Zeilen der Form ``SCHLUESSEL=WERT`` aus, damit das Ergebnis ohne
    Parserei auswertbar bleibt.
    """
    candidates = ", ".join(repr(name) for name in MODULE_CANDIDATES)
    deps = ", ".join(repr(name) for name in REQUIRED_DEPENDENCIES + OPTIONAL_DEPENDENCIES)
    return f'''\
import importlib

found = "NONE"
for name in ({candidates},):
    try:
        importlib.import_module(name)
        found = name
        break
    except Exception:
        continue
print("SOLLUMZ=" + found)

for dep in ({deps},):
    try:
        importlib.import_module(dep)
        print(dep.upper() + "=YES")
    except Exception:
        print(dep.upper() + "=NO")
'''


class SollumzAPI:
    """Die Sollumz-Symbole, die die Pipeline braucht - unter festen Namen.

    Bewusst ein Objekt und kein Tupel: die Rueckgabe ist im Lauf dieses
    Projekts schon zweimal gewachsen, und beim Tupel muss dann jeder
    Aufrufer mitwachsen. Ein vergessener Aufrufer faellt erst in der CI auf.
    """

    __slots__ = ("module", "SollumType", "LODLevel", "ArchetypeType",
                 "AssetType", "create_shader", "mesh_helper")

    def __init__(self, module_name, props, shaders, mesh_helper):
        self.module = module_name
        self.SollumType = props.SollumType
        self.LODLevel = props.LODLevel
        self.ArchetypeType = props.ArchetypeType
        self.AssetType = props.AssetType
        self.create_shader = shaders.create_shader
        # Ganzes Modul statt einzelner Funktionen: hier liegen die Helfer fuer
        # UV-Maps und Farb-Attribute, und davon werden es eher mehr.
        self.mesh_helper = mesh_helper


def import_sollumz() -> "SollumzAPI":
    """Importiert die Sollumz-Symbole, die die Pipeline braucht.

    Nur aus Blenders Python heraus sinnvoll. Wirft ``ImportError`` mit allen
    versuchten Namen, damit der Fehler etwas aussagt.
    """
    import importlib

    errors = []
    for module_name in MODULE_CANDIDATES:
        try:
            props = importlib.import_module(f"{module_name}.sollumz_properties")
            shaders = importlib.import_module(f"{module_name}.ydr.shader_materials")
            mesh_helper = importlib.import_module(f"{module_name}.tools.meshhelper")
            return SollumzAPI(module_name, props, shaders, mesh_helper)
        except ImportError as exc:
            errors.append(f"  {module_name}: {exc}")

    raise ImportError(
        "Sollumz konnte unter keinem bekannten Modulnamen importiert werden:\n"
        + "\n".join(errors)
    )
