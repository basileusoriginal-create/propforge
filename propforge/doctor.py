"""Umgebungspruefung: was fehlt, bevor ein Build ueberhaupt starten kann.

Die Blender-Stufe scheitert sonst mit Meldungen, die schwer zuzuordnen sind -
ein fehlendes szio sieht aus wie ein kaputtes Add-on, eine fehlende
PyMateria-Installation wie ein Exportfehler.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import sollumz_env


@dataclass
class Check:
    name: str
    ok: bool | None          # None = nicht ermittelbar
    detail: str
    required: bool = True

    def render(self) -> str:
        mark = {True: "ok  ", False: "FEHLT", None: "?   "}[self.ok]
        tag = "" if self.required else "  (optional)"
        return f"[{mark}] {self.name:<22} {self.detail}{tag}"


def _blender_version(exe: str) -> str | None:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    first = out.stdout.strip().splitlines()
    return first[0].strip() if first else None


def _blender_python(exe: str, code: str) -> str | None:
    """Fuehrt ein Snippet in Blenders eigenem Python aus und gibt stdout zurueck.

    Der Code wird in eine temporaere Datei geschrieben und mit ``--python``
    ausgefuehrt, nicht mit ``--python-expr``. Mehrzeiliger Code ueber
    ``--python-expr`` durch Shell und YAML zu schleusen ist eine
    Fehlerquelle, die man sich sparen kann.

    Wichtig: **ohne** ``--factory-startup``, denn die aktivierten Add-ons und
    ihre Abhaengigkeiten werden erst beim normalen Start gemountet.
    """
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
        fh.write(code)
        script = fh.name

    try:
        out = subprocess.run(
            [exe, "--background", "--python", script],
            capture_output=True, text=True, timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        Path(script).unlink(missing_ok=True)

    return out.stdout


def run(blender: str | None = None, texconv: str | None = None) -> list[Check]:
    checks: list[Check] = []
    system = platform.system()

    checks.append(Check("Betriebssystem", True, f"{system} {platform.machine()}", required=False))

    # --- Python-Abhaengigkeiten ---
    for mod, label in [("PIL", "Pillow"), ("numpy", "numpy")]:
        try:
            __import__(mod)
            checks.append(Check(label, True, "importierbar"))
        except ImportError:
            checks.append(Check(label, False, f"pip install {label.lower()}"))

    # --- Blender ---
    exe = blender or shutil.which("blender") or shutil.which("blender.exe")
    if exe is None:
        checks.append(Check("Blender", False, "nicht im PATH - mit --blender angeben"))
        return checks

    version = _blender_version(exe)
    if version is None:
        checks.append(Check("Blender", False, f"'{exe}' nicht ausfuehrbar"))
        return checks

    ok_version = _version_at_least(version, (4, 2))
    checks.append(Check(
        "Blender", ok_version, f"{version} ({exe})" + ("" if ok_version else " - benoetigt 4.2+"),
    ))

    # --- Sollumz und seine Abhaengigkeiten in Blenders Python ---
    # Die Kandidatenliste kommt aus sollumz_env, damit Pruefung und
    # Build-Stufe nicht auseinanderlaufen koennen.
    out = _blender_python(exe, sollumz_env.probe_source())
    if out is None:
        checks.append(Check("Sollumz", None, "Pruefung fehlgeschlagen"))
        return checks

    sollumz = next((l.split("=", 1)[1] for l in out.splitlines() if l.startswith("SOLLUMZ=")), "NONE")
    if sollumz != "NONE":
        detail = f"importierbar als '{sollumz}'"
    else:
        # Ohne Rohausgabe ist ein CI-Fehlschlag hier kaum zuzuordnen.
        tried = ", ".join(sollumz_env.MODULE_CANDIDATES)
        detail = (
            f"unter keinem dieser Namen gefunden: {tried}"
            " - Add-on installieren und aktivieren"
        )
    checks.append(Check("Sollumz", sollumz != "NONE", detail))

    szio = "SZIO=YES" in out
    checks.append(Check(
        "szio", szio,
        "vorhanden" if szio else "fehlt - in den Sollumz-Preferences installieren",
    ))

    pymateria = "PYMATERIA=YES" in out
    checks.append(Check(
        "PyMateria", pymateria,
        "vorhanden - NATIVE-Export moeglich" if pymateria
        else ("fehlt - nur CWXML-Export moeglich" if system == "Windows"
              else "nicht verfuegbar auf diesem System - CWXML verwenden"),
        required=False,
    ))

    # --- DDS-Konverter ---
    from .textures import find_dds_converter

    converter = find_dds_converter(texconv)
    if converter is None:
        detail = "keiner gefunden - texconv (DirectXTex) oder ImageMagick installieren"
    else:
        kind, path = converter
        note = "" if kind == "texconv" else " - nur DXT1/DXT5, fuer Props ausreichend"
        detail = f"{kind}: {path}{note}"
    checks.append(Check("DDS-Konverter", converter is not None, detail, required=False))

    return checks


def _version_at_least(version_string: str, minimum: tuple[int, int]) -> bool:
    import re
    match = re.search(r"(\d+)\.(\d+)", version_string)
    if not match:
        return False
    return (int(match.group(1)), int(match.group(2))) >= minimum


def summarize(checks: list[Check]) -> tuple[str, bool]:
    lines = [c.render() for c in checks]
    blocking = [c for c in checks if c.required and c.ok is False]
    if blocking:
        lines.append("")
        lines.append(f"{len(blocking)} blockierende(s) Problem(e) - Build wuerde scheitern.")
    else:
        lines.append("")
        lines.append("Umgebung ist buildfaehig.")
    return "\n".join(lines), not blocking
