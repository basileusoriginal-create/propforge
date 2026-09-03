"""Kollisionsmaterialien von GTA V - mit ihrem ueblichen Verwendungszweck.

Das Kollisionsmaterial bestimmt, was beim Anfassen des Props passiert:
Schrittgeraeusche, Einschlagpartikel und -sounds, Reifengrip, ob Kugeln
durchgehen, welche Bruchstuecke fliegen. Es ist kein Kosmetikfeld - ein
Holztisch aus BETON klingt und splittert falsch.

**Und es ist Pflicht.** Sollumz verwirft beim Export jedes Bound-Mesh ohne
Kollisionsmaterial. Uebrig bleibt ein leeres Bound Composite: eine gueltige
Datei, durch die man hindurchlaeuft.

Diese Liste ist eine *Beschreibung*, keine Quelle der Wahrheit. Der
Materialindex kommt zur Laufzeit aus Sollumz selbst
(``ybn/collision_materials.py``); hier stehen nur Namen, Einordnung und
Verwendungszweck. Damit beides nicht auseinanderlaeuft, vergleicht die CI die
Namen gegen die Sollumz-Liste (``ci/check_collision_materials.py``).
"""

from __future__ import annotations

from typing import NamedTuple


class Material(NamedTuple):
    name: str
    category: str
    usage: str


def _m(name: str, category: str, usage: str) -> Material:
    return Material(name, category, usage)


BODEN = "Boden & Stein"
LOSE = "Lose Boeden"
VEGETATION = "Vegetation"
METALL = "Metall"
HOLZ = "Holz"
BAUSTOFF = "Bau- & Kunststoffe"
INNEN = "Innenausbau & Textil"
VERPACKUNG = "Verpackung & Weiches"
GLAS = "Glas"
FAHRZEUG = "Fahrzeug"
FLUESSIG = "Fluessiges & Organisches"
EFFEKT = "Effekte"
PHYSIK = "Physik-Spezialfaelle"
PED = "Ped-Knochen (nicht fuer Props)"


