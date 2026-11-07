"""Bounded compatibility staging guards; these do not exercise engine playback."""
import unittest
from runtime_pose_probe import compatibility_timeline


class CompatibilityStagingGuards(unittest.TestCase):
    def clip(self,name,rate,count=1600):
        return {'clip':name,'sample_fps':rate,'independent_roundtrip':{'sample_count':count}}
    def test_final_960_death_plan(self):
        rate,count=compatibility_timeline(self.clip('death_shot.fbx',960))
        self.assertEqual(rate,960)
        self.assertAlmostEqual((count-1)/rate,1.665625)
    def test_final_240_ordinary_plan(self):
        self.assertEqual(compatibility_timeline(self.clip('combat_idle.fbx',240)),(240,1600))
    def test_more_than_fourfold_rate_rejected(self):
        for name,rate in [('combat_idle.fbx',480),('death_shot.fbx',1920),('stagger_fwd.fbx',720)]:
            with self.assertRaises(ValueError): compatibility_timeline(self.clip(name,rate))
    def test_unbounded_or_boolean_count_rejected(self):
        for count in (10001,True,1):
            with self.assertRaises(ValueError): compatibility_timeline(self.clip('death_shot.fbx',960,count))


if __name__=='__main__':
    unittest.main()
