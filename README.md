# PropForge

PropForge **0.2.0** konvertiert geprüfte GLBs zu nativen GTA-V-/FiveM-Props und
vollständigen Packs. Ein Pack kann mehrere Props in einer YTYP registrieren und
identische DDS-Inhalte in einer gemeinsamen YTD wiederverwenden.

```text
GLB + Job → Eingang prüfen → Bilder/DDS → Blender/LODs/Kollision
          → native Rücklesung → Sammel-YTYP → Ressource → Archiv
```

## Normaler Einstieg

```powershell
python -m propforge.cli init
python -m propforge.cli doctor --blender <blender.exe> --texconv <texconv.exe>
python -m propforge.cli convert --pack pf_office_pack --no-ask
```

Vorhandene Konfiguration erhalten und Werkzeugpfade einmalig hinterlegen.
GLB und `<name>.job.json` liegen in `work/eingang/`. Erfolgreiche Eingaben
wandern nach `work/fertig/`, die fertige Ressource liegt unter
`work/ausgabe/resources/pf_office_pack/`. Ein weiterer `convert`-Aufruf mit
neuen Eingaben erweitert denselben Pack. Für getrennte Packs `--root` verwenden.
Der betreuende Workflow erzeugt Begleitdateien; Nutzer müssen keine
`pipeline.toml` für einzelne Assets pflegen.

Geprüfter Eingangsvertrag: statisches opakes Prop, ein Materialatlas, reale
Metermaße, finale LOD0, explizites Profil und Ursprung. Details und gültige
Felder: [PIPELINE_CONTRACT.md](PIPELINE_CONTRACT.md). Weitere Metadaten gehören
in die `asset.json` der Asset-Produktion, die der Konverter nicht liest.

## Dieses Update

- Vollständige Packs mit einer Sammel-YTYP entstehen im normalen `convert`.
- Die native Freigabe liest echte YDR/YTD/YTYP zurück und prüft alle DDS-Mips,
  Shader-Verweise, LOD-Vertexdaten, Kollision, Archetypen und Build-Belege.
- Identische vollständige DDS-Dateien teilen Sampler-Namen und YTD-Einträge,
  auch bei späteren Erweiterungen. Alte Texturquellen bleiben erhalten.
- Schreibsperre, Arbeitskopie und Wiederherstellungsjournal schützen die
  bisherige Ausgabe. Eingaben werden erst nach Veröffentlichung archiviert.
- Kleine Meshes sowie erkannte dünne Teile und Bodenpunkte werden bei der
  LOD-Erzeugung geschützt. Tatsächliche Reduktionen und Fallbacks sind sichtbar.
- Der Diagnosehelfer platziert anhand der sichtbaren Standfläche und bietet
  Bodenmessung, feste Kamera, GTA-Referenz und Betrachtungsabstände.

## Texturen und Packs

```powershell
python -m propforge.cli convert --pack pf_office_pack --no-ask
python -m propforge.cli convert --ytd pf_shared_textures --no-ask
python -m propforge.cli convert --embed --no-ask
python -m propforge.cli verify-native --root <workspace>
python -m propforge.cli merge-ytyp <ordner> --name pf_combined
```

`--pack` verwendet standardmäßig eine gleichnamige YTD. `--ytd` oder `--embed`
überschreibt die Texturwahl für den Lauf. Ohne `--pack` bleibt der vorhandene
Stapelweg mit individuellen YTYPs erhalten. Ohne `--no-ask` fragt die CLI im
Terminal nach fehlenden Entscheidungen; vollständige Begleitdateien werden
respektiert. Die tatsächlich vorhandenen Optionen stehen in `convert --help`.

Der Shader `normal_spec.sps` verwendet Diffuse, Bump und Specular. DDS liegen
vor dem Materialaufbau vor: BC1 für opakes Diffuse/Specular, BC3 für Normal,
vollständige Mipkette. Die Specular-Ableitung ist eine Näherung, keine Zusage
identischer PBR-Materialwirkung. Der Normal-Grünkanal wird genau einmal gedreht.

