"""Abgleich: hat der Build gebaut, was in der Konfiguration stand?

Die Preflight-Stufe (`validate`) prueft die Eingabe, diese Stufe die Ausgabe.
Zusammen schliessen sie die Schleife, ohne dass GTA V dafuer laufen muss.
"""

from __future__ import annotations

from pathlib import Path

from .config import LOD_LEVELS, PipelineConfig, PropSpec
from .inspect import DrawableInfo, InspectError, YtypInfo, parse_drawable, parse_ytyp
from .validate import Finding, Level

# Wie stark die exportierte Sichtweite vom Sollwert abweichen darf.
DISTANCE_TOLERANCE = 0.5

# Ab wann eine exportierte Drawable-Datei nach leerer Huelle aussieht.
#
# Ein Prop mit ein paar tausend Dreiecken und eingebetteten Texturen liegt im
# Megabyte-Bereich - egal ob binaer oder als CWXML. Wenige Kilobyte heissen:
# die Datei ist formal in Ordnung, aber es steht nichts drin. Genau diese
# Sorte Fehler kommt sonst erst im Spiel heraus, als unsichtbarer Prop.
MIN_DRAWABLE_BYTES = 8 * 1024

# Und die Gegenrichtung.
#
# Ein Prop im Dreitausend-Dreieck-Bereich mit eingebetteten 512er-Texturen
# liegt bei rund einem Megabyte. Wird daraus ein dreistelliger Megabyte-Wert,
# ist der Schreiber entgleist - RAGE-Ressourcen haben eine seitenbasierte
# Speicherstruktur, und ein falsch gewaehltes Seitenschema blaeht die Datei um
# Groessenordnungen auf, ohne dass irgendetwas fehlschlaegt. Eine solche Datei
# ist nicht "gross", sondern kaputt: kein Werkzeug laedt sie, und gepackt
# wandert sie ungefragt auf den Server.
MAX_DRAWABLE_BYTES = 64 * 1024 * 1024

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

    # --- Vertexdaten ---
    #
    # Der teuerste Fehler dieses Projekts stand genau hier und war unsichtbar:
    # die Geometrie war vollstaendig, die LOD-Stufen stimmten, die Texturen
    # waren eingebettet, die Sampler belegt - aber der Vertexpuffer trug nur
    # Position, Normal und Tangent. Ohne TexCoord0 gibt es keine
    # Texturkoordinaten, und der Prop ist im Spiel bestenfalls texturlos.
    #
    # Ursache war ein Namensunterschied ("UVMap" statt "UVMap 0"), den
    # Sollumz mit einer Logzeile quittiert. Von aussen sah alles gut aus.
    textures_bound = bool(info.samplers)
    for lod, lod_info in info.lods.items():
        if not lod_info.semantics:
            continue

        if textures_bound and "TexCoord0" not in lod_info.semantics:
            add(
                Level.ERROR,
                "vertex_texcoord_missing",
                f"LOD '{lod}': der Vertexpuffer hat kein TexCoord0, obwohl Texturen "
                f"gebunden sind. Vorhanden ist nur: {', '.join(sorted(lod_info.semantics))}. "
                "Meist heisst das, dass die UV-Map nicht 'UVMap 0' heisst.",
            )

        if "Colour0" not in lod_info.semantics:
            add(
                Level.WARNING,
                "vertex_colour_missing",
                f"LOD '{lod}': der Vertexpuffer hat kein Colour0. Die meisten "
                "GTA-V-Shader erwarten Vertexfarben; ohne sie kann die Beleuchtung "
                "falsch aussehen. Das Farb-Attribut muss 'Color 1' heissen.",
            )

        if lod_info.vertices == 0 or lod_info.indices == 0:
            add(
                Level.ERROR,
                "geometry_empty",
                f"LOD '{lod}': {lod_info.vertices} Vertices, {lod_info.indices} Indizes - "
                "die Geometrie ist leer und waere im Spiel unsichtbar.",
            )

    # --- Kollision ---
    if spec.collision.enabled and not info.has_collision:
        add(Level.ERROR, "collision_missing",
            "Kollision war aktiviert, im Export ist aber kein Bound enthalten.")
    elif spec.collision.enabled and info.bound_children == 0:
        # Der Fall, der uns durchgerutscht ist: das Composite steht in der
        # Datei, aber ohne Kinder. Sollumz verwirft ein Bound-Mesh ohne
        # Kollisionsmaterial stillschweigend und schreibt die leere Huelle.
        add(Level.ERROR, "collision_composite_empty",
            "Das Bound Composite hat keine Kind-Bounds - eine leere Huelle. "
            "Die Datei enthaelt einen Kollisionsblock, im Spiel laeuft man "
            "hindurch. Meist fehlt der Kollisionsgeometrie ein "
            "Kollisionsmaterial.")
    if not spec.collision.enabled and info.has_collision:
        add(Level.WARNING, "collision_unexpected",
            "Kollision war deaktiviert, der Export enthaelt aber einen Bound.")

    return findings


