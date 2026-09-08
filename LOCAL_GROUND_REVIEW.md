# Bodenkontakt – lokaler Fix vom 07.09.2026

Historischer Nachweis des Bodenkontakt-Fixes. Aktueller Ablauf und die darauf
aufbauende Diagnosehilfe: [STATUS.md](STATUS.md), [PIPELINE_CONTRACT.md](PIPELINE_CONTRACT.md).

Der Dachtest widerlegt die frühere pauschale Bodenfreigabe. Die sichtbare
LOD0 des Tisches endet korrekt auf Z=0. Seine BVH-Grenze endet bei
Z=-0,039375 m: Sollumz bfcfa9d0 erweitert BVH-Bounds absichtlich um 0,04 m.
`PlaceObjectOnGroundProperly` setzt diese Grenze auf den Boden. Auf dem
ebenen Dach wurde dadurch ein **39,3753 mm** großer Abstand gemessen.
Beim selben Objekt ergibt Platzierung der sichtbaren Unterkante auf die
gemessene Dachhöhe einen Abstand von **0 mm**. Kein Quellfehler von Chat 01.

## Änderung

- `blender/sz_build_prop.py`: schreibt nach dem nativen Export die tatsächlichen
  LOD0-Grenzen im Drawable-Koordinatensystem als `<name>.placement.json` neben
  die YDR und in `build_result.json`. Geometrie, Kollision und Ursprung werden
  dafür nicht verändert.
- `propforge/placement.py`: liest/schreibt dieses interne Schema v1. Dateiname
  und SHA256 binden die Werte an genau die YDR; veraltete/ungültige Daten werden
  abgelehnt. Die Datei entsteht automatisch, ohne neues Job-Feld.
- `propforge/packaging.py`: liest die einzelnen Begleitdateien beim Packen,
  auch aus früheren Läufen, und integriert die Grenzen in `client.lua`.
  `/pfspawn` prüft fünf Bodenpunkte über der gedrehten Grundfläche und setzt
  das Modell mit `CreateObjectNoOffset` auf Bodenhöhe minus sichtbare Unterkante.
  Fehlende Oberfläche, Dachkante oder mehr als 15 mm Höhenunterschied führen
  zum Abbruch. Der Helper ist für ebene Diagnoseflächen bestimmt. Er richtet
  einen Tisch nicht automatisch an beliebiges Gefälle an.
- Alte/fremde Dateien ohne Metadaten behalten den bisherigen Native-Fallback
  mit ausdrücklicher Warnung „Bodenbezug ungesichert“. Ein fehlgeschlagenes
  Platzieren/Erstellen wird nicht mehr als erfolgreicher Spawn eingefroren.
  Beim Ressourcenstopp werden die vom Helper erzeugten Objekte entfernt.
- `requirements.txt`: `lupa==2.5` nur als Testabhängigkeit. Die neue Testsuite
  führt den tatsächlich erzeugten Lua-Code aus, inklusive 0/1- und boolescher
  Native-Rückgaben, Timeouts, Dachkanten, Gefälle, Ursprüngen unter/über Z=0,
  Rotation, fehlgeschlagenem Erstellen und alter Ressource.

## Nachweise

Diagnoseordner im gemeinsamen Projekt:
`work/diagnostics/20260907_ground_contact/`.

- 62 unterschiedliche gezielte Tests bestanden: zunächst 61 in Packaging,
  Placement, ausgeführtem Lua-Helper und Konvertierungs-/Ursprungsregressionen;
  nach zusätzlicher Sicherung eines vorhandenen Pakets bei ungültigen
  Metadaten 27 Packaging-/Placement-Tests erneut. Keine vollständige Suite.
- Drei unveränderte GLB-Kopien über den normalen `convert` neu gebaut; 3/3
  erfolgreich und erst nach Erfolg archiviert. Native Sammel-YTYP erneut mit
  vorhandenem Merger erstellt.
- `runtime_baseline.json`: tatsächliche FiveM-Messung vorher/nachher am selben
  Objekt auf dem Dach bei Carson Ave, Dachhöhe 38,2822876 m.
- `runtime_fixed_a.json`, `runtime_fixed_b.json`, `runtime_fixed_c.json`:
  regulärer neuer `/pfspawn` jeweils einzeln ausgeführt, alle fünf Proben je
  Tisch mit 0 mm Abstand. Nach Wiederherstellung der normalen Kamera bestätigt
  der Nutzer die gezielte neue Nahsicht an Tisch C: **„yes! ist verschwunden!“**.
- `native_ground_verification.json`: alle LODs, Shader und Kollisionsdaten
  beim nativen Rücklesen unverändert; Standhöhen stimmen mit nativen Vertices
  überein. Alle neun nativen DDS einschließlich vollständiger Mip-Payloads
  entsprechen dem vorherigen Pack. Binärdateien sind nach erneutem Export
  nicht pauschal byteidentisch; native Inhalte wurden getrennt verglichen.

Für eine Sammelressource beim Staging neben YDR/YTD/Sammel-YTYP auch die
automatisch erzeugten `.placement.json` neben ihrer jeweiligen YDR mitnehmen.
Der vorhandene Packager liest sie und integriert sie in den Helper; sie
gehören nicht in `stream/`. Ausgeführtes Beispiel: `package_and_verify.py`
im Diagnoseordner. Native Spieldateien benötigen diese Metadaten nicht.

## Grenzen

Der Fix betrifft die Platzierung durch `/pfspawn`. Andere Editoren/Skripte,
die die Kollisionsunterkante auf den Boden setzen, benötigen denselben
Grundsatz. Keine pauschale 4-cm-Korrektur und keine Änderung des Sollumz-Rands.
Manuelle/YMAP-Platzierung verwendet weiter den bewusst gewählten Ursprung.

Die reduzierte Geometrie selbst bleibt unverändert: low hebt die tiefsten
Punkte um etwa 0,6–0,8 mm an, verylow etwa 7,3 mm an den Rahmenbeinen und
15,5 mm am Schrank. Das ist eine getrennte LOD-Qualitätsgrenze, nicht die
gemessene 39-mm-Lücke in der Nahansicht. Keine neue Freigabe sämtlicher
LOD-Übergänge, unebener Flächen oder Leistung.

Frühere lokale YTD-/YTYP-Korrekturen bleiben erhalten. Kein Commit oder Push
durchgeführt; die neuen Dateien müssen zusammen mit den Änderungen übernommen
werden. `LOCAL_PACK_REVIEW.md` beschreibt die vorherigen Pack-Korrekturen.