MATERIALS: tuple[Material, ...] = (
    _m("DEFAULT", BODEN, "Neutraler Standard. Passt ueberall, klingt nach nichts Bestimmtem. Gute Wahl, solange nichts Besseres feststeht."),
    _m("CONCRETE", BODEN, "Beton: Gehwege, Fundamente, Poller, Betonmoebel."),
    _m("CONCRETE_POTHOLE", BODEN, "Beton mit Schlagloechern - fuer Fahrbahnschaeden."),
    _m("CONCRETE_DUSTY", BODEN, "Staubiger Beton, Baustelle und Industriehalle."),
    _m("TARMAC", BODEN, "Asphalt, Strassenbelag."),
    _m("TARMAC_PAINTED", BODEN, "Asphalt mit Markierung, etwa Parkplatzflaechen."),
    _m("TARMAC_POTHOLE", BODEN, "Schadhafter Asphalt."),
    _m("RUMBLE_STRIP", BODEN, "Ruettelstreifen am Fahrbahnrand."),
    _m("BREEZE_BLOCK", BODEN, "Hohlblockstein, einfache Mauern."),
    _m("ROCK", BODEN, "Fels und Naturstein, Klippen, Findlinge."),
    _m("ROCK_MOSSY", BODEN, "Bemooster Fels, feuchte Umgebung."),
    _m("STONE", BODEN, "Naturstein, Mauerwerk, Steinstufen."),
    _m("COBBLESTONE", BODEN, "Kopfsteinpflaster."),
    _m("BRICK", BODEN, "Ziegel und Klinker."),
    _m("MARBLE", BODEN, "Marmor: Lobby, Bad, edle Boeden. Klingt hart und hell."),
    _m("PAVING_SLAB", BODEN, "Gehwegplatten, Terrassenplatten."),
    _m("SANDSTONE_SOLID", BODEN, "Massiver Sandstein."),
    _m("SANDSTONE_BRITTLE", BODEN, "Bruechiger Sandstein, broeselt beim Beschuss."),
    _m("CONCRETE_PAVEMENT", BODEN, "Betongehweg - Variante fuer Strassenraender."),
    _m("BRICK_PAVEMENT", BODEN, "Ziegelpflaster."),
    _m("METAL_SOLID_ROAD_SURFACE", BODEN, "Metallfahrbahn, etwa Bruecken- und Rampenbelag."),
    _m("STUNT_RAMP_SURFACE", BODEN, "Stunt-Rampen mit erhoehtem Grip."),
    _m("ROCK_NOINST", BODEN, "Fels ohne prozedurale Bewuchs-Instanzen. Fuer Felsen, auf denen kein Gras wachsen soll."),

    _m("SAND_LOOSE", LOSE, "Loser Sand, Strand."),
    _m("SAND_COMPACT", LOSE, "Fester Sand, befahrbar."),
    _m("SAND_WET", LOSE, "Nasser Sand an der Wasserlinie."),
    _m("SAND_TRACK", LOSE, "Sandpiste, ausgefahren."),
    _m("SAND_UNDERWATER", LOSE, "Sandgrund unter Wasser."),
    _m("SAND_DRY_DEEP", LOSE, "Tiefer Trockensand, Fahrzeuge graben sich ein."),
    _m("SAND_WET_DEEP", LOSE, "Tiefer Nassand."),
    _m("ICE", LOSE, "Eis, kaum Grip."),
    _m("ICE_TARMAC", LOSE, "Vereiste Fahrbahn."),
    _m("SNOW_LOOSE", LOSE, "Pulverschnee."),
    _m("SNOW_COMPACT", LOSE, "Festgefahrener Schnee."),
    _m("SNOW_DEEP", LOSE, "Tiefschnee."),
    _m("SNOW_TARMAC", LOSE, "Schneebedeckte Fahrbahn."),
    _m("GRAVEL_SMALL", LOSE, "Feiner Schotter, Wege."),
    _m("GRAVEL_LARGE", LOSE, "Grober Schotter."),
    _m("GRAVEL_DEEP", LOSE, "Tiefer Schotter, Kiesgrube."),
    _m("GRAVEL_TRAIN_TRACK", LOSE, "Gleisschotter."),
    _m("DIRT_TRACK", LOSE, "Feldweg, Erdpiste."),
    _m("MUD_HARD", LOSE, "Getrockneter Schlamm."),
    _m("MUD_POTHOLE", LOSE, "Schlammloch."),
    _m("MUD_SOFT", LOSE, "Weicher Schlamm."),
    _m("MUD_UNDERWATER", LOSE, "Schlammgrund unter Wasser."),
    _m("MUD_DEEP", LOSE, "Tiefer Schlamm, Fahrzeuge bleiben stecken."),
    _m("MARSH", LOSE, "Sumpf."),
    _m("MARSH_DEEP", LOSE, "Tiefer Sumpf."),
    _m("SOIL", LOSE, "Muttererde, Beet."),
    _m("CLAY_HARD", LOSE, "Harter Lehm."),
    _m("CLAY_SOFT", LOSE, "Weicher Lehm."),
    _m("PUDDLE", LOSE, "Pfuetze - duenne Wasserschicht auf festem Grund."),

    _m("GRASS_LONG", VEGETATION, "Hohes Gras, Wiese."),
    _m("GRASS", VEGETATION, "Normaler Rasen."),
    _m("GRASS_SHORT", VEGETATION, "Kurz gemaehter Rasen, Sportplatz."),
    _m("HAY", VEGETATION, "Heu, Strohballen."),
    _m("BUSHES", VEGETATION, "Busch- und Strauchwerk, durchlaessig."),
    _m("BUSHES_NOINST", VEGETATION, "Busch ohne prozedurale Instanzen."),
    _m("TWIGS", VEGETATION, "Zweige, Reisig."),
    _m("LEAVES", VEGETATION, "Laub."),
    _m("WOODCHIPS", VEGETATION, "Rindenmulch, Hackschnitzel."),
    _m("TREE_BARK", VEGETATION, "Baumrinde - fuer Staemme."),

    _m("METAL_SOLID_SMALL", METALL, "Kleines massives Metallteil: Griff, Beschlag, Werkzeug."),
    _m("METAL_SOLID_MEDIUM", METALL, "Mittleres Metallteil: Metallmoebel, Schrank, Maschinengehaeuse. Der uebliche Metall-Standard."),
    _m("METAL_SOLID_LARGE", METALL, "Grosses Metallteil: Container, Traeger, Tresorwand."),
    _m("METAL_HOLLOW_SMALL", METALL, "Kleines Hohlmetall: Dose, Rohr, Schild. Klingt scheppernd."),
    _m("METAL_HOLLOW_MEDIUM", METALL, "Muelltonne, Fass, Lueftungskanal."),
    _m("METAL_HOLLOW_LARGE", METALL, "Grosser Hohlkoerper: Silo, Tank, Wellblechhalle."),
    _m("METAL_CHAINLINK_SMALL", METALL, "Maschendraht, kleines Stueck."),
    _m("METAL_CHAINLINK_LARGE", METALL, "Maschendrahtzaun, grossflaechig."),
    _m("METAL_CORRUGATED_IRON", METALL, "Wellblech."),
    _m("METAL_GRILLE", METALL, "Gitterrost, Lueftungsgitter."),
    _m("METAL_RAILING", METALL, "Gelaender, Handlauf, Absperrung."),
    _m("METAL_DUCT", METALL, "Lueftungskanal, duennwandig."),
    _m("METAL_GARAGE_DOOR", METALL, "Garagentor, Rolltor."),
    _m("METAL_MANHOLE", METALL, "Kanaldeckel."),

    _m("WOOD_SOLID_SMALL", HOLZ, "Kleines Massivholz: Latte, Stuhlbein, Werkzeuggriff."),
    _m("WOOD_SOLID_MEDIUM", HOLZ, "Mittleres Massivholz: Tisch, Bank, Regal, Kiste. Der uebliche Holz-Standard fuer Moebel."),
    _m("WOOD_SOLID_LARGE", HOLZ, "Grosses Massivholz: Balken, Baumstamm, Steg."),
    _m("WOOD_SOLID_POLISHED", HOLZ, "Poliertes Holz: Klavier, Theke, Edelmoebel."),
    _m("WOOD_FLOOR_DUSTY", HOLZ, "Staubiger Dielenboden, Dachboden und Scheune."),
    _m("WOOD_HOLLOW_SMALL", HOLZ, "Kleines Hohlholz: duenne Kiste, Schublade."),
    _m("WOOD_HOLLOW_MEDIUM", HOLZ, "Hohle Holzkiste, Sperrholzmoebel."),
    _m("WOOD_HOLLOW_LARGE", HOLZ, "Grosser Hohlkoerper aus Holz: Verschlag, Bretterbude."),
    _m("WOOD_CHIPBOARD", HOLZ, "Spanplatte, billige Moebel."),
    _m("WOOD_OLD_CREAKY", HOLZ, "Altes knarzendes Holz: Ruine, morscher Steg."),
    _m("WOOD_HIGH_DENSITY", HOLZ, "Sehr dichtes Holz, haelt mehr aus."),
    _m("WOOD_LATTICE", HOLZ, "Holzgitter, Spalier, Lattenzaun."),
    _m("WOOD_HIGH_FRICTION", HOLZ, "Holz mit erhoehtem Grip - fuer Flaechen, auf denen nichts rutschen soll."),
    _m("VFX_WOOD_BEER_BARREL", HOLZ, "Bierfass mit eigenem Effekt beim Zerstoeren."),

    _m("CERAMIC", BAUSTOFF, "Keramik: Fliesen, Sanitaer, Geschirr."),
    _m("ROOF_TILE", BAUSTOFF, "Dachziegel."),
    _m("ROOF_FELT", BAUSTOFF, "Dachpappe, Bitumenbahn."),
    _m("FIBREGLASS", BAUSTOFF, "Massives GFK: Bootsrumpf, Verkleidung."),
    _m("FIBREGLASS_HOLLOW", BAUSTOFF, "Hohles GFK, duenne Schale."),
    _m("TARPAULIN", BAUSTOFF, "Plane, Abdeckung, Zeltbahn."),
    _m("PLASTIC", BAUSTOFF, "Massiver Kunststoff: Gehaeuse, Gartenmoebel."),
    _m("PLASTIC_HOLLOW", BAUSTOFF, "Hohler Kunststoff: Muelltonne, Kanister, Spielzeug."),
    _m("PLASTIC_HIGH_DENSITY", BAUSTOFF, "Harter technischer Kunststoff, Industrieteil."),
    _m("PLASTIC_CLEAR", BAUSTOFF, "Klarer Kunststoff, massiv."),
    _m("PLASTIC_HOLLOW_CLEAR", BAUSTOFF, "Klarer Hohlkunststoff: Flasche, Becher."),
    _m("PLASTIC_HIGH_DENSITY_CLEAR", BAUSTOFF, "Harter klarer Kunststoff, Schutzscheibe."),
    _m("RUBBER", BAUSTOFF, "Gummi: Matte, Puffer, Reifen."),
    _m("RUBBER_HOLLOW", BAUSTOFF, "Hohler Gummi: Ball, Schlauch."),
    _m("PLASTER_SOLID", BAUSTOFF, "Massiver Putz, verputzte Wand."),
    _m("PLASTER_BRITTLE", BAUSTOFF, "Bruechiger Putz, Rigips - zerbroeselt beim Beschuss."),

    _m("LINOLEUM", INNEN, "Linoleumboden, Kueche und Flur."),
    _m("LAMINATE", INNEN, "Laminatboden."),
    _m("CARPET_SOLID", INNEN, "Teppichboden."),
    _m("CARPET_SOLID_DUSTY", INNEN, "Staubiger Teppich, verlassene Wohnung."),
    _m("CARPET_FLOORBOARD", INNEN, "Teppich auf Dielen - klingt hohler."),
    _m("CLOTH", INNEN, "Stoff: Polster, Vorhang, Kleidung."),
    _m("LEATHER", INNEN, "Leder: Sofa, Sitz, Tasche."),
    _m("SLATTED_BLINDS", INNEN, "Lamellenjalousie."),
    _m("TVSCREEN", INNEN, "Bildschirm, Monitorglas."),

    _m("CARDBOARD_SHEET", VERPACKUNG, "Pappe als Flaeche."),
    _m("CARDBOARD_BOX", VERPACKUNG, "Kartons - leicht, verschiebbar."),
    _m("PAPER", VERPACKUNG, "Papier, Stapel, Plakat."),
    _m("FOAM", VERPACKUNG, "Schaumstoff, Polsterung."),
    _m("FEATHER_PILLOW", VERPACKUNG, "Federkissen - platzt mit Federn."),
    _m("POLYSTYRENE", VERPACKUNG, "Styropor."),

    _m("GLASS_SHOOT_THROUGH", GLAS, "Fensterglas: Kugeln gehen durch, Scheibe zerbricht."),
    _m("GLASS_BULLETPROOF", GLAS, "Panzerglas, haelt Beschuss."),
    _m("GLASS_OPAQUE", GLAS, "Undurchsichtiges Glas, Milchglas."),
    _m("PERSPEX", GLAS, "Acrylglas, Plexiglas."),
    _m("EMISSIVE_GLASS", GLAS, "Leuchtendes Glas: Lampe, Leuchtreklame."),
    _m("EMISSIVE_PLASTIC", GLAS, "Leuchtender Kunststoff, Lichtabdeckung."),

    _m("CAR_METAL", FAHRZEUG, "Fahrzeugkarosserie."),
    _m("CAR_PLASTIC", FAHRZEUG, "Stossfaenger, Verkleidung."),
    _m("CAR_SOFTTOP", FAHRZEUG, "Stoffverdeck."),
    _m("CAR_SOFTTOP_CLEAR", FAHRZEUG, "Verdeckfenster."),
    _m("CAR_GLASS_WEAK", FAHRZEUG, "Fahrzeugglas, zerbricht leicht."),
    _m("CAR_GLASS_MEDIUM", FAHRZEUG, "Fahrzeugglas, mittlere Festigkeit."),
    _m("CAR_GLASS_STRONG", FAHRZEUG, "Fahrzeugglas, robust."),
    _m("CAR_GLASS_BULLETPROOF", FAHRZEUG, "Gepanzertes Fahrzeugglas."),
    _m("CAR_GLASS_OPAQUE", FAHRZEUG, "Undurchsichtiges Fahrzeugglas."),
    _m("CAR_ENGINE", FAHRZEUG, "Motorblock."),

    _m("WATER", FLUESSIG, "Wasseroberflaeche."),
    _m("BLOOD", FLUESSIG, "Blutlache."),
    _m("OIL", FLUESSIG, "Oellache, rutschig."),
    _m("PETROL", FLUESSIG, "Benzin - entzuendlich."),
    _m("FRESH_MEAT", FLUESSIG, "Frisches Fleisch, Schlachthof."),
    _m("DRIED_MEAT", FLUESSIG, "Getrocknetes Fleisch."),
    _m("ANIMAL_DEFAULT", FLUESSIG, "Standardmaterial fuer Tierkoerper."),

    _m("VFX_METAL_ELECTRIFIED", EFFEKT, "Metall unter Strom - Funken und Schaden."),
    _m("VFX_METAL_WATER_TOWER", EFFEKT, "Wasserturm - laeuft aus, wenn beschossen."),
    _m("VFX_METAL_STEAM", EFFEKT, "Metall mit Dampfaustritt."),
    _m("VFX_METAL_FLAME", EFFEKT, "Metall mit Flammenaustritt."),

    _m("PHYS_NO_FRICTION", PHYSIK, "Reibungsfrei - alles rutscht ab."),
    _m("PHYS_GOLF_BALL", PHYSIK, "Golfball-Physik."),
    _m("PHYS_TENNIS_BALL", PHYSIK, "Tennisball-Physik."),
    _m("PHYS_CASTER", PHYSIK, "Moebelrolle."),
    _m("PHYS_CASTER_RUSTY", PHYSIK, "Verrostete Moebelrolle, mehr Widerstand."),
    _m("PHYS_CAR_VOID", PHYSIK, "Aussparung fuer Fahrzeuge - Fahrzeuge fahren hindurch."),
    _m("PHYS_PED_CAPSULE", PHYSIK, "Kollisionskapsel fuer Peds."),
    _m("PHYS_ELECTRIC_FENCE", PHYSIK, "Elektrozaun."),
    _m("PHYS_ELECTRIC_METAL", PHYSIK, "Stromfuehrendes Metall."),
    _m("PHYS_BARBED_WIRE", PHYSIK, "Stacheldraht - verletzt beim Beruehren."),
    _m("PHYS_POOLTABLE_SURFACE", PHYSIK, "Billardtuch."),
    _m("PHYS_POOLTABLE_CUSHION", PHYSIK, "Billardbande."),
    _m("PHYS_POOLTABLE_BALL", PHYSIK, "Billardkugel."),
    _m("PHYS_DYNAMIC_COVER_BOUND", PHYSIK, "Deckungsvolumen fuer die KI."),
    _m("TEMP_01", PHYSIK, "Platzhalter von Rockstar. Nicht benutzen."),
    _m("TEMP_02", PHYSIK, "Platzhalter von Rockstar. Nicht benutzen."),

    _m("BUTTOCKS", PED, "Ped-Trefferzone."),
    _m("THIGH_LEFT", PED, "Ped-Trefferzone."),
    _m("SHIN_LEFT", PED, "Ped-Trefferzone."),
    _m("FOOT_LEFT", PED, "Ped-Trefferzone."),
    _m("THIGH_RIGHT", PED, "Ped-Trefferzone."),
    _m("SHIN_RIGHT", PED, "Ped-Trefferzone."),
    _m("FOOT_RIGHT", PED, "Ped-Trefferzone."),
    _m("SPINE0", PED, "Ped-Trefferzone."),
    _m("SPINE1", PED, "Ped-Trefferzone."),
    _m("SPINE2", PED, "Ped-Trefferzone."),
    _m("SPINE3", PED, "Ped-Trefferzone."),
    _m("CLAVICLE_LEFT", PED, "Ped-Trefferzone."),
    _m("UPPER_ARM_LEFT", PED, "Ped-Trefferzone."),
    _m("LOWER_ARM_LEFT", PED, "Ped-Trefferzone."),
    _m("HAND_LEFT", PED, "Ped-Trefferzone."),
    _m("CLAVICLE_RIGHT", PED, "Ped-Trefferzone."),
    _m("UPPER_ARM_RIGHT", PED, "Ped-Trefferzone."),
    _m("LOWER_ARM_RIGHT", PED, "Ped-Trefferzone."),
    _m("HAND_RIGHT", PED, "Ped-Trefferzone."),
    _m("NECK", PED, "Ped-Trefferzone."),
    _m("HEAD", PED, "Ped-Trefferzone."),
)

