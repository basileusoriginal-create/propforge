# PropForge: lokales YTD-/YTYP-Review vom 07.09.2026

Historischer Zwischenstand. Die aktuelle Weiterentwicklung und Freigabe stehen
in [STATUS.md](STATUS.md); Aussagen unten zu damaligen fehlenden Funktionen und
zum damaligen Commit-/Push-Status beziehen sich auf den 07.09.2026.

Geprüfte Basis: 7e2d8a156524f1443d6ff68a060e3380a746df25, beim Start sauber.
Die folgenden Korrekturen sind lokal vorhanden; Chat 02 hat nichts committet oder gepusht.

## Geändertes Verhalten

- `propforge/cli.py`: `--ytd` und `--embed` gelten auch für vorhandene `.job.json`. Die explizite Auswahl wird vor Überspringen der Nachfrage gespeichert, auch bei bereits eingetragenen Texturpfaden. Profil und Ursprung bleiben erhalten. Vier neue Regressionsfälle vor Änderung tatsächlich fehlgeschlagen.
- `blender/sz_build_prop.py`: Fehlende historische DDS oder fehlende/ungültige Begleitliste neben einer vorhandenen YTD brechen ab. Alte Texturen werden nicht still entfernt. Der Export erfolgt in einen temporären Ordner; nur erfolgreich zurückgelesene YTD ersetzt die bisherige Datei. Eine alte Datei kann keinen erfolgreichen Export vortäuschen. Fehlendes szio ist ein Fehler statt eines übersprungenen Checks. Nicht absturzsicher über YTD und JSON hinweg; kein konkurrierendes Schreiben zugesichert.
- `blender/sz_merge_ytyp.py`: Pfade vor Übergabe an szio/VPath absolut auflösen. Der Fehler wurde in einem echten nativen Merger-Lauf mit `../work/...` reproduziert. Versions-Unterordneroptionen unverändert; diese sind bei nur einem Ziel nicht wirksam.
- `propforge/ytyp_merge.py`: `hdTextureDist` im XML-Duplikatvergleich ergänzt. Unterschiedliche HD-Distanzen wurden zuvor fälschlich als identisch akzeptiert. Native Merger-Feldliste enthielt den Wert bereits.
- `ci/read_native.py`: YTD-Rücklesung und Textur-Namensliste ergänzt; externe YDRs ohne Dictionary unterstützt; absolute Pfade.
- `ci/check_native_textures.py`: optionaler Texture-Prefix erlaubt den bestehenden Rohdatencheck für eine gemeinsame YTD.
- `ci/check_native_pack.py`: separate, bewusst auf den Tisch-Testpack begrenzte Diagnose. Prüft native Payloads/Geometrie/Verweise; nicht in die normale CLI eingebaut.
- Tests: `test_ytd.py`, `test_ytyp_merge.py`, neues `test_ytd_failures.py`. Export-/Rücklesefehler lassen vorhandene YTD und Manifest unverändert. Keine globale bpy-Fälschung.

## Tatsächlich ausgeführt

Echtes pytest: Baseline 432 bestanden; nach Änderungen 94 relevante Tests bestanden (keine vollständige Suite erneut ausgeführt). Fünf neue Fälle vorher rot reproduziert. Native Lauf 1 mit Tisch A, gemischter Lauf mit B und fehlschlagendem Kleinstkörper, erfolgreicher Mehrfachlauf B+C, YTD-Rücklesung, nativer YTYP-Merger und native Duplikat-/Konfliktfälle.

Lokale Toolchain unverändert: Windows, Blender 4.5.13 LTS / Python 3.11.15, Sollumz 2.9.0-dev+bfcfa9d0 (Commit bfcfa9d022af7b9ba3581f295d7bb34163a559bc), szio 1.3.0.dev9, PyMateria 0.2.0, texconv 2026.5.8.1.

Native Daten: 3 YDR mit externen Samplern, 1 YTD mit 9 vollständigen DDS (512², DXT1/DXT5/DXT1, 10 Mips), 1 YTYP mit 3 Archetypen. Texturen von Lauf 1 nach Erweiterung unverändert. 4 LODs und eingebettete BVH je Tisch. GLB-/Job-Originale hashgleich.

Nachweise außerhalb des Repos: `../work/diagnostics/20260907_ytd_pack/`. Finale Ressource unter `delivery/pf_pack_validation_20260907`; aktuelle Ingame-Ergebnisse stehen in `INGAME_TEST.md` dort und in `../STATUS.md`.

## Verbliebene Grenzen

1. Keine Inhalts-Deduplizierung: 9 gespeicherte Texturen, nur 3 verschiedene DDS-Inhalte. Keine zugesicherte Speicherersparnis. Das ist die noch fehlende Funktion, falls identische Materialien tatsächlich mehrfach genutzt werden sollen.
2. `convert` packt individuelle YTYPs. Der zusätzliche Merger plus erneute Packager-Stufe erzeugt erst die finale Ressource mit einer YTYP. `merge-ytyp` durchsucht flache Ordner, keine Build-Unterordner.
3. 12-Tris-Kleinstkörper scheitert durch aggressive Decimation mit `LOD low: Null-Normale nach der Reduktion`. Der Abbruch ist korrekt; kein stiller Eingriff in die Quelle. Dieser bestehende LOD-Fall bleibt gezielt zu lösen.
4. CI weiterhin Blender 4.5.11 / unpinned Sollumz-main; Windows-Native-Job erlaubt Fehlschlag. Kein CI-Ergebnis dieser lokalen Änderungen behauptet. Pinning auf die nachgewiesene Kombination ist weiterhin sinnvoll.
5. Beispiel-pipeline.toml setzt nach wie vor 10000 Tris/1024 bei Standard-Defaults. Der geprüfte GLB-/Job-Workspace nutzt die tatsächlichen Standard-Profilwerte; Beispiel wurde in diesem Review nicht still geändert.
6. Kein allgemeiner YTYP-Merger-Nachweis für MLO/Time/Extensions/Abhängigkeiten. Die 13 Identitätsfelder decken nicht jede denkbare Archetyp-Eigenschaft ab. Native Merger-Rückprüfung im normalen Lauf prüft Namen; der zusätzliche Test hat die 13 Felder verglichen. Kein vollständiger Binärsemantik- oder GEN9-Nachweis.
7. Externe YTD allein plus Einträge in der Begleitliste reichen nicht als Nachweis korrekter Pixel. Deshalb die separat ausgeführte Prüfung sämtlicher nativer Mipblöcke. Keine FPS-Aussage.

Ingame-Zusatz: A/B/C auf Client b3570 geladen und texturiert gesehen, A+B gleichzeitig in Nahansicht; Regen/Tag. Nutzer bestätigt Kollision/Platte und einfachen Rückkehrtest mit „sieht gut aus“; genaue LOD-/Referenzprüfung offen. Separater CWXML-YTD-Lauf samt DDS-Ablage/Rücklesung ebenfalls bestanden.
