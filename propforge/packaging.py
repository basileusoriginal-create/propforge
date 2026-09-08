"""Letzte Stufe: fertige Assets zu einer FiveM-Resource buendeln.

FiveM streamt alles automatisch, was in einem `stream/`-Ordner liegt.
Zwei Ausnahmen brauchen einen expliziten Eintrag im fxmanifest:
ytyp-Dateien ueber `data_file 'DLC_ITYP_REQUEST'`, ymaps ueber `this_is_a_map`.
"""

from __future__ import annotations

import shutil
import json
from dataclasses import dataclass
from pathlib import Path

from . import placement
from .transaction import DirectoryTransaction

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
local BOUNDS = { %(bounds)s }
local LOD_DISTANCES = %(lod_distances)s
local spawned = {}
local spawnedNames = {}
local cleanupDiagnostics = function() end

local function surfaceAt(x, y, z, ignore)
    RequestCollisionAtCoord(x, y, z)
    local handle = StartShapeTestLosProbe(x, y, z + 1.0, x, y, z - 5.0, 17, ignore, 7)
    local deadline = GetGameTimer() + 2000
    repeat
        local status, hit, point = GetShapeTestResult(handle)
        if status == 2 then
            if hit == true or hit == 1 then return point.z end
            return nil
        elseif status == 0 then return nil end
        Wait(0)
    until GetGameTimer() >= deadline
    return nil
end

local function placementHeight(ped, x, y, z, heading, bounds)
    -- Die Diagnosehilfe setzt auf ebene Standflaechen. Mehrere Strahlen
    -- erkennen Dachkanten, Stufen und Gefaelle statt dort Erfolg zu melden.
    local lo, hi = bounds.min, bounds.max
    local angle = math.rad(heading)
    local c, s = math.cos(angle), math.sin(angle)
    local lowest, highest = math.huge, -math.huge
    for _, p in ipairs({{lo[1],lo[2]}, {lo[1],hi[2]}, {hi[1],lo[2]},
                       {hi[1],hi[2]}, {(lo[1]+hi[1])/2,(lo[2]+hi[2])/2}}) do
        local height = surfaceAt(x + c*p[1] - s*p[2], y + s*p[1] + c*p[2], z, ped)
        if height == nil then return nil, "Standflaeche nicht geladen oder Dachkante getroffen." end
        lowest, highest = math.min(lowest, height), math.max(highest, height)
    end
    if highest - lowest > 0.015 then
        return nil, "Standflaeche ist uneben. Bitte eine ebene Stelle waehlen."
    end
    return highest - lo[3]
