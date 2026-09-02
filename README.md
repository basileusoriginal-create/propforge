# PropForge

Automatisierte Prop-Pipeline für GTA V / FiveM.

```
generiertes Mesh  ->  Cleanup  ->  LOD-Kette  ->  Kollision
                                                     |
PBR-Texturen      ->  Specular  ->  DDS  -------------+--> .ydr --> FiveM-Resource
```

Die These dahinter: Assets *erzeugen* ist heute das kleinere Problem. Der Engpass
liegt am RAGE-Format-Ende der Kette — LODs, Kollision, Texturkonventionen,
Shader-Zuweisung, Manifest. Das ist repetitive Regelarbeit und damit
automatisierbar. Genau die deckt dieses Repo ab.

## Was automatisiert ist

| Stufe | Was passiert | Läuft wo |
|---|---|---|
| `doctor` | prüft Blender, Sollumz, szio, PyMateria, texconv | überall |
| `validate` | Namen, Texturmaße, LOD-Konsistenz, Shader-Sampler-Abgleich | überall |
| `textures` | Zweierpotenz-Resize, Specular aus Roughness/Metallic, OpenGL→DirectX-Normalmap, DDS via texconv | überall (DDS: Windows) |
| `jobs` | Prop-Definitionen zu Job-JSON für Blender | überall |
| `build` | Blender headless: Import, Cleanup, LOD-Kette, Material, Drawable, Kollision, Export | Linux (CWXML) / Windows (NATIVE) |
| `verify` | liest den Export zurück und gleicht ihn gegen die Konfiguration ab | überall |
| `pack` | stream/-Ordner plus fxmanifest.lua | überall |

`propforge run` führt alles nacheinander aus. Es gibt keinen manuellen Schritt
dazwischen.

## Verifikation ohne GTA V

Ein CodeWalker-`.ydr.xml` ist reiner Text und enthält alles, was die Pipeline
versprochen hat: LOD-Stufen, Sichtweiten, Shader, eingebettete Texturen,
Kollision. `propforge verify` parst den Export zurück und meldet, wenn er von
der Konfiguration abweicht — eine fehlende LOD-Stufe, ein nicht belegter
Sampler, eine Sichtweite, die nicht durchgereicht wurde, eine Textur, die keine
Zweierpotenz ist.

Das ersetzt keinen Blick ins Spiel. Es fängt aber die gesamte Klasse von
Fehlern ab, bei denen der Export stillschweigend etwas wegläßt — und genau die
sind sonst am teuersten, weil sie erst im Spiel auffallen.

## CI

`.github/workflows/build.yml` installiert Blender und Sollumz, erzeugt ein
synthetisches Testasset (kein Binärblob im Repo), fährt die komplette Kette
und prüft das Ergebnis maschinell. Der Linux-Job nutzt CWXML und läuft ohne
PyMateria; der Windows-Job deckt zusätzlich den NATIVE-Export ab.

Damit ist die Pipeline bei jedem Push verifiziert, ohne dass jemand etwas
anklicken muss.

## Was bewusst Handarbeit bleibt

- **UV-Layout.** Das Skript legt notfalls ein Smart-UV-Projekt an, damit der
  Build nicht scheitert. Für verkaufsfertige Assets ist das kein Ersatz für ein
  ordentliches Unwrap.
- **Silhouette der LOD-Stufen.** Decimate ist blind. Bei Props mit dünnen
  Strukturen (Geländer, Antennen) fallen niedrige LODs auseinander.
- **Vertex-Painting.** Sollumz erwartet für korrekte Beleuchtung Vertex-Farben
  (grün innen, rot außen). Noch nicht implementiert.
- **ytyp-Erzeugung.** Aktuell wird ein vorhandenes ytyp nur eingepackt, nicht
  generiert.

## Voraussetzungen

- Python 3.11+, Pillow, numpy
- Blender 4.2+ mit [Sollumz](https://github.com/Sollumz/Sollumz) 2.9-dev
- **PyMateria** für `export_format = "NATIVE"` (direkter Binärexport, nur
  Windows, wird von Sollumz über die Add-on-Preferences installiert). Ohne
  PyMateria auf `export_format = "CWXML"` wechseln und mit CodeWalker konvertieren.
- [texconv](https://github.com/microsoft/DirectXTex/releases) im PATH für den DDS-Schritt

## Benutzung

```bash
python -m propforge.cli validate pipeline.toml   # Preflight, kein Blender nötig
python -m propforge.cli textures pipeline.toml   # PBR -> DDS
python -m propforge.cli build    pipeline.toml   # Blender headless
python -m propforge.cli pack     pipeline.toml   # FiveM-Resource
python -m propforge.cli run      pipeline.toml   # alles nacheinander
```

Konfiguration: siehe `pipeline.toml`.

## Tests

```bash
pytest tests/                              # normal
python tools/minipytest.py tests/*.py      # ohne PyPI-Zugriff
```

89 Tests, grün. Sie decken die plattformunabhängigen Stufen ab —
Texturmathematik, Validierung, Packaging und die Auswertung exportierter
CWXML-Assets.

Die Blender-Stufe selbst ist **lokal nicht** automatisiert getestet: dafür
braucht es eine Blender-Installation mit Sollumz. Genau die stellt die CI
bereit — dort läuft sie bei jedem Push. Ihre API-Aufrufe sind gegen den
Sollumz-Quellcode und dessen eigene Testsuite geprüft, nicht aus Tutorials
abgeschrieben.

## Warum diese Design-Entscheidungen

**Specular aus Roughness.** AI-Generatoren liefern den metallic/roughness-Workflow,
GTA V will eine einzelne Specular-Map mit umgekehrter Bedeutung. Die Umrechnung
invertiert Roughness und hebt Metallflächen an — ohne diesen Schritt wirkt jedes
Metall im Spiel wie Plastik.

**Normalmap-Green-Flip.** Generatoren geben OpenGL-Konvention (Y+) aus, RAGE
erwartet DirectX (Y-). Der Fehler äußert sich in Beleuchtung, die nach innen
statt nach außen wölbt — und fällt oft erst spät auf.

**Kollision aus einem niedrigen LOD.** `sollumz.converttodrawable` baut die
eingebettete Kollision immer aus LOD0. Bei 10.000 Dreiecken sind das 10.000
Kollisionsdreiecke, die die Physik nicht braucht. `retarget_collision` hängt sie
nachträglich auf die konfigurierte Stufe um.

**Logarithmisches Runden auf Zweierpotenzen.** 1500 px liegt näher an 2048
(Faktor 1,37) als an 1024 (Faktor 1,46). Lineares Runden würde hier unnötig
Detail wegwerfen.

**Namenskollisionen als harter Fehler.** Streaming-Dateinamen sind in FiveM
serverweit global. Eine Kollision überschreibt stillschweigend ein anderes Asset
auf dem Server — das muss beim Packen auffallen, nicht im Betrieb.

**Export-Settings als Operator-Argumente.** Sollumz' eigene Testsuite übergibt
`target_formats` und `target_versions` zusammen mit `use_custom_settings=True`
direkt an `sollumz.export_assets`, statt die Add-on-Preferences zu verändern.
Das lässt die Einstellungen des Nutzers unangetastet und macht den Aufruf
reproduzierbar.
