"""Tests fuer den Software-Rasterizer.

Er ersetzt Blenders Render-Engines, weil die im Hintergrundmodus einen
OpenGL-Kontext brauchen, den es dort nicht gibt (libEGL unter Linux, Access
Violation unter Windows). Der Ersatz muss dafuer nachweisbar funktionieren.
"""

import math

import numpy as np
import pytest
from PIL import Image

from propforge import raster


def tetrahedron() -> raster.Geometry:
    vertices = np.array([
        [0.0, 0.0, 1.0],
        [0.94, 0.0, -0.33],
        [-0.47, 0.82, -0.33],
        [-0.47, -0.82, -0.33],
    ])
    triangles = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 1], [1, 3, 2]])
    return raster.Geometry(vertices, triangles)


def sphere(segments: int = 16, rings: int = 10) -> raster.Geometry:
    vertices = []
    for ring in range(rings + 1):
        phi = math.pi * ring / rings
        for seg in range(segments):
            theta = 2 * math.pi * seg / segments
            vertices.append([
                math.sin(phi) * math.cos(theta),
                math.sin(phi) * math.sin(theta),
                math.cos(phi),
            ])
    triangles = []
    for ring in range(rings):
        for seg in range(segments):
            a = ring * segments + seg
            b = ring * segments + (seg + 1) % segments
            c = a + segments
            d = b + segments
            triangles.append([a, b, c])
            triangles.append([b, d, c])
    return raster.Geometry(np.array(vertices), np.array(triangles))


def opaque_pixels(image: Image.Image) -> int:
    return int((np.asarray(image)[:, :, 3] > 0).sum())


class TestGeometry:
    def test_from_dict(self):
        geo = raster.Geometry.from_dict({
            "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            "triangles": [[0, 1, 2]],
        })
        assert geo.triangle_count == 1
        assert geo.vertices.shape == (3, 3)

    def test_empty(self):
        geo = raster.Geometry.from_dict({"vertices": [], "triangles": []})
        assert geo.triangle_count == 0

    def test_rejects_out_of_range_index(self):
        with pytest.raises(ValueError, match="hinter das Ende"):
            raster.Geometry.from_dict({
                "vertices": [[0, 0, 0]],
                "triangles": [[0, 1, 2]],
            })


class TestBounds:
    def test_centre_and_radius(self):
        geo = raster.Geometry(
            np.array([[-1.0, 0, 0], [1.0, 0, 0], [0, -1.0, 0], [0, 1.0, 0]]),
            np.array([[0, 1, 2]]),
        )
        center, radius = raster.compute_bounds(geo)
        assert np.allclose(center, [0, 0, 0])
        assert radius == pytest.approx(1.0)

    def test_offset_object(self):
        geo = raster.Geometry(np.array([[10.0, 10, 10], [12.0, 10, 10]]), np.array([[0, 1, 0]]))
        center, _ = raster.compute_bounds(geo)
        assert np.allclose(center, [11, 10, 10])

    def test_empty_has_safe_defaults(self):
        center, radius = raster.compute_bounds(raster.Geometry(np.zeros((0, 3)), np.zeros((0, 3), int)))
        assert radius == 1.0


class TestProjection:
    def test_output_inside_image(self):
        geo = sphere()
        bounds = raster.compute_bounds(geo)
        screen, depth = raster.project(geo, 256, bounds)
        assert screen.shape == (len(geo.vertices), 2)
        assert screen.min() >= 0 and screen.max() <= 256
        assert depth.shape == (len(geo.vertices),)

    def test_shared_bounds_keep_scale(self):
        # Der Kern der Vergleichbarkeit: dieselben bounds, derselbe Massstab -
        # auch wenn das reduzierte Mesh eine kleinere eigene Ausdehnung hat.
        big = sphere(24, 16)
        small = raster.Geometry(big.vertices * 0.5, big.triangles)
        bounds = raster.compute_bounds(big)
        a, _ = raster.project(big, 256, bounds)
        b, _ = raster.project(small, 256, bounds)
        extent_a = a.max(axis=0) - a.min(axis=0)
        extent_b = b.max(axis=0) - b.min(axis=0)
        assert extent_b[0] == pytest.approx(extent_a[0] / 2, rel=0.05)

    def test_view_matrix_is_rotation(self):
        m = raster.view_matrix()
        assert np.allclose(m @ m.T, np.eye(3), atol=1e-9)
        assert np.linalg.det(m) == pytest.approx(1.0)