BY_NAME: dict[str, Material] = {m.name: m for m in MATERIALS}

# Kategorien, die fuer einen statischen Prop praktisch nie richtig sind.
# Sie bleiben in der Liste - sie kommen im Spiel vor -, werden aber nicht
# vorgeschlagen und lösen bei der Prüfung einen Hinweis aus.
UNSUITABLE_FOR_PROPS = (PED,)

# Stichwort -> Material. Wird auf Prop- und Dateinamen angewandt, um bei der
# Abfrage etwas Sinnvolles vorzuschlagen. Laengere Stichwoerter gewinnen,
# damit "coffee_table" nicht an "table" scheitert, wenn beides passt.
KEYWORDS: tuple[tuple[str, str], ...] = (
    ("chainlink", "METAL_CHAINLINK_LARGE"),
    ("maschendraht", "METAL_CHAINLINK_LARGE"),
    ("dumpster", "METAL_HOLLOW_LARGE"),
    ("container", "METAL_SOLID_LARGE"),
    ("guardrail", "METAL_RAILING"),
    ("gelaender", "METAL_RAILING"),
    ("railing", "METAL_RAILING"),
    ("handrail", "METAL_RAILING"),
    ("barrel", "METAL_HOLLOW_MEDIUM"),
    ("fass", "METAL_HOLLOW_MEDIUM"),
    ("trash", "PLASTIC_HOLLOW"),
    ("bin", "PLASTIC_HOLLOW"),
    ("muell", "PLASTIC_HOLLOW"),
    ("bucket", "PLASTIC_HOLLOW"),
    ("cone", "PLASTIC_HOLLOW"),
    ("pylon", "PLASTIC_HOLLOW"),
    ("carton", "CARDBOARD_BOX"),
    ("cardboard", "CARDBOARD_BOX"),
    ("karton", "CARDBOARD_BOX"),
    ("pappe", "CARDBOARD_BOX"),
    ("crate", "WOOD_HOLLOW_MEDIUM"),
    ("kiste", "WOOD_HOLLOW_MEDIUM"),
    ("pallet", "WOOD_SOLID_MEDIUM"),
    ("palette", "WOOD_SOLID_MEDIUM"),
    ("desk", "WOOD_SOLID_MEDIUM"),
    ("table", "WOOD_SOLID_MEDIUM"),
    ("tisch", "WOOD_SOLID_MEDIUM"),
    ("shelf", "WOOD_SOLID_MEDIUM"),
    ("regal", "WOOD_SOLID_MEDIUM"),
    ("cabinet", "WOOD_SOLID_MEDIUM"),
    ("schrank", "WOOD_SOLID_MEDIUM"),
    ("bench", "WOOD_SOLID_MEDIUM"),
    ("bank", "WOOD_SOLID_MEDIUM"),
    ("chair", "WOOD_SOLID_SMALL"),
    ("stuhl", "WOOD_SOLID_SMALL"),
    ("plank", "WOOD_SOLID_SMALL"),
    ("brett", "WOOD_SOLID_SMALL"),
    ("wood", "WOOD_SOLID_MEDIUM"),
    ("holz", "WOOD_SOLID_MEDIUM"),
    ("timber", "WOOD_SOLID_MEDIUM"),
    ("piano", "WOOD_SOLID_POLISHED"),
    ("klavier", "WOOD_SOLID_POLISHED"),
    ("sofa", "CLOTH"),
    ("couch", "CLOTH"),
    ("cushion", "CLOTH"),
    ("kissen", "CLOTH"),
    ("curtain", "CLOTH"),
    ("vorhang", "CLOTH"),
    ("leather", "LEATHER"),
    ("leder", "LEATHER"),
    ("carpet", "CARPET_SOLID"),
    ("teppich", "CARPET_SOLID"),
    ("window", "GLASS_SHOOT_THROUGH"),
    ("fenster", "GLASS_SHOOT_THROUGH"),
    ("glass", "GLASS_SHOOT_THROUGH"),
    ("glas", "GLASS_SHOOT_THROUGH"),
    ("bottle", "PLASTIC_HOLLOW_CLEAR"),
    ("flasche", "PLASTIC_HOLLOW_CLEAR"),
    ("monitor", "TVSCREEN"),
    ("screen", "TVSCREEN"),
    ("bildschirm", "TVSCREEN"),
    ("lamp", "EMISSIVE_GLASS"),
    ("lampe", "EMISSIVE_GLASS"),
    ("light", "EMISSIVE_GLASS"),
    ("neon", "EMISSIVE_GLASS"),
    ("concrete", "CONCRETE"),
    ("beton", "CONCRETE"),
    ("kerb", "CONCRETE"),
    ("bordstein", "CONCRETE"),
    ("brick", "BRICK"),
    ("ziegel", "BRICK"),
    ("stone", "STONE"),
    ("stein", "STONE"),
    ("rock", "ROCK"),
    ("fels", "ROCK"),
    ("marble", "MARBLE"),
    ("marmor", "MARBLE"),
    ("tile", "CERAMIC"),
    ("fliese", "CERAMIC"),
    ("ceramic", "CERAMIC"),
    ("sink", "CERAMIC"),
    ("toilet", "CERAMIC"),
    ("metal", "METAL_SOLID_MEDIUM"),
    ("metall", "METAL_SOLID_MEDIUM"),
    ("steel", "METAL_SOLID_MEDIUM"),
    ("stahl", "METAL_SOLID_MEDIUM"),
    ("iron", "METAL_SOLID_MEDIUM"),
    ("pipe", "METAL_HOLLOW_SMALL"),
    ("rohr", "METAL_HOLLOW_SMALL"),
    ("fence", "WOOD_LATTICE"),
    ("zaun", "WOOD_LATTICE"),
    ("plastic", "PLASTIC"),
    ("kunststoff", "PLASTIC"),
    ("rubber", "RUBBER"),
    ("gummi", "RUBBER"),
    ("tyre", "RUBBER"),
    ("reifen", "RUBBER"),
    ("bush", "BUSHES"),
    ("busch", "BUSHES"),
    ("plant", "BUSHES"),
    ("pflanze", "BUSHES"),
    ("tree", "TREE_BARK"),
    ("baum", "TREE_BARK"),
    ("paper", "PAPER"),
    ("papier", "PAPER"),
)