end

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
    local x, y = pos.x + fwd.x * 2.0, pos.y + fwd.y * 2.0
    local heading = GetEntityHeading(ped)
    local bounds = BOUNDS[name]
    local obj
    if bounds then
        local height, reason = placementHeight(ped, x, y, pos.z, heading, bounds)
        if not height then
            SetModelAsNoLongerNeeded(hash)
            print("[propforge] Platzierung abgebrochen: " .. reason)
            return
        end
        -- Kein Radius-Offset und keine Platzierung anhand der BVH-Randzugabe.
        obj = CreateObjectNoOffset(hash, x, y, height, true, true, false)
        if obj ~= 0 then SetEntityHeading(obj, heading) end
    else
        print("[propforge] Alte/fremde Ressource ohne gepruefte Standhoehe. "
            .. "Bodenbezug ungesichert; fuer PropForge-Assets neu bauen und packen.")
        obj = CreateObject(hash, x, y, pos.z, true, true, false)
        if obj ~= 0 then
            local placed = PlaceObjectOnGroundProperly(obj)
            if placed ~= true and placed ~= 1 then
                DeleteEntity(obj)
                obj = 0
            end
        end
    end
    if obj == 0 then
        SetModelAsNoLongerNeeded(hash)
        print("[propforge] Objekt konnte nicht erstellt/platziert werden.")
        return
    end
    FreezeEntityPosition(obj, true)
    SetModelAsNoLongerNeeded(hash)

    spawned[#spawned + 1] = obj
    spawnedNames[obj] = name
    -- Modell geladen. Ist jetzt nichts zu sehen, liegt es an der .ydr.
    print(("[propforge] '%%s' gespawnt (Entity %%d). Nichts zu sehen? Dann ist "):format(name, obj)
        .. "das Modell das Problem, nicht der Archetyp.")
end

RegisterCommand("pfspawn", function(_, args)
    spawnProp(args[1] or PROPS[1])
end, false)

RegisterCommand("pfdelete", function()
    cleanupDiagnostics()
    for _, obj in ipairs(spawned) do
        if DoesEntityExist(obj) then DeleteEntity(obj) end
    end
    spawned = {}
    spawnedNames = {}
    print("[propforge] aufgeraeumt.")
end, false)

AddEventHandler("onResourceStop", function(resource)
    if resource == GetCurrentResourceName() then
        cleanupDiagnostics()
        for _, obj in ipairs(spawned) do
            if DoesEntityExist(obj) then DeleteEntity(obj) end
        end
    end
end)
"""


DIAGNOSTIC_HELPER = r'''

-- Stable, opt-in diagnosis. No camera/player change when the resource starts.
local camera, reference = nil, nil
local cameraDistance = nil
local sweep = 0

local function currentProp()
    for i = #spawned, 1, -1 do
        if DoesEntityExist(spawned[i]) then return spawned[i], spawnedNames[spawned[i]] end
    end
    return nil, nil
end

local function stopView()
    sweep = sweep + 1
    if camera then
        RenderScriptCams(false, false, 0, true, true)
        DestroyCam(camera, false)
        ClearFocus()
        camera = nil
        cameraDistance = nil
    end
end

cleanupDiagnostics = function()
    stopView()
    if reference and DoesEntityExist(reference) then DeleteEntity(reference) end
    reference = nil
end

local function measure()
    local obj, name = currentProp()
    if not obj then return {status="failed", error="Kein eigener Test-Prop vorhanden."} end
    local bounds = BOUNDS[name]
    if not bounds then return {status="failed", error="Keine geprueften sichtbaren Bounds."} end
    local lo, hi = bounds.min, bounds.max
    local points = {{lo[1],lo[2]}, {lo[1],hi[2]}, {hi[1],lo[2]}, {hi[1],hi[2]},
                    {(lo[1]+hi[1])/2,(lo[2]+hi[2])/2}}
    local gaps, surfaces = {}, {}
    local maximum, minimum = -math.huge, math.huge
    for _, p in ipairs(points) do
        local foot = GetOffsetFromEntityInWorldCoords(obj, p[1]+0.0, p[2]+0.0, lo[3]+0.0)
        local surface = surfaceAt(foot.x, foot.y, foot.z+0.05, obj)
        if surface == nil then return {status="failed", error="Standflaeche nicht messbar."} end
        local gap = (foot.z-surface)*1000.0
        gaps[#gaps+1] = gap
        surfaces[#surfaces+1] = surface
        maximum, minimum = math.max(maximum,gap), math.min(minimum,gap)
    end
    local coords = GetEntityCoords(obj)
    local report = {status="measured", name=name, entity=obj,
                   gap_mm=gaps, max_gap_mm=maximum, min_gap_mm=minimum,
                   within_2mm=maximum<=2.0 and minimum>=-2.0,
                   coords={x=coords.x,y=coords.y,z=coords.z}, heading=GetEntityHeading(obj),
                   ground_heights=surfaces, visible_bounds=bounds,
                   lod_distances=LOD_DISTANCES[name], camera_distance_m=cameraDistance,
                   coverage="visible LOD0 footprint against five world collision probes",
                   visual_and_walk_test="pending"}
    if reference and DoesEntityExist(reference) then
        local rlo, rhi = GetModelDimensions(GetEntityModel(reference))
        report.reference = {name="prop_table_03", dimensions={x=rhi.x-rlo.x,y=rhi.y-rlo.y,z=rhi.z-rlo.z}}
    end
    return report
end

local function printReport(report)
    print("[propforge:diagnostic] " .. json.encode(report))
end

local function view(argument)
    if argument == "off" then stopView(); return {status="camera_restored"} end
    local obj, name = currentProp()
    if not obj then return {status="failed", error="Zuerst /pfspawn benutzen."} end
    local distance = tonumber(argument) or 3.0
    if distance < 0.2 or distance > 1000.0 then return {status="failed", error="Kameraabstand 0.2 bis 1000 m."} end
    local bounds = BOUNDS[name]
    if not bounds then return {status="failed", error="Sichtbare Bounds fehlen."} end
    local height = (bounds.min[3]+bounds.max[3])/2.0
    if argument == "feet" then height=bounds.min[3]+0.045; distance=1.8 end
    local centerX = (bounds.min[1]+bounds.max[1])/2.0
    local centerY = (bounds.min[2]+bounds.max[2])/2.0
    local target = GetOffsetFromEntityInWorldCoords(obj, centerX, centerY, height)
    -- Spawn is two metres in front of the player. A camera directly behind
    -- the prop looks through that player; use a diagonal of unit length.
    local eye = GetOffsetFromEntityInWorldCoords(obj, centerX+distance*0.6, centerY-distance*0.8, height)
    if not camera then camera=CreateCam("DEFAULT_SCRIPTED_CAMERA", true) end
    SetCamCoord(camera, eye.x+0.0, eye.y+0.0, eye.z+0.0)
    PointCamAtCoord(camera, target.x+0.0, target.y+0.0, target.z+0.0)
    SetCamFov(camera, 45.0)
    -- A feet view is only 45 mm above the surface. The default near plane
    -- cuts through that surface and exposes geometry underneath the roof.
    SetCamNearClip(camera, 0.01)
    SetFocusPosAndVel(target.x+0.0, target.y+0.0, target.z+0.0, 0.0, 0.0, 0.0)
    RenderScriptCams(true, false, 0, true, true)
    InvalidateIdleCam()
    -- GetCamCoord can still return the previous position in this frame.
    -- Yield to the game before measuring; stop if another command took over.
    local measuredCamera, generation = camera, sweep
    local actual, positionError
    for attempt=1,5 do
        Wait(0)
        if camera~=measuredCamera or sweep~=generation then return {status="camera_cancelled"} end
        actual = GetCamCoord(measuredCamera)
        positionError = math.sqrt((actual.x-eye.x)^2+(actual.y-eye.y)^2+(actual.z-eye.z)^2)
        if positionError < 0.01 then break end
    end
    cameraDistance = math.sqrt((actual.x-target.x)^2+(actual.y-target.y)^2+(actual.z-target.z)^2)
    return {status=positionError < 0.01 and "camera_ready" or "failed", name=name, distance_m=cameraDistance,
            error=positionError >= 0.01 and "Kamera hat die Zielposition nicht erreicht." or nil,
            requested_distance_m=distance, fov=GetCamFov(camera),
            lod_distances=LOD_DISTANCES[name], actual_selected_lod="not_observable"}
end

local function spawnReference()
    local obj = currentProp()
    if not obj then return {status="failed", error="Zuerst /pfspawn benutzen."} end
    local hash = GetHashKey("prop_table_03")
    if not IsModelInCdimage(hash) or not IsModelValid(hash) then
        return {status="failed", error="GTA-Referenz prop_table_03 ist hier nicht verfuegbar."}
    end
    RequestModel(hash)
    local deadline = GetGameTimer()+5000
    while not HasModelLoaded(hash) and GetGameTimer()<deadline do Wait(50) end
    if not HasModelLoaded(hash) then return {status="failed", error="GTA-Referenz laedt nicht."} end
    if reference and DoesEntityExist(reference) then DeleteEntity(reference) end
    local p = GetOffsetFromEntityInWorldCoords(obj, -2.5, 0.0, 0.1)
    reference = CreateObjectNoOffset(hash, p.x, p.y, p.z, false, false, false)
    SetModelAsNoLongerNeeded(hash)
    if reference == 0 then reference=nil; return {status="failed", error="Referenz nicht erstellt."} end
    SetEntityHeading(reference, GetEntityHeading(obj))
    local placed = PlaceObjectOnGroundProperly(reference)
    if placed ~= true and placed ~= 1 then
        DeleteEntity(reference); reference=nil
        return {status="failed", error="Referenz nicht auf Boden platzierbar."}
    end
    FreezeEntityPosition(reference, true)
    return measure()
end

RegisterCommand("pfmeasure", function() printReport(measure()) end, false)
RegisterCommand("pfview", function(_,args) sweep=sweep+1; printReport(view(args[1])) end, false)
RegisterCommand("pfreference", function() printReport(spawnReference()) end, false)
RegisterCommand("pfstage", function(_,args)
    ExecuteCommand("pfdelete")
    spawnProp(args[1] or PROPS[1])
    printReport(spawnReference())
    printReport(view("3"))
end, false)
RegisterCommand("pflods", function()
    sweep=sweep+1
    local ownSweep=sweep
    CreateThread(function()
        local _, name = currentProp()
        local distances = LOD_DISTANCES[name] or {high=60.0,medium=120.0,low=250.0,verylow=500.0}
        for _, level in ipairs({"high","medium","low","verylow"}) do
            for _, factor in ipairs({0.9,1.1}) do
                if ownSweep~=sweep then return end
                printReport(view(tostring(distances[level]*factor)))
                Wait(2500)
                if not camera or ownSweep~=sweep then return end
            end
        end
        stopView()
    end)
end, false)

-- Local client event for controlled test fixtures; no public network event.
AddEventHandler("propforge:diagnose", function(request, callback)
    CreateThread(function()
        local report
        if request.action=="view" then sweep=sweep+1; report=view(request.distance or "feet")
        elseif request.action=="reference" then report=spawnReference()
        else report=measure() end
        if callback then callback(report) end
    end)
end)
'''


def render_spawn_helper(
    prop_names: list[str], bounds: dict[str, dict[str, list[float]]] | None = None,
    lod_distances: dict | None = None,
) -> str:
    props = ", ".join(json.dumps(name) for name in sorted(prop_names))
    entries = []
    for name, box in sorted((bounds or {}).items()):
        lo = ",".join(repr(v) for v in box["min"])
        hi = ",".join(repr(v) for v in box["max"])
        entries.append(f'[{json.dumps(name)}] = {{ min = {{{lo}}}, max = {{{hi}}} }}')
    distances = "{" + ", ".join("[" + json.dumps(name) + "]={" +
        ",".join(key + "=" + repr(float(value)) for key, value in values.items()) + "}"
        for name, values in sorted((lod_distances or {}).items())) + "}"
    return SPAWN_HELPER % {"props": props, "bounds": ", ".join(entries), "lod_distances": distances} + DIAGNOSTIC_HELPER


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
    if Path(resource_name).name != resource_name or resource_name in ("", ".", ".."):
        raise ValueError("Resource-Name muss ein einzelner Ordnername sein.")
    resource_root = Path(out_root).resolve() / resource_name
    stream_dir = resource_root / "stream"

    # Neue Prueffehler duerfen kein bereits brauchbares Paket entfernen.
    source_files = [src for src in sorted(build_dir.rglob("*"))
                    if src.is_file() and src.suffix.lower() in STREAM_SUFFIXES
                    and not any(part.startswith(".") for part in src.relative_to(build_dir).parts)]
    placement_bounds = {}
    lod_distances = {}
    seen = set()
    for src in source_files:
        key = src.name.lower()
        if key in seen:
            raise FileExistsError(f"Namenskollision beim Packen: '{src.name}'. Streaming-Dateinamen muessen eindeutig sein.")
        seen.add(key)
    if spawn_helper:
        for src in source_files:
            if src.suffix.lower() == ".ydr":
                box = placement.read(src)
                if box is not None:
                    placement_bounds[src.stem] = box
                receipt = src.with_suffix(".build.json")
                if receipt.is_file():
                    lod_distances[src.stem] = json.loads(receipt.read_text(encoding="utf-8"))["job"]["lod_distances"]

    streamed: list[Path] = []
    ytyps: list[Path] = []
    ymaps: list[Path] = []

    for src in source_files:
        dst = stream_dir / src.name
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
    spawn_helper = bool(spawn_helper and names)
    with DirectoryTransaction(resource_root, seed=not clean) as transaction:
        candidate = transaction.stage
        (candidate / "stream").mkdir(parents=True, exist_ok=True)
        for src in source_files:
            dst = candidate / "stream" / src.name
            if dst.exists():
                raise FileExistsError(f"Namenskollision beim Packen: '{src.name}'.")
            shutil.copy2(src, dst)
        if spawn_helper:
            (candidate / "client.lua").write_text(
                render_spawn_helper(names, placement_bounds, lod_distances), encoding="utf-8")
            (candidate / "PRUEFUNG.md").write_text(
                "# PropForge-Diagnose\n\n"
                "Ressource starten und auf einer ebenen Flaeche `/pfstage <name>` benutzen. "
                "Das stellt Prop und GTA-Tischreferenz auf und schaltet eine feste Kamera ein.\n\n"
                "- `/pfview feet`: Nahansicht der Fuesse.\n"
                "- `/pfmeasure`: fuenf Bodenabstaende in Millimetern (F8-Konsole).\n"
                "- `/pfview 20`: feste Kamera in 20 m Abstand; `/pfview off`: normale Kamera.\n"
                "- `/pflods`: Kamerafahrt vor/hinter den vier konfigurierten LOD-Distanzen.\n"
                "- `/pfreference`: GTA-Tisch zum Groessenvergleich.\n"
                "- `/pfdelete`: eigene Props, Referenz und Kamera entfernen.\n\n"
                "Danach normal dagegenlaufen, aufsteigen, entfernen und zurueckkehren. "
                "Texturen, Materialwirkung, sichtbare LOD-Wechsel und Kollision manuell beurteilen. "
                "Die Messung prueft den LOD0-Standflaechenbezug; sie beweist weder "
                "die sichtbare Darstellung noch die vom Spiel ausgewaehlte LOD oder FPS.\n", encoding="utf-8")
        manifest = render_manifest(resource_name, author, [p.name for p in ytyps],
                                   [p.name for p in ymaps], spawn_helper=spawn_helper)
        (candidate / "fxmanifest.lua").write_text(manifest, encoding="utf-8")
        transaction.publish()

    return ResourceReport(resource_root, streamed, ytyps, ymaps)
