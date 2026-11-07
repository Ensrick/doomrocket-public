"""Mutation gates for the native-duration-derived final runtime receipt."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'animation_rig'))
from verify_runtime_acceptance import validate_coverage


class RuntimeAcceptance(unittest.TestCase):
    def fixture(self):
        count=481
        return {'clip':'combat_idle.fbx','sample_fps':240,'pose_samples':count,'expected_pose_samples':count,
                'bone_comparisons':count*138,'weighted_vertex_samples':count*35310,'unchanged_compiled_tracks':138,
                'max_head_error_m':1e-6,'max_axis_error_m':2e-6,'max_weighted_skin_error_m':.001,
                'weighted_skin_rms_m':.0003,'grip_status_counts':{'active':count},
                'regions':{name:{'vertex_samples':count*(35305 if name=='body' else 1),'max_error_m':.001,'rms_error_m':.0003}
                           for name in ('body','backpack','waist_belt','buckle','buckle_trim','lower_coat')}}
    def test_native_duration_derived_complete_schedule(self):validate_coverage(self.fixture(),1.)
    def test_rate_label_mutation_rejected(self):
        c=self.fixture();c['sample_fps']=30
        with self.assertRaises(ValueError):validate_coverage(c,1.)
    def test_jointly_shortened_labels_rejected(self):
        c=self.fixture();c['pose_samples']=c['expected_pose_samples']=31
        c['bone_comparisons']=31*138;c['weighted_vertex_samples']=31*35310
        with self.assertRaises(ValueError):validate_coverage(c,1.)
    def test_nonfinite_maximum_rejected(self):
        c=self.fixture();c['max_axis_error_m']=float('nan')
        with self.assertRaises(ValueError):validate_coverage(c,1.)
    def test_missing_weighted_region_rejected(self):
        c=self.fixture();c['regions'].pop('lower_coat')
        with self.assertRaises(ValueError):validate_coverage(c,1.)
    def test_missing_grip_invocation_rejected(self):
        c=self.fixture();c['grip_status_counts']['active']-=1
        with self.assertRaises(ValueError):validate_coverage(c,1.)


if __name__=='__main__':unittest.main()
