"""Acceptance must derive coverage and provenance, not trust summary labels."""
from pathlib import Path
import copy
import json
import math
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'animation_rig'))
import verify_blend_acceptance as acceptance
from test_animation_blend_numeric import BlendCoverage


class BlendAcceptance(unittest.TestCase):
    def fixture(self):
        shard=BlendCoverage().fixture();stems={'clip'+str(i) for i in range(13)}
        report=dict(shard,status='actual-lua-snapshot-blend-and-skin-passed',clip_count=13,
            pose_samples=3276,ordinary_transition_pose_samples=1638,interrupted_transition_pose_samples=1638,
            bone_comparisons=452088,weighted_vertex_samples=115675560,pure_authored_zero_write_checks=234,
            authored_helper_no_legacy_bone_write_checks=1638,maxima={key:0. for key in
                ('max_head_error_m','max_axis_error_m','max_local_matrix_error','max_weighted_skin_error_m')},
            weighted_skin_rms_m=0.,clips=[],interruptions=[])
        for stem in sorted(stems):
            clip=copy.deepcopy(shard['clips'][0]);clip['clip']=stem;report['clips'].append(clip)
            report['interruptions'].extend(dict(row,clip=stem) for row in copy.deepcopy(shard['interruptions']))
        return report,stems

    def test_exact_complete_rows_pass(self):
        report,stems=self.fixture();self.assertEqual(set(acceptance.numerical_rows(report,stems)),stems)

    def test_thirteen_repeated_clips_cannot_fake_complete_coverage(self):
        report,stems=self.fixture();report['clips']=[copy.deepcopy(report['clips'][0]) for _ in range(13)]
        with self.assertRaises(ValueError):acceptance.numerical_rows(report,stems)

    def test_extra_interruption_cannot_hide_behind_count_label(self):
        report,stems=self.fixture();report['interruptions'].append(copy.deepcopy(report['interruptions'][0]))
        with self.assertRaises(ValueError):acceptance.numerical_rows(report,stems)

    def test_summary_maximum_must_equal_rows(self):
        report,stems=self.fixture();report['clips'][0]['samples'][0]['max_weighted_skin_error_m']=.001
        with self.assertRaises(ValueError):acceptance.numerical_rows(report,stems)

    def test_rms_summary_must_equal_rows(self):
        report,stems=self.fixture();report['weighted_skin_rms_m']=.001
        with self.assertRaises(ValueError):acceptance.numerical_rows(report,stems)

    def test_unknown_legacy_clip_rejected(self):
        rows=[{'clip':'clip'+str(i)+'.fbx'} for i in range(13)];rows[-1]['clip']='new_unknown.fbx'
        with self.assertRaises(ValueError):acceptance.complete_by_stem(rows,{'clip'+str(i) for i in range(13)})

    def test_missing_required_provenance_rejected(self):
        with self.assertRaises(ValueError):acceptance.require_frozen({'frozen_input_sha256':{}},{'actual.py'})

    def test_current_hash_drift_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'frozen.py';path.write_bytes(b'initial source')
            report={'frozen_input_sha256':{str(path):acceptance.v.digest(path)}}
            path.write_bytes(b'changed source')
            with self.assertRaises(ValueError):acceptance.require_frozen(report,{str(path)})

    def test_validated_recorded_shard_sha_is_retained(self):
        proof={'frozen_input_sha256':{'source.py':'source SHA'},
               'shard_reports':{'executed.blend.json':'validated shard SHA'}}
        frozen={'source.py':'source SHA','executed.blend.json':'validated shard SHA'}
        acceptance.merge_recorded_numerical_pins(frozen,proof)
        self.assertEqual(frozen['executed.blend.json'],proof['shard_reports']['executed.blend.json'])

    def test_all_twenty_six_late_shard_changes_cannot_be_rebound(self):
        with tempfile.TemporaryDirectory() as folder:
            for suffix in ('.blend.json','.equivalence.json'):
                for index in range(13):
                    with self.subTest(suffix=suffix,index=index):
                        path=(Path(folder)/(str(index)+suffix)).resolve()
                        path.write_bytes(b'validated executed rows')
                        proof={'frozen_input_sha256':{},'shard_reports':{str(path):acceptance.v.digest(path)}}
                        path.write_bytes(b'changed after row validation')
                        frozen={str(path):acceptance.v.digest(path)}
                        with self.assertRaises(ValueError):acceptance.merge_recorded_numerical_pins(frozen,proof)

    def test_lifetime_only_executed_prefix_is_compared(self):
        first="HARNESS='executed prefix\\nQuaternion={old unused stub}'"
        second="HARNESS='executed prefix\\nQuaternion={new unused stub}'"
        self.assertEqual(acceptance.harness_prefix(first),acceptance.harness_prefix(second))
        changed="HARNESS='changed executable prefix\\nQuaternion={new unused stub}'"
        self.assertNotEqual(acceptance.harness_prefix(first),acceptance.harness_prefix(changed))

    def test_invalid_harness_boundary_rejected(self):
        with self.assertRaises(ValueError):acceptance.harness_prefix("HARNESS='no fixed boundary'")