def verify_ytyp(spec: PropSpec, info: YtypInfo, drawable: DrawableInfo | None) -> list[Finding]:
    """Prueft die Archetyp-Definition gegen die Konfiguration.

    Der teuerste Fehler dieser Stufe ist der leiseste: eine .ytyp, die einen
    Archetyp mit falschem `assetName` enthaelt. Die Datei ist gueltig, der
    Export meldet Erfolg, und im Spiel passiert schlicht nichts.
    """
    findings: list[Finding] = []

    def add(level: Level, code: str, message: str) -> None:
        findings.append(Finding(level, code, message, prop=spec.name))

    match = [a for a in info.archetypes if a.name.lower() == spec.name.lower()]
    if not match:
        names = ", ".join(a.name for a in info.archetypes) or "(keine)"
        add(Level.ERROR, "archetype_missing",
            f"Die ytyp enthaelt keinen Archetyp '{spec.name}'. Enthalten: {names}.")
        return findings

    archetype = match[0]

    if archetype.asset_name.lower() != spec.name.lower():
        add(Level.ERROR, "archetype_asset_mismatch",
            f"Archetyp '{archetype.name}' verweist auf assetName "
            f"'{archetype.asset_name}', die exportierte Datei heisst aber "
            f"'{spec.name}.ydr'. Das Spiel wuerde den Prop nicht finden.")

    if "drawable" not in archetype.asset_type.lower():
        add(Level.ERROR, "archetype_asset_type",
            f"assetType ist '{archetype.asset_type}', erwartet wurde ein Drawable.")

    want_dist = spec.archetype_lod_dist()
    if abs(archetype.lod_dist - want_dist) > DISTANCE_TOLERANCE:
        add(Level.ERROR, "archetype_lod_dist",
            f"lodDist ist {archetype.lod_dist:g} m, konfiguriert waren {want_dist:g} m.")

    # Der Archetyp darf nicht frueher ausblenden als die groesste
    # LOD-Sichtweite: sonst ist Geometrie exportiert, die nie zu sehen ist.
    furthest = max(spec.lods.distances.values(), default=0.0)
    if archetype.lod_dist + DISTANCE_TOLERANCE < furthest:
        add(Level.WARNING, "archetype_lod_dist_below_lods",
            f"lodDist ({archetype.lod_dist:g} m) liegt unter der groessten "
            f"LOD-Sichtweite ({furthest:g} m) - die aeusserste LOD-Stufe "
            "wird nie sichtbar.")

    if archetype.flags != spec.ytyp.flags:
        add(Level.WARNING, "archetype_flags",
            f"flags sind {archetype.flags}, konfiguriert waren {spec.ytyp.flags}.")

    # Kollision: eingebettet heisst physicsDictionary == Propname.
    if spec.collision.enabled and archetype.physics_dictionary.lower() != spec.name.lower():
        add(Level.ERROR, "archetype_physics_dictionary",
            f"Kollision ist aktiviert, physicsDictionary ist aber "
            f"'{archetype.physics_dictionary}' statt '{spec.name}'. "
            "Der Prop haette im Spiel keine Kollision.")
    if not spec.collision.enabled and archetype.physics_dictionary:
        add(Level.WARNING, "archetype_physics_unexpected",
            f"physicsDictionary ist '{archetype.physics_dictionary}', obwohl "
            "keine Kollision gebaut wurde - das Spiel sucht eine .ybn, die es "
            "nicht gibt.")

    # Texturen liegen eingebettet in der .ydr. Ein Verweis auf eine .ytd waere
    # ins Leere gerichtet.
    if spec.ytyp.texture_dictionary is None and drawable is not None:
        if drawable.textures and archetype.texture_dictionary:
            add(Level.WARNING, "archetype_texture_dictionary",
                f"textureDictionary ist '{archetype.texture_dictionary}', die "
                "Texturen liegen aber eingebettet in der .ydr.")

    return findings


