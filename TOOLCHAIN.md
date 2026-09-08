# Geprüfte Toolchain – PropForge 0.2.0

Stand 08.09.2026. Maschinenlesbare Werte und SHA256 stehen in
[toolchain.lock.json](toolchain.lock.json).

| Bestandteil | Tatsächlich geprüft |
| --- | --- |
| Host | Windows, nativer GEN8-Export |
| CLI-Python | 3.12.14; CI verwendet 3.11 |
| Blender | 4.5.13 LTS, lokaler Build `daeeeca98fb0` |
| Blender-Python | 3.11.15 |
| Sollumz | `bfcfa9d022af7b9ba3581f295d7bb34163a559bc` |
| Sollumz-Manifest | `2.9.0-dev+bfcfa9d0` |
| szio | 1.3.0.dev9 |
| PyMateria | 0.2.0 |
| texconv | 2026.5.8.1, mitgelieferte EXE per SHA256 geprüft |
| Tests lokal | echtes pytest 8.4.2, lupa 2.5 |

Sollumz wird über die aktivierten Blender-Preferences ausgewählt. Ein altes,
importierbares, aber inaktives Add-on darf die aktive Version nicht verdrängen.
Zusätzlich werden `target_formats` und `target_versions` am Export-Operator
geprüft. Sollumz 2.8.3 ist für diesen Weg nicht ausreichend.

Die CI installiert den vollständigen Sollumz-Commit und Blender 4.5.13. Auch der
Sollumz-Fork von blender-downloader ist auf einen Commit festgelegt. Die
Sollumz-Abhängigkeiten werden unverändert durch dessen eigene Installation mit
Versions- und Hashvorgaben bezogen. `ci/prepare_sollumz.py` ersetzt nur den
Git-Archiv-Platzhalter im Manifest mit dem geprüften Commit-Kürzel. Es verändert
keine Abhängigkeitsversion. `ci/check_toolchain.py` kontrolliert das geladene
Add-on, die Versionen und die Export-API tatsächlich in Blender.

Die frische CI-Installation wurde lokal in getrennten Blender-Konfigurations-,
Script- und Extension-Ordnern nachgestellt, einschließlich Installation der
Abhängigkeiten und eines nativen Packtests. Die normale Benutzerkonfiguration
blieb dabei erhalten. Der Linux-Job prüft CWXML; nur der Windows-Job belegt den
nativen Export. Ein Windows-Fehler wird nicht mehr durch `continue-on-error`
als Erfolg behandelt.

Blender-Pfad einmalig in `propforge.toml`, texconv im PATH oder im lokalen
Starter hinterlegen. Vor Änderungen `--help` und `doctor` verwenden. Ein
Update auf ein anderes Sollumz-`main` ist kein Wartungsschritt ohne eigenen
praktischen Vergleich. Versionen erst zusammen mit bestandenem nativem
Packtest und aktualisiertem Lock ändern.

Bekannte Laufzeitmeldung: PyMateria/nanobind meldet beim Beenden mancher
Blender-Prüfprozesse Referenz-Leaks. Die Prozesse beendeten sich erfolgreich,
die strukturierten Prüfberichte bestanden. Die Meldung wurde nicht unterdrückt;
ihre Ursache im Binding wurde in diesem Update nicht behoben.