class NumericalHelperIdentity(unittest.TestCase):
    PREFIX=b'import struct\nfrom local_decoder import bounded_read\nLIMIT=138\ndef compiled_bones(data):\n return bounded_read(data,LIMIT)\n\n'
    OLD=PREFIX+b'HARNESS="unused old Lua"\nclass RuntimeTests:\n def test_original(self):pass\n'
    CURRENT=PREFIX+b'HARNESS="unused new Lua"\nclass RuntimeTests:\n def test_original(self):pass\n def test_added(self):pass\n'
    CLOCK_GUARDED=PREFIX+b'HARNESS="unused clock-read trap"\nclass RuntimeTests:\n def test_original(self):pass\n def test_added(self):pass\n def test_no_native_read(self):pass\n'
    VARIANTS=(CURRENT,CLOCK_GUARDED)

    def pins(self,index,current=None,old=None):
        return dict(acceptance.AIM_TEST_ONLY_UPDATES[index],
            current_sha256=acceptance.digest_bytes(self.VARIANTS[index] if current is None else current),
            historical_sha256=acceptance.digest_bytes(self.OLD if old is None else old),
            executed_prefix_sha256=acceptance.digest_bytes(self.PREFIX))

    def policies(self,index=None,current=None,old=None):
        return tuple(self.pins(i,current if i==index else None,old if i==index else None)
                     for i in range(len(self.VARIANTS)))

    def test_unchanged_helper_needs_no_exception(self):
        for relative in acceptance.HELPERS:
            identity=acceptance.numerical_helper_identity(relative,b'unchanged',b'unchanged')
            self.assertTrue(identity['whole_file_byte_identical'])
            self.assertNotIn('identity_policy',identity)

    def test_both_reviewed_pairs_record_prefix_and_complete_current_file(self):
        for index,current in enumerate(self.VARIANTS):
            with self.subTest(index=index),mock.patch.object(acceptance,'AIM_TEST_ONLY_UPDATES',self.policies()):
                identity=acceptance.numerical_helper_identity(acceptance.AIM_HELPER,current,self.OLD)
            self.assertFalse(identity['whole_file_byte_identical'])
            self.assertTrue(identity['executed_prefix_byte_identical'])
            self.assertEqual(identity['current_sha256'],acceptance.digest_bytes(current))
            self.assertEqual(identity['historical_sha256'],acceptance.digest_bytes(self.OLD))
            self.assertEqual(identity['executed_prefix_sha256'],acceptance.digest_bytes(self.PREFIX))
            self.assertEqual(identity['identity_policy'],'finite-reviewed-aim-test-only-update-v'+str(index+1))
            self.assertIn('no native playback acceptance',identity['scope'])
            if index==0:
                self.assertEqual(identity['reviewed_helper_source_git_ref'],
                                 acceptance.AIM_TEST_ONLY_UPDATE['reviewed_helper_source_git_ref'])
                self.assertNotIn('review_reference',identity)
            else:
                self.assertEqual(identity['review_reference'],
                                 'https://github.com/Ensrick/doomrocket-private/issues/65')
                self.assertNotIn('reviewed_helper_source_git_ref',identity)

    def test_v1_policy_and_metadata_remain_exact(self):
        old=acceptance.AIM_TEST_ONLY_UPDATE
        self.assertEqual(old,{
            'historical_sha256':'98943db7181e67a544a88c4705513a38c641b92dbe97d13e5e8889189cf1dd75',
            'current_sha256':'c5a400685964b906b5d633d4c7e0861317836ed6568267e128ccc27b65074975',
            'executed_prefix_sha256':'6bc75cc98fb8c4a0b879f8f4721f7ddbc464615b800ca9d012aaf6a581512814',
            'reviewed_helper_source_git_ref':'b805a418e2ccd00818f1ad674eb7f2394b6f9b37',
        })
        self.assertEqual(acceptance.AIM_TEST_ONLY_UPDATES[0],dict(old,
            identity_policy='finite-reviewed-aim-test-only-update-v1',
            scope='Exact reviewed full-file pair; unchanged import/decoder prefix; only unused aiming Lua harness and eleven test methods differ; no native playback acceptance'))

    def test_finite_policy_matches_current_reviewed_source_once(self):
        raw=(acceptance.v.ROOT/acceptance.AIM_HELPER).read_bytes()
        matches=[record for record in acceptance.AIM_TEST_ONLY_UPDATES
                 if acceptance.digest_bytes(raw)==record['current_sha256']]
        self.assertEqual(len(matches),1)
        self.assertIs(matches[0],acceptance.AIM_TEST_ONLY_CLOCK_GUARD_UPDATE)
        self.assertEqual(acceptance.digest_bytes(acceptance.aim_decoder_prefix(raw)),
                         matches[0]['executed_prefix_sha256'])

    def test_other_helpers_cannot_use_either_aim_exception(self):
        with mock.patch.object(acceptance,'AIM_TEST_ONLY_UPDATES',self.policies()):
            for current in self.VARIANTS:
                for relative in acceptance.HELPERS:
                    if relative==acceptance.AIM_HELPER:continue
                    with self.subTest(relative=relative,current=current),self.assertRaises(ValueError):
                        acceptance.numerical_helper_identity(relative,current,self.OLD)

    def test_unknown_base_current_or_reversed_pair_rejected_for_both_revisions(self):
        with mock.patch.object(acceptance,'AIM_TEST_ONLY_UPDATES',self.policies()):
            for variant in self.VARIANTS:
                for current,old in ((variant,self.OLD+b'\n'),(variant+b'\n',self.OLD),
                                    (self.OLD,variant),(variant,self.OLD.replace(b'old',b'unknown'))):
                    with self.subTest(current=current,old=old),self.assertRaises(ValueError):
                        acceptance.numerical_helper_identity(acceptance.AIM_HELPER,current,old)

    def test_reviewed_revisions_do_not_authorize_new_base_or_reverse_edge(self):
        with mock.patch.object(acceptance,'AIM_TEST_ONLY_UPDATES',self.policies()):
            for current,old in ((self.CLOCK_GUARDED,self.CURRENT),(self.CURRENT,self.CLOCK_GUARDED)):
                with self.subTest(current=current),self.assertRaises(ValueError):
                    acceptance.numerical_helper_identity(acceptance.AIM_HELPER,current,old)

    def test_duplicate_matching_reviewed_edges_rejected(self):
        for index,current in enumerate(self.VARIANTS):
            policies=self.policies()+(self.pins(index),)
            with self.subTest(index=index),mock.patch.object(acceptance,'AIM_TEST_ONLY_UPDATES',policies):
                with self.assertRaises(ValueError):
                    acceptance.numerical_helper_identity(acceptance.AIM_HELPER,current,self.OLD)

    def test_decoder_import_dependency_or_constant_drift_fails_even_with_new_full_file_pin(self):
        changes=((b'return bounded_read(data,LIMIT)',b'return ()'),(b'import struct',b'import json'),
                 (b'from local_decoder import bounded_read',b'from foreign_decoder import bounded_read'),
                 (b'LIMIT=138',b'LIMIT=137'))
        for index,variant in enumerate(self.VARIANTS):
            for before,after in changes:
                current=variant.replace(before,after)
                with self.subTest(index=index,change=after),mock.patch.object(
                        acceptance,'AIM_TEST_ONLY_UPDATES',self.policies(index,current)):
                    with self.assertRaises(ValueError):
                        acceptance.numerical_helper_identity(acceptance.AIM_HELPER,current,self.OLD)

    def test_arbitrary_test_tail_and_import_time_rebindings_are_not_ignored(self):
        tails=(b'\ncompiled_bones=lambda data:()\n',b'\nimport foreign_decoder\n',
               b'\n@replace_decoder\nclass NewTests:pass\n',
               b'\ndef test_new(value=replace_decoder()):pass\n',
               b'\nclass NewTests:\n compiled_bones=replace_decoder()\n',
               b'\nclass NewTests:\n def test_harmless(self):pass\n')
        with mock.patch.object(acceptance,'AIM_TEST_ONLY_UPDATES',self.policies()):
            for index,variant in enumerate(self.VARIANTS):
                for tail in tails:
                    with self.subTest(index=index,tail=tail),self.assertRaises(ValueError):
                        acceptance.numerical_helper_identity(acceptance.AIM_HELPER,variant+tail,self.OLD)

    def test_missing_duplicate_computed_or_annotated_boundary_rejected_even_when_pinned(self):
        boundaries=(b'',b'HARNESS="one"\nHARNESS="two"\n',b'HARNESS=str("computed")\n',
                    b'HARNESS: str="annotated"\n',b'HARNESS=OTHER="shared"\n',
                    b'HARNESS="one"\nHARNESS+="two"\n')
        for index in range(len(self.VARIANTS)):
            for boundary in boundaries:
                current=self.PREFIX+boundary
                with self.subTest(index=index,boundary=boundary),mock.patch.object(
                        acceptance,'AIM_TEST_ONLY_UPDATES',self.policies(index,current)):
                    with self.assertRaises(ValueError):
                        acceptance.numerical_helper_identity(acceptance.AIM_HELPER,current,self.OLD)

    def test_equal_but_different_prefix_is_not_a_new_reviewed_decoder(self):
        old=self.OLD.replace(b'LIMIT=138',b'LIMIT=137')
        for index,variant in enumerate(self.VARIANTS):
            current=variant.replace(b'LIMIT=138',b'LIMIT=137')
            with self.subTest(index=index),mock.patch.object(
                    acceptance,'AIM_TEST_ONLY_UPDATES',self.policies(index,current,old)):
                with self.assertRaises(ValueError):
                    acceptance.numerical_helper_identity(acceptance.AIM_HELPER,current,old)


