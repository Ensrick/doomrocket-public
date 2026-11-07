"""Prove the hidden sampler belongs to the actual compiled root package.

An indexed compiled resource is not necessarily loaded by the mod package.
This separate gate preserves the pose decoder used by concurrent audits.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import struct

import verify_compiled_animation as v
from compiled_integration import state_bindings, verify as verify_integration
from test_warlock_weapon_pipeline import murmur64a

PACKAGE='resource_packages/doomrocket/doomrocket.package'
COMPANION='scripts/mods/doomrocket/utils/doomrocket_animation_manifest.lua'
# Exact current SDK payload suffix, observed in both loose and bundled package
# outputs. Its meaning is not inferred; unsupported formats fail closed.
PACKAGE_TRAILER=bytes.fromhex('030000000026000000')


def package_members(payload):
    v.require(len(payload)>=4,'Truncated compiled package header')
    count=struct.unpack_from('<I',payload)[0]
    v.require(0<count<=100000,'Unsupported compiled package member count')
    end=4+16*count
    v.require(len(payload)==end+len(PACKAGE_TRAILER) and payload[end:]==PACKAGE_TRAILER,
              'Unsupported compiled package length or trailer')
    members=list(struct.iter_unpack('<QQ',payload[4:end]))
    v.require(len(set(members))==count,'Duplicate compiled package member')
    return set(members)


def require_members(payload,resources):
    members=package_members(payload)
    for kind,name in resources:
        v.require((murmur64a(kind.encode()),murmur64a(name.encode())) in members,
                  'Compiled root package does not load '+kind+': '+name)
    return len(members)


def verify_compiled_manifest(payload,expected):
    from compiled_lua_table import verify_manifest
    return verify_manifest(payload,expected)


def source_path(root,relative):
    p=PurePosixPath(relative)
    v.require(not p.is_absolute() and '\\' not in relative and
              all(x not in ('','..','.') and ':' not in x for x in p.parts),
              'Invalid package staging relative path')
    path=root/relative;v.reject_redirect(path)
    v.require(path.resolve().is_relative_to(root.resolve()),'Package staging path escaped root')
    return path


def trusted_profile(probe,receipt):
    v.require(v.digest(probe/'integration_manifest.json')==receipt['integration_manifest_sha256'] and
              v.digest(probe/'integration_receipt.json')==receipt['integration_receipt_sha256'],
              'Trusted integration manifest or receipt changed')
    for relative,sha in receipt['integration_staged_inputs'].items():
        v.require(v.digest(source_path(probe,relative.replace('\\','/')))==sha,
                  'Staged integration source changed: '+relative)
    registration=json.loads((probe/'integration_receipt.json').read_text())
    manifest=json.loads((probe/'integration_manifest.json').read_text())
    profile=manifest['profiles'][registration['profile_id']]
    v.require(registration['cross_owner_transition_policy']==profile['cross_owner_transition_policy']=='snapshot-blend-v1',
              'Integration presentation policy differs from trusted profile')
    return registration,manifest,profile


def compiled_resource_names(probe,profile):
    referenced={state['clip']+'.animation' for state in profile['states'].values()}
    legacy=json.loads((probe/'original-clips.json').read_text())
    referenced|={'units/warlock_bombardier/anims/'+Path(clip['clip']).stem+'.animation' for clip in legacy['clips']}
    referenced.add(v.CLIP+'.animation')
    return [v.UNIT+'.unit',v.UNIT+'.bones',v.UNIT+'.state_machine',
            profile['sampler_state_machine']+'.state_machine',PACKAGE,COMPANION]+sorted(referenced)


def verify_resource_seal(bindings,resources,paths):
    v.require(isinstance(bindings,dict) and set(bindings)==set(resources) and len(resources)==len(paths),
              'SDK compiled-resource inventory differs')
    for resource,path in zip(resources,paths):
        v.require(v.digest(path)==bindings[resource],
                  'Compiled resource changed after SDK acceptance: '+resource)


def verify_sdk_output_digests(sdk,bindings):
    """A fresh seal cannot bless replacements for already accepted outputs."""
    expected={v.UNIT+'.unit':sdk['compiled_unit_sha256'],
              v.CLIP+'.animation':sdk['compiled_animation_sha256']}
    sampler=sdk['compiled_integration']['presentation_sampler']
    expected[sampler['resource']+'.state_machine']=sampler['compiled_sha256']
    for authored in sdk['compiled_integration']['authored_clips']:
        expected[authored['resource']+'.animation']=authored['compiled_animation_sha256']
    original=sdk['original_clip_compatibility']
    v.require(original['all_thirteen_compiled'] and original['unchanged_tracks_per_clip']==138,
              'SDK original-clip acceptance is incomplete')
    for clip in original['clips']:
        expected['units/warlock_bombardier/anims/'+Path(clip['clip']).stem+'.animation']=clip['compiled_candidate_sha256']
    for resource,sha in expected.items():
        v.require(bindings.get(resource)==sha,'Compiled output differs from accepted SDK diagnostic: '+resource)


def seal_sdk_resources(probe):
    """Called only after the wrapper's real compile and complete SDK audit."""
    receipt=json.loads((probe/'input_receipt.json').read_text())
    _,_,profile=trusted_profile(probe,receipt)
    closure=receipt['package_closure']
    for path,sha in closure['source_input_sha256'].items():
        v.require(v.digest(path)==sha,'Package closure producer changed before SDK seal')
    destination=probe/'compiled_animation_contract.json';v.reject_redirect(destination)
    sdk=json.loads(destination.read_text())
    v.require(sdk['status']=='sdk-compiled-and-decoded' and sdk['input_receipt']==receipt,
              'Only the current complete SDK audit can be sealed')
    resources=compiled_resource_names(probe,profile)
    paths=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',resources)
    names=list(__import__('test_doomrocket_visible_aim').compiled_bones(paths[1].read_bytes()))
    v.require(names==profile['bone_names'] and len(names)==138,'Compiled bone inventory differs before SDK seal')
    v.require(v.digest(paths[0])==sdk['compiled_unit_sha256'] and
              v.digest(paths[3])==sdk['compiled_integration']['presentation_sampler']['compiled_sha256'],
              'Compiled Unit or sampler changed before SDK seal')
    bindings={resource:v.digest(path) for resource,path in zip(resources,paths)}
    verify_sdk_output_digests(sdk,bindings)
    sdk['compiled_resource_sha256']=bindings
    sdk['compiled_resource_seal_producer_sha256']=v.digest(__file__)
    destination.write_text(json.dumps(sdk,indent=2),encoding='utf8')


