"""Arbeitsablauf ueber Ordner statt ueber handgeschriebene Konfiguration.

Der Ablauf hat zwei Schritte, und dazwischen liegt ein Ordner:

    generate  ->  eingang/    <- hier landen GLBs, erzeugt oder selbst abgelegt
    convert   ->  ausgabe/    <- .ydr, .ytyp, fertige Resource
                  fertig/     <- die verarbeiteten GLBs wandern hierher

Der Sinn des Ordners in der Mitte: beide Schritte sind unabhaengig
benutzbar. Wer nicht generieren will, kopiert seine GLBs selbst in den
Eingang - `convert` sieht keinen Unterschied. Und wer zehn Sachen erzeugt
hat, konvertiert sie in einem Rutsch.

Neben jedem GLB liegt eine kleine Begleitdatei `<name>.job.json` mit allem,
was die Umwandlung wissen muss: Groessenklasse, Kollisionsmaterial, und
spaeter der ytd-Name. Damit muss niemand eine pipeline.toml von Hand
pflegen - die Konfiguration entsteht beim Konvertieren aus den
Begleitdateien.

Das ist zugleich die Schnittstelle fuer eine spaetere Oberflaeche: die
schreibt dieselben Begleitdateien und ruft dieselben zwei Schritte auf.
"""

from __future__ import annotations

import json
import shutil
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_PROFILE,
    PROFILES,
    CollisionSettings,
    PipelineConfig,
    PropSpec,
    TextureSet,
)

WORKSPACE_FILE = "propforge.toml"
JOB_SUFFIX = ".job.json"

DEFAULT_PATHS = {
    "inbox": "work/eingang",
    "done": "work/fertig",
    "out": "work/ausgabe",
}


@dataclass
class Job:
    """Ein Asset auf dem Weg durch die Kette."""

    name: str
    mesh: Path
    profile: str = DEFAULT_PROFILE
    material: str = "DEFAULT"
    # Herkunft, rein informativ - aber Gold wert, wenn ein Ergebnis
    # ueberrascht und man wissen will, welcher Prompt es erzeugt hat.
    prompt: str | None = None
    model: str | None = None
    source_up: str = "y"
    center: str = "none"
    # Vorgemerkt fuer die ytd-Produktion: ist ein Name gesetzt, sollen die
    # Texturen spaeter nicht eingebettet, sondern separat ausgegeben werden.
    ytd: str | None = None
    created: str | None = None
    textures: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "name": self.name,
            "profile": self.profile,
            "material": self.material,
            "source_up": self.source_up,
            "center": self.center,
            "textures": self.textures,
            "created": self.created or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        for optional in ("prompt", "model", "ytd"):
            value = getattr(self, optional)
            if value:
                data[optional] = value
        return data

    def write(self) -> Path:
        path = sidecar_for(self.mesh)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def to_spec(self) -> PropSpec:
        """Baut die Prop-Definition, die die Pipeline erwartet.

        Der Umweg ueber eine Datei entfaellt: die Konfiguration entsteht im
        Speicher aus der Begleitdatei.
        """
        roles = {k: str(Path(v)) for k, v in self.textures.items() if v}
        return PropSpec(
            name=self.name,
            mesh=str(self.mesh),
            textures=TextureSet(
                diffuse=roles.get("diffuse", ""),
                normal=roles.get("normal"),
                roughness=roles.get("roughness"),
                metallic=roles.get("metallic"),
                specular=roles.get("specular"),
            ),
            profile=self.profile if self.profile in PROFILES else DEFAULT_PROFILE,
            collision=CollisionSettings(material=self.material),
            source_up=self.source_up,
            center=self.center,
            max_tris=PROFILES.get(self.profile, PROFILES[DEFAULT_PROFILE]).max_tris,
            texture_size=PROFILES.get(self.profile, PROFILES[DEFAULT_PROFILE]).texture_size,
            lods=_lods_for(self.profile),
        )


def _lods_for(profile_name: str):
    from .config import LodSettings

    profile = PROFILES.get(profile_name, PROFILES[DEFAULT_PROFILE])
    return LodSettings(distances=dict(profile.distances))


def sidecar_for(mesh: Path) -> Path:
    """Pfad der Begleitdatei zu einem Mesh: modell.glb -> modell.job.json."""
    return mesh.with_name(mesh.stem + JOB_SUFFIX)