DEFAULT_MATERIAL = "DEFAULT"


def suggest(*hints: str) -> tuple[str, str | None]:
    """Schlaegt anhand von Namen ein Material vor.

    Rueckgabe: (Materialname, ausloesendes Stichwort). Ohne Treffer
    ``(DEFAULT_MATERIAL, None)`` - eine ehrliche Nichtaussage ist besser als
    ein hergeleiteter Zufallstreffer.
    """
    haystack = " ".join(h.lower() for h in hints if h)
    best: tuple[str, str] | None = None
    for keyword, material in KEYWORDS:
        if keyword not in haystack:
            continue
        if best is None or len(keyword) > len(best[1]):
            best = (material, keyword)
    return best if best is not None else (DEFAULT_MATERIAL, None)


def search(term: str) -> list[Material]:
    """Materialien, deren Name, Kategorie oder Beschreibung den Begriff enthaelt."""
    needle = term.lower()
    return [
        m for m in MATERIALS
        if needle in m.name.lower() or needle in m.category.lower() or needle in m.usage.lower()
    ]


def categories() -> list[str]:
    seen: list[str] = []
    for m in MATERIALS:
        if m.category not in seen:
            seen.append(m.category)
    return seen


def render_reference() -> str:
    """Die Liste als Textdatei, nach Kategorien gegliedert."""
    lines = [
        "KOLLISIONSMATERIALIEN FUER GTA V",
        "=" * 72,
        "",
        "Das Kollisionsmaterial bestimmt Schrittgeraeusche, Einschlagpartikel,",
        "Reifengrip und Bruchverhalten. Es ist Pflicht: ohne Kollisionsmaterial",
        "verwirft der Export die Kollision, und man laeuft durch den Prop.",
        "",
        f"{len(MATERIALS)} Materialien, gegliedert nach Verwendung.",
        "Setzen ueber  [prop.collision] material = \"NAME\"",
        "",
    ]
    for category in categories():
        members = [m for m in MATERIALS if m.category == category]
        lines.append(category.upper())
        lines.append("-" * 72)
        for m in members:
            lines.append(f"  {m.name:<28} {m.usage}")
        lines.append("")
    return "\n".join(lines)
