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
    """Lambert-Schattierung, aufgehellt, damit auch abgewandte Flaechen lesbar bleiben."""
    light = LIGHT / np.linalg.norm(LIGHT)
    intensity = np.clip(normals @ light, 0.0, 1.0)
    # 0.25 Grundhelligkeit: reines Lambert laesst Randflaechen im Schwarz
    # verschwinden, und dort sitzt die Silhouette, um die es geht.
    intensity = 0.25 + 0.75 * intensity
    return intensity


def render_solid(geometry: Geometry, size: int, bounds: tuple[np.ndarray, float]) -> Image.Image:
    """Zeichnet die gefuellte Form mit Maleralgorithmus."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if geometry.triangle_count == 0:
        return image

    screen, depth = project(geometry, size, bounds)
    draw = ImageDraw.Draw(image)

    tri = geometry.triangles
    v0 = geometry.vertices[tri[:, 0]]
    v1 = geometry.vertices[tri[:, 1]]
    v2 = geometry.vertices[tri[:, 2]]

    normals = np.cross(v1 - v0, v2 - v0)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    normals = normals / lengths
    normals_cam = normals @ view_matrix().T

    intensity = _shade(normals_cam)

    # Maleralgorithmus: hinten zuerst. Ein Z-Buffer pro Pixel waere genauer,
    # aber fuer eine Silhouettenpruefung ist der Aufwand nicht gerechtfertigt.
    tri_depth = depth[tri].mean(axis=1)
    order = np.argsort(tri_depth)[::-1]

    for index in order:
        a, b, c = tri[index]
        shade = intensity[index]
        color = SOLID_BASE + (SOLID_LIT - SOLID_BASE) * shade
        fill = tuple(int(v) for v in color) + (255,)
        draw.polygon(
            [tuple(screen[a]), tuple(screen[b]), tuple(screen[c])],
            fill=fill,
            outline=EDGE_COLOR,
        )

    return image


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
