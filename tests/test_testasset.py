"""Tests fuer den Testasset-Generator.

Anlass: die geschriebene OBJ-Datei enthielt Vertexindizes mit einem Versatz
von eins. OBJ zaehlt ab 1, das Modul intern ab 0, und die Umrechnung stand an
zwei Stellen unterschiedlich. Im Speicher war die Geometrie korrekt -- nur die
Datei nicht, und Blender liest die Datei.

Kein einziger bestehender Test hat das gefunden, weil alle direkt gegen die
In-Memory-Geometrie liefen. Diese hier gehen ueber die Datei.
"""

import pytest

from tools.make_testasset import box, cylinder, torture_rig, uv_sphere, write_obj


def parse_obj(path):
    """Unabhaengiger Parser: liest zurueck, was tatsaechlich in der Datei steht."""
    vertices, uvs, faces = [], [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            vertices.append([float(x) for x in parts[1:4]])
        elif parts[0] == "vt":
            uvs.append([float(x) for x in parts[1:3]])
        elif parts[0] == "f":
            faces.append([int(t.split("/")[0]) for t in parts[1:4]])
    return vertices, uvs, faces


SHAPES = {
    "sphere": lambda: uv_sphere(16, 10),
    "torture": torture_rig,
}


class TestIndexConvention:
    @pytest.mark.parametrize("shape", ["sphere", "torture"])
    def test_generators_are_zero_based(self, shape):
        _, _, faces = SHAPES[shape]()
        assert min(min(f) for f in faces) >= 0

    @pytest.mark.parametrize("shape", ["sphere", "torture"])
    def test_file_is_one_based(self, shape, tmp_path):
        # Genau der Fehler: 0-basierte Indizes landeten unveraendert in einem
        # Format, das ab 1 zaehlt. Index 0 ist in OBJ ungueltig.
        positions, uvs, faces = SHAPES[shape]()
        path = tmp_path / "t.obj"
        write_obj(path, positions, uvs, faces)
        _, _, file_faces = parse_obj(path)
        assert min(min(f) for f in file_faces) >= 1

    @pytest.mark.parametrize("shape", ["sphere", "torture"])
    def test_roundtrip_preserves_topology(self, shape, tmp_path):
        positions, uvs, faces = SHAPES[shape]()
        path = tmp_path / "t.obj"
        write_obj(path, positions, uvs, faces)
        file_verts, file_uvs, file_faces = parse_obj(path)

        assert len(file_verts) == len(positions)
        assert len(file_uvs) == len(uvs)
        assert len(file_faces) == len(faces)
        # Nach Ruecknahme der 1-Basierung muss exakt dieselbe Topologie stehen.
        assert [[i - 1 for i in f] for f in file_faces] == [list(f) for f in faces]

    @pytest.mark.parametrize("shape", ["sphere", "torture"])
    def test_file_indices_within_range(self, shape, tmp_path):
        positions, uvs, faces = SHAPES[shape]()
        path = tmp_path / "t.obj"
        write_obj(path, positions, uvs, faces)
        file_verts, _, file_faces = parse_obj(path)
        assert max(max(f) for f in file_faces) <= len(file_verts)


class TestWriteObjGuards:
    def test_rejects_negative_index(self, tmp_path):
        with pytest.raises(ValueError, match="Negativer Vertexindex"):
            write_obj(tmp_path / "t.obj", [(0, 0, 0)], [(0, 0)], [(-1, 0, 0)])

    def test_rejects_out_of_range_index(self, tmp_path):
        with pytest.raises(ValueError, match="hinter das Ende"):
            write_obj(tmp_path / "t.obj", [(0, 0, 0)], [(0, 0)], [(0, 1, 2)])


class TestPrimitives:
    def test_box_has_twelve_triangles(self):
        positions, faces = box(0, 0, 0, 1, 1, 1)
        assert len(positions) == 8
        assert len(faces) == 12

    def test_cylinder_indices_within_range(self):
        positions, faces = cylinder(0, 0, 0, 0.1, 1.0, segments=12)
        assert max(max(f) for f in faces) < len(positions)

    def test_torture_rig_mixes_feature_sizes(self):
        # Der Zweck des Objekts: dicke und duenne Teile im selben Mesh.
        positions, _, faces = torture_rig()
        assert len(faces) > 1000
        zs = [p[2] for p in positions]
        assert max(zs) - min(zs) > 1.0  # aufrecht, nicht flach
