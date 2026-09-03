"""Kleiner Software-Rasterizer fuer die LOD-Vorschau.

Warum nicht Blender rendern lassen: dessen Render-Engines brauchen einen
OpenGL-Kontext, den `--background` nicht bereitstellt. Workbench scheiterte
unter Linux an libEGL.so.1 und liess Blender unter Windows mit einer Access
Violation abstuerzen.

Hier reichen ein paar hundert Zeilen numpy: es geht nicht um ein schoenes Bild,
sondern um eine Frage - haelt die reduzierte Stufe noch die Silhouette? Dafuer
braucht es Umriss und Drahtgitter, sonst nichts. Und dieser Code laeuft
ausserhalb von Blender, ist also testbar.

Projiziert wird **orthografisch**. Das ist kein Kompromiss, sondern die richtige
Wahl: alle LOD-Stufen bekommen damit zwangslaeufig denselben Massstab, und genau
das braucht ein Vergleich. Eine perspektivische Kamera koennte den
Silhouettenverlust durch minimal andere Distanz kaschieren.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

# Blickrichtung: Dreiviertelansicht von schraeg oben. Zeigt Vorder-, Seiten-
# und Oberflaeche gleichzeitig, damit ein Silhouettenverlust nicht zufaellig
# hinter der Ansicht verschwindet.
AZIMUTH = math.radians(35.0)
ELEVATION = math.radians(22.0)

# Richtung des Lichts im Kameraraum. Von links oben vorne - die uebliche
# Konvention, bei der Formen am besten lesbar sind.
LIGHT = np.array([-0.4, 0.5, 0.75])

# Hoechster Lambert-Wert, den eine sichtbare Flaeche erreichen kann: die
# Kamera blickt entlang +Z im Kameraraum, das Licht faellt seitlich ein.
# Auf diesen Wert wird normiert, damit der volle Farbbereich genutzt wird.
LIGHT_MAX = float(LIGHT[2] / np.linalg.norm(LIGHT))

SOLID_BASE = np.array([92, 92, 104], dtype=float)
SOLID_LIT = np.array([214, 214, 224], dtype=float)
WIRE_COLOR = (198, 198, 210)
EDGE_COLOR = (38, 38, 46)


@dataclass
class Geometry:
    vertices: np.ndarray  # (N, 3)
    triangles: np.ndarray  # (M, 3) Indizes

    @property
    def triangle_count(self) -> int:
        return int(self.triangles.shape[0])

    @staticmethod
    def from_dict(data: dict) -> "Geometry":
        vertices = np.asarray(data.get("vertices", []), dtype=float).reshape(-1, 3)
        triangles = np.asarray(data.get("triangles", []), dtype=int).reshape(-1, 3)
        if triangles.size and triangles.max() >= len(vertices):
            raise ValueError("Dreiecksindex zeigt hinter das Ende der Vertexliste.")
        return Geometry(vertices, triangles)


def view_matrix(azimuth: float = AZIMUTH, elevation: float = ELEVATION) -> np.ndarray:
    """Rotationsmatrix von Welt- in Kamerakoordinaten.

    Blender ist Z-up, deshalb wird zuerst um Z (Azimut) und dann um die
    Kamera-X-Achse (Elevation) gedreht.
    """
    ca, sa = math.cos(azimuth), math.sin(azimuth)
    rot_z = np.array([[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]])

    ce, se = math.cos(elevation), math.sin(elevation)
    # Z-up nach Y-up drehen und dabei die Elevation einbauen.
    rot_x = np.array([[1.0, 0.0, 0.0], [0.0, se, ce], [0.0, -ce, se]])

    return rot_x @ rot_z


def project(
    geometry: Geometry,
    size: int,
    bounds: tuple[np.ndarray, float],
    margin: float = 0.9,
) -> tuple[np.ndarray, np.ndarray]:
    """Projiziert die Vertices orthografisch in Bildkoordinaten.

    `bounds` ist (Mittelpunkt, Radius) und wird bewusst von aussen vorgegeben:
    alle LOD-Stufen eines Props teilen sich dieselben Werte, sonst waeren die
    Bilder nicht vergleichbar.
    """
    center, radius = bounds
    if radius <= 0:
        radius = 1.0

    camera_space = (geometry.vertices - center) @ view_matrix().T

    scale = (size * margin) / (2.0 * radius)
    xs = camera_space[:, 0] * scale + size / 2.0
    # Bild-Y zeigt nach unten, Kamera-Y nach oben.
    ys = -camera_space[:, 1] * scale + size / 2.0

    screen = np.stack([xs, ys], axis=1)
    depth = camera_space[:, 2]
    return screen, depth


def compute_bounds(geometry: Geometry) -> tuple[np.ndarray, float]:
    """Mittelpunkt und Radius, gemessen an der Bounding-Box."""
    if len(geometry.vertices) == 0:
        return np.zeros(3), 1.0
    lo = geometry.vertices.min(axis=0)
    hi = geometry.vertices.max(axis=0)
    center = (lo + hi) / 2.0
    radius = float(np.linalg.norm(geometry.vertices - center, axis=1).max())
    return center, (radius or 1.0)


def _shade(normals: np.ndarray) -> np.ndarray:
    """Lambert-Schattierung, auf den sichtbaren Bereich normiert.

    Ohne Normierung bleibt das Bild flau: eine zur Kamera zeigende Flaeche
    erreicht nur `LIGHT_MAX` statt 1.0, weil das Licht seitlich einfaellt. Der
    nutzbare Kontrast waere damit ein knappes Viertel des Farbbereichs - zu
    wenig, um Flaechen auseinanderzuhalten.

    Die Grundhelligkeit bleibt: reines Lambert laesst abgewandte Flaechen im
    Schwarz verschwinden, und dort sitzt die Silhouette, um die es geht.
    """
    light = LIGHT / np.linalg.norm(LIGHT)
    intensity = np.clip(normals @ light, 0.0, 1.0) / LIGHT_MAX
    return 0.18 + 0.82 * np.clip(intensity, 0.0, 1.0)


def render_solid(geometry: Geometry, size: int, bounds: tuple[np.ndarray, float]) -> Image.Image:
    """Zeichnet die gefuellte Form mit echtem Tiefenpuffer.

    Der erste Ansatz war ein Maleralgorithmus - Dreiecke nach mittlerer Tiefe
    sortieren und von hinten nach vorne malen. Der taugt hier aus zwei Gruenden
    nicht:

    1. Bei ineinandergreifender Geometrie versagt die Sortierung. Eine grosse
       Platte kann "im Mittel" weit weg sein und trotzdem vor einer Strebe
       liegen. Das Ergebnis sah aus wie ein zerlegtes Objekt.
    2. Die Sortierrichtung war zudem vertauscht. Bei einer Kugel faellt das
       nicht auf, weil ihre Rueckseite genauso aussieht wie ihre Vorderseite -
       ein Fehler, der sich erst an einem Objekt mit Struktur zeigt.

    Pro Pixel zu entscheiden ist ein paar Zeilen mehr und dafuer richtig.
    """
    if geometry.triangle_count == 0:
        return Image.new("RGBA", (size, size), (0, 0, 0, 0))

    screen, depth = project(geometry, size, bounds)

    tri = geometry.triangles
    v0, v1, v2 = (geometry.vertices[tri[:, i]] for i in range(3))

    normals = np.cross(v1 - v0, v2 - v0)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    normals_cam = (normals / lengths) @ view_matrix().T
    intensity = _shade(normals_cam)

    # Groesseres z bedeutet naeher an der Kamera (nachgemessen, nicht geraten).
    zbuffer = np.full((size, size), -np.inf, dtype=float)
    canvas = np.zeros((size, size, 3), dtype=float)
    covered = np.zeros((size, size), dtype=bool)

    for index in range(len(tri)):
        a, b, c = tri[index]
        pa, pb, pc = screen[a], screen[b], screen[c]

        min_x = max(int(np.floor(min(pa[0], pb[0], pc[0]))), 0)
        max_x = min(int(np.ceil(max(pa[0], pb[0], pc[0]))), size - 1)
        min_y = max(int(np.floor(min(pa[1], pb[1], pc[1]))), 0)
        max_y = min(int(np.ceil(max(pa[1], pb[1], pc[1]))), size - 1)
        if min_x > max_x or min_y > max_y:
            continue

        area = (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pc[0] - pa[0]) * (pb[1] - pa[1])
        if abs(area) < 1e-9:
            continue  # entartetes Dreieck

        ys, xs = np.mgrid[min_y:max_y + 1, min_x:max_x + 1]
        px = xs + 0.5
        py = ys + 0.5

        # Baryzentrische Koordinaten ueber Kantenfunktionen.
        w0 = ((pb[0] - pa[0]) * (py - pa[1]) - (px - pa[0]) * (pb[1] - pa[1])) / area
        w1 = ((px - pa[0]) * (pc[1] - pa[1]) - (pc[0] - pa[0]) * (py - pa[1])) / area
        w2 = 1.0 - w0 - w1

        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue

        z = w2 * depth[a] + w1 * depth[b] + w0 * depth[c]

        window = zbuffer[min_y:max_y + 1, min_x:max_x + 1]
        nearer = inside & (z > window)
        if not nearer.any():
            continue

        window[nearer] = z[nearer]
        shade = intensity[index]
        canvas[min_y:max_y + 1, min_x:max_x + 1][nearer] = (
            SOLID_BASE + (SOLID_LIT - SOLID_BASE) * shade
        )
        covered[min_y:max_y + 1, min_x:max_x + 1][nearer] = True

    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[:, :, :3] = np.clip(canvas, 0, 255).astype(np.uint8)
    rgba[:, :, 3] = np.where(covered, 255, 0)
    return Image.fromarray(rgba, mode="RGBA")


def signed_area(screen: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Vorzeichenbehaftete Flaeche der projizierten Dreiecke.

    Bei konsistent gewickelten Meshes trennt das Vorzeichen Vorder- von
    Rueckseite - ohne dass man wissen muss, in welche Richtung die Kamera
    blickt. Das Cleanup vereinheitlicht die Normalen, also ist die
    Voraussetzung erfuellt.
    """
    a = screen[triangles[:, 0]]
    b = screen[triangles[:, 1]]
    c = screen[triangles[:, 2]]
    return 0.5 * ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                  - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))


