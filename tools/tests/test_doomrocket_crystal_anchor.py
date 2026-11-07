#!/usr/bin/env python3
"""Exact under-barrel crystal geometry; no selected/enabled particle is implied."""
import hashlib
import json
import math
from pathlib import Path
import unittest

from test_warlock_weapon_pipeline import (
    BinaryFbx, canonical_geometry_points, geometry_by_vertex_count,
    point_centroid, source_points_to_engine, triangulated_fbx_faces,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / 'tools/fixtures/warlock_crystal_anchor.json').read_text())


class CrystalAnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fbx = BinaryFbx(ROOT / DATA['shipping_fbx'])
        cls.points = source_points_to_engine(canonical_geometry_points(cls.fbx, 3308))
        cls.indices = set(range(1858, 1933))

    def close(self, actual, expected, tolerance=1e-10):
        self.assertEqual(len(actual), len(expected))
        for a, b in zip(actual, expected):
            self.assertTrue(math.isfinite(a) and math.isfinite(b))
            self.assertAlmostEqual(a, b, delta=tolerance)

    def test_measured_shipping_identity(self):
        self.assertEqual(hashlib.sha256((ROOT / DATA['shipping_fbx']).read_bytes()).hexdigest(),
                         DATA['shipping_fbx_sha256'])
        self.assertEqual(DATA['crystal_vertex_range_inclusive'], [1858, 1932])

    def test_centroid_tip_mount_and_extent_are_actual_geometry(self):
        self.close(point_centroid(tuple(self.points[i] for i in sorted(self.indices))),
                   DATA['centroid_engine_m'])
        self.close(point_centroid(tuple(self.points[i] for i in DATA['tip_vertex_indices'])),
                   DATA['tip_engine_m'])
        self.close(self.points[DATA['mount_cap_vertex_index']], DATA['mount_engine_m'])
        self.close([max(self.points[i][a] for i in self.indices) -
                    min(self.points[i][a] for i in self.indices) for a in range(3)],
                   DATA['crystal_extent_m'])

    def test_crystal_is_exact_disconnected_component_not_socket_or_barrel(self):
        triangles = triangulated_fbx_faces(geometry_by_vertex_count(self.fbx, 3308))
        touched = set()
        adjacency = {i: set() for i in self.indices}
        for face in triangles:
            overlap = set(face) & self.indices
            if overlap:
                self.assertEqual(len(overlap), 3, 'crystal now connected to other geometry')
                touched.update(face)
                for i in face:
                    adjacency[i].update(set(face) - {i})
        self.assertEqual(touched, self.indices)
        todo = [1858]
        visited = set()
        while todo:
            current = todo.pop()
            if current not in visited:
                visited.add(current)
                todo.extend(adjacency[current] - visited)
        self.assertEqual(visited, self.indices)

    def test_frame_is_right_handed_and_points_from_mount_towards_tip(self):
        x, y, z = [DATA['frame_' + a + '_axis'] for a in 'xyz']
        dot = lambda a, b: sum(v * w for v, w in zip(a, b))
        for axis in (x, y, z):
            self.assertAlmostEqual(dot(axis, axis), 1)
        self.assertAlmostEqual(dot(x, y), 0)
        self.assertAlmostEqual(dot(x, z), 0)
        self.assertAlmostEqual(dot(y, z), 0)
        self.close((x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2],
                    x[0]*y[1]-x[1]*y[0]), z)
        direction = [t-b for t,b in zip(DATA['tip_engine_m'], DATA['mount_engine_m'])]
        length = math.sqrt(dot(direction, direction))
        self.close([v/length for v in direction], x)


if __name__ == '__main__':
    unittest.main(verbosity=2)
