# Übergabevertrag Blender → PropForge

Version **1.3**, PropForge **0.2.0**, geprüft am 08.09.2026. Der GLB-/Job-Eingang
bleibt kompatibel zu 1.2. Neu sind vollständige Packs, gemeinsame DDS-Inhalte,
native Freigabe, wiederherstellbare Veröffentlichung und die Diagnosehilfe.
Die tatsächlich ausgeführten Prüfungen stehen in [STATUS.md](STATUS.md).

## Eingabe

Ein statisches, opakes Prop mit einem Materialatlas: `<name>.glb` und
`<name>.job.json`. Das GLB enthält ausschließlich finale LOD0-Geometrie, ein
Mesh/eine Primitive, reale Metermaße und eingebettete Bilder. Keine Studios,
Referenzen, alternativen Modelle, zusätzlichen LODs, Rigs oder Kollisionen.
Die Gestaltung und Freigabe der Quelle bleiben bei der Asset-Produktion.

```json
{
  "name": "pf_office_desk_01",
  "profile": "standard",
  "material": "WOOD_SOLID_MEDIUM",
  "source_up": "y",
  "center": "base",
  "textures": {}
}
```

Die betreuende Pipeline erstellt die Begleitdatei. Nutzer müssen keine JSON-
oder TOML-Dateien von Hand pflegen. `profile` ist im Projektvertrag ausdrücklich
gesetzt; die CLI besitzt weiterhin Fallbacks und erzwingt kein vollständiges
JSON-Schema. Namen, Profil und Material vor der Übergabe prüfen; `materials`
liefert die vorhandene Kollisionsmaterialliste.

`workspace.read_job` liest `name`, `profile`, `material`, `prompt`, `model`,
`source_up`, `center`, `ytd`, `created`, `textures`. Weitere Metadaten, Herkunft,
Lizenzen, Sollmaße und Freigaben gehören in die begleitende `asset.json` der
Asset-Produktion. Diese Datei wird vom Konverter nicht gelesen.

| Profil | LOD0-Budget | maximale Texturkante | LOD-Distanzen high/medium/low/verylow, m |
| --- | ---: | ---: | --- |
| clutter | 1.500 | 256 | 30/60/120/200 |
| standard | 4.000 | 512 | 60/120/250/500 |
| detailed | 10.000 | 1.024 | 80/150/300/600 |
| hero | 20.000 | 1.024 | 100/200/400/800 |

Die Quelle soll das Budget bereits einhalten. Der bestehende Build kann LOD0
über Budget reduzieren; das ist kein Ersatz für eine Gestaltungsfreigabe.
Er skaliert nicht auf ein gewünschtes Zielmaß.

## Ursprung, Atlas und LODs

Blender Z-up wird regulär zu glTF Y-up exportiert. `source_up: y` verarbeitet
diese Übergabe ohne zusätzliche manuelle Achsrotation. `center: none` erhält
Quellkoordinaten, `xy` zentriert horizontal, `base` setzt zusätzlich die sichtbare
Unterkante auf Z=0, `all` zentriert alle Achsen. Eine explizite Wahl wird nicht
aus der Bounding-Box-Mitte überschrieben. Bodenprops verwenden vereinbart `base`,
Anschluss-/Wandprops mit bewusstem Ursprung `none`.

Eingebettete PNGs: Base Color in sRGB, Metallic/Roughness als Non-Color
(G=Roughness, B=Metallic), optional Tangentnormal +Y. Faktoren und Normalstärke
bleiben neutral; die gewünschte Wirkung steckt in den Bildern. Der Extraktor
liest das erste Material. Beliebige Blender-Nodes, glTF-Erweiterungen und
mehrere Materialbelegungen sind nicht durch diesen Vertrag abgedeckt.

`textures: {}` aktiviert die vollständige Extraktion. Nichtleere Blöcke
überspringen sie; relative externe Pfade werden nicht gegen den Job aufgelöst.
Der normale Übergabeweg nutzt deshalb eingebettete Bilder. Externe absolute
Pfade sind ein vorhandener Konfigurationsweg und werden in der CI verwendet.