class TestSolidRendering:
    def test_produces_visible_shape(self):
        geo = sphere()
        img = raster.render_solid(geo, 128, raster.compute_bounds(geo))
        assert img.size == (128, 128)
        assert opaque_pixels(img) > 128 * 128 * 0.3

    def test_empty_geometry_is_transparent(self):
        geo = raster.Geometry(np.zeros((0, 3)), np.zeros((0, 3), int))
        assert opaque_pixels(raster.render_solid(geo, 64, (np.zeros(3), 1.0))) == 0

    def test_shading_varies_across_surface(self):
        # Eine Kugel muss unterschiedlich helle Flaechen haben, sonst ist die
        # Form im Bild nicht lesbar. Gemessen: Bereich 113..195, std ~11.
        geo = sphere(24, 16)
        img = raster.render_solid(geo, 192, raster.compute_bounds(geo))
        arr = np.asarray(img)
        visible = arr[arr[:, :, 3] > 0][:, 0]
        assert visible.std() > 8
        # Der Hellbereich muss breit genug sein, um Flaechen zu unterscheiden.
        assert int(visible.max()) - int(visible.min()) > 60

    def test_smaller_lod_covers_less_area(self):
        # Der eigentliche Zweck: der Silhouettenverlust muss messbar sein.
        high = sphere(32, 20)
        low = sphere(6, 4)
        bounds = raster.compute_bounds(high)
        area_high = opaque_pixels(raster.render_solid(high, 192, bounds))
        area_low = opaque_pixels(raster.render_solid(low, 192, bounds))
        assert area_low < area_high


class TestWireRendering:
    def test_draws_lines(self):
        geo = sphere()
        img = raster.render_wire(geo, 128, raster.compute_bounds(geo))
        count = opaque_pixels(img)
        assert 0 < count < 128 * 128 * 0.5  # Linien, keine Flaeche

    def test_culling_reduces_line_count(self):
        geo = sphere(20, 12)
        bounds = raster.compute_bounds(geo)
        culled = opaque_pixels(raster.render_wire(geo, 192, bounds, cull_backfaces=True))
        full = opaque_pixels(raster.render_wire(geo, 192, bounds, cull_backfaces=False))
        assert culled < full

    def test_empty_geometry_is_transparent(self):
        geo = raster.Geometry(np.zeros((0, 3)), np.zeros((0, 3), int))
        assert opaque_pixels(raster.render_wire(geo, 64, (np.zeros(3), 1.0))) == 0

    def test_flat_shape_still_renders(self):
        # Bei einem flachen Objekt zeigen alle Dreiecke in dieselbe Richtung.
        # Wenn Culling dann alles wegwirft, faellt der Code auf ungefiltert
        # zurueck statt ein leeres Bild zu liefern.
        geo = tetrahedron()
        img = raster.render_wire(geo, 128, raster.compute_bounds(geo))
        assert opaque_pixels(img) > 0


class TestSignedArea:
    def test_sign_flips_with_winding(self):
        screen = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
        forward = raster.signed_area(screen, np.array([[0, 1, 2]]))
        backward = raster.signed_area(screen, np.array([[0, 2, 1]]))
        assert forward[0] == -backward[0]
        assert abs(forward[0]) == pytest.approx(50.0)


class TestDepthBuffer:
    """Der Tiefenpuffer ersetzt einen Maleralgorithmus, der zweimal falsch war:
    vertauschte Sortierrichtung und ungeeignet fuer ineinandergreifende Formen.
    Beides blieb an einer Kugel unsichtbar - diese Tests nutzen deshalb Formen,
    bei denen Verdeckung eindeutig ist."""

    def _two_quads(self, near_first: bool):
        """Zwei parallele Vierecke, eines klar vor dem anderen."""
        import numpy as np

        direction = raster.view_matrix().T @ np.array([0.0, 0.0, 1.0])
        near = direction * 2.0
        far = -direction * 2.0

        verts = []
        for offset in ((near, far) if near_first else (far, near)):
            for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                point = offset + np.array([dx, dy, 0.0]) * 0.9
                verts.append(point)
        tris = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]])
        return raster.Geometry(np.array(verts), tris)

    def test_nearer_surface_wins_regardless_of_order(self):
        # Egal in welcher Reihenfolge die Dreiecke in der Liste stehen: das
        # Bild muss identisch sein. Beim Maleralgorithmus war es das nicht.
        import numpy as np

        a = self._two_quads(near_first=True)
        b = self._two_quads(near_first=False)
        bounds = raster.compute_bounds(a)
        img_a = np.asarray(raster.render_solid(a, 96, bounds))
        img_b = np.asarray(raster.render_solid(b, 96, bounds))
        assert np.array_equal(img_a, img_b)

    def test_hidden_surface_does_not_show(self):
        # Ein kleines Objekt vollstaendig hinter einer grossen Flaeche darf
        # im Bild nicht auftauchen.
        import numpy as np

        direction = raster.view_matrix().T @ np.array([0.0, 0.0, 1.0])
        verts = []
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            verts.append(direction * 2.0 + np.array([dx, dy, 0.0]) * 1.0)
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            verts.append(-direction * 2.0 + np.array([dx, dy, 0.0]) * 0.2)
        tris = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]])
        geo = raster.Geometry(np.array(verts), tris)

        only_front = raster.Geometry(np.array(verts[:4]), np.array([[0, 1, 2], [0, 2, 3]]))
        bounds = raster.compute_bounds(geo)

        with_hidden = np.asarray(raster.render_solid(geo, 96, bounds))
        without = np.asarray(raster.render_solid(only_front, 96, bounds))
        assert np.array_equal(with_hidden, without)

    def test_output_is_deterministic(self):
        import numpy as np

        geo = sphere(16, 10)
        bounds = raster.compute_bounds(geo)
        first = np.asarray(raster.render_solid(geo, 64, bounds))
        second = np.asarray(raster.render_solid(geo, 64, bounds))
        assert np.array_equal(first, second)