Im gemeinsamen Wörterbuch bestimmt der SHA256 der vollständigen DDS-Datei den
Namen. Nur bytegleiche Inhalte werden zusammengefasst. Die Liste neben der YTD
und alle referenzierten DDS müssen für Erweiterungen erhalten bleiben. Alte
Builds ohne die neuen Belege werden aus ihren Quellen neu gebaut. Automatisches
Entfernen unbenutzter Alt-Assets/Texturen ist noch nicht implementiert.

## Werkzeuge und Ausgabe

Geprüft: Windows, Blender 4.5.13 LTS, Sollumz-Commit
`bfcfa9d022af7b9ba3581f295d7bb34163a559bc`, dessen szio 1.3.0.dev9/PyMateria 0.2.0
und die mitgelieferte texconv-Version. Alle Pins und Hashes stehen in
[TOOLCHAIN.md](TOOLCHAIN.md) und [toolchain.lock.json](toolchain.lock.json).
Die CLI benötigt Python 3.11+, Pillow und numpy.

Native GEN8-Ausgabe: YDRs mit eingebetteter BVH-Kollision, YTYP sowie optional
gemeinsame YTDs. Die Ressource enthält `stream/`, `fxmanifest.lua`, `client.lua`
und `PRUEFUNG.md`. Zusätzliche YBN oder automatische YMAP sind keine Pflicht
und kein Merkmal dieses Ablaufs. CWXML bleibt eine eigene diagnostische Ausgabe
ohne spielbare Ressource. CodeWalker kann kontrollieren, ist im nativen Weg
kein zusätzlicher Pflicht-Konverter.

## Testen

```powershell
python -m pip install -r requirements.txt
python -m pytest tests -q
python ci/pack_regression.py --blender <blender.exe> --root <neuer-testordner>
```

Der Packtest verwendet Kopien des vorhandenen CI-Assets, baut zwei Läufe und
erzeugt anschließend absichtlich einen Blender-Buildfehler. Er prüft, dass
alte Props/Texturen erhalten bleiben und die veröffentlichte Ausgabe bei
Fehlern bytegleich bleibt. **Echtes pytest** ist der Freigabeweg; der historische
`tools/minipytest.py`-Ersatz deckt nicht alle aktuellen Fixture-Arten ab.

Die CI pinnt Blender und Sollumz. Linux prüft CWXML, Windows den nativen Build
einschließlich Pack-Erweiterung. Native Fehler lassen den Job scheitern.
Lokale Resultate und Grenzen: [STATUS.md](STATUS.md).

```text
/pfstage <propname>   Prop, GTA-Referenz, Bodenmessung und Kamera
/pfmeasure           fünf Bodenabstände in Millimetern
/pfview feet         niedrige Ansicht (oder Abstand in Metern)
/pflods              acht Abstände um die Profilgrenzen
/pfview off          normale Kamera wiederherstellen
/pfdelete            eigene Testobjekte und Kamera entfernen
```

`/pfspawn <name>` und `/pfreference` bleiben einzeln verfügbar. Die Diagnose
unterstützt ebene Standflächen. Die ausgewählte interne LOD-Stufe ist nicht
direkt messbar; der Bericht benennt diese Grenze ausdrücklich. Materialwirkung,
Silhouette, begehbare Kollision und Streaming brauchen passende Spieltests.
Eine Polygon-/Texturzahl ist keine FPS-Zusage.

## Weitere vorhandene Einstiege

`validate`, `textures`, `jobs`, `build`, `verify`, `pack`, `run` arbeiten mit
Konfigurationen wie `pipeline.toml`. `ingest` bereitet GLBs auf, `materials`
liefert gültige Kollisionsmaterialien. Die vorhandenen `generate`-/`batch`-
Einstiege zum Tripo-Anbieter bleiben erhalten; das Pack-Update nutzt sie nicht.
Schlüssel bleiben in der ignorierten `.env` oder der Prozessumgebung.

Der vollständige betreute Ablauf steht in
[workflows/gta_conversion.md](workflows/gta_conversion.md). Mehrere Materialien,
transparente Spezialshader, externe LOD-/Kollisionsquellen, ein eigener Box-
Kollisionsbuild und andere Assetklassen sind damit nicht freigegeben.
