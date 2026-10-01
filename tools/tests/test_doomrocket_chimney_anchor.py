#!/usr/bin/env python3
"""Measured chimney/skin attachment contract; no Blender or game install needed.

Source FBX checks always run. Existing compiled packages are also checked so a
changed body, skin bind, or stale package cannot silently keep an old offset.
These establish coordinates and ownership, not visible in-game smoke acceptance.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
import sys
import unittest
from pathlib import Path

from lupa.lua51 import LuaRuntime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_warlock_weapon_pipeline import (
    BinaryFbx, PackedCursor, clean_fbx_name, compiled_bundle_resources,
    compiled_node_index, compiled_unit_structure, geometry_by_vertex_count,
    identity_matrix, matrix_multiply, raw_geometry_points, resource_key,
    transform_point,
)

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / 'scripts/mods/doomrocket/utils/doomrocket_chimney_anchor.lua'
FIXTURE = json.loads((ROOT / 'tools/fixtures/warlock_chimney_anchor.json').read_text())


def profile() -> dict:
    value = LuaRuntime().execute(PROFILE_PATH.read_text())
    return {'node': value['node'], **{
        name: [value[name][i] for i in range(1, 4)]
        for name in ('x_axis', 'y_axis', 'z_axis', 'position')
    }}


def profile_matrix(value: dict) -> tuple:
    # Stingray x/y/z setters take basis vectors. In column-vector notation they
    # are columns, although Stingray Lua commonly describes row-vector products.
    columns = [value[key] for key in ('x_axis', 'y_axis', 'z_axis', 'position')]
    return tuple(tuple(columns[col][row] for col in range(4)) for row in range(3)) + ((0, 0, 0, 1),)


def expected_frame() -> tuple:
    translation = [list(row) for row in identity_matrix()]
    for axis in range(3):
        translation[axis][3] = FIXTURE['rim_centroid_mesh_cm'][axis] * .01
    return matrix_multiply(FIXTURE['compiled_inverse_bind_column_matrix'], translation)


def validate_frame(value: dict) -> None:
    if value['node'] != FIXTURE['node']:
        raise AssertionError('chimney must belong to the weighted backpack node')
    matrix = profile_matrix(value)
    expected = expected_frame()
    if any(not math.isfinite(x) for row in matrix for x in row):
        raise AssertionError('anchor contains a non-finite value')
    if max(abs(matrix[r][c] - expected[r][c]) for r in range(4) for c in range(4)) > 1e-10:
        raise AssertionError('anchor differs from measured compiled inverse-bind frame')


def centroid(points):
    return tuple(sum(p[a] for p in points) / len(points) for a in range(3))


def norm(v):
    return math.sqrt(sum(x*x for x in v))


def source_rim():
    fbx = BinaryFbx(ROOT / FIXTURE['shipping_fbx'])
    geometry = geometry_by_vertex_count(fbx, FIXTURE['shipping_mesh_vertices'])
    all_points = raw_geometry_points(geometry)
    indices = [i + FIXTURE['shipping_vertex_index_offset'] for i in FIXTURE['source_rim_indices']]
    return fbx, geometry, indices, tuple(all_points[i] for i in indices)


def fbx_positive_weights(fbx, geometry, indices):
    connections = [n.properties for n in fbx.descendants('C') if n.properties[0] == 'OO']
    models = {n.properties[0]: clean_fbx_name(n.properties[1]) for n in fbx.object_nodes('Model')}
    deformers = {n.properties[0]: n for n in fbx.object_nodes('Deformer')}
    skins = {child for _, child, parent in connections if parent == geometry.properties[0] and child in deformers}
    weights = {i: [] for i in indices}
    for cluster_id, cluster in deformers.items():
        if cluster.properties[2] != 'Cluster' or not any(child == cluster_id and parent in skins for _, child, parent in connections):
            continue
        bones = [models[child] for _, child, parent in connections if parent == cluster_id and child in models]
        if len(bones) != 1:
            raise AssertionError('skin cluster must identify exactly one bone')
        if not any(n.name in ('Indexes','Weights') for n in cluster.children):
            continue  # Exported unused bones have an empty, valid skin cluster.
        for index, weight in zip(cluster.child('Indexes').properties[0], cluster.child('Weights').properties[0]):
            if index in weights and weight > 0:
                weights[index].append((bones[0], weight))
    return weights


def compiled_skin_prefix(payload):
    """Parse only documented v189 stream/batch/skin fields, not game runtime data."""
    cur = PackedCursor(payload)
    if cur.u32() != 189:
        raise AssertionError('unreviewed compiled unit version')
    geometries = []
    for _ in range(cur.u32()):
        streams = []
        for _ in range(cur.u32()):
            data = cur.byte_array()
            streams.append((data, struct.unpack('<4I', cur.take(16))))
        channels = [struct.unpack('<4IB', cur.take(17)) for _ in range(cur.u32())]
        cur.skip(16)
        cur.byte_array()
        batches = [struct.unpack('<4I', cur.take(16)) for _ in range(cur.u32())]
        cur.skip(28)
        cur.skip(cur.u32()*4)
        geometries.append((streams, channels, batches))
    skins = []
    for _ in range(cur.u32()):
        binds = []
        for _ in range(cur.u32()):
            values = struct.unpack('<16f', cur.take(64))
            binds.append(tuple(tuple(values[c*4+r] for c in range(4)) for r in range(4)))
        nodes = [cur.u32() for _ in range(cur.u32())]
        sets = [[cur.u32() for _ in range(cur.u32())] for _ in range(cur.u32())]
        skins.append((binds, nodes, sets))
    return geometries, skins


class ChimneyAnchorSourceTests(unittest.TestCase):
    def test_profile_loads_without_engine_and_matches_bind(self):
        validate_frame(profile())

    def test_shipping_fbx_is_the_measured_asset(self):
        payload = (ROOT / FIXTURE['shipping_fbx']).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), FIXTURE['shipping_fbx_sha256'], 'Remeasure chimney after any body FBX change')

    def test_actual_shipping_top_lip_centroid_and_plane(self):
        _, _, indices, points = source_rim()
        self.assertEqual(len(set(indices)), 32)
        for actual, expected in zip(centroid(points), FIXTURE['rim_centroid_mesh_cm']):
            self.assertAlmostEqual(actual, expected, delta=2e-5)
        self.assertLess(max(p[2] for p in points) - min(p[2] for p in points), 1e-4)
        centre = centroid(points)
        radii = [norm((p[0]-centre[0], p[1]-centre[1]))*.01 for p in points]
        inner, outer = [r for r in radii if r < .07], [r for r in radii if r > .07]
        self.assertEqual((len(inner), len(outer)), (16,16))
        self.assertAlmostEqual(sum(inner)/16, FIXTURE['rim_inner_radius_m'], delta=1e-6)
        self.assertAlmostEqual(sum(outer)/16, FIXTURE['rim_outer_radius_m'], delta=1e-6)

    def test_shipping_rim_is_rigidly_weighted_to_backpack(self):
        fbx, geometry, indices, _ = source_rim()
        for weights in fbx_positive_weights(fbx, geometry, indices).values():
            self.assertEqual(weights, [(FIXTURE['node'], 1.0)])

    def test_native_positive_z_maps_outward(self):
        value = profile()
        axis = value['z_axis']
        bind = FIXTURE['compiled_inverse_bind_column_matrix']
        expected = tuple(bind[r][2] for r in range(3))
        dot = sum(a*b for a,b in zip(axis,expected)) / (norm(axis)*norm(expected))
        self.assertGreater(dot, .999999999)

    def test_scale_100_wrapper_is_cancelled(self):
        matrix = profile_matrix(profile())
        for c in range(3):
            self.assertAlmostEqual(norm([matrix[r][c] for r in range(3)]), .01, delta=2e-8)
        world = matrix_multiply(FIXTURE['compiled_pose_column_matrix'], matrix)
        for c in range(3):
            self.assertAlmostEqual(norm([world[r][c] for r in range(3)]), 1.0, delta=2e-6)

    def test_same_skin_equation_at_other_bone_poses(self):
        matrix = profile_matrix(profile())
        inverse_bind = FIXTURE['compiled_inverse_bind_column_matrix']
        _, _, _, rim = source_rim()
        poses = [FIXTURE['compiled_pose_column_matrix'],
                 ((0,-100,0,3),(100,0,0,-2),(0,0,100,5),(0,0,0,1)),
                 ((100,0,0,-20),(0,0,-100,10),(0,100,0,2),(0,0,0,1))]
        for pose in poses:
            actual = transform_point(matrix_multiply(pose,matrix), (0,0,0))
            skin = matrix_multiply(pose,inverse_bind)
            expected = centroid([transform_point(skin,tuple(x*.01 for x in p)) for p in rim])
            self.assertLess(norm(tuple(a-b for a,b in zip(actual,expected))), 3e-7)

    def test_normalized_axis_mutation_is_rejected(self):
        mutated = copy.deepcopy(profile())
        for name in ('x_axis','y_axis','z_axis'):
            mutated[name] = [v/norm(mutated[name]) for v in mutated[name]]
        with self.assertRaises(AssertionError): validate_frame(mutated)

    def test_blender_metre_translation_mutation_is_rejected(self):
        mutated = copy.deepcopy(profile())
        mutated['position'] = [v*100 for v in mutated['position']]
        with self.assertRaises(AssertionError): validate_frame(mutated)

    def test_transposed_basis_mutation_is_rejected(self):
        mutated = copy.deepcopy(profile())
        rows = [mutated[n] for n in ('x_axis','y_axis','z_axis')]
        for i,name in enumerate(('x_axis','y_axis','z_axis')):
            mutated[name] = [rows[j][i] for j in range(3)]
        with self.assertRaises(AssertionError): validate_frame(mutated)


@unittest.skipUnless(any((ROOT/'bundleV2').glob('*.mod_bundle')), 'compiled package not present; source-only run')
class ChimneyAnchorCompiledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = compiled_bundle_resources()
        hits = cls.resources[resource_key('unit', FIXTURE['compiled_unit'])]
        if len(hits) != 1: raise AssertionError('compiled body must occur exactly once')
        cls.payload = hits[0][1]
        cls.structure = compiled_unit_structure(cls.payload)
        cls.geometries, cls.skins = compiled_skin_prefix(cls.payload)

    def test_compiled_body_is_the_measured_payload(self):
        self.assertEqual(hashlib.sha256(self.payload).hexdigest(), FIXTURE['compiled_unit_sha256'], 'Remeasure after compiled body changes')

    def test_compiled_inverse_bind_matches_profile_provenance(self):
        index = compiled_node_index(self.structure,FIXTURE['node'])
        self.assertEqual(index,FIXTURE['compiled_node_index'])
        self.assertEqual(len(self.skins),1)
        binds,nodes,_ = self.skins[0]
        self.assertEqual(binds[nodes.index(index)],tuple(tuple(r) for r in FIXTURE['compiled_inverse_bind_column_matrix']))

    def test_compiled_rim_positions_and_positive_weights(self):
        _,_,_,rim = source_rim()
        geometry = self.structure.geometries[0]
        streams,channels,batches = self.geometries[0]
        _,nodes,sets = self.skins[0]
        indices_stream = next(ch[3] for ch in channels if ch[0]==6 and ch[1]==19)
        weight_stream = next(ch[3] for ch in channels if ch[0]==7 and ch[1]==17)
        self.assertEqual(streams[indices_stream][1][3],4)
        self.assertEqual(streams[weight_stream][1][3],8)
        batch_vertices = [set(i for tri in geometry.triangles[start:start+count] for i in tri) for _,start,count,_ in batches]
        for p in rim:
            p = tuple(x*.01 for x in p)
            index = min(range(len(geometry.positions)),key=lambda i: sum((a-b)**2 for a,b in zip(geometry.positions[i],p)))
            self.assertLess(math.dist(geometry.positions[index],p),FIXTURE['compiled_rim_position_tolerance_m'])
            belonging = [i for i,vertices in enumerate(batch_vertices) if index in vertices]
            self.assertEqual(len(belonging),1)
            matrix_set = sets[batches[belonging[0]][3]]
            bone_indices = struct.unpack_from('<4B',streams[indices_stream][0],index*4)
            weights = struct.unpack_from('<4e',streams[weight_stream][0],index*8)
            mapped = [(nodes[matrix_set[b]],w) for b,w in zip(bone_indices,weights) if w>0]
            self.assertEqual(mapped,[(FIXTURE['compiled_node_index'],1.0)])

    def test_anchor_profile_is_in_the_compiled_package(self):
        hits = self.resources.get(resource_key('lua','scripts/mods/doomrocket/utils/doomrocket_chimney_anchor'),[])
        self.assertEqual(len(hits),1,'rebuild stale package to include measured anchor profile')
        for marker in (b'j_backpack',b'x_axis',b'y_axis',b'z_axis',b'position'):
            self.assertIn(marker,hits[0][1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
