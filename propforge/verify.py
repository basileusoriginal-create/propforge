"""Abgleich: hat der Build gebaut, was in der Konfiguration stand?

Die Preflight-Stufe (`validate`) prueft die Eingabe, diese Stufe die Ausgabe.
Zusammen schliessen sie die Schleife, ohne dass GTA V dafuer laufen muss.
"""

from __future__ import annotations

from pathlib import Path

from .config import LOD_LEVELS, PipelineConfig, PropSpec
from .inspect import DrawableInfo, InspectError, parse_drawable
from .validate import Finding, Level

# Wie stark die exportierte Sichtweite vom Sollwert abweichen darf.
DISTANCE_TOLERANCE = 0.5

# Erwartete Samplernamen je Texturrolle.
ROLE_SAMPLERS = {"_d": "DiffuseSampler", "_n": "BumpSampler", "_s": "SpecSampler"}


def verify_drawable(spec: PropSpec, info: DrawableInfo) -> list[Finding]:
    findings: list[Finding] = []

    def add(level: Level, code: str, message: str) -> None:
        findings.append(Finding(level, code, message, prop=spec.name))

    # --- Shader ---
    if spec.shader not in info.shaders:
        add(
            Level.ERROR,
            "shader_mismatch",
            f"Exportiert wurde {info.shaders or '[kein Shader]'}, konfiguriert war '{spec.shader}'.",
        )

    # --- LOD-Stufen ---
    expected = [lod for lod in LOD_LEVELS if lod in spec.lods.ratios]
    for lod in expected:
        if lod not in info.lods:
            add(
                Level.ERROR,
                "lod_missing_in_export",
                f"LOD '{lod}' war konfiguriert, fehlt aber im Export. "
                "Meist bedeutet das, dass die LOD-Zuweisung in Blender nicht gegriffen hat.",
            )
    for lod in info.lods:
        if lod not in expected:
            add(Level.WARNING, "lod_unexpected",
                f"Export enthaelt LOD '{lod}', das nicht konfiguriert war.")

    # --- Geometrie tatsaechlich vorhanden ---
    for lod, lod_info in info.lods.items():
        if lod_info.geometries == 0:
            add(Level.ERROR, "lod_empty_geometry",
                f"LOD '{lod}' enthaelt kein Geometrie-Element - das Modell waere unsichtbar.")

    # --- Sichtweiten ---
    for lod, lod_info in info.lods.items():
        want = spec.lods.distances.get(lod)
        if want is None:
            continue
        if abs(lod_info.distance - want) > DISTANCE_TOLERANCE:
            add(
                Level.ERROR,
                "lod_distance_mismatch",
                f"LOD '{lod}': exportiert {lod_info.distance:g} m, konfiguriert {want:g} m.",
            )

    # --- Reduktion hat gewirkt ---
    high = info.lods.get("high")
    if high is not None:
        for lod in ("medium", "low", "verylow"):
            lower = info.lods.get(lod)
            if lower is None:
                continue
            if lower.geometries > high.geometries:
                add(Level.WARNING, "lod_not_reduced",
                    f"LOD '{lod}' hat mehr Geometrien als LOD0 - Decimate hat nicht gegriffen.")

    # --- Texturen ---
    for suffix, sampler in ROLE_SAMPLERS.items():
        has_source = {
            "_d": bool(spec.textures.diffuse),
            "_n": bool(spec.textures.normal),
            "_s": bool(spec.textures.specular or spec.textures.roughness or spec.textures.metallic),
        }[suffix]
        if not has_source:
            continue
        if sampler not in info.samplers:
            add(
                Level.ERROR,
                "sampler_not_bound",
                f"{sampler} ist im Export nicht belegt, obwohl eine passende Textur konfiguriert war.",
            )

    for tex in info.textures:
        if not tex.is_power_of_two:
            add(Level.ERROR, "texture_not_pot",
                f"Textur '{tex.name}' ist {tex.width}x{tex.height} - keine Zweierpotenz.")
        if max(tex.width, tex.height) > spec.texture_size:
            add(
                Level.WARNING,
                "texture_larger_than_configured",
                f"Textur '{tex.name}' ist {tex.width}x{tex.height}, konfiguriert war {spec.texture_size}.",
            )

    # --- Kollision ---
    if spec.collision.enabled and not info.has_collision:
        add(Level.ERROR, "collision_missing",
            "Kollision war aktiviert, im Export ist aber kein Bound enthalten.")
    if not spec.collision.enabled and info.has_collision:
        add(Level.WARNING, "collision_unexpected",
            "Kollision war deaktiviert, der Export enthaelt aber einen Bound.")

    return findings


def verify(config: PipelineConfig, build_dir: Path | None = None) -> list[Finding]:
    build_dir = Path(build_dir) if build_dir else config.workdir / "build"
    findings: list[Finding] = []

    if not build_dir.is_dir():
        return [Finding(Level.ERROR, "build_dir_missing",
                        f"Build-Verzeichnis nicht gefunden: {build_dir}")]

    for spec in config.props:
        matches = list(build_dir.rglob(f"{spec.name}.ydr.xml"))
        if not matches:
            binary = list(build_dir.rglob(f"{spec.name}.ydr"))
            if binary:
                findings.append(Finding(
                    Level.INFO, "binary_export_not_inspectable",
                    f"'{spec.name}.ydr' liegt als Binaerdatei vor. Automatische Pruefung "
                    "braucht CWXML - fuer den Verifikationslauf export_format='CWXML' setzen.",
                    prop=spec.name,
                ))
            else:
                findings.append(Finding(
                    Level.ERROR, "export_missing",
                    f"Kein Export fuer '{spec.name}' in {build_dir} gefunden.",
                    prop=spec.name,
                ))
            continue

        try:
            info = parse_drawable(matches[0])
        except InspectError as exc:
            findings.append(Finding(Level.ERROR, "export_unreadable", str(exc), prop=spec.name))
            continue

        findings.extend(verify_drawable(spec, info))

    return findings
