"""Revalidate every historical dense pose with old and current actual Lua.

Exact float32 local matrices and identical compiled skin streams imply the
historical linear weighted skin results are unchanged. This reuses that skin
evidence transparently; it does not claim another 850 million skin evaluations.
"""
import argparse
import ast
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import verify_runtime_outfit as r


@contextmanager
def flat_scratch(prefix, directory=None):
    """mkdtemp folder whose flat files are removed by explicit path; never rmtree."""
    folder = Path(tempfile.mkdtemp(prefix=prefix, dir=directory))
    try:
        yield str(folder)
    finally:
        for entry in folder.iterdir():
            if entry.is_file() and not entry.is_symlink():
                entry.unlink()
        folder.rmdir()

v=r.v


def git_bytes(ref,relative):
    v.require(isinstance(ref,str) and ref and not ref.startswith('-'),'Invalid original Git revision')
    return subprocess.check_output(['git','show',ref+':'+relative],cwd=v.ROOT)


def identical_decoder_functions(old,current):
    required=('normalized_quaternion','decode_animation','sample_compiled','transform','compiled_weights','weighted_batch')
    def definitions(source):
        return {n.name:ast.get_source_segment(source,n) for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
    a,b=definitions(old),definitions(current)
    for name in required:v.require(name in a and name in b and a[name]==b[name],
                                  'Historical pose/skin evaluator changed: '+name)
    return list(required)


def compiled_lane_equivalence(old_probe,current_probe,names):
    from compiled_integration import unit_metadata
    from test_warlock_weapon_pipeline import idstring32
    resources=[v.UNIT+'.unit',v.UNIT+'.bones']
    old=v.indexed_resources(v.ROOT,old_probe,old_probe/'candidate/data',resources)
    current=v.indexed_resources(v.ROOT,current_probe,current_probe/'candidate/data',resources)
    a,b=old[0].read_bytes(),current[0].read_bytes()
    end_a=unit_metadata(a)['geometry_scene_actor_prefix_end'];end_b=unit_metadata(b)['geometry_scene_actor_prefix_end']
    v.require(end_a==end_b and a[:end_a]==b[:end_b],'New compiled scene/geometry/skin/bind prefix differs')
    v.require(old[1].read_bytes()==current[1].read_bytes(),'New compiled 138-bone contract differs')
    records=[]
    for clip in v.verify_original_clips(old_probe,names)['clips']:
        resource='units/warlock_bombardier/anims/'+Path(clip['clip']).stem+'.animation'
        paths=[v.indexed_resources(v.ROOT,p,p/'candidate/data',[resource])[0] for p in (old_probe,current_probe)]
        v.require(paths[0].read_bytes()==paths[1].read_bytes(),'New compiled original138 tracks differ: '+resource)
        records.append({'resource':resource,'sha256':v.digest(paths[0])})
    manifest=json.loads((current_probe/'integration_manifest.json').read_text());profile=manifest['profiles']['localized-v1-runtime']
    data=unit_metadata(b)['data']
    v.require(data=={idstring32('warlock_rig_profile'):'localized-v1-runtime',
                    idstring32('warlock_animation_manifest_id'):profile['manifest_id']},'New compiled Unit markers differ')
    sdk=json.loads((current_probe/'compiled_animation_contract.json').read_text())
    v.require(sdk['status']=='sdk-compiled-and-decoded','Current SDK lane is not accepted')
    return {'old_compiled_unit_sha256':v.digest(old[0]),'current_compiled_unit_sha256':v.digest(current[0]),
        'exact_geometry_scene_skin_bind_actor_prefix_bytes':end_a,'all_original_tracks_identical':True,
        'original_clips':records,'current_sdk_receipt_sha256':v.digest(current_probe/'compiled_animation_contract.json'),
        'current_manifest_sha256':v.digest(current_probe/'integration_manifest.json'),'current_manifest_id':profile['manifest_id']}


def run(args):
    probe=v.validate_probe(v.ROOT,args.probe_root)
    report_path=v.validate_probe(v.ROOT,args.report.parent)/args.report.name;v.reject_redirect(report_path)
    report_path.parent.mkdir(parents=True,exist_ok=True)
    old_report=json.loads(args.original_report.read_text())
    v.require(old_report['status']=='runtime-lua-decoded-hierarchy-and-skin-passed' and old_report['all_thirteen']
              and old_report['skin_checked'] and old_report['post_grip'] and not old_report['fidelity_errors']
              and old_report['fixed_tolerance_m']==.002,'Historical full legacy proof is incomplete')
    v.require(v.digest(Path(r.__file__))==old_report['verifier_sha256'],'Historical Lua scene evaluator changed')
    old_source={}
    for field,path in (('grip_module_sha256',r.GRIP),('runtime_module_sha256',r.RUNTIME)):
        raw=git_bytes(args.original_git_ref,str(path.relative_to(v.ROOT)).replace('\\','/'))
        v.require(hashlib.sha256(raw).hexdigest()==old_report[field],'Git source does not match historical actual Lua '+field)
        old_source[path.name]=raw
    old_decoder=git_bytes(args.original_git_ref,str(Path(v.__file__).relative_to(v.ROOT)).replace('\\','/')).decode()
    functions=identical_decoder_functions(old_decoder,Path(v.__file__).read_text())
    for path,sha in old_report['frozen_input_sha256'].items():
        if Path(path).resolve() in {r.GRIP.resolve(),r.RUNTIME.resolve(),Path(v.__file__).resolve()} :continue
        v.require(v.digest(path)==sha,'Historical frozen asset/evaluator changed: '+path)
    paths=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',[v.UNIT+'.unit',v.UNIT+'.bones'])
    unit=r.compiled_unit_structure(paths[0].read_bytes());names=list(r.compiled_bones(paths[1].read_bytes()))
    v.require(len(names)==138,'Legacy skeleton changed')
    original=v.verify_original_clips(probe,names)
    manifest=json.loads((probe/'integration_manifest.json').read_text());profile=manifest['profiles']['localized-v1-runtime']
    metadata={'warlock_rig_profile':'localized-v1-runtime','warlock_animation_manifest_id':profile['manifest_id']}
    sampler=r.NativePoseSampler(unit,names)
    native=r.compiled_unit_structure(r.NATIVE_UNIT.read_bytes());native_names=list(r.compiled_bones(r.NATIVE_BONES.read_bytes()))
    owner_sampler=r.NativePoseSampler(native,native_names)
    frozen_paths=[args.original_report,r.GRIP,r.RUNTIME,Path(__file__),Path(r.__file__),Path(v.__file__),
        probe/'integration_manifest.json',probe/'original-clips.json',probe/'input_receipt.json',*paths,r.NATIVE_UNIT,r.NATIVE_BONES]
    input_clips=[]
    for clip in original['clips']:
        stem=Path(clip['clip']).stem
        path=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',['units/warlock_bombardier/anims/'+stem+'.animation'])[0]
        owner=r.NATIVE_ANIMS/(stem+'.animation');input_clips.append((clip,stem,path,owner));frozen_paths.extend((path,owner))
    frozen={str(p.resolve()):v.digest(p) for p in frozen_paths}
    report_path.write_text(json.dumps({'schema':1,'status':'running-not-validated','frozen_input_sha256':frozen},indent=2))
    old_by_clip={Path(c['clip']).stem:c for c in old_report['clips']};results=[]
    current_grip,current_outfit=r.GRIP,r.RUNTIME
    # Other workers recursively validate the indexed SDK probe. Captures must
    # live outside that immutable tree, so deleting this worker's temporary
    # directory cannot race another worker's path-redirect traversal.
    captured_root=v.validate_probe(v.ROOT,v.ROOT/'.build/animator_rig/legacy_lua_worker_source')
    captured_root.mkdir(parents=True,exist_ok=True)
    with flat_scratch('old_lua_',captured_root) as temp:
        temp=Path(temp)
        for name,raw in old_source.items():(temp/name).write_bytes(raw)
        for clip,stem,path,owner_path in input_clips:
            if args.clip and stem!=args.clip:continue
            animation=v.decode_animation(path.read_bytes());owner_animation=v.decode_animation(owner_path.read_bytes())
            sampler.set_animation(animation);owner_sampler.set_animation(owner_animation)
            current=r.LuaPoseScene(sampler,owner_sampler,manifest,metadata)
            try:
                r.GRIP=temp/current_grip.name;r.RUNTIME=temp/current_outfit.name
                old=r.LuaPoseScene(sampler,owner_sampler,manifest,metadata)
            finally:r.GRIP,r.RUNTIME=current_grip,current_outfit
            for scene in (old,current):scene.reset(sampler.locals(0),owner_sampler.locals(0));scene.start()
            fps=960 if stem=='death_shot' or stem.startswith('stagger_') else 240
            count=2*(round(animation['duration']*fps)+1)-1
            prior=old_by_clip[stem]
            v.require(prior['sample_fps']==fps and prior['pose_samples']==count and prior['bone_comparisons']==count*138
                      and prior['weighted_vertex_samples']==count*35310,'Historical dense coverage differs: '+stem)
            for index in range(count):
                time=index/(fps*2);carrier_time=time/animation['duration']*owner_animation['duration']
                local=sampler.locals(time);carrier=owner_sampler.locals(carrier_time)
                for scene in (old,current):
                    scene.reset(local,carrier);scene.lua.globals().run_grip()
                    applied,_,status=scene.apply();v.require(applied,'Legacy writer rejected '+stem+': '+str(status))
                for node in sampler.indices.values():
                    v.require(np.array_equal(old.locals_[True][node],current.locals_[True][node]),
                              'Actual Lua legacy pose changed: '+stem+'/'+str(index)+'/'+str(node))
                if index%1024==1023:print(json.dumps({'clip':stem,'completed':index+1,'expected':count}),flush=True)
            results.append({'clip':clip['clip'],'sample_fps':fps,'pose_samples':count,'exact_local_matrix_comparisons':count*138,
                'max_local_matrix_error':0.,'compiled_animation_sha256':v.digest(path),
                'native_carrier_animation_sha256':v.digest(owner_path),
                'historical_weighted_vertex_comparisons_preserved_by_exact_pose_identity':count*35310})
            print(json.dumps(results[-1]),flush=True)
    for path,sha in frozen.items():v.require(v.digest(path)==sha,'Frozen equivalence input changed: '+path)
    v.require(v.verify_original_clips(probe,names)==original,'Original tracks changed during equivalence run')
    total=sum(c['pose_samples'] for c in results)
    v.require(bool(results),'Requested original clip is absent')
    if not args.clip:v.require(len(results)==13 and total==24077,'Required complete original legacy coverage is missing')
    bridge=compiled_lane_equivalence(probe,v.validate_probe(v.ROOT,args.current_probe),names) if args.current_probe else None
    report={'schema':1,'status':'actual-lua-partial-legacy-poses-byte-identical' if args.clip else
            'actual-lua-all-legacy-poses-byte-identical','clip_count':len(results),'pose_samples':total,
        'exact_local_matrix_comparisons':total*138,'max_local_matrix_error':0.,'fixed_tolerance_m':.002,
        'historical_weighted_vertex_comparisons_preserved_by_exact_pose_identity':total*35310,
        'new_weighted_vertex_evaluations':0,'native_Unit_pose_samples':0,'game_acceptance':'not performed',
        'historical_report_sha256':v.digest(args.original_report),'historical_source_git_ref':args.original_git_ref,
        'historical_grip_sha256':old_report['grip_module_sha256'],'historical_outfit_sha256':old_report['runtime_module_sha256'],
        'current_grip_sha256':v.digest(r.GRIP),'current_outfit_sha256':v.digest(r.RUNTIME),
        'decoder_and_skin_functions_byte_identical':functions,'compiled_lane_equivalence':bridge,
        'frozen_input_sha256':frozen,'clips':results}
    report_path.write_text(json.dumps(report,indent=2),encoding='utf8');print('REPORT_SHA256 '+v.digest(report_path))


def merge(args):
    probe=v.validate_probe(v.ROOT,args.probe_root);directory=v.validate_probe(v.ROOT,args.merge)
    names=list(r.compiled_bones(v.indexed_resources(v.ROOT,probe,probe/'candidate/data',[v.UNIT+'.bones'])[0].read_bytes()))
    expected=v.verify_original_clips(probe,names)['clips'];expected_names={Path(c['clip']).stem for c in expected}
    records=[];clips={}
    for path in sorted(directory.glob('*.equivalence.json')):
        report=json.loads(path.read_text());v.require(report['status']=='actual-lua-partial-legacy-poses-byte-identical'
            and report['clip_count']==1 and report['fixed_tolerance_m']==.002 and report['max_local_matrix_error']==0
            and report['new_weighted_vertex_evaluations']==0,'Incomplete/invalid exact legacy shard')
        for frozen,sha in report['frozen_input_sha256'].items():v.require(v.digest(frozen)==sha,'Frozen legacy shard input changed')
        for other in records:
            for field in ('frozen_input_sha256','historical_report_sha256','historical_source_git_ref',
                          'historical_grip_sha256','historical_outfit_sha256','current_grip_sha256','current_outfit_sha256',
                          'decoder_and_skin_functions_byte_identical'):
                v.require(report[field]==other[field],'Legacy equivalence shards differ: '+field)
        v.require(len(report['clips'])==1,'Expected one complete clip per shard')
        clip=report['clips'][0];stem=Path(clip['clip']).stem
        v.require(stem in expected_names and stem not in clips,'Unknown/duplicate legacy equivalence shard')
        resource='units/warlock_bombardier/anims/'+stem+'.animation'
        compiled=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',[resource])[0]
        animation=v.decode_animation(compiled.read_bytes());fps=960 if stem=='death_shot' or stem.startswith('stagger_') else 240
        count=2*(round(animation['duration']*fps)+1)-1
        v.require(clip['sample_fps']==fps and clip['pose_samples']==count and
                  clip['exact_local_matrix_comparisons']==count*138 and clip['max_local_matrix_error']==0
                  and clip['historical_weighted_vertex_comparisons_preserved_by_exact_pose_identity']==count*35310,
                  'Legacy equivalence coverage does not match decoded native duration')
        v.require(report['pose_samples']==count and report['exact_local_matrix_comparisons']==count*138,
                  'Legacy shard summary is stale')
        clips[stem]=clip;records.append(report)
    v.require(set(clips)==expected_names and len(records)==13,'All complete thirteen legacy equivalence shards required')
    result=records[0].copy();result['clips']=[clips[Path(c['clip']).stem] for c in expected]
    total=sum(c['pose_samples'] for c in result['clips']);v.require(total==24077,'Unexpected legacy dense sample count')
    result.update(status='actual-lua-all-legacy-poses-byte-identical',clip_count=13,pose_samples=total,
        exact_local_matrix_comparisons=total*138,
        historical_weighted_vertex_comparisons_preserved_by_exact_pose_identity=total*35310,
        shard_reports={str(p.resolve()):v.digest(p) for p in sorted(directory.glob('*.equivalence.json'))})
    result['compiled_lane_equivalence']=compiled_lane_equivalence(probe,v.validate_probe(v.ROOT,args.current_probe),names) if args.current_probe else None
    destination=v.validate_probe(v.ROOT,args.report.parent)/args.report.name;v.reject_redirect(destination)
    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({'status':result['status'],'pose_samples':total,'exact_local_matrix_comparisons':total*138,
                      'report_sha256':v.digest(destination)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-root',type=Path,required=True)
    parser.add_argument('--original-report',type=Path,required=True)
    parser.add_argument('--original-git-ref',required=True)
    parser.add_argument('--current-probe',type=Path)
    parser.add_argument('--clip',help='One complete clip; only strict merge grants all-thirteen acceptance')
    parser.add_argument('--merge',type=Path,help='Merge thirteen complete frozen clip shards')
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.merge:merge(args)
    else:run(args)
