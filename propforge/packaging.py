"""Letzte Stufe: fertige Assets zu einer FiveM-Resource buendeln.

FiveM streamt alles automatisch, was in einem `stream/`-Ordner liegt.
Zwei Ausnahmen brauchen einen expliziten Eintrag im fxmanifest:
ytyp-Dateien ueber `data_file 'DLC_ITYP_REQUEST'`, ymaps ueber `this_is_a_map`.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

FX_VERSION = "cerulean"
GAME = "gta5"

# Endungen, die FiveM aus stream/ selbst aufsammelt.
STREAM_SUFFIXES = {".ydr", ".ydd", ".yft", ".ytd", ".ybn", ".ycd", ".ymap", ".ytyp"}


# Kleiner Client-Helfer, der jeder Resource beiliegt.
#
# Zweck ist nicht Komfort, sondern Diagnose. Ein Prop, der im Spiel nicht
# auftaucht, hat zwei ganz verschiedene Ursachen, und dieser Befehl trennt sie:
#
#   Modell laedt nicht  -> Archetyp oder Streaming stimmt nicht (.ytyp fehlt,
#                          ist nicht registriert, Name falsch)
#   Modell laedt, aber  -> die .ydr selbst ist das Problem (Geometrie, Shader)
#   nichts ist zu sehen
#
# Ohne diese Unterscheidung sucht man an der falschen Stelle. Deshalb meldet
# der Befehl beides ausdruecklich, statt still zu scheitern.
SPAWN_HELPER = """\
-- Von PropForge erzeugt. Diagnosehilfe, kein Produktionscode.
--
--   /pfspawn            spawnt den ersten Prop dieser Resource
--   /pfspawn <name>     spawnt einen bestimmten Prop
--   /pfdelete           entfernt die zuletzt gespawnten Props wieder

local PROPS = { %(props)s }
local spawned = {}

local function spawnProp(name)
    local hash = GetHashKey(name)
    RequestModel(hash)

    local waited = 0
    while not HasModelLoaded(hash) and waited < 5000 do
        Wait(50)
        waited = waited + 50
    end

    if not HasModelLoaded(hash) then
        -- Aussagekraeftig: das Spiel kennt den Archetyp nicht. Die .ydr mag
        -- vorhanden sein, aber die .ytyp registriert sie nicht.
        print(("[propforge] '%%s' konnte nicht geladen werden. Das Spiel kennt "):format(name)
            .. "den Archetyp nicht - .ytyp pruefen, nicht das Modell.")
        return
    end

    local ped = PlayerPedId()
    local pos = GetEntityCoords(ped)
    local fwd = GetEntityForwardVector(ped)
    local obj = CreateObject(hash, pos.x + fwd.x * 2.0, pos.y + fwd.y * 2.0, pos.z, true, true, false)
    PlaceObjectOnGroundProperly(obj)
    FreezeEntityPosition(obj, true)
    SetModelAsNoLongerNeeded(hash)

    spawned[#spawned + 1] = obj
    -- Modell geladen. Ist jetzt nichts zu sehen, liegt es an der .ydr.
    print(("[propforge] '%%s' gespawnt (Entity %%d). Nichts zu sehen? Dann ist "):format(name, obj)
        .. "das Modell das Problem, nicht der Archetyp.")
end

RegisterCommand("pfspawn", function(_, args)
    spawnProp(args[1] or PROPS[1])
end, false)

RegisterCommand("pfdelete", function()
    for _, obj in ipairs(spawned) do
        if DoesEntityExist(obj) then DeleteEntity(obj) end
    end
    spawned = {}
    print("[propforge] aufgeraeumt.")
end, false)
"""


def render_spawn_helper(prop_names: list[str]) -> str:
    props = ", ".join(f'"{name}"' for name in sorted(prop_names))
    return SPAWN_HELPER % {"props": props}


@dataclass
class ResourceReport:
    root: Path
    streamed: list[Path]
    ytyps: list[Path]
    ymaps: list[Path]

    def summary(self) -> str:
        lines = [f"Resource: {self.root.name}  ({len(self.streamed)} Streaming-Dateien)"]
        by_suffix: dict[str, int] = {}
        for p in self.streamed:
            by_suffix[p.suffix] = by_suffix.get(p.suffix, 0) + 1
        for suffix, count in sorted(by_suffix.items()):
            lines.append(f"  {suffix:<7} {count}")
        return "\n".join(lines)


def render_manifest(
    resource_name: str,
    author: str,
    ytyps: list[str],
    ymaps: list[str],
    spawn_helper: bool = False,
) -> str:
    lines = [
        f"fx_version '{FX_VERSION}'",
        f"game '{GAME}'",
        "",
        f"name '{resource_name}'",
        f"author '{author}'",
        "version '1.0.0'",
        "description 'Generiert mit PropForge'",
        "",
    ]

    if spawn_helper:
        lines += ["client_script 'client.lua'", ""]

    if ymaps:
        lines += ["this_is_a_map 'yes'", ""]

    if ytyps:
        lines.append("-- Archetype-Definitionen muessen explizit registriert werden,")
        lines.append("-- sonst findet das Spiel die Props trotz vorhandener .ydr nicht.")
        for name in sorted(ytyps):
            lines.append(f"data_file 'DLC_ITYP_REQUEST' 'stream/{name}'")
        lines.append("")

    lines += [
        "files {",
        "    'stream/**.ytyp',",
        "}",
        "",
    ]
    return "\n".join(lines)


def build_resource(
    build_dir: Path,
    out_root: Path,
    resource_name: str,
    author: str,
    clean: bool = True,
    spawn_helper: bool = True,
    prop_names: list[str] | None = None,
) -> ResourceReport:
    """Sammelt alle Build-Artefakte in eine installierbare FiveM-Resource."""
    build_dir = Path(build_dir)
    resource_root = Path(out_root) / resource_name
    stream_dir = resource_root / "stream"

    if clean and resource_root.exists():
        shutil.rmtree(resource_root)
    stream_dir.mkdir(parents=True, exist_ok=True)

    streamed: list[Path] = []
    ytyps: list[Path] = []
    ymaps: list[Path] = []

    for src in sorted(build_dir.rglob("*")):
        if not src.is_file() or src.suffix.lower() not in STREAM_SUFFIXES:
            continue
        dst = stream_dir / src.name
        if dst.exists():
            raise FileExistsError(
                f"Namenskollision beim Packen: '{src.name}' existiert bereits in stream/. "
                "Streaming-Dateinamen muessen serverweit eindeutig sein."
            )
        shutil.copy2(src, dst)
        streamed.append(dst)
        if src.suffix.lower() == ".ytyp":
            ytyps.append(dst)
        elif src.suffix.lower() == ".ymap":
            ymaps.append(dst)

    # Ohne explizite Liste die Propnamen aus den gestreamten Drawables
    # ableiten: der Dateiname ohne Endung ist der Archetypname.
    names = prop_names or sorted(
        {p.stem for p in streamed if p.suffix.lower() in {".ydr", ".ydd", ".yft"}}
    )
    if spawn_helper and names:
        (resource_root / "client.lua").write_text(
            render_spawn_helper(names), encoding="utf-8")
    else:
        spawn_helper = False

    manifest = render_manifest(
        resource_name,
        author,
        [p.name for p in ytyps],
        [p.name for p in ymaps],
        spawn_helper=spawn_helper,
    )
    (resource_root / "fxmanifest.lua").write_text(manifest, encoding="utf-8")

    return ResourceReport(resource_root, streamed, ytyps, ymaps)
