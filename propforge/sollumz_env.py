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
                 "AssetType", "create_shader", "mesh_helper",
                 "apply_flag_preset", "flag_preset_names")

    def __init__(self, module_name, props, shaders, mesh_helper, bound_helper, flag_presets):
        self.module = module_name
        self.SollumType = props.SollumType
        self.LODLevel = props.LODLevel
        self.ArchetypeType = props.ArchetypeType
        self.AssetType = props.AssetType
        self.create_shader = shaders.create_shader
        # Ganzes Modul statt einzelner Funktionen: hier liegen die Helfer fuer
        # UV-Maps und Farb-Attribute, und davon werden es eher mehr.
        self.mesh_helper = mesh_helper
        self.apply_flag_preset = bound_helper.apply_flag_preset
        self.flag_preset_names = flag_presets


def _flag_preset_names(module_name: str) -> list[str]:
    """Namen aller verfuegbaren Kollisions-Flag-Presets.

    Wird nur gebraucht, um im Fehlerfall etwas Brauchbares sagen zu koennen:
    ein Preset-Name, den es nicht gibt, wird von Sollumz stillschweigend
    ignoriert - die Kollision hat dann Flags 0 und kollidiert mit nichts.
    """
    import importlib

    try:
        store = importlib.import_module(f"{module_name}.shared.presets.store")
        flag = importlib.import_module(f"{module_name}.ybn.gta5.presets.flag")
        return [p.get("name", "?") for p in store.load_presets(flag.FLAG_PRESET_CATEGORY)]
    except Exception:  # noqa: BLE001 - eine fehlende Liste darf nichts kippen
        return []


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
            bound_helper = importlib.import_module(f"{module_name}.tools.boundhelper")
            return SollumzAPI(
                module_name, props, shaders, mesh_helper, bound_helper,
                _flag_preset_names(module_name),
            )
        except ImportError as exc:
            errors.append(f"  {module_name}: {exc}")

    raise ImportError(
        "Sollumz konnte unter keinem bekannten Modulnamen importiert werden:\n"
        + "\n".join(errors)
    )
