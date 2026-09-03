"""Konfigurationsmodell der Prop-Pipeline.

Ein `pipeline.toml` beschreibt globale Defaults plus eine Liste von Props.
Jeder Prop ist eine in sich geschlossene Job-Beschreibung, die als JSON an die
Blender-Stufe weitergereicht wird.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# GTA V akzeptiert nur Zweierpotenzen als Texturkantenlaenge.
# 2048 ist laut Sollumz-FAQ die empfohlene Obergrenze fuer Props.
VALID_TEXTURE_SIZES = (16, 32, 64, 128, 256, 512, 1024, 2048)

# Sollumz-LOD-Stufen, die fuer statische Props relevant sind.
# (VERYHIGH bleibt Fragments/Vehicles vorbehalten.)
LOD_LEVELS = ("high", "medium", "low", "verylow")


class ConfigError(ValueError):
    """Fehlerhafte oder unvollstaendige Pipeline-Konfiguration."""


@dataclass
class TextureSet:
    """Rohtexturen, wie sie ein Generator (Meshy, Tripo, Rodin) ausgibt."""

    diffuse: str
    normal: str | None = None
    roughness: str | None = None
    metallic: str | None = None
    # Fertig gebauter Specular-Kanal; falls gesetzt, wird nicht aus roughness abgeleitet.
    specular: str | None = None

    def present(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v}


@dataclass
class LodSettings:
    """Decimate-Verhaeltnisse und Sichtweiten je LOD-Stufe.

    `ratios` sind Anteile der LOD0-Dreiecke (1.0 = unveraendert).
    `distances` sind die GTA-Sichtweiten in Metern und muessen aufsteigend sein.
    """

    ratios: dict[str, float] = field(
        default_factory=lambda: {"high": 1.0, "medium": 0.5, "low": 0.22, "verylow": 0.08}
    )
    distances: dict[str, float] = field(
        default_factory=lambda: {"high": 60.0, "medium": 120.0, "low": 250.0, "verylow": 500.0}
    )

    def ordered_ratios(self) -> list[tuple[str, float]]:
        return [(lod, self.ratios[lod]) for lod in LOD_LEVELS if lod in self.ratios]


@dataclass
class CollisionSettings:
    """Einstellungen fuer die eingebettete Kollision (YBN / Bound Composite)."""

    enabled: bool = True
    # "bvh"  -> BOUND_GEOMETRYBVH, exakte Dreieckskollision, Standard fuer Props
    # "box"  -> BOUND_BOX, billigste Variante fuer Kisten/Container
    # "hull" -> konvexe Huelle, guter Kompromiss fuer organische Formen
    kind: str = "bvh"
    flag_preset: str = "Default"
    # Aus welcher LOD-Stufe die Kollision abgeleitet wird. "low" haelt die
    # Kollisionsgeometrie guenstig, ohne die Silhouette zu verlieren.
    source_lod: str = "low"


# Archetyp-Flag 6 ("Static") - Bit 5, also 32. Der uebliche Wert fuer einen
# statischen Prop und die Vorgabe verbreiteter ytyp-Generatoren.
ARCHETYPE_FLAG_STATIC = 32


@dataclass
class YtypSettings:
    """Archetyp-Definition, die den Prop im Spiel ueberhaupt erst spawnbar macht.

    Eine .ydr ist nur Geometrie. Erst der Archetyp in einer .ytyp gibt ihr
    einen Namen, unter dem sie in einer .ymap oder per Script referenziert
    werden kann.
    """

    enabled: bool = True
    # Name der ytyp selbst. Leer = "<prop>_ityp".
    #
    # Bewusst nicht gleich dem Archetypnamen: die ytyp und die Archetypen
    # darin sind zwei getrennte Namensraeume, und Rockstar haelt sie ebenfalls
    # auseinander. Gleiche Namen sind schwer zu lesen und bei Kollisionen im
    # Serverbetrieb schwer zu finden.
    name: str | None = None
    # Entfernung, ab der das Spiel den Prop nicht mehr laedt. `None` leitet
    # den Wert aus der groessten LOD-Sichtweite ab - alles andere waere
    # widerspruechlich: Geometrie fuer 500 m, aber Ausblenden bei 200 m.
    lod_dist: float | None = None
    hd_texture_dist: float = 100.0
    flags: int = ARCHETYPE_FLAG_STATIC
    # Name der .ytd. `None` = automatisch: leer bei eingebetteten Texturen
    # (die liegen in der .ydr), sonst der Propname.
    texture_dictionary: str | None = None


@dataclass
class PropSpec:
    """Eine vollstaendige Prop-Definition."""

    name: str
    mesh: str
    textures: TextureSet
    shader: str = "normal_spec.sps"
    lods: LodSettings = field(default_factory=LodSettings)
    collision: CollisionSettings = field(default_factory=CollisionSettings)
    texture_size: int = 1024
    # Maximale Dreiecke auf LOD0 nach dem Aufraeumen des generierten Meshes.
    max_tris: int = 10000
    # Normalmap-Konvention: AI-Generatoren liefern meist OpenGL (Y+),
    # GTA V erwartet DirectX (Y-).
    flip_normal_green: bool = True
    # Welche Achse im Quellmesh nach oben zeigt.
    #
    # Das ist keine Kosmetik: ein falsch orientierter Prop steht im Spiel auf
    # der Seite, und kein Test merkt es -- die Datei ist ja formal korrekt.
    # "y" ist die uebliche Konvention fuer OBJ und glTF und damit das, was
    # Meshy, Tripo und Rodin liefern. "z" ist Blender-Konvention.
    source_up: str = "y"
    # Wohin der Ursprung gelegt wird.
    #
    # Marktplatz- und Generator-Assets sind selten am Ursprung modelliert. Ein
    # Prop mit Mittelpunkt bei (1.07, -0.16, -0.60) steht im Spiel einen Meter
    # neben der Stelle, an die man ihn setzt.
    #
    #   "none"  unveraendert lassen
    #   "xy"    in X und Y zentrieren, Hoehe unangetastet
    #   "base"  in X und Y zentrieren, Unterkante auf Z=0 (Standardfall fuer
    #           Props, die auf dem Boden stehen)
    #   "all"   in allen drei Achsen zentrieren
    center: str = "none"
    ytyp: YtypSettings = field(default_factory=YtypSettings)

    def ytyp_name(self) -> str:
        return self.ytyp.name or f"{self.name}_ityp"

    def archetype_lod_dist(self) -> float:
        """Sichtweite des Archetyps - abgeleitet, wenn nicht gesetzt."""
        if self.ytyp.lod_dist is not None:
            return float(self.ytyp.lod_dist)
        return float(max(self.lods.distances.values(), default=500.0))

    def to_job(self, workdir: Path) -> dict[str, Any]:
        """Serialisiert den Prop als Job-Dict fuer die Blender-Stufe."""
        return {
            "name": self.name,
            "mesh": str(Path(self.mesh).resolve()),
            "shader": self.shader,
            "texture_dir": str((workdir / "textures" / self.name).resolve()),
            "output_dir": str((workdir / "build" / self.name).resolve()),
            "lod_ratios": dict(self.lods.ordered_ratios()),
            "lod_distances": self.lods.distances,
            "collision": asdict(self.collision),
            "source_up": self.source_up,
            "center": self.center,
            "max_tris": self.max_tris,
            "ytyp": {
                "enabled": self.ytyp.enabled,
                "name": self.ytyp_name(),
                "lod_dist": self.archetype_lod_dist(),
                "hd_texture_dist": self.ytyp.hd_texture_dist,
                "flags": self.ytyp.flags,
                "texture_dictionary": self.ytyp.texture_dictionary,
            },
        }


@dataclass
class PipelineConfig:
    resource_name: str
    author: str
    workdir: Path
    props: list[PropSpec]
    # Exportziel von Sollumz: "NATIVE" schreibt direkt Binaerdateien
    # (benoetigt PyMateria, nur Windows), "CWXML" schreibt CodeWalker-XML.
    export_format: str = "NATIVE"
    # "GEN8" = klassisches GTA V, "GEN9" = Enhanced-Release.
    export_version: str = "GEN8"

    @staticmethod
    def load(path: str | Path) -> "PipelineConfig":
        path = Path(path)
        if not path.is_file():
            raise ConfigError(f"Konfigurationsdatei nicht gefunden: {path}")
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        return PipelineConfig.from_dict(raw, base=path.parent)

    @staticmethod
    def from_dict(raw: dict[str, Any], base: Path = Path(".")) -> "PipelineConfig":
        try:
            pipeline = raw["pipeline"]
        except KeyError as exc:
            raise ConfigError("Abschnitt [pipeline] fehlt.") from exc

        defaults = raw.get("defaults", {})
        props_raw = raw.get("prop", [])
        if not props_raw:
            raise ConfigError("Keine [[prop]]-Eintraege gefunden.")

        props = [_prop_from_dict(p, defaults, base) for p in props_raw]

        return PipelineConfig(
            resource_name=pipeline["resource_name"],
            author=pipeline.get("author", "unknown"),
            workdir=(base / pipeline.get("workdir", "out")).resolve(),
            props=props,
            export_format=pipeline.get("export_format", "NATIVE").upper(),
            export_version=pipeline.get("export_version", "GEN8").upper(),
        )


def _prop_from_dict(raw: dict[str, Any], defaults: dict[str, Any], base: Path) -> PropSpec:
    merged: dict[str, Any] = {**defaults, **raw}

    try:
        name = merged["name"]
        mesh = merged["mesh"]
        tex_raw = merged["textures"]
    except KeyError as exc:
        raise ConfigError(f"Prop-Eintrag unvollstaendig, fehlender Schluessel: {exc}") from exc

    def resolve(value: str) -> str:
        p = Path(value)
        return str(p if p.is_absolute() else (base / p))

    textures = TextureSet(
        diffuse=resolve(tex_raw["diffuse"]),
        normal=resolve(tex_raw["normal"]) if tex_raw.get("normal") else None,
        roughness=resolve(tex_raw["roughness"]) if tex_raw.get("roughness") else None,
        metallic=resolve(tex_raw["metallic"]) if tex_raw.get("metallic") else None,
        specular=resolve(tex_raw["specular"]) if tex_raw.get("specular") else None,
    )

    lod_raw = merged.get("lods", {})
    lods = LodSettings(
        ratios=lod_raw.get("ratios", LodSettings().ratios),
        distances=lod_raw.get("distances", LodSettings().distances),
    )

    col_raw = merged.get("collision", {})
    collision = CollisionSettings(
        enabled=col_raw.get("enabled", True),
        kind=col_raw.get("kind", "bvh"),
        flag_preset=col_raw.get("flag_preset", "Default"),
        source_lod=col_raw.get("source_lod", "low"),
    )

    ytyp_raw = merged.get("ytyp", {})
    ytyp = YtypSettings(
        enabled=bool(ytyp_raw.get("enabled", True)),
        name=ytyp_raw.get("name") or None,
        lod_dist=float(ytyp_raw["lod_dist"]) if ytyp_raw.get("lod_dist") is not None else None,
        hd_texture_dist=float(ytyp_raw.get("hd_texture_dist", 100.0)),
        flags=int(ytyp_raw.get("flags", ARCHETYPE_FLAG_STATIC)),
        texture_dictionary=ytyp_raw.get("texture_dictionary"),
    )

    return PropSpec(
        name=name,
        mesh=resolve(mesh),
        textures=textures,
        shader=merged.get("shader", "normal_spec.sps"),
        lods=lods,
        collision=collision,
        ytyp=ytyp,
        texture_size=int(merged.get("texture_size", 1024)),
        max_tris=int(merged.get("max_tris", 10000)),
        flip_normal_green=bool(merged.get("flip_normal_green", True)),
        source_up=str(merged.get("source_up", "y")).lower(),
        center=str(merged.get("center", "none")).lower(),
    )
