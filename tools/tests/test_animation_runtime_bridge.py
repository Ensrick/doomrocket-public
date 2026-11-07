"""Reject producer declarations that no longer match actual staged bytes."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'animation_rig'))
import verify_runtime_bridge as bridge


class RuntimeBridge(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.old=self.root/'.build/old';self.new=self.root/'.build/new'
        self.probe=self.root/'.build/probe';self.probe.mkdir(parents=True)
        self.stager=self.root/'stage.py';self.stager.write_text('current producer')
        self.ident='a'*64
        manifest={'schema':1,'profiles':{'localized-v1-runtime':{'manifest_id':self.ident}}}
        files={'integration_manifest.json':json.dumps(manifest).encode(),
               'scripts/mods/doomrocket/utils/doomrocket_animation_manifest.lua':b'manifest',
               bridge.v.UNIT+'.unit':b'materials = { x = "materials/warlock_bombardier/body" }\n',
               bridge.v.UNIT+'.fbx':b'geometry and binds',bridge.v.UNIT+'.state_machine':b'controller',
               'units/warlock_bombardier/anims/authored/continuous.fbx':b'authored curves',
               'units/warlock_bombardier/anims/authored/continuous.animation':b'lossless'}
        for i in range(13):
            for suffix in ('.fbx','.animation'):files[f'units/warlock_bombardier/anims/clip{i}{suffix}']=str(i).encode()
        for overlay,producer in ((self.old,'b'*64),(self.new,bridge.v.digest(self.stager))):
            for relative,value in files.items():
                path=overlay/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
            receipt={'schema':1,'status':'isolated-integration-staged','output':str(overlay),
                     'profile_id':'localized-v1-runtime','manifest_id':self.ident,'legacy_sources_unchanged':True,
                     'shipping_clips_and_sidecars_preserved':26,'staging_script_sha256':producer,
                     'source_inputs_sha256':{},'payload_files':{p:{'bytes':len(raw),'sha256':bridge.v.digest(overlay/p)}
                                                              for p,raw in files.items()}}
            (overlay/'integration_receipt.json').write_text(json.dumps(receipt))
        self.path=self.root/'.build/producer.json'
        self.data={'schema':1,'status':'identical-integration-assets','all_selected_bytes_identical':True,
                   'old_overlay':str(self.old),'new_overlay':str(self.new),'manifest_id':self.ident,
                   'old_staging_producer_sha256':'b'*64,'new_staging_producer_sha256':bridge.v.digest(self.stager),
                   'file_sha256':{p:bridge.v.digest(self.old/p) for p in files if '/anims/clip' not in p}}
        self.save()
        receipt_bytes=(self.old/'integration_receipt.json').read_bytes()
        (self.probe/'integration_receipt.json').write_bytes(receipt_bytes)
        (self.probe/'input_receipt.json').write_text(json.dumps({'integration_receipt_sha256':bridge.v.digest(self.old/'integration_receipt.json')}))
        for relative,value in files.items():
            if not relative.startswith('units/'):continue
            path=self.probe/'candidate/source'/relative;path.parent.mkdir(parents=True,exist_ok=True)
            if relative==bridge.v.UNIT+'.unit':value=value.replace(b'materials/warlock_bombardier/body',b'materials/animation_probe')
            path.write_bytes(value)
    def save(self):self.path.write_text(json.dumps(self.data))
    def audit(self):
        return bridge.producer_proof(self.path,self.probe,bridge.v.digest(self.old/'integration_manifest.json'),
                                     self.ident,self.root,self.stager)
    def test_complete_current_byte_inventory_passes(self):
        self.assertEqual(self.audit()['complete_payload_files_checked'],33)
    def test_status_claim_rejected(self):
        self.data['status']='assumed-equivalent';self.save()
        with self.assertRaises(ValueError):self.audit()
    def test_overlay_escape_rejected(self):
        self.data['new_overlay']=str(self.root/'outside');self.save()
        with self.assertRaises(ValueError):self.audit()
    def test_payload_mutation_rejected_even_when_report_claims_equal(self):
        (self.new/(bridge.v.UNIT+'.fbx')).write_bytes(b'changed geometry')
        with self.assertRaises(ValueError):self.audit()
    def test_unlisted_extra_file_rejected(self):
        (self.new/'unlisted.unit').write_bytes(b'not in accepted inventory')
        with self.assertRaises(ValueError):self.audit()
    def test_legacy_animation_mutation_rejected_outside_selected_inventory(self):
        (self.new/'units/warlock_bombardier/anims/clip7.fbx').write_bytes(b'changed tracks')
        with self.assertRaises(ValueError):self.audit()
    def test_missing_critical_selected_hash_rejected(self):
        del self.data['file_sha256'][bridge.v.UNIT+'.unit'];self.save()
        with self.assertRaises(ValueError):self.audit()
    def test_current_producer_change_rejected(self):
        self.stager.write_text('new unvalidated producer')
        with self.assertRaises(ValueError):self.audit()
    def test_compiled_staging_receipt_change_rejected(self):
        (self.probe/'integration_receipt.json').write_text('{}')
        with self.assertRaises(ValueError):self.audit()
    def test_profile_offset_change_rejected(self):
        profile={key:None for key in bridge.PROJECTION};profile['channels']=[{'bind_offset':[1,2,3]}]
        changed=copy.deepcopy(profile);changed['channels'][0]['bind_offset'][0]=100
        with self.assertRaises(ValueError):bridge.require_profile_equivalent(profile,changed)
    def test_metadata_identity_change_allowed_with_exact_solver_inputs(self):
        profile={key:None for key in bridge.PROJECTION};changed=copy.deepcopy(profile)
        profile['manifest_id']='a'*64;changed['manifest_id']='c'*64
        bridge.require_profile_equivalent(profile,changed)
    def test_current_controller_bytes_are_redecoded(self):
        expected={'status':'decoded','compiled_transition_edges':154}
        with patch.object(bridge,'verify',return_value=expected) as decoder:
            self.assertEqual(bridge.revalidate_controller(b'unit',b'CURRENT ASM',b'reference',{},'profile',expected),expected)
            decoder.assert_called_once_with(b'unit',b'CURRENT ASM',{},'profile',b'reference')
    def test_changed_current_controller_rejects_stale_report(self):
        expected={'compiled_transition_edges':154}
        with patch.object(bridge,'verify',return_value={'compiled_transition_edges':153}):
            with self.assertRaises(ValueError):bridge.revalidate_controller(b'unit',b'changed ASM',b'reference',{},'profile',expected)


if __name__=='__main__':unittest.main()
