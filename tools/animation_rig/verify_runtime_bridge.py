"""Bind frozen pure-legacy numerical proof to a fresh compiled cut profile.

Only controller/metadata policy changes may cross this bridge. Geometry,
scene hierarchy, bind/skin streams, all138 original tracks and all seven
runtime offset inputs must remain exact. This is not native pose capture.
"""
import argparse
import json
from pathlib import Path
import re
import verify_compiled_animation as v
import verify_runtime_outfit as runtime
from compiled_integration import unit_metadata,verify

PROJECTION=('unit','accessory_skin','native_bind_scale','reference_bone','channels',
            'body_fbx_sha256','shipping_body_sha256','shipping_bones_sha256','rest_contract_sha256')


def profile_projection(profile):
    return {key:profile[key] for key in PROJECTION}


def require_profile_equivalent(old,new):
    v.require(profile_projection(old)==profile_projection(new),'Numeric runtime solver profile inputs changed')


def revalidate_controller(unit_payload,controller_payload,baseline_payload,manifest,profile_id,sdk_contract):
    """A past receipt cannot substitute for decoding today's controller bytes."""
    actual=verify(unit_payload,controller_payload,manifest,profile_id,baseline_payload)
    for key,value in actual.items():
        v.require(sdk_contract.get(key)==value,'Current compiled controller differs from its accepted SDK proof: '+key)
    return actual


def checked_relative(base,relative):
    v.require(isinstance(relative,str) and relative and '\\' not in relative,
              'Invalid staging relative path')
    parts=relative.split('/')
    v.require(not Path(relative).is_absolute() and all(p not in ('','.','..') and ':' not in p for p in parts),
              'Staging path escapes its overlay')
    path=base/relative;v.reject_redirect(path)
    v.require(path.resolve().is_relative_to(base.resolve()),'Staging path escapes its overlay')
    return path