def render_wire(
    geometry: Geometry,
    size: int,
    bounds: tuple[np.ndarray, float],
    cull_backfaces: bool = True,
) -> Image.Image:
    """Zeichnet nur die Kanten - macht die Topologie der Reduktion sichtbar.

    Rueckseiten werden standardmaessig weggelassen. Ohne Culling ueberlagern
    sich Vorder- und Rueckseite und ein dichtes LOD0 wird zum Wollknaeuel, in
    dem man die Struktur gerade nicht mehr erkennt.
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if geometry.triangle_count == 0:
        return image

    screen, _ = project(geometry, size, bounds)
    draw = ImageDraw.Draw(image)

    triangles = geometry.triangles
    if cull_backfaces:
        areas = signed_area(screen, triangles)
        # Die Mehrheitsrichtung ist die Vorderseite: bei einem geschlossenen
        # Koerper ist gut die Haelfte sichtbar, und welches Vorzeichen das ist,
        # haengt an der Wicklung. So muss man es nicht fest verdrahten.
        visible = areas > 0 if (areas > 0).sum() >= (areas < 0).sum() else areas < 0
        triangles = triangles[visible]
        if len(triangles) == 0:
            triangles = geometry.triangles

    # Jede Kante nur einmal zeichnen: bei geschlossenen Meshes gehoert jede
    # Kante zu zwei Dreiecken, und doppelte Linien wirken dicker als sie sind.
    seen: set[tuple[int, int]] = set()
    for a, b, c in triangles:
        for start, end in ((a, b), (b, c), (c, a)):
            key = (start, end) if start < end else (end, start)
            if key in seen:
                continue
            seen.add(key)
            draw.line([tuple(screen[start]), tuple(screen[end])], fill=WIRE_COLOR, width=1)

    return image
