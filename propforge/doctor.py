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
    """Fuehrt ein Snippet in Blenders eigenem Python aus und gibt stdout zurueck."""
    try:
        out = subprocess.run(
            [exe, "--background", "--factory-startup", "--python-expr", code],
            capture_output=True, text=True, timeout=180,
        )
    except (OSError, subprocess.SubprocessError):
        return None
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
    probe = (
        "import sys;"
        "mods = [];"
        "\nfor name in ('sollumz', 'bl_ext.user_default.sollumz'):\n"
        "    try:\n"
        "        __import__(name); mods.append(name)\n"
        "    except Exception: pass\n"
        "print('SOLLUMZ=' + (mods[0] if mods else 'NONE'))\n"
        "for dep in ('szio', 'pymateria'):\n"
        "    try:\n"
        "        __import__(dep); print(dep.upper() + '=YES')\n"
        "    except Exception: print(dep.upper() + '=NO')\n"
    )
    out = _blender_python(exe, probe)
    if out is None:
        checks.append(Check("Sollumz", None, "Pruefung fehlgeschlagen"))
        return checks

    sollumz = next((l.split("=", 1)[1] for l in out.splitlines() if l.startswith("SOLLUMZ=")), "NONE")
    checks.append(Check(
        "Sollumz", sollumz != "NONE",
        f"importierbar als '{sollumz}'" if sollumz != "NONE"
        else "nicht gefunden - Add-on installieren und aktivieren",
    ))

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

    # --- texconv ---
    tc = texconv or shutil.which("texconv") or shutil.which("texconv.exe")
    checks.append(Check(
        "texconv", tc is not None,
        tc if tc else "fehlt - DDS-Schritt wird uebersprungen (DirectXTex installieren)",
        required=False,
    ))

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
