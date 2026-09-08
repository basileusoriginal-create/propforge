# Ablauf: GLB bis FiveM-Pack

PropForge 0.2.0, Übergabevertrag 1.3. Für Gestaltung und hochwertige Quellen ist
die Asset-Produktion zuständig. Dieser Ablauf konvertiert geprüfte Quellen mit
der in [TOOLCHAIN.md](../TOOLCHAIN.md) festgehaltenen Kombination.

## Einmalig einrichten

```powershell
python -m propforge.cli --version
python -m propforge.cli convert --help
python -m propforge.cli init --root <workspace>
python -m propforge.cli doctor --blender <blender.exe> --texconv <texconv.exe>
python -m propforge.cli materials holz
```

`init` nur für fehlende Einrichtung benutzen; vorhandene Pfade erhalten.
Der betreuende Starter speichert/übergibt bekannte Werkzeugpfade. Kein
Asset-spezifisches Anlegen einer `pipeline.toml` durch den Nutzer.

## Pack bauen und erweitern

1. Nur beauftragte GLB-/Job-Kopien in `work/eingang/` des gewünschten Roots legen.
   Maße, Ursprung, Profil, ein Atlas und ausschließlich finale LOD0 prüfen.
2. Für den ersten Lauf den Packnamen wählen:

   ```powershell
   python -m propforge.cli convert --root <workspace> --pack pf_office_pack --no-ask
   ```

3. `build_result.json`, `native_check/native_result.json`,
   `merged/merge_result.json` und `pack_result.json` prüfen. Die CLI lässt
   fehlerhafte native Daten nicht bis zur Veröffentlichung durch.
4. `work/ausgabe/resources/pf_office_pack/` ist die vollständige Ressource.
   `stream/` enthält eine YDR je Prop, die benötigten YTDs und genau eine
   Sammel-YTYP. Die kopierten Binärdateien werden per SHA256 abgeglichen.
5. Für eine Erweiterung neue Kopien in denselben Eingang legen und `convert`
   erneut ausführen. Der Packname und alte Assets bleiben erhalten. Gleiche
   vollständige DDS-Inhalte benutzen dieselben Sampler-Namen.

`--ytd NAME` überschreibt die Wörterbuchwahl für diesen Lauf; `--embed` setzt
eingebettete Texturen. `--pack NAME --embed` erzeugt weiterhin eine Sammel-YTYP.
Der normale Atlasvertrag bleibt gleich. Neue Packnamen und CWXML-Diagnosen
verwenden getrennte Roots. Alt-Builds ohne Belege für die neue native Prüfung
aus den freigegebenen Quellen neu bauen; Metadaten nicht nachträglich erfinden.

Nach einem Fehler bleiben die bisherige Ausgabe und die Eingaben erhalten.
Strukturierte Blender-/Prüffehler werden unter `ausgabe_failed/` gesichert.
Ein Absturz während des Ordneraustauschs wird beim nächsten Aufruf anhand des
Journals wiederhergestellt. Die Ausgabe nicht während einer Konvertierung
manuell ändern; eine aktive FiveM-Ressource separat und kontrolliert ersetzen.

Die vorhandenen Einzelbefehle `validate`, `textures`, `build`, `verify`, `pack`
und `run` bleiben für Konfigurationen nutzbar. `verify` prüft bei NATIVE jetzt
tatsächliche Binärdaten. Ein erneuter unabhängiger Abgleich ist möglich:

```powershell
python -m propforge.cli verify-native --root <workspace>
```

Die Prüfung braucht Build-Belege und die aufbewahrten DDS, nicht nur einen
beliebigen fremden `stream/`-Ordner. Sie dekodiert native Dateien über szio und
vergleicht alle DDS-Mipdaten direkt im Binärinhalt. Sie beweist nicht alle
Eigenschaften einer beliebigen GTA-Assetklasse. CWXML wird separat geprüft und
nicht als spielbare Ressource gepackt. `merge-ytyp` bleibt auch einzeln verfügbar.

## Im Spiel

Ressource in den Testserver übernehmen und starten. Nur einen PropForge-
Diagnosehelfer aktivieren, damit die gleichnamigen Befehle eindeutig sind.
Die mitgelieferte `PRUEFUNG.md` enthält dieselben kurzen Schritte:

```text
/pfstage pf_office_desk_01
/pfmeasure
/pfview feet
/pflods
/pfview off
/pfdelete
```

`pfstage` platziert auf der gemessenen ebenen Oberfläche, setzt eine GTA-
Referenz daneben und richtet die feste Kamera ein. `pfmeasure` meldet fünf
Bodenabstände. `pfview` akzeptiert auch einen Abstand in Metern. `pflods`
verwendet 0,9× und 1,1× jeder im Build gespeicherten Sichtweite, jeweils 2,5 s,
und beendet die Kamera anschließend. Manuelle Ansichtswechsel brechen den
Durchlauf ab. Der Bericht enthält gemessenen Kameraabstand und FOV; eine
tatsächlich ausgewählte interne LOD-Stufe wird nicht behauptet.

Sichtprüfung: Texturen und Materialwirkung, Größe neben Referenz, sichtbarer
Bodenbezug, dünne Teile/Schrift/Silhouette bei sinnvollen Abständen. Bewegung:
gegen relevante Flächen laufen, auf geeignete Standflächen steigen, Öffnungen
und Durchgänge prüfen, entfernen und zurückkehren. Bei Nacht, Verdeckung oder
ungeeignetem Boden keinen vollständigen Qualitätserfolg behaupten. Leistung
nur mit dokumentierter Objektzahl, Abständen, Einstellungen und Messdauer.

Konverterfehler mit Log und Binär-/Build-Fundstelle bearbeiten. Quellfehler
mit Assetversion und konkreter Geometrie-/Textur-Fundstelle an die Produktion
melden. Geometrie oder Maßstab nicht still zur Umgehung eines Exportfehlers ändern.

## Freigabe im betreuten lokalen Projekt

Entwicklung im Asset Generation Center, Diagnosen in einem getrennten Workspace.
Vorhandene Änderungen werden gesichert und mit übernommen. Nur fertig geprüfte
Dateien gehen in den vereinbarten Backup-Checkout; ausschließlich dort wird
committet und gepusht. Lokale `.env`, Rohquellen und Testserver-Konfigurationen
bleiben außerhalb des Updates. Vor Push Dateiabgleich und Validierung, danach
den zugehörigen CI-Lauf prüfen. Kein automatisches Update der Export-Toolchain.
