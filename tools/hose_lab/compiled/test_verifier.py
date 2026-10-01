"""CI-safe compiled-verifier mutation tests; standard library and synthetic data."""
import ast
import copy
from pathlib import Path
import subprocess
import sys
import unittest

import verify_asset
import verifier_core as core

BASE = Path(__file__).resolve().parent
IDENTITY = ((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1))
SCALE_100 = ((100,0,0,0),(0,100,0,0),(0,0,100,0),(0,0,0,1))
QUAD = [(0,1,2,3)]
FAN = [(0,1,2),(0,2,3)]
DIAGONAL = [(0,1,3),(1,2,3)]


class VerifierTests(unittest.TestCase):
    def topology(self, triangles=FAN, faces=QUAD, mapping=(0,1,2,3)):
        return core.validate_topology(faces, (0,1,2,3), triangles, mapping)

    def weights(self, values, indices=(0,0,0,0)):
        return core.decode_influences(indices, values, [0], [5], {5: 'bone'})

    def test_import_has_no_cli_or_asset_access(self):
        self.assertTrue(callable(verify_asset.audit))
        self.assertTrue(callable(verify_asset.main))

    def test_acceptance_code_contains_no_removable_asserts(self):
        for path in (BASE/'verify_asset.py', BASE/'verifier_core.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            self.assertFalse(any(isinstance(node, ast.Assert) for node in ast.walk(tree)), path.name)

    def test_validation_survives_optimized_python_without_site_packages(self):
        script = '''
import verify_asset
from verifier_core import *
mutations = [lambda: require(False, 'gate'),
    lambda: decode_influences((0,0,0,0),(1,0,float('nan'),0),[0],[5],{5:'bone'}),
    lambda: validate_topology([(0,1,2,3)],(0,1,2,3),[(0,2,1),(0,3,2)],(0,1,2,3))]
for mutation in mutations:
    try:
        mutation()
    except VerificationError:
        continue
    raise SystemExit('Invalid data passed under -O')
'''
        result = subprocess.run([sys.executable, '-S', '-O', '-c', script], cwd=BASE, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_valid_unused_weight_slots(self):
        self.assertEqual(self.weights((1,0,0,0)), {'bone': 1})

    def test_nan_in_unused_slot_is_rejected(self):
        with self.assertRaises(core.VerificationError):
            self.weights((1,0,float('nan'),0))

    def test_negative_unused_slot_is_rejected(self):
        with self.assertRaises(core.VerificationError):
            self.weights((1,0,-.01,0))

    def test_infinite_weight_is_rejected(self):
        with self.assertRaises(core.VerificationError):
            self.weights((1,0,0,float('inf')))

    def test_invalid_unused_palette_index_is_rejected(self):
        with self.assertRaises(core.VerificationError):
            self.weights((1,0,0,0), (0,0,0,7))

    def test_either_quad_diagonal_is_accepted(self):
        self.assertEqual(self.topology(FAN), self.topology(DIAGONAL))

    def test_cyclic_polygon_start_is_irrelevant(self):
        self.assertEqual(self.topology(), self.topology(faces=[(2,3,0,1)]))

    def test_reversed_winding_is_rejected(self):
        with self.assertRaises(core.VerificationError):
            self.topology([(0,2,1),(0,3,2)])

    def test_one_reversed_triangle_is_rejected(self):
        with self.assertRaises(core.VerificationError):
            self.topology([(0,2,1),(0,2,3)])

    def test_missing_triangle_is_rejected(self):
        with self.assertRaises(core.VerificationError):
            self.topology(FAN[:1])

    def test_extra_triangle_is_rejected(self):
        with self.assertRaises(core.VerificationError):
            self.topology(FAN + FAN[:1])

    def test_wrong_diagonal_pair_is_rejected(self):
        with self.assertRaises(core.VerificationError):
            self.topology([(0,1,2),(0,1,3)])

    def test_duplicate_source_polygon_multiplicity_is_preserved(self):
        self.assertEqual(self.topology(FAN+DIAGONAL, QUAD*2)['triangles'], 4)
        with self.assertRaises(core.VerificationError):
            self.topology(FAN, QUAD*2)

    def test_missing_canonical_vertex_is_rejected(self):
        with self.assertRaises(core.VerificationError):
            self.topology(mapping=(0,1,2,2))

    def test_unreferenced_compiled_vertex_is_rejected(self):
        with self.assertRaises(core.VerificationError):
            self.topology(mapping=(0,1,2,3,0))

    def test_seam_weld_and_complete_coverage(self):
        canonical, members, mapping = core.weld_positions([(0,0,0),(1,0,0),(0,.0000002,0)])
        self.assertEqual(mapping, [0,1,0])
        self.assertEqual(members, [[0,2],[1]])
        self.assertEqual(core.map_positions([(0,0,0),(1,0,0)], canonical)[0], [0,1])
        with self.assertRaises(core.VerificationError):
            core.map_positions([(0,0,0)], canonical)

    def test_nonfinite_position_is_rejected(self):
        with self.assertRaises(core.VerificationError):
            core.map_positions([(float('nan'),0,0)], [(0,0,0)])

    def test_nonfinite_matrix_is_rejected(self):
        matrix = [list(row) for row in IDENTITY]
        matrix[2][1] = float('nan')
        with self.assertRaises(core.VerificationError):
            core.check_matrix(matrix)

    def deformation_data(self):
        controls = [{'name': 'a', 'frame': IDENTITY}, {'name': 'b', 'frame': IDENTITY}]
        profiles = [{'name': c['name'], 'compiled_inverse_bind': IDENTITY,
                     'control_to_compiled_bone': SCALE_100} for c in controls]
        return controls, profiles

    def test_true_weighted_lbs_uses_distinct_per_bone_targets(self):
        controls, profiles = self.deformation_data()
        weights = {0: {'a': .25, 'b': .75}}
        errors = core.validate_deformation([(1,2,3)], weights, [(.01,.02,.03)], weights,
            [0], [[0]], controls, profiles, tolerance=1e-10)
        self.assertEqual(len(errors), 3)
        targets = core.pose_targets(controls, 1)
        self.assertNotEqual(targets['a'], targets['b'])
        wrong_weights = {0: {'a': .75, 'b': .25}}
        with self.assertRaises(core.VerificationError):
            core.validate_deformation([(1,2,3)], weights, [(.01,.02,.03)], wrong_weights,
                [0], [[0]], controls, profiles, tolerance=1e-6)

    def test_missing_mesh_bind_scale_is_rejected(self):
        controls, profiles = self.deformation_data()
        profiles = copy.deepcopy(profiles)
        for profile in profiles:
            profile['control_to_compiled_bone'] = IDENTITY
        weights = {0: {'a': .25, 'b': .75}}
        with self.assertRaises(core.VerificationError):
            core.validate_deformation([(1,2,3)], weights, [(.01,.02,.03)], weights,
                [0], [[0]], controls, profiles)


if __name__ == '__main__':
    unittest.main(verbosity=2)