def stage(probe,overlay):
    overlay=v.validate_probe(v.ROOT,overlay)
    receipt=json.loads((overlay/'integration_receipt.json').read_text())
    manifest=json.loads((overlay/'integration_manifest.json').read_text())
    profile=manifest['profiles'][receipt['profile_id']]
    v.require(receipt['status']=='isolated-integration-staged' and
              receipt['cross_owner_transition_policy']==profile['cross_owner_transition_policy']=='snapshot-blend-v1',
              'Package closure requires a validated presentation overlay')
    for relative,item in receipt['payload_files'].items():
        path=source_path(overlay,relative)
        v.require(v.digest(path)==item['sha256'],'Overlay payload changed: '+relative)
    expected=set(receipt['payload_files'])|{'integration_receipt.json'}
    actual={p.relative_to(overlay).as_posix() for p in overlay.rglob('*') if p.is_file()}
    v.require(actual==expected,'Overlay complete file inventory differs')
    for path,sha in receipt['source_inputs_sha256'].items():
        v.require(v.digest(path)==sha,'Overlay source changed: '+path)
    validation=profile['validation']
    v.require(validation['resource_package']==PACKAGE and
              validation['resource_package_sha256']==v.digest(overlay/PACKAGE)==v.digest(v.ROOT/PACKAGE),
              'Overlay package differs from the reviewed canonical package')
    # The package explicitly lists the mod entry. Its compiled Lua need not run
    # during this isolated test, but the exact source must exist for compilation.
    inputs={str((overlay/p).resolve()):v.digest(overlay/p) for p in
            (PACKAGE,COMPANION,'integration_manifest.json','integration_receipt.json')}
    inputs[str((v.ROOT/'doomrocket.mod').resolve())]=v.digest(v.ROOT/'doomrocket.mod')
    inputs[str(Path(__file__).resolve())]=v.digest(__file__)
    inputs[str((Path(__file__).parent/'compiled_lua_table.py').resolve())]=v.digest(Path(__file__).parent/'compiled_lua_table.py')
    for relative in ('tools/animation_rig/Invoke-AnimationProbe.ps1','tools/animation_rig/compiled_integration.py',
                     'tools/animation_rig/verify_compiled_animation.py','tools/hose_lab/compile_paths.py',
                     'tools/hose_lab/compiled/verifier_core.py','tools/tests/test_warlock_weapon_pipeline.py',
                     'tools/tests/test_doomrocket_visible_aim.py','tools/tests/test_doomrocket_chimney_anchor.py'):
        inputs[str((v.ROOT/relative).resolve())]=v.digest(v.ROOT/relative)
    staged={}
    for relative,origin in ((PACKAGE,overlay/PACKAGE),(COMPANION,overlay/COMPANION),
                            ('doomrocket.mod',v.ROOT/'doomrocket.mod')):
        target=source_path(probe/'candidate/source',relative)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,target)
        v.require(v.digest(target)==v.digest(origin),'Package staging copy differs')
        staged[str(target.relative_to(probe)).replace('\\','/')]=v.digest(target)
    for path,sha in inputs.items():v.require(v.digest(path)==sha,'Package input changed during stage')
    destination=probe/'input_receipt.json';v.reject_redirect(destination)
    input_receipt=json.loads(destination.read_text())
    v.require(input_receipt['integration_manifest_sha256']==v.digest(overlay/'integration_manifest.json') and
              input_receipt['integration_receipt_sha256']==v.digest(overlay/'integration_receipt.json'),
              'Package overlay differs from staged animation integration')
    input_receipt['package_closure']={'schema':1,'profile_id':receipt['profile_id'],
        'manifest_id':profile['manifest_id'],'root_package':PACKAGE,
        'source_input_sha256':inputs,'staged_input_sha256':staged}
    destination.write_text(json.dumps(input_receipt,indent=2),encoding='utf8')
    pending=probe/'compiled_package_closure.json';v.reject_redirect(pending)
    pending.write_text(json.dumps({'schema':1,'status':'staged-not-validated'},indent=2),encoding='utf8')


