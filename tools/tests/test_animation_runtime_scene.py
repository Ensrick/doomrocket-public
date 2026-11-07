"""Actual Lua solver against independent float32 local/world scene storage."""
from pathlib import Path
from types import SimpleNamespace
import copy
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'animation_rig'))
import verify_runtime_outfit as runtime


def fixture():
    names=['root','j_hips','j_loot_sack']+runtime.CHANNELS+[
        'j_spine','j_spine1','j_leftshoulder','j_rightshoulder','j_leftarm','j_rightarm',
        'j_leftforearm','j_rightforearm','j_lefthand','j_righthand','j_leftforearmroll','j_rightforearmroll']
    indices={n:i for i,n in enumerate(names)}
    parents={0:None,1:0,2:1}
    for n in runtime.CHANNELS:
        parents[indices[n]]=indices['j_whip_parent'] if n=='j_whip_dynamic' else (1 if n=='j_whip_parent' else 2)
    for n in names[10:]:parents[indices[n]]=1
    parents[indices['j_spine1']]=indices['j_spine']
    offsets={n:np.eye(4) for n in runtime.CHANNELS}
    for i,n in enumerate(runtime.CHANNELS):offsets[n][:3,3]=(.05+i*.02,.03,.1)
    profile={'unit':runtime.v.UNIT,'accessory_skin':'localized-v1','native_bind_scale':100,'reference_bone':'j_hips',
             'manifest_id':'a'*64,'body_fbx_sha256':'b'*64,
             'shipping_body_sha256':'cb2eba0224d1eff044a30b1bf0269d1a10395e8db9244af5c011e5c0ba0bd0bc',
             'shipping_bones_sha256':'6e4eb323ba5a21db1e2f09f91d73cfa1e3234a03d7b183223f48ccd96c51a197',
             'rest_contract_sha256':'e'*64,
             'channels':[{'bone':n,'parent':names[parents[indices[n]]],'bind_offset':offsets[n].tolist()} for n in runtime.CHANNELS]}
    manifest={'schema':1,'profiles':{'localized-v1-runtime':profile}}
    metadata={'warlock_rig_profile':'localized-v1-runtime','warlock_animation_manifest_id':'a'*64}
    sampler=SimpleNamespace(indices=indices,parents=parents)
    locals_={i:np.eye(4) for i in range(len(names))};locals_[0][:3,:3]*=100
    locals_[1][:3,3]=(.001,.002,.003)
    for i in range(2,len(names)):locals_[i][:3,3]=(.0001,.0002,.0003)
    return sampler,locals_,manifest,metadata,offsets


class RuntimeScene(unittest.TestCase):
    def scene(self,manifest_change=None,metadata_change=None):
        sampler,poses,manifest,metadata,offsets=fixture()
        if manifest_change:manifest_change(manifest)
        if metadata_change:metadata_change(metadata)
        scene=runtime.LuaPoseScene(sampler,sampler,manifest,metadata);scene.reset(poses,poses)
        return scene,offsets

    def test_actual_seven_writes_recompose_corrected_child(self):
        scene,offsets=self.scene();scene.start();before=scene.worlds()
        expected=runtime.corrected_expectation(before,offsets)
        self.assertTrue(scene.apply()[0]);self.assertEqual(scene.written,scene.corrective_nodes)
        head,axis,_=runtime.probe_errors(scene.worlds(),expected,list(before))
        self.assertLess(max(head,axis),2e-6)
        for n in before:
            if n not in runtime.CHANNELS:self.assertTrue(np.array_equal(before[n],scene.worlds()[n]))

    def test_hundredfold_metre_offset_rejected_before_writes(self):
        def change(m):
            for c in m['profiles']['localized-v1-runtime']['channels']:
                for r in range(3):c['bind_offset'][r][3]*=100
        scene,_=self.scene(manifest_change=change)
        with self.assertRaises(Exception):scene.start()
        self.assertFalse(scene.written)

    def test_wrong_compiled_marker_rejected_before_writes(self):
        scene,_=self.scene(metadata_change=lambda m:m.update(warlock_animation_manifest_id='f'*64))
        with self.assertRaises(Exception):scene.start()
        self.assertFalse(scene.written)

    def test_authored_ownership_has_zero_correction_writes(self):
        scene,_=self.scene();scene.start();scene.lua.globals().ownership_mode='authored'
        self.assertFalse(scene.apply()[0]);self.assertFalse(scene.written)

    def test_singular_parent_is_atomic_failure(self):
        scene,_=self.scene();scene.start();i=scene.samplers[True].indices['j_loot_sack']
        scene.locals_[True][i][:3,:3]=0;scene.flush(True)
        self.assertFalse(scene.apply()[0]);self.assertFalse(scene.written)

    def test_corpse_handoff_survives_registry_cleanup(self):
        scene,_=self.scene();scene.start()
        scene.lua.execute('assert(mod._handoff_warlock_outfit_correction(owner,outfit));mod._warlock_outfits={};HEALTH_ALIVE[owner]=false')
        g=scene.lua.globals()
        self.assertTrue(g.mod._apply_warlock_outfit_correction(g.owner,g.outfit,True))
        self.assertEqual(scene.written,scene.corrective_nodes)


if __name__=='__main__':unittest.main()
