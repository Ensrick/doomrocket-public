"""Compiled presence alone must not satisfy actual package load membership."""
from pathlib import Path
import json
import struct
import sys
import unittest
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'animation_rig'))
import package_closure as p


def payload(entries):
    return struct.pack('<I',len(entries))+b''.join(struct.pack('<QQ',*x) for x in entries)+p.PACKAGE_TRAILER


class PackageClosure(unittest.TestCase):
    def test_sampler_must_be_a_loaded_member(self):
        pair=(p.murmur64a(b'state_machine'),p.murmur64a(b'units/body/presentation_sampler'))
        self.assertEqual(p.require_members(payload([pair]),[('state_machine','units/body/presentation_sampler')]),1)

    def test_indexed_but_missing_package_sampler_rejected(self):
        with self.assertRaises(ValueError):
            p.require_members(payload([(1,2)]),[('state_machine','units/body/presentation_sampler')])

    def test_same_name_wrong_resource_type_rejected(self):
        pair=(p.murmur64a(b'unit'),p.murmur64a(b'units/body/presentation_sampler'))
        with self.assertRaises(ValueError):
            p.require_members(payload([pair]),[('state_machine','units/body/presentation_sampler')])

    def test_duplicate_members_rejected(self):
        with self.assertRaises(ValueError):p.package_members(payload([(1,2),(1,2)]))

    def test_truncated_table_rejected(self):
        with self.assertRaises(ValueError):p.package_members(payload([(1,2)])[:-1])

    def test_unrecognized_trailer_rejected(self):
        raw=payload([(1,2)])
        with self.assertRaises(ValueError):p.package_members(raw[:-1]+b'\x01')

    def test_trailing_unlisted_data_rejected(self):
        with self.assertRaises(ValueError):p.package_members(payload([(1,2)])+b'\0')

    def test_unreasonable_count_rejected(self):
        with self.assertRaises(ValueError):p.package_members(struct.pack('<I',100001)+p.PACKAGE_TRAILER)

    def test_relative_source_path_cannot_escape(self):
        for bad in ('../body.unit','C:/body.unit','/body.unit','units\\body.unit'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):p.source_path(Path(__file__).parent,bad)