def read_job(mesh: Path) -> Job:
    """Liest die Begleitdatei. Fehlt sie, gilt das Mesh trotzdem als Auftrag.

    Wer ein GLB einfach in den Eingang kopiert, soll nicht erst eine
    JSON-Datei schreiben muessen. Dann greifen die Vorgaben, und die
    Groessenklasse wird beim Konvertieren geschaetzt.
    """
    path = sidecar_for(mesh)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} ist kein gueltiges JSON: {exc}") from exc

    return Job(
        name=str(data.get("name") or mesh.stem),
        mesh=mesh,
        profile=str(data.get("profile") or DEFAULT_PROFILE),
        material=str(data.get("material") or "DEFAULT").upper(),
        prompt=data.get("prompt"),
        model=data.get("model"),
        source_up=str(data.get("source_up") or "y"),
        center=str(data.get("center") or "none"),
        ytd=data.get("ytd"),
        created=data.get("created"),
        textures=dict(data.get("textures") or {}),
    )


@dataclass
class Workspace:
    root: Path
    inbox: Path
    done: Path
    out: Path
    resource_name: str = "propforge_props"
    author: str = "PropForge"
    blender: str | None = None

    @staticmethod
    def load(root: str | Path = ".") -> "Workspace":
        root = Path(root).resolve()
        raw: dict[str, Any] = {}
        config = root / WORKSPACE_FILE
        if config.is_file():
            with config.open("rb") as fh:
                raw = tomllib.load(fh).get("workspace", {})

        def path_for(key: str) -> Path:
            return (root / str(raw.get(key, DEFAULT_PATHS[key]))).resolve()

        return Workspace(
            root=root,
            inbox=path_for("inbox"),
            done=path_for("done"),
            out=path_for("out"),
            resource_name=str(raw.get("resource_name", "propforge_props")),
            author=str(raw.get("author", "PropForge")),
            blender=raw.get("blender"),
        )

    def ensure(self) -> None:
        for folder in (self.inbox, self.done, self.out):
            folder.mkdir(parents=True, exist_ok=True)

    def meshes(self) -> list[Path]:
        """Alle wartenden Meshes im Eingang, in stabiler Reihenfolge."""
        if not self.inbox.is_dir():
            return []
        return sorted(
            p for p in self.inbox.iterdir()
            if p.is_file() and p.suffix.lower() in {".glb", ".gltf", ".obj", ".fbx"}
        )

    def jobs(self) -> list[Job]:
        return [read_job(mesh) for mesh in self.meshes()]

    def to_config(self, jobs: list[Job], export_format: str = "NATIVE") -> PipelineConfig:
        return PipelineConfig(
            resource_name=self.resource_name,
            author=self.author,
            workdir=self.out,
            props=[job.to_spec() for job in jobs],
            export_format=export_format,
        )

    def archive(self, job: Job) -> Path:
        """Schiebt Mesh und Begleitdatei nach 'fertig'.

        Erst nach erfolgreicher Umwandlung: ein fehlgeschlagenes Asset bleibt
        im Eingang liegen, damit der naechste Lauf es erneut versucht und man
        es nicht in einem Archivordner suchen muss.
        """
        self.done.mkdir(parents=True, exist_ok=True)
        target = _free_name(self.done / job.mesh.name)
        shutil.move(str(job.mesh), target)

        side = sidecar_for(job.mesh)
        if side.is_file():
            shutil.move(str(side), _free_name(self.done / side.name))
        return target

    def render_config(self) -> str:
        """Vorlage fuer die propforge.toml."""
        return (
            "# Arbeitsordner der lokalen Routine.\n"
            "#\n"
            "#   eingang  GLBs, die noch umgewandelt werden muessen\n"
            "#   fertig   verarbeitete GLBs samt Begleitdatei\n"
            "#   ausgabe  .ydr, .ytyp und die fertige FiveM-Resource\n"
            "\n"
            "[workspace]\n"
            f'inbox = "{DEFAULT_PATHS["inbox"]}"\n'
            f'done = "{DEFAULT_PATHS["done"]}"\n'
            f'out = "{DEFAULT_PATHS["out"]}"\n'
            f'resource_name = "{self.resource_name}"\n'
            f'author = "{self.author}"\n'
            "# Pfad zur Blender-Binary, damit --blender nicht jedes Mal noetig ist.\n"
            '# blender = "C:\\\\Program Files\\\\Blender Foundation\\\\Blender 4.5\\\\blender.exe"\n'
        )


def _free_name(target: Path) -> Path:
    """Verhindert, dass ein zweiter Durchlauf eine aeltere Fassung ueberschreibt."""
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    for index in range(2, 1000):
        candidate = target.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Zu viele Fassungen von {target.name} in {target.parent}.")
