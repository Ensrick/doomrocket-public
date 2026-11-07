"""Strict final gate for independently executed decoded-scene Lua shards.

Rates/counts come from the actual indexed native clips, never report labels.
This wraps the frozen execution verifier without changing its running bytes.
"""
import argparse
import json
import math
from pathlib import Path
import verify_compiled_animation as v
import verify_runtime_outfit as runtime


def schedule(clip,duration):
    stem=Path(clip).stem
    fps=960 if stem=='death_shot' or stem.startswith('stagger_') else 240
    v.require(math.isfinite(duration) and 0<duration<=250,'Invalid native clip duration')
    return fps,2*(round(duration*fps)+1)-1


def validate_coverage(clip,duration):
    fps,count=schedule(clip['clip'],duration)
    v.require(clip['sample_fps']==fps,'Runtime shard used another sampling rate')
    v.require(clip['pose_samples']==clip['expected_pose_samples']==count,
              'Runtime shard omitted native-duration-derived key or halfway samples')
    v.require(clip['bone_comparisons']==count*138 and clip['weighted_vertex_samples']==count*35310,
              'Runtime shard omitted bones or weighted vertices')
    v.require(clip['unchanged_compiled_tracks']==138,'Runtime shard did not retain all138 tracks')
    for field in ('max_head_error_m','max_axis_error_m','max_weighted_skin_error_m','weighted_skin_rms_m'):
        value=clip[field]
        v.require(type(value) in (float,int) and math.isfinite(value) and 0<=value<=.002,
                  'Runtime shard failed finite fixed2mm gate: '+field)
    v.require(sum(clip['grip_status_counts'].values())==count,'Actual grip invocation coverage is incomplete')
    regions=clip['regions']
    v.require(set(regions)=={'body','backpack','waist_belt','buckle','buckle_trim','lower_coat'},
              'Runtime weighted skin regions are incomplete')
    v.require(sum(x['vertex_samples'] for x in regions.values())==count*35310,'Runtime skin region coverage is incomplete')
    for region in regions.values():
        v.require(region['vertex_samples']>0 and all(type(region[k]) in (int,float)
                and math.isfinite(region[k]) and 0<=region[k]<=.002 for k in ('max_error_m','rms_error_m')),
                  'Runtime region failed finite fixed2mm gate')


def audit(probe,directory,manifest,destination):
    expected=json.loads((probe/'original-clips.json').read_text())['clips']
    resources=['units/warlock_bombardier/anims/'+Path(c['clip']).stem+'.animation' for c in expected]
    paths=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',resources)
    durations={c['clip']:(v.decode_animation(path.read_bytes())['duration'],v.digest(path))
               for c,path in zip(expected,paths)}
    candidates=list(directory.glob('*.runtime.json'))
    v.require(len(candidates)==13,'Exactly thirteen independent runtime shards are required')
    for path in candidates:
        v.reject_redirect(path);report=json.loads(path.read_text())
        v.require(report['schema']==1 and report['fixed_tolerance_m']==.002,
                  'Runtime shard schema or fidelity budget changed')
        v.require(report['skin_checked'] is True and report['post_grip'] is True
                  and report['native_Unit_pose_samples']==0,'Runtime shard scope is incorrectly declared')
        v.require(len(report['clips'])==1,'One clip per runtime shard required')
        clip=report['clips'][0];v.require(clip['clip'] in durations,'Unknown runtime clip')
        duration,sha=durations[clip['clip']]
        v.require(clip['compiled_animation_sha256']==sha,'Runtime shard used other native animation bytes')
        native=runtime.NATIVE_ANIMS/(Path(clip['clip']).stem+'.animation')
        v.require(v.digest(native)==clip['native_carrier_animation_sha256'],'Native carrier source changed')
        validate_coverage(clip,duration)
    runtime.merge_reports(probe,directory,manifest,destination)
    report=json.loads(destination.read_text())
    report['strict_acceptance']={'status':'all-thirteen-native-duration-derived-rates-counts-and-finite-gates-passed',
        'acceptance_verifier_sha256':v.digest(Path(__file__)),'evaluator_verifier_sha256':v.digest(Path(v.__file__)),
        'native_clip_duration_bound':True,'key_and_halfway_rates_hz':{'ordinary':240,'death_and_staggers':960},
        'fixed_tolerance_m':.002,'native_Unit_pose_samples':0}
    destination.write_text(json.dumps(report,indent=2),encoding='utf8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--probe-root',type=Path,required=True)
    p.add_argument('--shards',type=Path,required=True)
    p.add_argument('--animation-manifest',type=Path,required=True)
    p.add_argument('--report',type=Path)
    args=p.parse_args();probe=v.validate_probe(v.ROOT,args.probe_root);directory=v.validate_probe(v.ROOT,args.shards)
    destination=args.report or probe/'legacy_runtime_contract.json';v.reject_redirect(destination)
    v.require(destination.resolve().is_relative_to(probe.resolve()),'Final report must stay in its probe')
    audit(probe,directory,args.animation_manifest,destination)


if __name__=='__main__':main()
