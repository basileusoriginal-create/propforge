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
            "max_tris": self.max_tris,
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

    return PropSpec(
        name=name,
        mesh=resolve(mesh),
        textures=textures,
        shader=merged.get("shader", "normal_spec.sps"),
        lods=lods,
        collision=collision,
        texture_size=int(merged.get("texture_size", 1024)),
        max_tris=int(merged.get("max_tris", 10000)),
        flip_normal_green=bool(merged.get("flip_normal_green", True)),
    )
