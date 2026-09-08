# PropForge 0.2.0 – Prüfstand 08.09.2026

Das gemeinsame Pack-Update basiert auf `7e2d8a156524f1443d6ff68a060e3380a746df25`.
Die vorher vorhandenen lokalen YTD-/YTYP- und Bodenkontakt-Korrekturen wurden
gesichert und erhalten. [LOCAL_PACK_REVIEW.md](LOCAL_PACK_REVIEW.md) und
[LOCAL_GROUND_REVIEW.md](LOCAL_GROUND_REVIEW.md) dokumentieren historische
Zwischenstände; ihre damaligen Einschränkungen sind keine aktuelle Featureliste.
Aktueller Vertrag: [PIPELINE_CONTRACT.md](PIPELINE_CONTRACT.md), Version 1.3.

## Umgesetzt

1. Geprüfte Blender-/Sollumz-Kombination und Downloader in CI festgelegt;
   tatsächliche Versionen/Export-API werden geprüft. Native Fehler sind verbindlich.
2. Wiederherstellbare Veröffentlichung mit Schreibsperre, Journal und Vorversion;
   YTD und Begleitliste werden zusammen ersetzt. Wiederherstellung erfolgt vor
   dem Lesen des Packnamens, Sperre vor jeder Job-Änderung.
3. `convert --pack NAME`: native Freigabe, Sammel-YTYP, vollständige Ressource,
   Erhalt früherer Props bei Erweiterungen und dokumentierte Herkunft der Binärdateien.
4. Gemeinsamer DDS-Inhaltspool, stabile Hash-Namen und echte YTD-Deduplizierung.
5. Schutz für kleine Meshes, Bodenpunkte und erkannte dünne Komponenten;
   validierte Reduktion mit berichteten tatsächlichen Zahlen/Fallbacks.
6. Wiederverwendbarer Spawn-/Mess-/Kamerahelfer mit GTA-Referenz und Abstandsfolge.
   Sichtbare Standflächen statt kollisionsbedingter Bounding-Box-Ränder.

## Tatsächlich ausgeführt

- **501 Tests bestanden**, echtes pytest 8.4.2 mit Lua-Ausführung durch lupa 2.5.
  54 bestehende DeprecationWarnings betreffen Element-Truthiness im alten
  `ci/report_geometry.py`. Sie sind keine übersprungenen Tests.
- Reale Blender-LOD-Prüfung: 12-Tris-Körper bleibt 12/12/12/12; ein synthetischer
  Körper mit dünnen Beinen ergibt 744/372/162/58, Schutzpunkte bleiben erhalten.
- Isolierter lokaler Pack: drei Kopien des vorhandenen Schreibtischs plus
  vorhandener kleiner Diagnosekörper, in mehreren Läufen aufgebaut. Ergebnis:
  **4 YDR, 1 YTD mit 6 Einträgen, 1 YTYP mit 4 Archetypen**. Ohne Inhaltsfreigabe
  wären es 12 Texturrollen mit getrennten Namen; sechs identische Rollen der
  Tischkopien verwenden jetzt dieselben drei DDS-Inhalte.
- Alle vier Props aus echten GEN8-Binärdateien zurückgelesen. Alle DDS-Mipdaten
  direkt mit ihren komprimierten Quellen verglichen, Shader-/Dictionary-Verweise,
  LOD-Attribute/Indizes/Normalen/Bounds, eingebettete Kollisionsgeometrie,
  Archetypwerte und Hash-Belege geprüft. Stream-Dateien entsprechen bytegleich
  dem geprüften Build und der geprüften Sammel-YTYP.
- Negativprüfung an einer getrennten nativen Kopie: ein Byte der tatsächlichen
  GPU-Texturdaten verändert. `verify-native` lehnte die weiterhin lesbare YTD
  wegen abweichender DDS-Mipblöcke ab; die veröffentlichte Ressource blieb unverändert.
- Schreibtisch: 1,6 × 0,800079 × 0,75 m, tatsächliche LOD-Dreiecke
  **2628/1314/1300/1102**. Der Schutz begrenzt die Reduktion deutlich; 22/8 Prozent
  wurden nicht als erreicht behauptet. Diagnosekörper: 0,6 × 0,4 × 0,9 m,
  **12/12/12/12**. Quelle, Job und Blender-Original des Tisches per SHA256 unverändert.
- Frische isolierte Sollumz-Installation mit eigenem Blender-Profil und den
  unveränderten Add-on-Abhängigkeiten: Versionsprüfung und nativer Packtest bestanden.