def producer_proof(bridge_path,probe,manifest_sha,manifest_id,root=None,stager=None):
    """Re-read both complete inventories; declarations alone are never proof."""
    root=Path(root or v.ROOT);stager=Path(stager or root/'tools/animation_rig/stage_integration.py')
    v.reject_redirect(bridge_path)
    bridge=json.loads(bridge_path.read_text())
    v.require(bridge.get('schema')==1 and bridge.get('status')=='identical-integration-assets'
              and bridge.get('all_selected_bytes_identical') is True and bridge.get('manifest_id')==manifest_id,
              'Invalid producer bridge schema/status/manifest identity')
    overlays=[v.validate_probe(root,Path(bridge[key])) for key in ('old_overlay','new_overlay')]
    v.require(overlays[0]!=overlays[1],'Producer overlays must be distinct')
    receipts=[]
    for lane,overlay in zip(('old','new'),overlays):
        receipt=json.loads((overlay/'integration_receipt.json').read_text())
        v.require(receipt.get('schema')==1 and receipt.get('status')=='isolated-integration-staged'
                  and Path(receipt['output']).resolve()==overlay.resolve()
                  and receipt['profile_id']=='localized-v1-runtime'
                  and receipt['manifest_id']==manifest_id
                  and receipt['legacy_sources_unchanged'] is True
                  and receipt['shipping_clips_and_sidecars_preserved']==26,
                  'Invalid current staging receipt')
        v.require(receipt['staging_script_sha256']==bridge[lane+'_staging_producer_sha256'],
                  'Producer SHA differs from staging receipt')
        inventory=receipt['payload_files']
        v.require(isinstance(inventory,dict) and inventory,'Empty staging inventory')
        present={str(path.relative_to(overlay)).replace('\\','/') for path in overlay.rglob('*') if path.is_file()}
        v.require(present==set(inventory)|{'integration_receipt.json'},
                  'Actual staging file set differs from its complete inventory')
        for relative,item in inventory.items():
            path=checked_relative(overlay,relative)
            v.require(path.is_file() and path.stat().st_size==item['bytes'] and v.digest(path)==item['sha256'],
                      'Current staging payload changed: '+relative)
        for source,sha in receipt['source_inputs_sha256'].items():
            v.reject_redirect(Path(source))
            v.require(v.digest(source)==sha,'Staging source input changed: '+source)
        v.require(v.digest(overlay/'integration_manifest.json')==manifest_sha,
                  'Staging manifest differs from compiled manifest')
        manifest=json.loads((overlay/'integration_manifest.json').read_text())
        v.require(manifest['schema']==1 and manifest['profiles']['localized-v1-runtime']['manifest_id']==manifest_id,
                  'Staging manifest identity changed')
        receipts.append(receipt)
    v.require(receipts[0]['payload_files']==receipts[1]['payload_files'],
              'Complete staged asset inventories differ')
    legacy={p for p in receipts[0]['payload_files'] if p.startswith('units/warlock_bombardier/anims/')
            and '/authored/' not in p}
    v.require(len(legacy)==26 and {Path(p).suffix for p in legacy}=={'.fbx','.animation'}
              and len({str(Path(p).with_suffix('')) for p in legacy})==13,
              'Complete original thirteen clip/sidecar inventory is required')
    v.require(v.digest(stager)==receipts[1]['staging_script_sha256'],
              'Final staging producer source changed')
    mandatory={v.UNIT+'.fbx',v.UNIT+'.unit',v.UNIT+'.state_machine','integration_manifest.json',
               'scripts/mods/doomrocket/utils/doomrocket_animation_manifest.lua'}
    mandatory.update(p for p in receipts[0]['payload_files'] if '/anims/authored/' in p)
    selected=bridge['file_sha256']
    v.require(isinstance(selected,dict) and mandatory.issubset(selected),
              'Producer bridge omits a critical integration asset')
    for relative,sha in selected.items():
        v.require(relative in receipts[0]['payload_files'] and receipts[0]['payload_files'][relative]['sha256']==sha,
                  'Producer selected hash differs from complete inventory')
        for overlay in overlays:
            v.require(v.digest(checked_relative(overlay,relative))==sha,'Producer selected asset changed')
    compiled_receipt=json.loads((probe/'input_receipt.json').read_text())
    v.require(v.digest(overlays[0]/'integration_receipt.json')==compiled_receipt['integration_receipt_sha256']
              and (probe/'integration_receipt.json').read_bytes()==(overlays[0]/'integration_receipt.json').read_bytes(),
              'Producer bridge does not bind the actually compiled overlay')
    for relative,item in receipts[0]['payload_files'].items():
        if not relative.startswith('units/'):continue
        source=probe/'candidate/source'/relative
        if relative==v.UNIT+'.unit':
            text=(overlays[0]/relative).read_text()
            text=re.sub(r'\"materials/warlock_bombardier/[^\"]+\"','\"materials/animation_probe\"',text)
            v.require(source.read_bytes()==text.encode('utf8'),'Compiled Unit source differs beyond the approved gray material substitution')
        else:v.require(v.digest(source)==item['sha256'],'Compiled resource differs from producer inventory: '+relative)
    return {'path':str(bridge_path),'sha256':v.digest(bridge_path),'status':'current-complete-staging-inventories-and-compiled-source-passed',
            'old_overlay':str(overlays[0]),'final_overlay':str(overlays[1]),
            'old_staging_receipt_sha256':v.digest(overlays[0]/'integration_receipt.json'),
            'final_staging_receipt_sha256':v.digest(overlays[1]/'integration_receipt.json'),
            'old_staging_producer_sha256':receipts[0]['staging_script_sha256'],
            'final_staging_producer_sha256':receipts[1]['staging_script_sha256'],
            'complete_payload_files_checked':len(receipts[0]['payload_files']),
            'manifest_id':manifest_id,'manifest_sha256':manifest_sha}


