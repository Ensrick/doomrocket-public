"""CI-safe checks for measured hose metadata; no Blender, SDK or artist files."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import unittest
import sys

if sys.flags.optimize:
    raise RuntimeError('Run the measured contract checks without -O/PYTHONOPTIMIZE; assertions are required.')

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
CONTRACT = json.loads((BASE / 'runtime_contract.json').read_text(encoding='utf-8'))
CHIMNEY = json.loads((ROOT / 'tools/fixtures/warlock_chimney_anchor.json').read_text(encoding='utf-8'))
SOURCE_SHA = 'ab6ebc9ef45cea6e402bbd0415c2d40716824552c2ab514947902d1eac06c1b2'


def distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def product(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def check_frame(frame, expected_scale=1.0):
    assert len(frame) == 4 and all(len(row) == 4 for row in frame)
    assert all(math.isfinite(value) for row in frame for value in row)
    assert frame[3] == [0, 0, 0, 1]
    axes = [[frame[r][c] / expected_scale for r in range(3)] for c in range(3)]
    for i, a in enumerate(axes):
        for j, b in enumerate(axes):
            assert abs(sum(x * y for x, y in zip(a, b)) - (1 if i == j else 0)) < 3e-6
    x, y, z = axes
    determinant = x[0] * (y[1]*z[2] - y[2]*z[1]) - y[0] * (x[1]*z[2] - x[2]*z[1]) + z[0] * (x[1]*y[2] - x[2]*y[1])
    assert abs(determinant - 1) < 3e-6


def validate_contract(data):
    assert data['prototype_only'] is True
    assert data['source_scene_sha256'] == SOURCE_SHA
    assert data['source_hose_vertex_range'] == [3308, 4915]
    assert data['geometry_vertices'] == data['geometry_polygons'] == 1608
    assert data['material'] == 'DoomRocket_Weapon'
    assert data['units'] == 'metres'
    assert data['fbx_axes'] == {'axis_forward': 'Y', 'axis_up': 'Z'}
    assert 'sibling' in data['hierarchy'] and 'Column-vector' in data['bone_axis_convention']

    controls = data['controls']
    lengths = data['control_rest_lengths_m']
    assert [c['name'] for c in controls] == [f'j_hose_{i:02d}' for i in range(29)]
    expected_ring_ids = sorted({section * 14 + ring for section in range(7) for ring in (0, 4, 7, 10, 14)})
    assert [c['ring_index'] for c in controls] == expected_ring_ids
    assert len(lengths) == 28 and all(math.isfinite(x) and x > 0 for x in lengths)
    assert min(lengths) > .064 and max(lengths) < .105
    assert max(lengths) - min(lengths) > .04
    assert abs(sum(lengths) - 2.3238061919335924) < 1e-8
    assert abs(data['source_ring_arc_length_m'] - 2.328132847231959) < 1e-8
    positions = []
    for control in controls:
        check_frame(control['frame'])
        positions.append([control['frame'][r][3] for r in range(3)])
    for a, b, length in zip(positions, positions[1:], lengths):
        assert abs(distance(a, b) - length) < 1e-8

    pack = data['endpoints']['pack']
    weapon = data['endpoints']['weapon']
    assert pack['bone'] == controls[0]['name'] and weapon['bone'] == controls[-1]['name']
    assert pack['target_resource'] == 'units/warlock_bombardier/warlock_bombardier_3p'
    assert pack['target_node'] == 'j_backpack' and pack['source_cap_vertex'] == 5426
    assert pack['body_fbx_sha256'] == CHIMNEY['shipping_fbx_sha256']
    assert pack['body_unit_sha256'] == CHIMNEY['compiled_unit_sha256']
    check_frame(pack['target_local_frame'], .01)
    check_frame(product(CHIMNEY['compiled_pose_column_matrix'], pack['target_local_frame']))
    cap = [v / 100 for v in pack['source_cap_mesh_cm']] + [1]
    expected_cap = [sum(a*b for a, b in zip(row, cap)) for row in CHIMNEY['compiled_inverse_bind_column_matrix']]
    assert distance(expected_cap[:3], [pack['target_local_frame'][r][3] for r in range(3)]) < 1e-8
    assert pack['source_world_frame'] == controls[0]['frame']

    assert weapon['target_resource'] == 'units/rocket/pRocketLauncher'
    assert weapon['target_node'] == 'pRocketLauncher'
    assert weapon['socket_ring_source_indices'] == [1749,1750,1751,1752,1761,1762,1763,1772,1773,1774,1775,1776]
    assert weapon['insertion_m'] == .001
    assert 'Not artist-confirmed' in weapon['inference']
    check_frame(weapon['target_canonical_frame_m'])
    check_frame(weapon['target_local_frame'], .01)
    grip = [-.00002098033, -.91097664833, .06153465062]
    expected_socket = [v+d-n*.001 for v, d, n in zip(weapon['socket_source_world_center'], grip, weapon['socket_outward_normal'])]
    assert distance(expected_socket, [weapon['target_canonical_frame_m'][r][3] for r in range(3)]) < 1e-7
    for r in range(3):
        assert abs(weapon['target_canonical_frame_m'][r][1] + weapon['socket_outward_normal'][r]) < 1e-6
        for c in range(4):
            assert abs(100 * weapon['target_local_frame'][r][c] - weapon['target_canonical_frame_m'][r][c]) < 3e-7
    assert data['offline_checks']['actors'] == 0
    check_frame(data['preview_weapon_world'])


class HoseContractTests(unittest.TestCase):
    def test_reviewed_contract(self):
        validate_contract(CONTRACT)

    def reject(self, mutation):
        value = copy.deepcopy(CONTRACT)
        mutation(value)
        with self.assertRaises(AssertionError):
            validate_contract(value)

    def test_reject_uniform_lengths(self):
        self.reject(lambda d: d.update(control_rest_lengths_m=[sum(d['control_rest_lengths_m']) / 28] * 28))

    def test_reject_wrong_control_name(self):
        self.reject(lambda d: d['controls'][12].update(name='j_hose_99'))

    def test_reject_nonfinite_frame(self):
        self.reject(lambda d: d['controls'][0]['frame'][0].__setitem__(0, float('nan')))

    def test_reject_reflected_control_frame(self):
        def mutate(d):
            for row in d['controls'][3]['frame'][:3]:
                row[0] *= -1
        self.reject(mutate)

    def test_reject_normalized_target_scale(self):
        def mutate(d):
            for row in d['endpoints']['pack']['target_local_frame'][:3]:
                for c in range(3):
                    row[c] *= 100
        self.reject(mutate)

    def test_reject_wrong_target_owner(self):
        self.reject(lambda d: d['endpoints']['weapon'].update(target_node='pRocket'))

    def test_reject_changed_source(self):
        self.reject(lambda d: d.update(source_scene_sha256='0'*64))

    def test_reject_runtime_acceptance_claim(self):
        self.reject(lambda d: d.update(prototype_only=False))


if __name__ == '__main__':
    unittest.main(verbosity=2)