class NumericalFrozenInputInventory(unittest.TestCase):
    def test_clock_helper_is_required_only_by_new_blend_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            probe=Path(folder);manifest=probe/'current_manifest.json';report=probe/'historical_report.json'
            def indexed(root,source,data,resources):
                return [probe/'compiled'/resource for resource in resources]
            bones=probe/'compiled'/(acceptance.v.UNIT+'.bones')
            bones.parent.mkdir(parents=True);bones.write_bytes(b'bounded fixture')
            original={'clips':[{'clip':'combat_idle.fbx'}]}
            with mock.patch.object(acceptance.v,'indexed_resources',side_effect=indexed),mock.patch.object(
                    acceptance.r,'compiled_bones',return_value=('j_root',)),mock.patch.object(
                    acceptance.v,'verify_original_clips',return_value=original):
                blend,legacy,names,clips=acceptance.expected_inputs(probe,manifest,report)
            clock=str(acceptance.blend.CLOCK.resolve())
            self.assertIn(clock,blend)
            self.assertNotIn(clock,legacy)
            self.assertEqual(names,['j_root']);self.assertEqual(clips,original)
            clip='units/warlock_bombardier/anims/combat_idle.animation'
            expected_legacy=[acceptance.r.GRIP,acceptance.r.RUNTIME,Path(acceptance.r.__file__),
                Path(acceptance.v.__file__),acceptance.r.NATIVE_UNIT,acceptance.r.NATIVE_BONES,
                probe/'input_receipt.json',probe/'original-clips.json',
                probe/'compiled'/(acceptance.v.UNIT+'.unit'),bones,
                probe/'compiled'/clip,acceptance.r.NATIVE_ANIMS/'combat_idle.animation',
                report,Path(acceptance.legacy.__file__),probe/'integration_manifest.json']
            self.assertEqual(legacy,{str(path.resolve()) for path in expected_legacy})


if __name__=='__main__':unittest.main()
