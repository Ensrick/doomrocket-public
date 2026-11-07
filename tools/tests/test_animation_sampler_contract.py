"""A pose sampler may remove transition blending, but not change its targets."""
from pathlib import Path
import copy
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'animation_rig'))
from compiled_integration import verify_sampler_states


class SamplerContract(unittest.TestCase):
    def fixtures(self):
        visible={11:{'animations':(101,),'constraints':(),
            'transitions':[{'event':1,'target_index':1,'blend_time':.25,'mode':0,'on_beat':0}]},
            12:{'animations':(102,),'constraints':(0,),
            'transitions':[{'event':2,'target_index':0,'blend_time':.25,'mode':0,'on_beat':0}]}}
        helper=copy.deepcopy(visible)
        for state in helper.values():
            for edge in state['transitions']:edge['blend_time']=0.
        return visible,helper

    def test_zero_edges_preserve_events_and_owner_constraints(self):
        a,b=self.fixtures();self.assertEqual(verify_sampler_states(a,b),2)

    def test_nonzero_endpoint_blend_rejected(self):
        a,b=self.fixtures();b[11]['transitions'][0]['blend_time']=.25
        with self.assertRaises(ValueError):verify_sampler_states(a,b)

    def test_wrong_clip_rejected(self):
        a,b=self.fixtures();b[11]['animations']=(102,)
        with self.assertRaises(ValueError):verify_sampler_states(a,b)

    def test_aim_reintroduced_into_custom_pose_rejected(self):
        a,b=self.fixtures();b[11]['constraints']=(0,)
        with self.assertRaises(ValueError):verify_sampler_states(a,b)

    def test_destination_rejected(self):
        a,b=self.fixtures();b[11]['transitions'][0]['target_index']=0
        with self.assertRaises(ValueError):verify_sampler_states(a,b)

    def test_missing_event_rejected(self):
        a,b=self.fixtures();b[11]['transitions']=[]
        with self.assertRaises(ValueError):verify_sampler_states(a,b)

    def test_different_state_order_uses_state_identity(self):
        a,b=self.fixtures();b={12:b[12],11:b[11]}
        b[11]['transitions'][0]['target_index']=0;b[12]['transitions'][0]['target_index']=1
        self.assertEqual(verify_sampler_states(a,b),2)

    def test_out_of_bounds_destination_rejected(self):
        a,b=self.fixtures();b[11]['transitions'][0]['target_index']=100
        with self.assertRaises(ValueError):verify_sampler_states(a,b)


if __name__=='__main__':unittest.main()