DDS müssen **vor** Blender vorhanden sein: Diffuse und Specular opak als BC1,
Normal als BC3, POT-Kanten 16–2048, vollständige Mips bis 1×1. Das Profil begrenzt
die maximale Kante weiter. POT-Anpassung der Diffuse vergrößert die Quelle nicht.
Normal/Specular werden auf die Diffuse-Größe gebracht; gleich große Quellkarten
verwenden. Unter 16 px ist eine aktuelle Atlas-Projektregel, keine GTA-Formatgrenze.
Konstante 1×1-Quellen sind noch kein eigener unterstützter Zweig.

Der Shader ist `normal_spec.sps`, mit Diffuse-, Bump- und Specular-Sampler.
Roughness/Metallic → Specular bleibt eine Näherung. Der Normal-Grünkanal wird
einmal +Y → −Y gewechselt; keine bereits gewendete Quelle liefern.

Vier LODs beginnen bei 100/50/22/8. Bodennahe Vertices und erkannte dünne,
getrennte Komponenten werden geschützt. Meshes bis 64 Dreiecke behalten ihre
Geometrie in allen vier Stufen. Reduktionen mit verlorenen Schutzpunkten oder
ungültigen Dreiecken/Normalen werden abgeschwächt, nötigenfalls bis zur
Quellgeometrie. Tatsächliche Zahlen, Bounds und Fallbacks stehen im Build-Beleg.
Das schützt keine beliebige Schriftfläche oder Silhouette automatisch und kann
die Optimierung deutlich begrenzen. `UVMap 0` und `Color 1` werden in allen LODs
angelegt; die native Rücklesung prüft TexCoord0/Colour0 und die Vertexdaten.

## Ordner und Ausgabe

Ein Workspace verwendet `work/eingang`, `work/fertig`, `work/ausgabe` oder die
vorhandenen Einstellungen aus `propforge.toml`. Blender wird dort einmalig
hinterlegt; texconv liegt im PATH oder wird vom vorhandenen lokalen Starter
übergeben. Diagnosen verwenden einen eigenen Root und Kopien freigegebener Quellen.

Reihenfolge: Eingang/Bilder → Konfiguration → Texturen/DDS → Blender → native
Prüfung → YTYP-Zusammenfassung/Pack → Veröffentlichung → Archivierung. Der
Ausgabeordner darf weder Repository noch Eingabequellen enthalten.

`convert --pack mein_pack --no-ask` erzeugt eine Ressource mit einer Sammel-YTYP,
einer YDR pro Prop und standardmäßig einer gemeinsamen `mein_pack.ytd`.
Weitere Aufrufe mit demselben Root übernehmen den gespeicherten Packnamen.
`--ytd NAME` wählt ein anderes Wörterbuch, `--embed` eingebettete Texturen.
Ein neuer Packname braucht einen eigenen Workspace. Ohne Pack bleibt der
Einzelprop-/Stapelweg mit individuellen YTYPs verfügbar.

Identische vollständige DDS-Dateien erhalten in gemeinsamen Wörterbüchern
denselben `pftex_<sha256>`-Namen, auch über mehrere Läufe. Gleiches Aussehen
allein genügt nicht; die komprimierten Inhalte müssen bytegleich sein.
Der Shader verwendet diesen Namen. Eingebettete Texturen behalten Propnamen.

`build/_ytd/<name>.textures.json` Version 2 enthält relative DDS-Pfade;
`textures/_shared/` hält die Inhalte für spätere Erweiterungen. Vorhandene
Version-1-Listen mit absoluten Pfaden bleiben lesbar. Fehlende alte Quellen
oder eine fehlende Liste neben einer existierenden YTD führen zum Abbruch.
Unbenutzte alte Texturen/Assets werden derzeit nicht automatisch entfernt.
Alte Builds ohne neue Belege müssen aus ihren Quellen neu gebaut werden.

