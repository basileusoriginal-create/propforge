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
| `build` | Blender headless: Import, Cleanup, LOD-Kette, Material, Drawable, Kollision, Archetyp (.ytyp), Export | Linux (CWXML) / Windows (NATIVE) |
| `verify` | liest den Export zurück und gleicht ihn gegen die Konfiguration ab | überall |
| `pack` | stream/-Ordner, fxmanifest.lua, Spawn-Helfer für den Test im Spiel | überall |

`propforge run` führt alles nacheinander aus. Es gibt keinen manuellen Schritt
dazwischen.

## Verifikation ohne GTA V

Ein CodeWalker-`.ydr.xml` ist reiner Text und enthält alles, was die Pipeline
versprochen hat: LOD-Stufen, Sichtweiten, Shader, eingebettete Texturen,
Kollision. Dasselbe gilt für die `.ytyp.xml` mit der Archetyp-Definition.
`propforge verify` parst beides zurück und meldet, wenn es von der
Konfiguration abweicht — eine fehlende LOD-Stufe, ein nicht belegter Sampler,
eine Sichtweite, die nicht durchgereicht wurde, eine Textur, die keine
Zweierpotenz ist, ein Archetyp, der auf eine andere `.ydr` zeigt als die
gebaute.

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

Die Blender-Installation folgt dem Muster aus Sollumz' eigener CI —
`blender-downloader` aus dem **Sollumz-Fork**, weil blender.org den
Standard-Python-User-Agent blockt. Die Abhängigkeiten installiert Sollumz'
eigene `install_dependencies()` mit gepinnter Version und Hash-Prüfung.

### Loslegen

Das Repo enthält bereits einen Initial-Commit. Zum Starten:

```bash
git remote add origin git@github.com:<dein-user>/propforge.git
git push -u origin main
```

Danach unter *Actions* den Lauf öffnen. Der Job **Pipeline (Linux, CWXML)**
zeigt das vollständige Blender-Log; das gebaute Asset liegt als Artefakt
`propforge-build-linux` daran.

## Was bewusst Handarbeit bleibt

- **UV-Layout.** Das Skript legt notfalls ein Smart-UV-Projekt an, damit der
  Build nicht scheitert. Für verkaufsfertige Assets ist das kein Ersatz für ein
  ordentliches Unwrap.
- **Silhouette der LOD-Stufen.** Decimate ist blind. Bei Props mit dünnen
  Strukturen (Geländer, Antennen) fallen niedrige LODs auseinander.
- **Vertex-Painting.** Die Pipeline legt die vom Shader verlangten
  Farb-Attribute an und setzt sie auf neutrales Weiß. Eine gestaltete
  Bemalung (grün innen, rot außen) für weichere Beleuchtung bleibt Handarbeit.
- **Mehrere Props in einer ytyp.** Jeder Prop bekommt seine eigene
  Archetyp-Definition. Für große Packs wäre eine gemeinsame ytyp sparsamer.

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

Die Archetyp-Definition entsteht automatisch mit sinnvollen Vorgaben. Wer sie
anpassen will:

```toml
[[prop]]
name = "pf_desk"
# ...

[prop.ytyp]
enabled = true            # false: keine .ytyp erzeugen
name = "pf_desk_ityp"     # Vorgabe: "<prop>_ityp"
lod_dist = 500.0          # Vorgabe: die größte LOD-Sichtweite des Props
hd_texture_dist = 100.0
flags = 32                # 32 = "Static", der Normalfall für einen Prop
# texture_dictionary = "" # Vorgabe: leer, weil die Texturen in der .ydr liegen
```

## Lokale Routine

Kein Hantieren mit Konfigurationsdateien — der Ablauf läuft über Ordner:

```bash
python -m propforge.cli init       # legt work/eingang, work/fertig, work/ausgabe an
python -m propforge.cli batch      # fragt Assets ab und erzeugt sie in den Eingang
python -m propforge.cli convert    # macht daraus .ydr, .ytyp und die Resource
```

`batch` fragt Zeile für Zeile: Prompt, Größenklasse, Kollisionsmaterial (mit
Vorschlag aus dem Namen, `?` sucht). Leere Zeile beendet die Eingabe, dann
läuft alles durch.