class TrustedSources(unittest.TestCase):
    def fixture(self,root):
        (root/'integration_manifest.json').write_text(json.dumps({'profiles':{'localized-v1-runtime':
            {'manifest_id':'a'*64,'cross_owner_transition_policy':'snapshot-blend-v1'}}}))
        (root/'integration_receipt.json').write_text(json.dumps({'profile_id':'localized-v1-runtime',
            'cross_owner_transition_policy':'snapshot-blend-v1'}))
        source=root/'candidate/source/units/body.unit';source.parent.mkdir(parents=True);source.write_bytes(b'approved unit')
        return {'integration_manifest_sha256':p.v.digest(root/'integration_manifest.json'),
            'integration_receipt_sha256':p.v.digest(root/'integration_receipt.json'),
            'integration_staged_inputs':{'candidate/source/units/body.unit':p.v.digest(source)}}

    def test_current_frozen_sources_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);receipt=self.fixture(root)
            self.assertEqual(p.trusted_profile(root,receipt)[2]['manifest_id'],'a'*64)

    def test_changed_profile_with_old_id_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);receipt=self.fixture(root)
            manifest=json.loads((root/'integration_manifest.json').read_text())
            manifest['profiles']['localized-v1-runtime']['cross_owner_transition_policy']='cut'
            (root/'integration_manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):p.trusted_profile(root,receipt)

    def test_disagreeing_policy_even_with_fresh_digests_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);receipt=self.fixture(root)
            (root/'integration_receipt.json').write_text(json.dumps({'profile_id':'localized-v1-runtime',
                'cross_owner_transition_policy':'cut'}))
            receipt['integration_receipt_sha256']=p.v.digest(root/'integration_receipt.json')
            with self.assertRaises(ValueError):p.trusted_profile(root,receipt)

    def test_changed_staged_unit_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);receipt=self.fixture(root)
            (root/'candidate/source/units/body.unit').write_bytes(b'changed profile')
            with self.assertRaises(ValueError):p.trusted_profile(root,receipt)

    def test_compiled_resource_change_cannot_reuse_a_prior_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'compiled_unit';path.write_bytes(b'approved geometry and bones')
            binding={'units/body.unit':p.v.digest(path)}
            p.verify_resource_seal(binding,['units/body.unit'],[path])
            path.write_bytes(b'changed geometry but identical metadata')
            with self.assertRaises(ValueError):p.verify_resource_seal(binding,['units/body.unit'],[path])

    def test_companion_lua_seal_requires_exact_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'compiled_lua';path.write_bytes(b'old trusted manifest bytecode')
            binding={'manifest.lua':p.v.digest(path)};path.write_bytes(b'stale or changed bytecode')
            with self.assertRaises(ValueError):p.verify_resource_seal(binding,['manifest.lua'],[path])

    def test_incomplete_compiled_inventory_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'compiled_asm';path.write_bytes(b'controller')
            with self.assertRaises(ValueError):p.verify_resource_seal({},['sampler.state_machine'],[path])

    def test_authored_clip_cannot_change_between_sdk_acceptance_and_seal(self):
        sdk={'compiled_unit_sha256':'unit','compiled_animation_sha256':'diagnostic',
             'compiled_integration':{'presentation_sampler':{'resource':'units/body/sampler','compiled_sha256':'helper'},
                 'authored_clips':[{'resource':'units/anims/authored','compiled_animation_sha256':'accepted-authored'}]},
             'original_clip_compatibility':{'all_thirteen_compiled':True,'unchanged_tracks_per_clip':138,'clips':[]}}
        binding={p.v.UNIT+'.unit':'unit',p.v.CLIP+'.animation':'diagnostic',
                 'units/body/sampler.state_machine':'helper','units/anims/authored.animation':'accepted-authored'}
        p.verify_sdk_output_digests(sdk,binding)
        binding['units/anims/authored.animation']='changed-after-complete-diagnostic'
        with self.assertRaises(ValueError):p.verify_sdk_output_digests(sdk,binding)

    def test_original_clip_cannot_change_before_seal(self):
        sdk={'compiled_unit_sha256':'unit','compiled_animation_sha256':'diagnostic',
             'compiled_integration':{'presentation_sampler':{'resource':'units/body/sampler','compiled_sha256':'helper'},'authored_clips':[]},
             'original_clip_compatibility':{'all_thirteen_compiled':True,'unchanged_tracks_per_clip':138,
                 'clips':[{'clip':'combat_idle.fbx','compiled_candidate_sha256':'approved-original'}]}}
        binding={p.v.UNIT+'.unit':'unit',p.v.CLIP+'.animation':'diagnostic',
                 'units/body/sampler.state_machine':'helper','units/warlock_bombardier/anims/combat_idle.animation':'changed'}
        with self.assertRaises(ValueError):p.verify_sdk_output_digests(sdk,binding)

    def test_seal_inventory_includes_diagnostic_and_unused_original_idle(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            clips=[{'clip':path.name} for path in (p.v.ROOT/'units/warlock_bombardier/anims').glob('*.fbx')]
            self.assertEqual(len(clips),13)
            (root/'original-clips.json').write_text(json.dumps({'clips':clips}))
            profile={'sampler_state_machine':p.v.UNIT+'/presentation_sampler',
                     'states':{'base/idle':{'clip':'units/warlock_bombardier/anims/authored/continuous'}}}
            resources=p.compiled_resource_names(root,profile)
            self.assertEqual(resources.count(p.v.CLIP+'.animation'),1)
            self.assertIn('units/warlock_bombardier/anims/combat_idle.animation',resources)
            self.assertIn('units/warlock_bombardier/anims/authored/continuous.animation',resources)
            self.assertEqual(len(resources),len(set(resources)))


if __name__=='__main__':unittest.main()