- `ci/pack_regression.py` mit der finalen CLI: zwei native Läufe, gleiche
  Sampler-Namen, alte Texturen erhalten, eine Sammel-YTYP. Ein danach absichtlich
  defektes GLB erreichte die Blender-Stufe nach der DDS-Kompression; Build fehlgeschlagen,
  bisherige Ausgabe vollständig bytegleich, fehlgeschlagene Eingabe im Eingang.
- Vorhandener CI-Assetstapel (Sphäre, Torture-Körper, vorhandener Tisch) lokal
  nativ eingebettet gebaut, binär geprüft und gepackt. CWXML separat erfolgreich
  gebaut/geprüft; die CLI erzeugt dafür keine scheinbar spielbare leere Ressource.
- Zwei zusätzliche Recovery-Regressionsfälle wurden vor dem Fix rot reproduziert:
  Abbruch zwischen Ordnerumbenennungen mit vorhandenem Packnamen sowie ein
  konkurrierender Convert, der vor der Sperre die Begleitdatei umschrieb. Beide
  sind nach dem Fix grün.

## FiveM-Beobachtungen und verbleibende Freigabe

Auf dem vorhandenen lokalen Testserver, FiveM/GTA-Build 3570, wurden alle drei
Tische sowie der Diagnosekörper mit der erzeugten Ressource geladen. In der
Nahansicht waren Texturen sichtbar. Bodenmessungen meldeten fünfmal **0 mm**
je geprüftem Modell. GTA-Referenz `prop_table_03` war sichtbar; ihre vom Spiel
gemeldeten Modellgrenzen betragen ca. 1,862 × 1,171 × 0,838 m. Diese Grenzen
sind keine unabhängig vermessene sichtbare Referenzgeometrie.

Der Schreibtisch wurde durch den Helper aus acht Abständen betrachtet:
54/66/108/132/225/275/450/550 m. Die Rückmeldung liest tatsächlichen Kameraabstand
und FOV, statt nur die gewünschten Parameter zu wiederholen. Die Kamera wurde
danach wieder freigegeben. Auf dem Dach verdecken Masten, Leitungen und Bebauung
Teile der Fernansichten; daraus wurde keine vollständige LOD-Sichtfreigabe abgeleitet.

Die Spielprüfung deckte zwei Fehler im neuen Kamerahelfer auf: die Standard-
Nah-Clipping-Ebene schnitt in der 45-mm-Bodenansicht die Dachfläche ab; außerdem
meldet `GetCamCoord` im Frame des Versetzens noch die vorherige Position. Kleine
Nah-Clipping-Distanz und Ablesen nach dem Framewechsel beheben das. Eine nicht
erreichte Kameraposition wird als Fehler gemeldet; ein Lua-Regressionsfall
simuliert die verzögerte Positionsübernahme.

Die frühere Nutzerbestätigung des Bodenkontakt-Fixes bleibt ein historischer
manueller Nachweis. Für die nun geschützten LODs und daraus erzeugte Kollision
stehen **erneute Begehung relevanter Flächen/Öffnungen und vollständige
LOD-/Material-Sichtprüfung** aus. Heute wurden keine manuellen Nutzerschritte
angefordert. Keine FPS-Messung oder allgemeine Streaming-Leistungszusage.

## Bekannte Grenzen

Ein opaker Atlas, statische Props, NATIVE/GEN8. Keine bestätigte Mehrmaterial-,
Transparenz-, externe LOD-/Kollisions- oder eigene Box-Kollisionsfunktion.
Keine automatische YMAP. Alte Daten ohne neue Build-Belege müssen neu gebaut
werden. Unbenutzte Dictionary-Inhalte/Alt-Assets werden nicht automatisch
bereinigt. Der LOD-Schutz ist geometrisch begrenzt und kann zusätzliche Dreiecke
erhalten; Schrift, Silhouette und Öffnungen bleiben Qualitätsthemen.

Die nativen Prüfprozesse können die in TOOLCHAIN.md dokumentierte nanobind-
Referenz-Leak-Meldung beim Beenden ausgeben. Alle genannten nativen Prüfungen
hatten erfolgreiche strukturierte Berichte; die Binding-Ursache bleibt offen.
Ein CI-Resultat gilt ausschließlich für den zugehörigen Commit, nicht für einen
später veränderten Arbeitsstand. Veröffentlichung erfolgt aus dem vereinbarten
Backup-Checkout nach Dateiabgleich und Validierung.
