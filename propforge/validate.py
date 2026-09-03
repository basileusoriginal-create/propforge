"""Preflight-Checks, bevor Blender ueberhaupt startet.

Der teuerste Fehler in der GTA-Pipeline ist der, den man erst im Spiel sieht.
Diese Stufe faengt ab, was sich ohne Blender und ohne GTA V pruefen laesst -
Namenskonventionen, Texturmasse, LOD-Konsistenz, fehlende Dateien.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PIL import Image

from . import collision_materials as pf_materials
from .config import (
    LOD_LEVELS,
    PROFILES,
    VALID_TEXTURE_SIZES,
    PipelineConfig,
    PropSpec,
    texture_memory,
)

# Archetype-Namen landen in ytyp/ymap und werden gehasht. Grossbuchstaben,
# Leerzeichen und Sonderzeichen fuehren zu stillen Fehlschlaegen beim Lookup.
ARCHETYPE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")

SUPPORTED_MESH_SUFFIXES = {".glb", ".gltf", ".obj", ".fbx", ".ply", ".stl"}

# Shader, die fuer statische Props sinnvoll sind, mit ihren Pflicht-Samplern.
PROP_SHADERS = {
    "default.sps": {"DiffuseSampler"},
    "normal.sps": {"DiffuseSampler", "BumpSampler"},
    "spec.sps": {"DiffuseSampler", "SpecSampler"},
    "normal_spec.sps": {"DiffuseSampler", "BumpSampler", "SpecSampler"},
    "normal_spec_reflect.sps": {"DiffuseSampler", "BumpSampler", "SpecSampler"},
    "cutout.sps": {"DiffuseSampler"},
    "normal_cutout.sps": {"DiffuseSampler", "BumpSampler"},
}


class Level(str, Enum):
    ERROR = "error"      # Build wird scheitern oder das Asset ist im Spiel kaputt
    WARNING = "warning"  # laeuft, ist aber schlechte Praxis
    INFO = "info"


@dataclass
class Finding:
    level: Level
    code: str
    message: str
    prop: str | None = None

    def __str__(self) -> str:
        where = f"[{self.prop}] " if self.prop else ""
        return f"{self.level.value.upper():<7} {where}{self.code}: {self.message}"


def _sampler_for(role: str) -> str:
    return {"diffuse": "DiffuseSampler", "normal": "BumpSampler", "specular": "SpecSampler"}[role]


def validate_prop(spec: PropSpec) -> list[Finding]:
    findings: list[Finding] = []

    def add(level: Level, code: str, message: str) -> None:
        findings.append(Finding(level, code, message, prop=spec.name))

    # --- Budget ---
    #
    # Nicht bevormundend, aber sichtbar: wer ueber das Budget seiner
    # Groessenklasse geht, soll es wissen. Ein einzelner grosser Prop ist
    # kein Problem - hundert davon auf einem Server schon.
    profile = PROFILES.get(spec.profile)
    if profile is not None:
        if spec.max_tris > profile.max_tris:
            add(Level.WARNING, "budget_tris",
                f"{spec.max_tris} Dreiecke liegen ueber dem Budget des Profils "
                f"'{profile.name}' ({profile.max_tris}). Passt die Groessenklasse?")
        if spec.texture_size > profile.texture_size:
            add(Level.WARNING, "budget_texture",
                f"Textur {spec.texture_size} px liegt ueber dem Budget des Profils "
                f"'{profile.name}' ({profile.texture_size} px).")

    roles = len(spec.textures.present())
    memory = texture_memory(spec.texture_size, roles)
    if memory > 4 * 1024 * 1024:
        add(Level.WARNING, "texture_memory",
            f"Rund {memory / 1024 / 1024:.1f} MiB Texturspeicher fuer {roles} Texturen "
            f"a {spec.texture_size} px. Als Faustzahl gilt eine .ytd ab etwa 16 MB "
            "als zu gross - ein einzelner Prop sollte deutlich darunter bleiben.")

    # --- Name ---
    if not ARCHETYPE_NAME_RE.match(spec.name):
        add(
            Level.ERROR,
            "name_invalid",
            f"'{spec.name}' ist kein gueltiger Archetype-Name. Erlaubt: klein-"
            "geschrieben, 3-63 Zeichen, beginnend mit einem Buchstaben, nur a-z 0-9 _",
        )

    # --- Mesh ---
    mesh_path = Path(spec.mesh)
    if not mesh_path.is_file():
        add(Level.ERROR, "mesh_missing", f"Mesh-Datei nicht gefunden: {mesh_path}")
    elif mesh_path.suffix.lower() not in SUPPORTED_MESH_SUFFIXES:
        add(
            Level.ERROR,
            "mesh_format",
            f"Format '{mesh_path.suffix}' wird nicht unterstuetzt. "
            f"Moeglich: {', '.join(sorted(SUPPORTED_MESH_SUFFIXES))}",
        )

    # --- Shader vs. vorhandene Texturen ---
    if spec.shader not in PROP_SHADERS:
        add(
            Level.WARNING,
            "shader_unknown",
            f"'{spec.shader}' ist kein gelaeufiger Prop-Shader. "
            f"Bewaehrt: {', '.join(sorted(PROP_SHADERS))}",
        )
    else:
        required = PROP_SHADERS[spec.shader]
        available = {_sampler_for(r) for r in ("diffuse", "normal", "specular")
                     if getattr(spec.textures, r, None)}
        if spec.textures.roughness or spec.textures.metallic:
            available.add("SpecSampler")
        for sampler in sorted(required - available):
            add(
                Level.ERROR,
                "sampler_missing",
                f"Shader '{spec.shader}' benoetigt {sampler}, aber die passende "
                "Textur fehlt in der Konfiguration.",
            )

    # --- Texturen ---
    if spec.texture_size not in VALID_TEXTURE_SIZES:
        add(
            Level.ERROR,
            "texture_size_invalid",
            f"texture_size={spec.texture_size} ist keine Zweierpotenz. "
            f"Erlaubt: {', '.join(map(str, VALID_TEXTURE_SIZES))}",
        )
    elif spec.texture_size > 2048:
        add(Level.WARNING, "texture_size_large",
            "Ueber 2048 px empfiehlt Sollumz nicht - Streaming-Budget beachten.")

    for role, path_str in spec.textures.present().items():
        path = Path(path_str)
        if not path.is_file():
            add(Level.ERROR, "texture_missing", f"{role}: Datei nicht gefunden ({path})")
            continue
        try:
            with Image.open(path) as img:
                w, h = img.size
        except Exception as exc:  # noqa: BLE001 - alles, was Pillow nicht oeffnen kann
            add(Level.ERROR, "texture_unreadable", f"{role}: nicht lesbar ({exc})")
            continue
        if max(w, h) > spec.texture_size * 4:
            add(
                Level.WARNING,
                "texture_oversized",
                f"{role} ist {w}x{h} und wird auf {spec.texture_size} herunterskaliert - "
                "der Generator produziert mehr Aufloesung als du ausspielst.",
            )

    # --- LODs ---
    ratios = spec.lods.ratios
    ordered = [ratios[l] for l in LOD_LEVELS if l in ratios]
    if not ordered:
        add(Level.ERROR, "lod_empty", "Keine LOD-Verhaeltnisse definiert.")
    else:
        if "high" not in ratios:
            add(Level.ERROR, "lod_no_high", "LOD-Stufe 'high' (= LOD0) fehlt.")
        if any(r <= 0 or r > 1 for r in ordered):
            add(Level.ERROR, "lod_ratio_range", "LOD-Verhaeltnisse muessen in (0, 1] liegen.")
        if any(a < b for a, b in zip(ordered, ordered[1:])):
            add(
                Level.ERROR,
                "lod_ratio_order",
                f"LOD-Verhaeltnisse muessen absteigend sein, sind aber {ordered}.",
            )

    dists = spec.lods.distances
    ordered_d = [dists[l] for l in LOD_LEVELS if l in dists]
    if any(a > b for a, b in zip(ordered_d, ordered_d[1:])):
        add(
            Level.ERROR,
            "lod_dist_order",
            f"Sichtweiten muessen aufsteigend sein, sind aber {ordered_d}.",
        )
    for lod in ratios:
        if lod not in dists:
            add(Level.WARNING, "lod_dist_missing",
                f"Keine Sichtweite fuer LOD '{lod}' - Sollumz-Default 9998 greift.")

    # --- Kollision ---
    if spec.collision.enabled:
        if spec.collision.kind not in {"bvh", "box", "hull"}:
            add(Level.ERROR, "collision_kind",
                f"Unbekannter Kollisionstyp '{spec.collision.kind}'. Moeglich: bvh, box, hull")
        # Materialname vor dem Build pruefen. Ein unbekannter Name faellt
        # sonst erst in Blender auf - nach Texturaufbereitung und Import.
        if spec.collision.material not in pf_materials.BY_NAME:
            hits = pf_materials.search(spec.collision.material.split("_")[0].lower())
            tip = (" Passt vielleicht: " + ", ".join(m.name for m in hits[:5])) if hits else ""
            add(Level.ERROR, "collision_material_unknown",
                f"Kollisionsmaterial '{spec.collision.material}' gibt es nicht.{tip} "
                "Vollstaendige Liste: python -m propforge.cli materials")
        elif pf_materials.BY_NAME[spec.collision.material].category in \
                pf_materials.UNSUITABLE_FOR_PROPS:
            add(Level.WARNING, "collision_material_unsuitable",
                f"'{spec.collision.material}' gehoert zur Kategorie "
                f"'{pf_materials.BY_NAME[spec.collision.material].category}' und ist "
                "fuer einen statischen Prop kaum je richtig.")
        if spec.collision.source_lod not in ratios:
            add(
                Level.ERROR,
                "collision_source_lod",
                f"Kollision soll aus LOD '{spec.collision.source_lod}' gebaut werden, "
                "diese Stufe ist aber nicht definiert.",
            )
    else:
        add(Level.WARNING, "collision_disabled",
            "Ohne Kollision laeuft der Spieler durch den Prop hindurch.")

    # --- Orientierung ---
    if spec.source_up not in {"y", "z"}:
        add(
            Level.ERROR,
            "source_up_invalid",
            f"source_up='{spec.source_up}' ist unbekannt. Moeglich: 'y' (OBJ/glTF-"
            "Konvention, was Meshy und Tripo liefern) oder 'z' (Blender-Konvention).",
        )

    if spec.center not in {"none", "xy", "base", "all"}:
        add(
            Level.ERROR,
            "center_invalid",
            f"center='{spec.center}' ist unbekannt. Moeglich: none, xy, base, all.",
        )

    # --- Budget ---
    if spec.max_tris > 30000:
        add(Level.WARNING, "tris_high",
            f"max_tris={spec.max_tris} ist fuer einen Prop sehr hoch.")

    return findings


def validate(config: PipelineConfig) -> list[Finding]:
    findings: list[Finding] = []

    if config.export_format not in {"NATIVE", "CWXML"}:
        findings.append(Finding(Level.ERROR, "export_format",
                                f"Unbekanntes Exportformat '{config.export_format}'."))
    if config.export_version not in {"GEN8", "GEN9"}:
        findings.append(Finding(Level.ERROR, "export_version",
                                f"Unbekannte Zielversion '{config.export_version}'."))
    if config.export_format == "NATIVE":
        findings.append(Finding(
            Level.INFO, "native_requires_pymateria",
            "NATIVE-Export schreibt direkt Binaerdateien und benoetigt PyMateria "
            "(nur Windows). Ohne PyMateria auf CWXML wechseln und mit CodeWalker konvertieren.",
        ))

    seen: dict[str, int] = {}
    for prop in config.props:
        seen[prop.name] = seen.get(prop.name, 0) + 1
        findings.extend(validate_prop(prop))

    for name, count in seen.items():
        if count > 1:
            findings.append(Finding(
                Level.ERROR, "name_duplicate",
                f"Prop-Name '{name}' ist {count}x vergeben - Archetype-Namen muessen eindeutig sein.",
            ))

    return findings


def has_errors(findings: list[Finding]) -> bool:
    return any(f.level is Level.ERROR for f in findings)
