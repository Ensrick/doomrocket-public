"""Independent quaternion/pose reference must reject unsupported matrices."""
from pathlib import Path
import copy
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'animation_rig'))
import verify_runtime_blend as blend


class NumericReference(unittest.TestCase):
    def test_scaled_rotated_matrix_round_trip(self):
        q=np.array([.3,-.2,.4,.8]);q/=np.linalg.norm(q)
        pose=np.asarray(blend.v.transform((1,2,3),q,(.5,1,1.7)))
        actual=blend.quaternion(pose)
        self.assertAlmostEqual(abs(np.dot(q,actual)),1,places=12)

    def test_negative_scale_rejected(self):
        bad=np.eye(4);bad[0,0]=-1
        with self.assertRaises(ValueError):blend.quaternion(bad)

    def test_shear_rejected(self):
        bad=np.eye(4);bad[0,1]=.1
        with self.assertRaises(ValueError):blend.quaternion(bad)

    def test_antipodal_rotation_has_no_midpoint_flip(self):
        q=np.array([.3,.1,-.2,.8]);q/=np.linalg.norm(q)
        self.assertAlmostEqual(abs(np.dot(blend.slerp(q,-q,.5),q)),1,places=12)

    def test_zero_weight_keeps_snapshot_and_unit_root_is_not_blended(self):
        a={0:np.eye(4),1:np.eye(4)};b={0:np.eye(4),1:np.eye(4)}
        b[0][0,3]=10;b[1][1,3]=2
        out=blend.blend_locals(a,b,0,[1])
        self.assertEqual(out[0][0,3],10);self.assertEqual(out[1][1,3],0)

    def test_invalid_weight_rejected(self):
        with self.assertRaises(ValueError):blend.blend_locals({}, {},float('nan'),[])


class BlendCoverage(unittest.TestCase):
    def fixture(self):
        rows=[dict(direction=d,global_scale=s,source_phase=p,weight=w,bone_comparisons=138,
                   weighted_vertex_samples=35310,max_head_error_m=0.,max_axis_error_m=0.,
                   max_local_matrix_error=0.,max_weighted_skin_error_m=0.,skin_squared_error_sum=0.)
              for d in ('legacy-to-authored','authored-to-legacy') for s in blend.SCALES
              for p in (0.,.5,.999) for w in blend.WEIGHTS]
        return dict(status='actual-lua-partial-snapshot-blend-and-skin-passed',fixed_tolerance_m=.002,
                    clip_count=1,native_Unit_pose_samples=0,SDK_runs=0,weights=list(blend.WEIGHTS),
                    global_scales=list(blend.SCALES),source_phases=[0.,.5,.999],pose_samples=252,
                    ordinary_transition_pose_samples=126,interrupted_transition_pose_samples=126,
                    bone_comparisons=252*138,weighted_vertex_samples=252*35310,
                    pure_authored_zero_write_checks=18,authored_helper_no_legacy_bone_write_checks=126,
                    clips=[dict(clip='combat_idle',unchanged_compiled_tracks=138,samples=rows,
                                legacy_builder_pose_checks=9,legacy_builder_max_head_error_m=0.,
                                legacy_builder_max_axis_error_m=0.)],
                    interruptions=[dict(clip='combat_idle',**copy.deepcopy(row)) for row in rows])

    def test_complete_clip_is_partial_until_thirteen_merge(self):
        self.assertEqual(blend.validate_shard(self.fixture(),{'combat_idle'}),'combat_idle')

    def test_duplicate_weight_row_cannot_hide_missing_endpoint(self):
        report=self.fixture();report['clips'][0]['samples'][-1]=copy.deepcopy(report['clips'][0]['samples'][0])
        with self.assertRaises(ValueError):blend.validate_shard(report,{'combat_idle'})

    def test_nan_skin_measurement_rejected(self):
        report=self.fixture();report['interruptions'][4]['max_weighted_skin_error_m']=float('nan')
        with self.assertRaises(ValueError):blend.validate_shard(report,{'combat_idle'})

    def test_one_real_failure_cannot_be_hidden_in_summary(self):
        report=self.fixture();report['clips'][0]['samples'][0]['max_weighted_skin_error_m']=.0021
        with self.assertRaises(ValueError):blend.validate_shard(report,{'combat_idle'})

    def test_less_than_full_skin_inventory_rejected(self):
        report=self.fixture();report['interruptions'][0]['weighted_vertex_samples']=29123
        with self.assertRaises(ValueError):blend.validate_shard(report,{'combat_idle'})

    def test_missing_independent_legacy_endpoint_probes_rejected(self):
        report=self.fixture();report['clips'][0]['legacy_builder_pose_checks']=0
        with self.assertRaises(ValueError):blend.validate_shard(report,{'combat_idle'})

    def test_current_scope_must_not_claim_native_capture(self):
        report=self.fixture();report['native_Unit_pose_samples']=252
        with self.assertRaises(ValueError):blend.validate_shard(report,{'combat_idle'})


if __name__=='__main__':unittest.main()