def audit(probe):
    receipt=json.loads((probe/'input_receipt.json').read_text())
    closure=receipt.get('package_closure')
    v.require(isinstance(closure,dict) and closure['root_package']==PACKAGE,'No package closure staging receipt')
    for path,sha in closure['source_input_sha256'].items():
        v.require(v.digest(path)==sha,'Package closure source changed: '+path)
    for relative,sha in closure['staged_input_sha256'].items():
        v.require(v.digest(source_path(probe,relative))==sha,'Staged package closure input changed')
    sdk_path=probe/'compiled_animation_contract.json';sdk=json.loads(sdk_path.read_text())
    v.require(sdk['status']=='sdk-compiled-and-decoded' and sdk['input_receipt']==receipt,
              'Package proof requires the current accepted SDK receipt')
    registration,manifest,profile=trusted_profile(probe,receipt)
    v.require(registration['profile_id']==closure['profile_id'],'Package profile selector changed')
    v.require(profile['manifest_id']==closure['manifest_id'],'Package profile identity changed')
    resource_names=[v.UNIT+'.unit',v.UNIT+'.bones',v.UNIT+'.state_machine',
                    profile['sampler_state_machine']+'.state_machine',PACKAGE,COMPANION]
    paths=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',resource_names)
    bindings=sdk.get('compiled_resource_sha256')
    v.require(isinstance(bindings,dict) and sdk['compiled_resource_seal_producer_sha256']==v.digest(__file__),
              'Missing current SDK compiled-resource seal')
    all_resources=compiled_resource_names(probe,profile)
    bound_paths=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',all_resources)
    verify_resource_seal(bindings,all_resources,bound_paths)
    verify_sdk_output_digests(sdk,bindings)
    v.require(v.digest(paths[0])==sdk['compiled_unit_sha256'] and
              v.digest(paths[3])==sdk['compiled_integration']['presentation_sampler']['compiled_sha256'],
              'Current compiled Unit or sampler differs from accepted SDK proof')
    baseline=v.indexed_resources(v.ROOT,probe,probe/'reference/data',[v.UNIT+'.state_machine'])[0]
    graph=verify_integration(paths[0].read_bytes(),paths[2].read_bytes(),manifest,
                            closure['profile_id'],baseline.read_bytes(),paths[3].read_bytes())
    v.require(graph['compiled_transition_edges']==154 and
              graph['presentation_sampler']['compiled_transition_edges']==154,
              'Unexpected presentation graph edge coverage')
    companion=verify_compiled_manifest(paths[5].read_bytes(),manifest)
    _,visible=state_bindings(paths[2].read_bytes());_,helper=state_bindings(paths[3].read_bytes())
    referenced={name for state in profile['states'].values() for name in (state['clip'],)}
    expected_hashes={murmur64a(name.encode()) for name in referenced}
    for controller in (visible,helper):
        v.require({x for state in controller.values() for x in state['animations']}==expected_hashes,
                  'Compiled graph animation inventory differs')
    required=[('unit',v.UNIT),('state_machine',v.UNIT),
              ('state_machine',profile['sampler_state_machine']),
              ('lua',COMPANION.removesuffix('.lua'))]
    required +=[('animation',name) for name in sorted(referenced)]
    package_payload=paths[4].read_bytes();count=require_members(package_payload,required)
    # Every loaded animation must also resolve to an exact current compiled file.
    animation_paths=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',
                                        [name+'.animation' for name in sorted(referenced)])
    names=list(r for r in __import__('test_doomrocket_visible_aim').compiled_bones(paths[1].read_bytes()))
    v.require(names==profile['bone_names'] and len(names)==138,'Compiled bone inventory differs from trusted profile')
    originals=v.verify_original_clips(probe,names)
    v.require(originals['all_thirteen_compiled'] and originals['unchanged_tracks_per_clip']==138 and
              all(c['compiled_bytes_identical'] and c['unchanged_compiled_tracks']==138 for c in originals['clips']),
              'Original source/native clip preservation failed')
    result={'schema':1,'status':'compiled-root-package-presentation-closure-passed',
        'root_package':PACKAGE.removesuffix('.package'),'compiled_package_sha256':v.digest(paths[4]),
        'compiled_package_members':count,'required_loaded_resources':[{'type':kind,'name':name} for kind,name in required],
        'loaded_animation_sha256':{name:v.digest(path) for name,path in zip(sorted(referenced),animation_paths)},
        'presentation_sampler_sha256':v.digest(paths[3]),'visible_controller_sha256':v.digest(paths[2]),
        'compiled_unit_sha256':v.digest(paths[0]),'compiled_unit_markers_and_graph':graph,
        'compiled_companion_lua_sha256':v.digest(paths[5]),'compiled_companion_manifest':companion,
        'compiled_resource_sha256':bindings,
        'all_thirteen_original':originals,'manifest_id':profile['manifest_id'],
        'manifest_sha256':v.digest(probe/'integration_manifest.json'),
        'sdk_receipt_sha256':v.digest(sdk_path),'input_receipt_sha256':v.digest(probe/'input_receipt.json'),
        'verifier_sha256':v.digest(__file__),'native_Unit_pose_samples':0,
        'hidden_helper_runtime_evaluation':'not captured; requires in-game evaluation',
        'package_format_scope':'Current SDK counted member table and exact audited nine-byte suffix'}
    for path,sha in closure['source_input_sha256'].items():
        v.require(v.digest(path)==sha,'Package closure input changed during audit')
    destination=probe/'compiled_package_closure.json';v.reject_redirect(destination)
    destination.write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({'status':result['status'],'compiled_package_members':count,
                      'required_loaded_resources':len(required),'report_sha256':v.digest(destination)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-root',type=Path,required=True)
    parser.add_argument('--stage',action='store_true')
    parser.add_argument('--seal-sdk-resources',action='store_true')
    parser.add_argument('--integration-overlay',type=Path)
    args=parser.parse_args();probe=v.validate_probe(v.ROOT,args.probe_root)
    if args.stage:
        v.require(args.integration_overlay is not None,'Package stage requires an integration overlay')
        stage(probe,args.integration_overlay)
    elif args.seal_sdk_resources:seal_sdk_resources(probe)
    else:audit(probe)
