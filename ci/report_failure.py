"""Schreibt den Fehlschlag als GitHub-Annotation.

Hintergrund: die Schritt-Logs und die Job-Zusammenfassung eines Laufs sind nur
fuer eingeloggte Nutzer sichtbar. **Annotations dagegen rendert GitHub auch
anonym** auf der Run-Seite. Sie sind damit der einzige Kanal, ueber den ein
Fehlschlag von aussen diagnostizierbar ist, ohne dass jemand Screenshots macht.

Aufruf im Workflow:

    python ci/report_failure.py ci-build.log "Pipeline (Linux, CWXML)"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# GitHub kappt Annotations bei rund 4 KB. Lieber selbst kuerzen als abgeschnitten
# werden - der Anfang eines Tracebacks ist weniger wert als sein Ende.
MAX_CHARS = 3500
MAX_LINES = 60

# Zeilen, die im Log nur Rauschen sind.
NOISE = (
    "Blender quit",
    "found bundled python",
    "Read prefs:",
    "Warning: This script was written for",
)


def interesting(lines: list[str]) -> list[str]:
    kept = [l for l in lines if not any(n in l for n in NOISE)]
    return kept or lines


def encode(text: str) -> str:
    """GitHub-Annotation-Escaping: Zeilenumbrueche und Prozentzeichen."""
    return (
        text.replace("%", "%25")
        .replace("\r", "")
        .replace("\n", "%0A")
    )


def main(argv: list[str]) -> int:
    log_path = Path(argv[1]) if len(argv) > 1 else Path("ci-build.log")
    title = argv[2] if len(argv) > 2 else "PropForge"

    if not log_path.is_file():
        print(f"::error title={title}::Kein Log unter {log_path} - der Fehler trat vor "
              "dem ersten protokollierten Schritt auf.")
        return 0

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = interesting(lines)[-MAX_LINES:]
    body = "\n".join(tail)

    if len(body) > MAX_CHARS:
        body = "[...gekuerzt...]\n" + body[-MAX_CHARS:]

    print(f"::error title={title} fehlgeschlagen::{encode(body)}")

    # Zusaetzlich in die Zusammenfassung, dort ohne Laengenlimit.
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"## {title} fehlgeschlagen\n\n```\n")
            fh.write("\n".join(lines[-300:]))
            fh.write("\n```\n")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
