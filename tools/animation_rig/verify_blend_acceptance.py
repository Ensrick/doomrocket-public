"""Close provenance and SDK correspondence around frozen numerical producers.

This gate does not extrapolate numerical coverage or repeat its skin loops.
It derives required input inventories, verifies executable helper identity,
and connects the exact executed poses/skin to the current compiled asset lane.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path

import verify_runtime_blend as blend
import verify_legacy_lua_equivalence as legacy
import package_closure as package

r=blend.r;v=r.v
HELPERS=('tools/hose_lab/compile_paths.py','tools/hose_lab/compiled/verifier_core.py',
         'tools/tests/test_warlock_weapon_pipeline.py','tools/tests/test_doomrocket_visible_aim.py',
         'tools/tests/test_doomrocket_chimney_anchor.py')
LIFETIME='tools/tests/test_doomrocket_hose_lifecycle.py'
AIM_HELPER='tools/tests/test_doomrocket_visible_aim.py'
# v0.1.90 changed only the unused aiming Lua HARNESS and added eleven test
# methods. Keep this a finite, reviewed pair: arbitrary future test edits can
# execute decorators/default expressions or rebind decoder globals on import.
AIM_TEST_ONLY_UPDATE={
    'historical_sha256':'98943db7181e67a544a88c4705513a38c641b92dbe97d13e5e8889189cf1dd75',
    'current_sha256':'c5a400685964b906b5d633d4c7e0861317836ed6568267e128ccc27b65074975',
    'executed_prefix_sha256':'6bc75cc98fb8c4a0b879f8f4721f7ddbc464615b800ca9d012aaf6a581512814',
    'reviewed_helper_source_git_ref':'b805a418e2ccd00818f1ad674eb7f2394b6f9b37',
}
# #65 replaces the unused aiming-harness clock mock with a forbidden-call
# trap, updates two expected fields and adds one no-native-read regression.
# This is another reviewed full-file edge, not permission for future test edits.
AIM_TEST_ONLY_CLOCK_GUARD_UPDATE={
    'historical_sha256':'98943db7181e67a544a88c4705513a38c641b92dbe97d13e5e8889189cf1dd75',
    'current_sha256':'5b87d8217e797dcadfeab377fb0831618a1f9dec02e4e9a15d9ca3a72f3cb7f1',
    'executed_prefix_sha256':'6bc75cc98fb8c4a0b879f8f4721f7ddbc464615b800ca9d012aaf6a581512814',
    'identity_policy':'finite-reviewed-aim-test-only-update-v2',
    'review_reference':'https://github.com/Ensrick/doomrocket-private/issues/65',
    'scope':'Exact reviewed full-file pair; unchanged import/decoder prefix; unused aiming Lua harness rejects native clock reads, two expected fields are not_sampled and one no-native-read regression is added; no native playback acceptance',
}
AIM_TEST_ONLY_UPDATES=(
    dict(AIM_TEST_ONLY_UPDATE,
         identity_policy='finite-reviewed-aim-test-only-update-v1',
         scope='Exact reviewed full-file pair; unchanged import/decoder prefix; only unused aiming Lua harness and eleven test methods differ; no native playback acceptance'),
    AIM_TEST_ONLY_CLOCK_GUARD_UPDATE,
)


def digest_bytes(raw):return hashlib.sha256(raw).hexdigest()


def harness_prefix(source):
    nodes=[node for node in ast.parse(source).body if isinstance(node,ast.Assign) and
           any(isinstance(target,ast.Name) and target.id=='HARNESS' for target in node.targets)]
    v.require(len(nodes)==1,'Lifetime harness declaration changed')
    value=ast.literal_eval(nodes[0].value)
    v.require(isinstance(value,str) and 'Quaternion={' in value,'Lifetime harness boundary changed')
    return value.split('Quaternion={')[0]


def aim_decoder_prefix(raw):
    """Keep the complete import/decoder context before the unused Lua harness."""
    source=raw.decode('utf8')
    nodes=[]
    for node in ast.parse(source).body:
        targets=node.targets if isinstance(node,ast.Assign) else [node.target] if isinstance(
            node,(ast.AnnAssign,ast.AugAssign)) else []
        if any(isinstance(target,ast.Name) and target.id=='HARNESS' for target in targets):nodes.append(node)
    v.require(len(nodes)==1,'Aiming helper needs one top-level literal HARNESS boundary')
    node=nodes[0]
    v.require(isinstance(node,ast.Assign) and len(node.targets)==1 and node.col_offset==0 and
              isinstance(node.value,ast.Constant) and isinstance(node.value.value,str),
              'Aiming helper HARNESS boundary is not a single literal string assignment')
    return ''.join(source.splitlines(keepends=True)[:node.lineno-1]).encode('utf8')


def numerical_helper_identity(relative,current,old):
    identity={'current_sha256':digest_bytes(current),'historical_sha256':digest_bytes(old),
              'whole_file_byte_identical':current==old}
    if current==old:return identity
    matches=[record for record in AIM_TEST_ONLY_UPDATES if relative==AIM_HELPER and
             all(identity[key]==record[key] for key in ('current_sha256','historical_sha256'))]
    v.require(len(matches)==1,
              'Executed numerical helper differs from reviewed historical identity: '+relative)
    reviewed=matches[0]
    a,b=aim_decoder_prefix(current),aim_decoder_prefix(old)
    v.require(a==b and digest_bytes(a)==reviewed['executed_prefix_sha256'],
              'Executed aiming decoder or import context changed')
    identity.update({'executed_prefix_sha256':digest_bytes(a),'executed_prefix_byte_identical':True})
    identity.update({key:reviewed[key] for key in
                     ('identity_policy','reviewed_helper_source_git_ref','review_reference','scope')
                     if key in reviewed})
    return identity


def helper_identity(ref):
    results=[]
    for relative in HELPERS:
        current=(v.ROOT/relative).read_bytes();old=legacy.git_bytes(ref,relative)
        identity=numerical_helper_identity(relative,current,old)
        results.append(dict(identity,path=str((v.ROOT/relative).resolve())))
    current=(v.ROOT/LIFETIME).read_bytes();old=legacy.git_bytes(ref,LIFETIME)
    a,b=harness_prefix(current.decode('utf8')),harness_prefix(old.decode('utf8'))
    v.require(a==b and r.LUA_SCENE.startswith(a),'Executed lifetime harness prefix changed')
    results.append({'path':str((v.ROOT/LIFETIME).resolve()),'current_sha256':digest_bytes(current),
        'historical_sha256':digest_bytes(old),'executed_prefix_sha256':digest_bytes(a.encode()),
        'executed_prefix_byte_identical':True,
        'scope':'Only the HARNESS prefix before Quaternion={ is executed; later unused test stubs may differ'})
    return results


def expected_inputs(probe,manifest,original_report):
    core=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',[v.UNIT+'.unit',v.UNIT+'.bones'])
    authored=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',
        ['units/warlock_bombardier/anims/authored/continuous.animation'])[0]
    names=list(r.compiled_bones(core[1].read_bytes()));original=v.verify_original_clips(probe,names)
    pairs=[]
    for clip in original['clips']:
        stem=Path(clip['clip']).stem
        compiled=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',
            ['units/warlock_bombardier/anims/'+stem+'.animation'])[0]
        pairs.extend((compiled,r.NATIVE_ANIMS/(stem+'.animation')))
    common=[r.GRIP,r.RUNTIME,Path(r.__file__),Path(v.__file__),r.NATIVE_UNIT,r.NATIVE_BONES,
            probe/'input_receipt.json',probe/'original-clips.json',*core,*pairs]
    legacy_paths=[*common,original_report,Path(legacy.__file__),probe/'integration_manifest.json']
    blend_paths=[*common,authored,manifest,blend.COMPOSER,blend.CLOCK,Path(blend.__file__),
                 probe/'skin_profile.json',probe/'animation_export.json']
    for clip in original['clips']:
        resource='units/warlock_bombardier/anims/'+Path(clip['clip']).stem
        for suffix in ('.fbx','.animation'):
            blend_paths.extend((v.ROOT/(resource+suffix),probe/f'candidate/source/{resource}{suffix}',
                                probe/f'reference/source/{resource}{suffix}'))
    return {str(p.resolve()) for p in blend_paths},{str(p.resolve()) for p in legacy_paths},names,original


def require_frozen(report,required):
    supplied=report['frozen_input_sha256']
    v.require(isinstance(supplied,dict) and set(supplied)==required,'Numerical proof frozen input inventory is incomplete')
    for path,sha in supplied.items():v.require(v.digest(path)==sha,'Numerical proof input changed: '+path)


def merge_recorded_numerical_pins(frozen,proof):
    for field in ('frozen_input_sha256','shard_reports'):
        for path,sha in proof[field].items():
            v.require(path not in frozen or frozen[path]==sha,'Final numerical proof pin conflict: '+path)
            frozen[path]=sha


def require_legacy_scope(report,original_report,ref):
    v.require(report['status']=='actual-lua-all-legacy-poses-byte-identical' and report['clip_count']==13 and
              report['pose_samples']==24077 and report['exact_local_matrix_comparisons']==3322626 and
              report['historical_weighted_vertex_comparisons_preserved_by_exact_pose_identity']==850158870 and
              report['max_local_matrix_error']==0 and report['fixed_tolerance_m']==.002 and
              report['new_weighted_vertex_evaluations']==0 and report['native_Unit_pose_samples']==0 and
              report['game_acceptance']=='not performed','Legacy proof scope or fixed complete coverage differs')
    v.require(report['historical_report_sha256']==v.digest(original_report) and
              report['historical_source_git_ref']==ref,'Legacy proof differs from requested historical source')


def complete_by_stem(rows,expected,field='clip'):
    v.require(len(rows)==13,'Exact thirteen-clip evidence required')
    result={}
    for row in rows:
        stem=Path(row[field]).stem
        v.require(stem in expected and stem not in result,'Unknown or duplicate clip evidence')
        result[stem]=row
    v.require(set(result)==expected,'Complete original clip inventory required')
    return result


def numerical_rows(report,expected):
    clips=complete_by_stem(report['clips'],expected)
    interruptions=report['interruptions']
    v.require(len(interruptions)==1638 and {row['clip'] for row in interruptions}==expected,
              'Complete interrupted clip coverage required')
    rows=[]
    for stem,clip in clips.items():
        shard=dict(report,status='actual-lua-partial-snapshot-blend-and-skin-passed',clip_count=1,
            clips=[clip],interruptions=[row for row in interruptions if row['clip']==stem],
            pose_samples=252,ordinary_transition_pose_samples=126,interrupted_transition_pose_samples=126,
            bone_comparisons=252*138,weighted_vertex_samples=252*35310,pure_authored_zero_write_checks=18,
            authored_helper_no_legacy_bone_write_checks=126)
        blend.validate_shard(shard,expected)
        rows.extend(clip['samples'])
    rows.extend(interruptions)
    v.require(len(rows)==3276 and report['ordinary_transition_pose_samples']==1638 and
              report['interrupted_transition_pose_samples']==1638 and
              sum(row['bone_comparisons'] for row in rows)==report['bone_comparisons']==452088 and
              sum(row['weighted_vertex_samples'] for row in rows)==report['weighted_vertex_samples']==115675560,
              'Numerical aggregate counts differ from complete rows')
    maxima={key:max(row[key] for row in rows) for key in
            ('max_head_error_m','max_axis_error_m','max_local_matrix_error','max_weighted_skin_error_m')}
    rms=math.sqrt(sum(row['skin_squared_error_sum'] for row in rows)/115675560)
    v.require(report['maxima']==maxima and math.isfinite(rms) and report['weighted_skin_rms_m']==rms,
              'Numerical maxima or RMS differ from measured rows')
    return clips


def checked_shards(report,expected,kind,required):
    paths=report['shard_reports'];v.require(len(paths)==13,'Exact thirteen shard receipts required')
    result={}
    suffix='.blend.json' if kind=='blend' else '.equivalence.json'
    for path,sha in paths.items():
        path=Path(path);v.validate_probe(v.ROOT,path.parent);v.reject_redirect(path)
        v.require(path.name.endswith(suffix),'Wrong shard report suffix')
        stem=path.name.removesuffix(suffix)
        v.require(stem in expected and stem not in result and v.digest(path)==sha,'Stale/duplicate/unknown shard receipt')
        shard=json.loads(path.read_text());require_frozen(shard,required)
        if kind=='blend':blend.validate_shard(shard,expected)
        else:v.require(shard['status']=='actual-lua-partial-legacy-poses-byte-identical' and
                       shard['native_Unit_pose_samples']==0 and shard['game_acceptance']=='not performed',
                       'Legacy shard has invalid scope')
        v.require(len(shard['clips'])==1 and Path(shard['clips'][0]['clip']).stem==stem,
                  'Shard receipt filename/clip identity differs')
        result[stem]=(path,shard)
    v.require(set(result)==expected,'Incomplete shard receipt inventory')
    return result


def run(args):
    old=v.validate_probe(v.ROOT,args.old_probe);current=v.validate_probe(v.ROOT,args.current_probe)
    initial_proof_paths=[args.blend_report,args.legacy_report,args.original_report,args.animation_manifest,
                         current/'compiled_animation_contract.json',Path(__file__),Path(package.__file__),
                         Path(legacy.__file__),Path(blend.__file__)]
    initial_proof_pins={str(p.resolve()):v.digest(p) for p in initial_proof_paths}
    blend_report=json.loads(args.blend_report.read_text());legacy_report=json.loads(args.legacy_report.read_text())
    blend_inputs,legacy_inputs,names,original=expected_inputs(old,args.animation_manifest,args.original_report)
    require_frozen(blend_report,blend_inputs);require_frozen(legacy_report,legacy_inputs)
    require_legacy_scope(legacy_report,args.original_report,args.original_git_ref)
    v.require(blend_report['status']=='actual-lua-snapshot-blend-and-skin-passed' and
              blend_report['clip_count']==13 and blend_report['pose_samples']==3276 and
              blend_report['bone_comparisons']==452088 and blend_report['weighted_vertex_samples']==115675560 and
              blend_report['pure_authored_zero_write_checks']==234 and
              blend_report['authored_helper_no_legacy_bone_write_checks']==1638 and
              blend_report['fixed_tolerance_m']==.002 and blend_report['native_Unit_pose_samples']==0 and
              blend_report['SDK_runs']==0 and blend_report['game_acceptance']=='not performed',
              'Blend proof scope or full coverage differs')
    v.require(blend_report['original_clip_compatibility']==original,'Numerical original clip proof differs')
    expected={Path(item['clip']).stem for item in original['clips']}
    blend_clips=numerical_rows(blend_report,expected)
    legacy_clips=complete_by_stem(legacy_report['clips'],expected)
    blend_shards=checked_shards(blend_report,expected,'blend',blend_inputs)
    legacy_shards=checked_shards(legacy_report,expected,'legacy',legacy_inputs)
    for stem in expected:
        bs=blend_shards[stem][1];ls=legacy_shards[stem][1]
        v.require(bs['clips'][0]==blend_clips[stem] and
                  bs['interruptions']==[row for row in blend_report['interruptions'] if row['clip']==stem],
                  'Merged blend rows differ from executed shard')
        for field in ('original_clip_compatibility','scope','helper_clock_scope','outgoing_semantics',
                      'weights','global_scales','source_phases','fixed_tolerance_m'):
            v.require(bs[field]==blend_report[field],'Blend shard declared semantics differ: '+field)
        v.require(ls['clips'][0]==legacy_clips[stem] and ls['historical_report_sha256']==v.digest(args.original_report) and
                  ls['historical_source_git_ref']==args.original_git_ref,'Merged legacy rows/source differ from executed shard')
        for field in ('historical_report_sha256','historical_source_git_ref','historical_grip_sha256',
                      'historical_outfit_sha256','current_grip_sha256','current_outfit_sha256',
                      'decoder_and_skin_functions_byte_identical'):
            v.require(ls[field]==legacy_report[field],'Legacy shard source identity differs: '+field)
        clip=legacy_clips[stem]
        animation_path=v.indexed_resources(v.ROOT,old,old/'candidate/data',
            ['units/warlock_bombardier/anims/'+stem+'.animation'])[0]
        duration=v.decode_animation(animation_path.read_bytes())['duration']
        for evidence in (blend_clips[stem],legacy_clips[stem]):
            v.require(evidence['compiled_animation_sha256']==v.digest(animation_path) and
                      evidence['native_carrier_animation_sha256']==v.digest(r.NATIVE_ANIMS/(stem+'.animation')),
                      'Numerical clip provenance differs from actual compiled or native carrier bytes')
        fps=960 if stem=='death_shot' or stem.startswith('stagger_') else 240
        count=2*(round(duration*fps)+1)-1
        v.require(clip['sample_fps']==fps and clip['pose_samples']==count and
                  clip['exact_local_matrix_comparisons']==count*138 and clip['max_local_matrix_error']==0 and
                  clip['historical_weighted_vertex_comparisons_preserved_by_exact_pose_identity']==count*35310 and
                  clip['compiled_animation_sha256']==v.digest(animation_path),
                  'Legacy coverage differs from decoded duration and fixed sample rate')
        v.require(ls['clip_count']==1 and ls['pose_samples']==count and ls['exact_local_matrix_comparisons']==count*138 and
                  ls['historical_weighted_vertex_comparisons_preserved_by_exact_pose_identity']==count*35310 and
                  ls['max_local_matrix_error']==0 and ls['fixed_tolerance_m']==.002 and
                  ls['new_weighted_vertex_evaluations']==0,'Legacy shard summary differs from complete decoded coverage')
    v.require(sum(c['pose_samples'] for c in legacy_clips.values())==legacy_report['pose_samples'] and
              sum(c['exact_local_matrix_comparisons'] for c in legacy_clips.values())==legacy_report['exact_local_matrix_comparisons'] and
              sum(c['historical_weighted_vertex_comparisons_preserved_by_exact_pose_identity'] for c in legacy_clips.values())==
              legacy_report['historical_weighted_vertex_comparisons_preserved_by_exact_pose_identity'],
              'Legacy aggregate sums differ from validated per-clip coverage')
    helpers=helper_identity(args.original_git_ref)
    bridge=legacy.compiled_lane_equivalence(old,current,names)
    manifest=json.loads(args.animation_manifest.read_text())
    v.require(v.digest(args.animation_manifest)==v.digest(current/'integration_manifest.json'),
              'Final SDK lane uses another trusted presentation manifest')
    old_manifest=json.loads((old/'integration_manifest.json').read_text())
    a,b=old_manifest['profiles']['localized-v1-runtime'],manifest['profiles']['localized-v1-runtime']
    for field in ('channels','native_bind_scale','reference_bone','accessory_skin','body_fbx_sha256',
                  'shipping_body_sha256','shipping_bones_sha256','rest_contract_sha256'):
        v.require(a[field]==b[field],'Current numerical accessory/skin contract differs: '+field)
    resource='units/warlock_bombardier/anims/authored/continuous.animation'
    authored_paths=[v.indexed_resources(v.ROOT,p,p/'candidate/data',[resource])[0] for p in (old,current)]
    v.require(authored_paths[0].read_bytes()==authored_paths[1].read_bytes(),'Current authored decoded pose source differs')
    # Recheck live compiled files, loader closure and decoded companion semantics.
    package.audit(current)
    package_path=current/'compiled_package_closure.json';closure=json.loads(package_path.read_text())
    v.require(closure['manifest_sha256']==v.digest(args.animation_manifest),'Package proof uses another manifest')
    proof_paths=[args.blend_report,args.legacy_report,args.original_report,args.animation_manifest,
                 current/'compiled_animation_contract.json',package_path,Path(__file__),
                 Path(package.__file__),Path(legacy.__file__),Path(blend.__file__),
                 *[Path(item['path']) for item in helpers],
                 *[path for path,_ in blend_shards.values()],*[path for path,_ in legacy_shards.values()]]
    frozen={str(p.resolve()):v.digest(p) for p in proof_paths}
    for path,sha in initial_proof_pins.items():
        v.require(frozen.get(path)==sha,'Acceptance proof or producer changed during audit')
    for helper in helpers:
        v.require(frozen[helper['path']]==helper['current_sha256'],'Executed helper changed during audit')
    for proof in (blend_report,legacy_report):
        merge_recorded_numerical_pins(frozen,proof)
    input_receipt=json.loads((current/'input_receipt.json').read_text())
    for path,sha in input_receipt['package_closure']['source_input_sha256'].items():
        v.require(path not in frozen or frozen[path]==sha,'Final SDK producer pin conflict')
        frozen[path]=sha
    for resource,sha in closure['compiled_resource_sha256'].items():
        path=v.indexed_resources(v.ROOT,current,current/'candidate/data',[resource])[0]
        frozen[str(path.resolve())]=sha
    result={'schema':1,'status':'current-source-snapshot-blend-sdk-and-provenance-passed',
        'fixed_tolerance_m':.002,'blend_report_sha256':v.digest(args.blend_report),
        'legacy_equivalence_report_sha256':v.digest(args.legacy_report),'historical_report_sha256':v.digest(args.original_report),
        'current_sdk_report_sha256':v.digest(current/'compiled_animation_contract.json'),
        'current_package_closure_sha256':v.digest(package_path),'manifest_sha256':v.digest(args.animation_manifest),
        'manifest_id':b['manifest_id'],'compiled_lane_equivalence':bridge,
        'compiled_authored_animation_sha256':v.digest(authored_paths[1]),'executable_helper_identity':helpers,
        'numerical_pose_samples':3276,'bone_comparisons':452088,'weighted_vertex_samples':115675560,
        'maxima':blend_report['maxima'],'weighted_skin_rms_m':blend_report['weighted_skin_rms_m'],
        'current_legacy_pose_samples':24077,'exact_legacy_local_matrices':3322626,
        'historical_weighted_vertices_preserved_by_exact_pose_and_skin_identity':850158870,
        'new_legacy_weighted_evaluations':0,'native_Unit_pose_samples':0,'game_acceptance':'not performed',
        'numerical_clip_scope':'All thirteen decoded legacy clips are pose specimens, including death/staggers; this does not register authored death or staggers',
        'registered_authored_states':[name for name,state in b['states'].items() if state['owner']=='authored'],
        'helper_clock_scope':blend_report['helper_clock_scope'],'outgoing_semantics':blend_report['outgoing_semantics'],
        'frozen_input_sha256':frozen}
    destination=v.validate_probe(v.ROOT,args.report.parent)/args.report.name;v.reject_redirect(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    for path,sha in frozen.items():v.require(v.digest(path)==sha,'Final acceptance input changed')
    destination.write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({'status':result['status'],'report_sha256':v.digest(destination)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('old-probe','current-probe','blend-report','legacy-report','original-report','animation-manifest','report'):
        parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--original-git-ref',required=True)
    run(parser.parse_args())