**Ohne Generator geht dasselbe:** GLBs einfach in `work/eingang` kopieren und
`convert` aufrufen — der Schritt sieht keinen Unterschied. Wer will, legt
neben ein Mesh eine Begleitdatei `name.job.json` mit Größenklasse und
Material; fehlt sie, greifen die Vorgaben.

Nach dem Umwandeln wandern die verarbeiteten Meshes nach `work/fertig`. **Was
fehlschlägt, bleibt im Eingang liegen** und kommt beim nächsten Lauf wieder
dran. In der `propforge.toml` steht einmalig der Blender-Pfad, damit
`--blender` nicht jedes Mal nötig ist.

## Größenklassen

Ein Prop ist nicht gleich ein Prop. Statt einer Zahl für alles gibt es vier
Klassen, die Dreiecksbudget, Texturgröße und Sichtweiten setzen:

| Profil | Dreiecke | Textur | Wofür |
|---|---|---|---|
| `clutter` | 1 500 | 256 px | Flasche, Dose, Becher, Werkzeug |
| `standard` | 4 000 | 512 px | Kiste, Stuhl, Tisch, Tonne, Regal |
| `detailed` | 10 000 | 1024 px | Automat, Maschine, Tür, Schild mit Text |
| `hero` | 20 000 | 1024 px | Schaustück im Mittelpunkt |

```toml
[[prop]]
profile = "clutter"
```

Die Texturgrößen folgen den FiveM-Optimierungsleitfäden (Kleinkram 256–512,
lesbare Schilder 512–1024; eine `.ytd` ab etwa 16 MB gilt als zu groß), die
Dreiecksbudgets den üblichen Polycount-Bändern für Spiel-Props — GTA V ist von
2013 und liegt jeweils im unteren Teil. Die Sichtweiten sind Heuristik: was
klein ist, muss nicht auf 500 m gerendert werden.

Das Profil ist die **unterste Schicht** — alles, was in `[defaults]` oder am
Prop ausdrücklich steht, gewinnt. `validate` warnt, wenn ein Prop sein Budget
überschreitet, und schätzt den Texturspeicher mit.

## Fertige Assets einlesen

Der Generator ist optional. Ein vorhandenes Modell geht denselben Weg:

```bash
python -m propforge.cli ingest mein_modell.glb --name pf_tisch
```

Texturen werden entpackt und auf die Profilgröße begrenzt, die Größenklasse
aus der Dreieckszahl geschätzt, das Kollisionsmaterial abgefragt, der
`[[prop]]`-Block geschrieben.

## Mesh erzeugen lassen

**Schlüssel hinterlegen** — einer der drei Wege reicht:

```
1. Datei .env im Repo-Ordner:   TRIPO_API_KEY=tsk_...
   (steht in der .gitignore — landet nicht im öffentlichen Repo)
2. Windows, dauerhaft:          setx TRIPO_API_KEY "tsk_..."   → neues Terminal öffnen
3. Nur für einen Aufruf:        --api-key tsk_...
```

```bash
python -m propforge.cli generate "ein rustikaler Holztisch aus Eiche" --profile standard
```

Erzeugt das Mesh, lädt es herunter und reicht es direkt an `ingest` weiter —
Texturen entpackt, Kollisionsmaterial abgefragt, `[[prop]]`-Block geschrieben.
`--dry-run` zeigt ohne Schlüssel, was abgeschickt würde.

**Modellwahl:** Vorgabe ist `P1-20260311` — schneller und günstiger, für
Hintergrund- und Einrichtungs-Props ausreichend. `--model P2-20260801` bringt
sauberere Texturen im Nahbereich und Quad-Topologie, kostet aber mehr Credits.
Der tatsächliche Preis je Generierung steht im Tripo-Konto; nach dem ersten
Lauf lohnt ein Blick auf den Kontostand.

**Warum Tripo:** Pay-as-you-go ohne Abo (1 Credit = 1 US-Cent), kommerzielle
Rechte hängen an der API-Nutzung ohne Namensnennung, und die Ausgabe ist GLB mit PBR-Texturen und einer
Dreiecksobergrenze — genau das, was die Pipeline danach braucht. Bei Meshy
braucht es für API und volles Eigentum den Pro-Plan; die kostenlose Stufe steht
unter CC BY und verlangt Attribution im Endprodukt.