def audit(old_probe,new_probe,numerical,producer_bridge,destination):
    proof=json.loads(numerical.read_text())
    v.require(proof['status']=='runtime-lua-decoded-hierarchy-and-skin-passed'
              and proof['all_thirteen'] is True and proof['skin_checked'] is True and proof['post_grip'] is True
              and proof['strict_acceptance']['status']=='all-thirteen-native-duration-derived-rates-counts-and-finite-gates-passed',
              'A complete strict pure-legacy runtime proof is required')
    for path,sha in proof['frozen_input_sha256'].items():v.require(v.digest(path)==sha,'Frozen legacy proof input changed: '+path)
    v.require(proof['runtime_module_sha256']==v.digest(runtime.RUNTIME)
              and proof['grip_module_sha256']==v.digest(runtime.GRIP),'Executed runtime modules changed')
    reports=[];manifests=[];profiles=[];unit_paths=[];unit_bytes=[];data=[]
    for probe in (old_probe,new_probe):
        sdk=json.loads((probe/'compiled_animation_contract.json').read_text())
        v.require(sdk['status']=='sdk-compiled-and-decoded' and sdk['original_clip_compatibility']['all_thirteen_compiled']
                  and sdk['compiled_integration']['status']=='compiled-unit-markers-and-asm-bindings-passed',
                  'Compiled integration contract is incomplete')
        receipt=json.loads((probe/'input_receipt.json').read_text())
        v.require(sdk['input_receipt']==receipt,'SDK receipt identity differs')
        manifest=json.loads((probe/'integration_manifest.json').read_text())
        v.require(v.digest(probe/'integration_manifest.json')==receipt['integration_manifest_sha256'],
                  'Compiled manifest changed')
        profile=manifest['profiles']['localized-v1-runtime']
        paths=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',[v.UNIT+'.unit',v.UNIT+'.state_machine'])
        payload=paths[0].read_bytes();metadata=unit_metadata(payload)
        v.require(v.digest(paths[0])==sdk['compiled_unit_sha256'],'Compiled Unit changed')
        v.require(metadata['data']=={runtime.idstring32('warlock_rig_profile'):'localized-v1-runtime',
                  runtime.idstring32('warlock_animation_manifest_id'):profile['manifest_id']},'Compiled Unit markers do not bind the actual profile')
        contract=json.loads((probe/'animation_export.json').read_text());rest=json.loads((probe/'skin_profile.json').read_text())
        runtime.validate_profile(manifest,contract,receipt['body_fbx_sha256'],rest)
        reports.append(sdk);manifests.append(manifest);profiles.append(profile);unit_paths.append(paths[0]);unit_bytes.append(payload);data.append(metadata)
    require_profile_equivalent(profiles[0],profiles[1])
    v.require(profiles[1].get('cross_owner_transition_policy')=='cut','Final profile lacks mandatory cross-owner cut policy')
    a,b=(payload[:metadata['geometry_scene_actor_prefix_end']] for payload,metadata in zip(unit_bytes,data))
    v.require(a==b,'Compiled geometry, skin, inverse binds, scene poses or actors changed')
    v.require(proof['compiled_body_sha256']==v.digest(unit_paths[0]),'Legacy numerical proof used another Unit')
    v.require(proof['input_receipt_sha256']==v.digest(old_probe/'input_receipt.json'),'Legacy numerical proof used another SDK receipt')
    v.require(proof['animation_manifest_sha256']==v.digest(old_probe/'integration_manifest.json'),'Legacy numerical proof used another profile')
    v.require(reports[0]['original_clip_compatibility']==reports[1]['original_clip_compatibility'],
              'Original thirteen-clip compiled compatibility changed')
    inventory=json.loads((old_probe/'original-clips.json').read_text())['clips']
    resources=['units/warlock_bombardier/anims/'+Path(c['clip']).stem+'.animation' for c in inventory]
    old_paths=v.indexed_resources(v.ROOT,old_probe,old_probe/'candidate/data',resources)
    new_paths=v.indexed_resources(v.ROOT,new_probe,new_probe/'candidate/data',resources)
    for old,new in zip(old_paths,new_paths):v.require(old.read_bytes()==new.read_bytes(),'Original native animation bytes changed across bridge')
    controller_path=v.indexed_resources(v.ROOT,new_probe,new_probe/'candidate/data',[v.UNIT+'.state_machine'])[0]
    baseline_path=v.indexed_resources(v.ROOT,new_probe,new_probe/'reference/data',[v.UNIT+'.state_machine'])[0]
    edges=revalidate_controller(unit_bytes[1],controller_path.read_bytes(),baseline_path.read_bytes(),
                                manifests[1],'localized-v1-runtime',reports[1]['compiled_integration'])
    v.require(edges['compiled_transition_edges']==154 and edges['cross_owner_edges']==23
              and edges['same_owner_edges']==131 and edges['same_owner_blends_compared_to_shipping'] is True,
              'Final compiled ownership transition policy was not independently verified')
    report={'schema':1,'status':'pure-legacy-runtime-proof-and-compiled-cut-profile-equivalence-passed',
            'legacy_numeric_receipt':str(numerical),'legacy_numeric_receipt_sha256':v.digest(numerical),
            'old_sdk_receipt_sha256':v.digest(old_probe/'compiled_animation_contract.json'),
            'final_sdk_receipt_sha256':v.digest(new_probe/'compiled_animation_contract.json'),
            'old_input_receipt_sha256':v.digest(old_probe/'input_receipt.json'),
            'final_input_receipt_sha256':v.digest(new_probe/'input_receipt.json'),
            'old_manifest_sha256':v.digest(old_probe/'integration_manifest.json'),
            'final_manifest_sha256':v.digest(new_probe/'integration_manifest.json'),
            'old_profile_manifest_id':profiles[0]['manifest_id'],'final_profile_manifest_id':profiles[1]['manifest_id'],
            'old_compiled_unit_sha256':v.digest(unit_paths[0]),'final_compiled_unit_sha256':v.digest(unit_paths[1]),
            'geometry_scene_actor_prefix_bytes':len(a),'geometry_skin_bind_scene_bytes_identical':True,
            'all_thirteen_native_animation_payloads_identical':True,'all_138_tracks_retained':True,
            'seven_runtime_solver_profile_inputs_identical':True,'runtime_module_sha256':v.digest(runtime.RUNTIME),
            'grip_module_sha256':v.digest(runtime.GRIP),'bridge_verifier_sha256':v.digest(Path(__file__)),
            'compiled_transition_edges':154,'cross_owner_cut_edges':23,'same_owner_original_blends':131,
            'native_Unit_pose_samples':0,'game_acceptance':'not performed',
            'scope':'frozen pure-legacy actual-Lua/float32 decoded-scene proof; fresh SDK Unit markers and instantaneous ownership edges'}
    if producer_bridge:
        report['final_stager_producer_bridge']=producer_proof(producer_bridge,new_probe,
                   v.digest(new_probe/'integration_manifest.json'),profiles[1]['manifest_id'])
    destination.write_text(json.dumps(report,indent=2),encoding='utf8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--legacy-probe',type=Path,required=True);p.add_argument('--final-probe',type=Path,required=True)
    p.add_argument('--numeric-receipt',type=Path,required=True);p.add_argument('--producer-bridge',type=Path)
    p.add_argument('--report',type=Path)
    args=p.parse_args();old=v.validate_probe(v.ROOT,args.legacy_probe);new=v.validate_probe(v.ROOT,args.final_probe)
    destination=args.report or new/'runtime_integration_bridge.json';v.reject_redirect(destination)
    v.require(destination.resolve().is_relative_to(new.resolve()),'Bridge output must stay in final isolated probe')
    report=audit(old,new,args.numeric_receipt,args.producer_bridge,destination)
    print(json.dumps({k:x for k,x in report.items() if k!='final_stager_producer_bridge'},indent=2))


if __name__=='__main__':main()