Native Ausgabe ist GEN8, unter Windows über Sollumz/szio/PyMateria. Die YDR
enthält eine einfache BVH-Kollision, im Normalfall aus `low`, mit explizitem
Material und `General (Default)`-Flags. Eine zusätzliche YBN oder automatische
YMAP wird nicht erzeugt. `box` ist kein bestätigter eigenständiger Box-Build.
CWXML bleibt eine diagnostische Ausgabe ohne spielbare Ressource; CodeWalker
ist kein notwendiger zusätzlicher Schritt im nativen Weg.

## Veröffentlichung und Belege

`convert` und `run` arbeiten unter einer Betriebssystem-Schreibsperre in einer
Kopie der Ausgabe auf demselben Laufwerk. Erst nach erfolgreicher Prüfung wird
der gesamte Ordner ausgetauscht. Ein Journal ermöglicht Wiederherstellung beim
nächsten Lauf; eine Vorversion bleibt erhalten. Zwischen zwei Umbenennungen
kann bei einem Prozessabbruch kurz kein Zielordner vorhanden sein. Dies ist
eine wiederherstellbare Veröffentlichung, keine Datenbank-Transaktion und kein
Live-Update-Versprechen für eine gerade streamende FiveM-Ressource.

YTD und Liste sowie einzelne Build-/Ressourcenordner werden ebenfalls gemeinsam
veröffentlicht. Gleichzeitige Schreiber auf dasselbe Ziel werden abgewiesen.
Erst anschließend werden GLB und Job mit zusammengehörigen Archivnamen verschoben.
Archivierungsfehler können nach einer bereits erfolgreichen Veröffentlichung
auftreten; eine fehlschlagende Job-Verschiebung rollt die Mesh-Verschiebung zurück.

Automatisch erzeugte Belege: `build_result.json`, `<name>.build.json` v1
(Job, tatsächliche LODs, Toolchain, Datei-Hashes), `<name>.placement.json` v1
(sichtbare Bounds und YDR-Hash), `native_check/native_result.json`,
`merged/merge_result.json` und `pack_result.json`. Fehlerberichte liegen außerhalb
der unveränderten Ausgabe in `ausgabe_failed/`. JSON-Metadaten sind kein alleiniger
Beweis: die native Prüfung liest die Binärdateien zurück und vergleicht alle DDS-Mips.

## FiveM-Diagnose und Grenzen

Die Ressource enthält `stream/`, `fxmanifest.lua`, `client.lua` und `PRUEFUNG.md`.
`/pfspawn` verwendet die geprüfte sichtbare Unterkante; die Kollisions-Bounds
von `GetModelDimensions` können darunter liegen und dürfen sie nicht ersetzen.
Fünf Bodenstrahlen prüfen die gedrehte Grundfläche. Fehlender Boden oder mehr
als 15 mm Unebenheit führt zum Abbruch der Diagnoseplatzierung. Bewusste
Quellursprünge bleiben unverändert. Fremde/alte Assets ohne Beleg nutzen nur
den ausdrücklich als ungeprüft gemeldeten Fallback.

`/pfstage <name>` kombiniert Spawn, GTA-Referenz, Messung und feste Kamera.
`/pfmeasure` meldet fünf Abstände in mm; `/pfview feet|DISTANZ|off` steuert die
Ansicht. `/pflods` fährt acht Betrachtungsabstände um die Profilgrenzen ab.
Tatsächlicher Kameraabstand und FOV werden gelesen, die intern ausgewählte
LOD-Stufe ist dabei nicht beobachtbar. `/pfdelete` räumt die eigenen Objekte,
Referenz und Kamera auf. Nur eine Diagnose-Ressource mit diesen Befehlen aktivieren.

Materialwirkung, relevante Öffnungen/Durchgänge, Begehbarkeit, LOD-Übergänge und
Streaming unter konkreter Last benötigen eine passende Spielprüfung. Die
automatischen Werte sind keine pauschale visuelle Freigabe oder FPS-Zusage.
Transparente Spezialshader, mehrere Materialien, externe LOD-/Kollisionsquellen
und andere Assetklassen werden durch dieses Update nicht freigegeben.