def verify(config: PipelineConfig, build_dir: Path | None = None) -> list[Finding]:
    build_dir = Path(build_dir) if build_dir else config.workdir / "build"
    findings: list[Finding] = []

    if not build_dir.is_dir():
        return [Finding(Level.ERROR, "build_dir_missing",
                        f"Build-Verzeichnis nicht gefunden: {build_dir}")]

    for spec in config.props:
        matches = list(build_dir.rglob(f"{spec.name}.ydr.xml"))
        info: DrawableInfo | None = None
        if not matches:
            binary = list(build_dir.rglob(f"{spec.name}.ydr"))
            if binary:
                findings.extend(_verify_size(spec, binary[0]))
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
        else:
            findings.extend(_verify_size(spec, matches[0]))
            try:
                info = parse_drawable(matches[0])
            except InspectError as exc:
                findings.append(
                    Finding(Level.ERROR, "export_unreadable", str(exc), prop=spec.name))
            else:
                findings.extend(verify_drawable(spec, info))

        findings.extend(_verify_ytyp_file(spec, build_dir, info))

    return findings


def _verify_size(spec: PropSpec, path: Path) -> list[Finding]:
    """Groessenpruefung der exportierten Drawable-Datei.

    Die inhaltliche Pruefung zaehlt Elemente - Geometrien, LOD-Stufen, Sampler.
    Sie sagt nichts darueber, ob in diesen Elementen auch Vertexdaten stehen.
    Eine Datei von wenigen Kilobyte kann jede Strukturpruefung bestehen und im
    Spiel trotzdem unsichtbar sein. Die Groesse deckt genau diese Luecke ab,
    ohne dass das Binaerformat geparst werden muss.
    """
    size = path.stat().st_size

    if size > MAX_DRAWABLE_BYTES:
        return [Finding(
            Level.ERROR, "drawable_implausibly_large",
            f"'{path.name}' ist {size / (1024 * 1024):.0f} MB gross. Fuer "
            f"{spec.max_tris} Dreiecke mit {spec.texture_size}er-Texturen sind "
            "das Groessenordnungen zu viel - die Datei ist nicht gross, sondern "
            "kaputt. Kein Werkzeug wird sie laden.",
            prop=spec.name,
        )]

    if size < MIN_DRAWABLE_BYTES:
        return [Finding(
            Level.WARNING, "drawable_suspiciously_small",
            f"'{path.name}' ist nur {size} Bytes gross. Ein Prop mit Geometrie und "
            f"eingebetteten Texturen liegt weit darueber - das sieht nach einer "
            "leeren Huelle aus, die im Spiel unsichtbar waere.",
            prop=spec.name,
        )]

    return []


def _verify_ytyp_file(
    spec: PropSpec,
    build_dir: Path,
    drawable: DrawableInfo | None,
) -> list[Finding]:
    """Sucht die .ytyp zum Prop und prueft sie, soweit sie lesbar ist."""
    if not spec.ytyp.enabled:
        return []

    name = spec.ytyp_name()
    matches = list(build_dir.rglob(f"{name}.ytyp.xml"))
    if matches:
        try:
            return verify_ytyp(spec, parse_ytyp(matches[0]), drawable)
        except InspectError as exc:
            return [Finding(Level.ERROR, "ytyp_unreadable", str(exc), prop=spec.name)]

    if list(build_dir.rglob(f"{name}.ytyp")):
        return [Finding(
            Level.INFO, "binary_ytyp_not_inspectable",
            f"'{name}.ytyp' liegt als Binaerdatei vor und ist nicht automatisch pruefbar.",
            prop=spec.name,
        )]

    return [Finding(
        Level.ERROR, "ytyp_missing",
        f"Keine .ytyp fuer '{spec.name}' gefunden (erwartet: {name}.ytyp). "
        "Ohne Archetyp-Definition ist der Prop im Spiel nicht spawnbar.",
        prop=spec.name,
    )]