Selbst hosten spart die laufenden Kosten, hat aber zwei Haken: **Hunyuan3D
schließt die Europäische Union in seiner Lizenz ausdrücklich aus**
(„excluding the territory of the European Union, United Kingdom and South
Korea"), und TRELLIS.2 (MIT, kommerziell frei) kann nur Bild-zu-3D und will
24 GB VRAM. Die Anbieterschnittstelle in `propforge/generate.py` ist deshalb
bewusst schmal gehalten.

## Kollisionsmaterial

Das Material bestimmt Schrittgeräusche, Einschlagpartikel, Reifengrip und
Bruchverhalten — ein Holztisch aus `CONCRETE` klingt falsch. Und es ist
Pflicht: ohne Kollisionsmaterial verwirft der Export die Kollision.

```bash
python -m propforge.cli materials                    # alle 185, nach Verwendung gegliedert
python -m propforge.cli materials holz               # suchen
python -m propforge.cli materials --suggest pf_desk  # Vorschlag zu einem Namen
```

`propforge ingest` fragt beim Import danach und schlägt anhand des Namens etwas
vor (`desk` → `WOOD_SOLID_MEDIUM`). Ohne Terminal — CI, Skript — wird nicht
gefragt, sondern der Vorschlag genommen und gemeldet; `--material` setzt ihn
direkt. Die vollständige Liste mit Verwendungszweck steht in
[`docs/kollisionsmaterialien.txt`](docs/kollisionsmaterialien.txt), erzeugt aus
`propforge/collision_materials.py`. Die CI gleicht sie bei jedem Lauf gegen
Sollumz ab, damit Beschreibung und Wirklichkeit nicht auseinanderlaufen.

## Test im Spiel

Jede gepackte Resource bringt eine `client.lua` mit — nicht als Komfort,
sondern als Diagnose:

```
/pfspawn            spawnt den ersten Prop
/pfspawn pf_desk    spawnt einen bestimmten
/pfdelete           räumt wieder auf
```

Der Befehl unterscheidet die beiden Fehlerbilder, die sich sonst gleich
anfühlen:

- **„konnte nicht geladen werden"** → das Spiel kennt den Archetyp nicht. Die
  `.ytyp` ist das Problem, nicht das Modell.
- **gespawnt, aber nichts zu sehen** → der Archetyp stimmt, die `.ydr` nicht.

Abschaltbar über `spawn_helper = false` im `[pipeline]`-Abschnitt.

## Tests

```bash
pytest tests/                              # normal
python tools/minipytest.py tests/*.py      # ohne PyPI-Zugriff
```

344 Tests, grün. Sie decken die plattformunabhängigen Stufen ab —
Texturmathematik, Validierung, GLB-Einlesen, Vorschau-Rasterizer, Packaging und
die Auswertung exportierter CWXML-Assets inklusive der Archetyp-Definition.

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

**Kollisionsmaterial ist Pflicht, nicht Kosmetik.** Sollumz verwirft beim
Export jedes Bound-Mesh, das kein Kollisionsmaterial trägt — oder eines mit
einem Nicht-Kollisionsmaterial. Beides trifft zu, wenn die Kollision als Kopie
des Rendermeshes entsteht: sie bringt dessen Shadermaterial mit. Übrig bleibt
ein Bound Composite ohne Kinder, eine gültige leere Hülle. Die Datei enthält
einen Kollisionsblock, und man läuft trotzdem hindurch.

**Kollisions-Preset beim Namen nennen.** Das eingebaute Standard-Preset heißt
`General (Default)`, nicht `Default`. Sollumz sucht es nach Namen und ignoriert
einen unbekannten stillschweigend — die Kollision hat dann Flags `0` und
kollidiert mit nichts. Man läuft durch den Prop, ohne dass eine Datei fehlt.
Die Pipeline wertet den Rückgabewert aus und prüft danach nach, ob wirklich
Flags gesetzt sind.

**UV-Maps und Farb-Attribute nach Sollumz-Konvention.** Sollumz sucht die
Vertexdaten unter festen Namen — `UVMap 0`, `Color 1`. Heißt die UV-Map wie bei
Blender üblich `UVMap`, überspringt der Vertexpuffer-Bauer sie stillschweigend,
und die exportierte Geometrie hat kein `TexCoord0`, obwohl der Shader es
deklariert. Sollumz warnt ins Log und exportiert trotzdem. Normalerweise
erledigt das der Operator `sollumz.createshadermaterial`; wer wie diese
Pipeline `create_shader` direkt aufruft, muss den Schritt selbst nachziehen.

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
