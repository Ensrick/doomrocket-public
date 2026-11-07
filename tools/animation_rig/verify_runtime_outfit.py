"""Execute the actual opt-in Lua correction on decoded SDK scene poses.

The Lua solver runs with independent float32 local-write/scene composition
doubles. This is a numerical runtime contract audit, not a native Unit capture
or rendered game session. Shipping clip bytes and all 138 tracks are retained.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import sys
import struct
import hashlib
import copy

import numpy as np
from lupa.lua51 import LuaRuntime
import verify_compiled_animation as v

ROOT=v.ROOT
sys.path.insert(0,str(ROOT/'tools/tests'))
import test_doomrocket_hose_lifecycle as lifetime
from test_warlock_weapon_pipeline import compiled_unit_structure,compiled_node_index,idstring32,BinaryFbx
from test_doomrocket_visible_aim import compiled_bones

RUNTIME=ROOT/'scripts/mods/doomrocket/extensions/doomrocket_outfit_correction.lua'
GRIP=ROOT/'scripts/mods/doomrocket/extensions/doomrocket_grip_alignment.lua'
CHANNELS=['j_whip_parent','j_whip_dynamic',*[f'j_loot_sack_component{i}' for i in range(1,6)]]
NATIVE_BASE=ROOT.parent/'_warlock_bombardier_art'
NATIVE_UNIT=NATIVE_BASE/'vt2_extract_tree/units/beings/enemies/skaven_ratlinggunner/chr_skaven_ratlinggunner.unit'
NATIVE_BONES=NATIVE_UNIT.with_suffix('.bones')
NATIVE_ANIMS=NATIVE_BASE/'ratling_anims'
IDENTITY=np.eye(4,dtype=np.float64)


class NativePoseSampler:
    """Cache scene topology; preserve decoded tracks while skipping constants."""
    def __init__(self,unit,names):
        self.unit=unit;self.names=list(names)
        self.indices={name:compiled_node_index(unit,name) for name in names}
        self.bone_by_node={index:i for i,index in enumerate(self.indices.values())}
        self.parents={i:n.parent_index if n.parent_type==1 else None for i,n in enumerate(unit.nodes)}
        self.static={i:np.asarray(v.matrix_multiply(v.inverse(unit.nodes[n.parent_index].world_transform),n.world_transform)
                                if n.parent_type==1 else n.world_transform,dtype=np.float64)
                     for i,n in enumerate(unit.nodes)}
        self.animation=None

    def set_animation(self,animation):
        v.require(animation['bones']==len(self.names),'Pose sampler skeleton mismatch')
        self.animation=animation
        self.constants={(i,channel):keys[0][1] for i,t in enumerate(animation['tracks']) for channel,keys in t.items()
                        if all(value==keys[0][1] for _,value in keys)}

    def locals(self,time):
        result={i:m.copy() for i,m in self.static.items()}
        for index,bone in self.bone_by_node.items():
            track=self.animation['tracks'][bone]
            values={channel:self.constants.get((bone,channel)) or v.sample_compiled(keys,time,channel=='rotation')
                    for channel,keys in track.items()}
            result[index]=np.asarray(v.transform(values['position'],values['rotation'],values['scale']),dtype=np.float64)
        return result

    def world(self,locals_):
        memo={}
        def visit(i):
            if i not in memo:
                parent=self.parents[i]
                memo[i]=locals_[i] if parent is None else visit(parent)@locals_[i]
            return memo[i]
        return {name:visit(index) for name,index in self.indices.items()}


LUA_SCENE=lifetime.HARNESS.split('Quaternion={')[0]+r'''
function keep(p) local q=Matrix4x4.copy(p);q.epoch=nil;return q end
function rotation(p)
 local q=Matrix4x4.copy(p)
 for _,axis in ipairs({'x','y','z'}) do
  local value=Matrix4x4[axis](q);local n=Vector3.length(value)
  Matrix4x4['set_'..axis](q,Vector3(value.x/n,value.y/n,value.z/n))
 end
 Matrix4x4.set_translation(q,Vector3(0,0,0));return q
end
Matrix4x4.rotation=rotation
Matrix4x4.from_quaternion_position=function(q,v)
 local p=Matrix4x4.copy(q);Matrix4x4.set_translation(p,v);return p
end
Vector3.is_valid=function(v)
 return v.x==v.x and v.y==v.y and v.z==v.z and math.abs(v.x)<math.huge and math.abs(v.y)<math.huge and math.abs(v.z)<math.huge
end
world={};other_world={};owner={alive=true,name='carrier'};outfit={alive=true,name='units/warlock_bombardier/warlock_bombardier_3p'}
weapon={alive=true,name='units/rocket/pRocketLauncher'};callbacks={};pose_calls={writes=0,flushes=0}
local function checked(u) assert(u and u.alive,'dead native unit');return u end
Unit={
 alive=function(u) return u and u.alive end,
 world=function(u) checked(u);return world end,
 get_data=function(u,key) checked(u);if key=='unit_name' then return u.name end;return u.metadata and u.metadata[key] end,
 has_node=function(u,name) checked(u);return u.nodes[name]~=nil end,
 node=function(u,name) checked(u);return assert(u.nodes[name],'missing native node') end,
 scene_graph_parent=function(u,node) checked(u);return u.parents[node] end,
 world_pose=function(u,node) checked(u);return py_world(u==outfit,node) end,
 local_pose=function(u,node) checked(u);return py_local(u==outfit,node) end,
 world_position=function(u,node) return Matrix4x4.translation(Unit.world_pose(u,node)) end,
 world_rotation=function(u,node) return rotation(Unit.world_pose(u,node)) end,
 local_scale=function(u,node)
  local p=Unit.local_pose(u,node)
  return Vector3(Vector3.length(Matrix4x4.x(p)),Vector3.length(Matrix4x4.y(p)),Vector3.length(Matrix4x4.z(p)))
 end,
 set_local_rotation=function(u,node,q)
  checked(u);assert(u==outfit and allowed_nodes[node],'unowned native pose write')
  local p=Unit.local_pose(u,node);local scale=Unit.local_scale(u,node)
  for i,axis in ipairs({'x','y','z'}) do
   local vector=Matrix4x4[axis](q);local n=Vector3.length(vector)
   Matrix4x4['set_'..axis](p,Vector3(vector.x/n*scale[i],vector.y/n*scale[i],vector.z/n*scale[i]))
  end
  py_write(node,p);pose_calls.writes=pose_calls.writes+1
 end,
 set_local_position=function(u,node,position)
  checked(u);assert(u==outfit and allowed_nodes[node],'unowned native position write')
  local p=Unit.local_pose(u,node);Matrix4x4.set_translation(p,position)
  py_write(node,p);pose_calls.writes=pose_calls.writes+1
 end,
 set_local_scale=function() error('unexpected scale write') end,
 set_local_pose=function() error('raw pose write bypassed native T/R contract') end,
 set_animation_state_machine=function() error('foreign skeleton binding') end,
}
World={update_unit=function(w,u)
 checked(u);assert(w==world);py_flush(u==outfit);pose_calls.flushes=pose_calls.flushes+1
end}
mod={_warlock_outfits={[owner]=outfit}}
function mod:pcall(fn,...) local ok,result=pcall(fn,...);if not ok then self.last_error=result end;return ok,result end
function get_mod(name) assert(name=='doomrocket');return mod end
HEALTH_ALIVE={[owner]=true}
inventory={inventory_item_units={}}
animation={add_safe_animation_callback=function(self,fn) callbacks[#callbacks+1]=fn end}
Managers={state={entity={system=function(self,name) assert(name=='animation_system');return animation end}}}
function mod._warlock_animation_ownership()
 return {accessories=ownership_mode,upper_body=ownership_mode=='authored' and 'authored' or 'legacy',
         weapon=ownership_mode=='authored' and 'authored' or 'legacy'}
end
function run_grip()
 mod._queue_warlock_grip_alignment(world,1/60)
 local todo=callbacks;callbacks={};for _,fn in ipairs(todo) do fn() end
 assert(not mod.last_error,mod.last_error)
 return mod._warlock_grip_alignment_status(owner)
end
'''


class LuaPoseScene:
    """Actual Lua modules, with independent native-like pose stores and caches."""
    def __init__(self,outfit_sampler,owner_sampler,manifest,metadata):
        self.samplers={True:outfit_sampler,False:owner_sampler}
        self.locals_={};self.cache={True:{},False:{}};self.written=set()
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        g=self.lua.globals();g.py_local=self.local_table;g.py_world=self.world_table;g.py_write=self.write;g.py_flush=self.flush
        self.lua.execute(LUA_SCENE)
        for is_outfit,u in ((True,g.outfit),(False,g.owner)):
            sampler=self.samplers[is_outfit]
            u.nodes=self.lua.table_from(sampler.indices)
            u.parents=self.lua.table_from({i:p if p is not None else 0 for i,p in sampler.parents.items()})
        g.outfit.metadata=self.to_lua(metadata)
        g.mod._warlock_animation_manifest=self.to_lua(manifest)
        g.ownership_mode='legacy-pelvis'
        grip_names=['j_spine','j_spine1','j_leftshoulder','j_rightshoulder','j_leftarm','j_rightarm',
                    'j_leftforearm','j_rightforearm','j_lefthand','j_righthand','j_leftforearmroll','j_rightforearmroll']
        self.grip_nodes={outfit_sampler.indices[n] for n in grip_names}
        self.corrective_nodes={outfit_sampler.indices[n] for n in CHANNELS}
        g.allowed_nodes=self.lua.table_from({i:True for i in self.grip_nodes|self.corrective_nodes})
        self.lua.execute(GRIP.read_text(encoding='utf8'));self.lua.execute(RUNTIME.read_text(encoding='utf8'))

    def to_lua(self,value):
        if isinstance(value,dict):return self.lua.table_from({k:self.to_lua(v) for k,v in value.items()})
        if isinstance(value,(list,tuple)):return self.lua.table_from([self.to_lua(v) for v in value])
        return value

    def matrix_table(self,matrix):
        return self.lua.table_from([self.lua.table_from([float(x) for x in row]) for row in matrix])

    def reset(self,outfit_locals,owner_locals):
        self.locals_={True:{i:np.asarray(m,dtype=np.float32).astype(np.float64) for i,m in outfit_locals.items()},
                      False:{i:np.asarray(m,dtype=np.float32).astype(np.float64) for i,m in owner_locals.items()}}
        self.cache={True:{},False:{}};self.written.clear()
        self.lua.execute('epoch=epoch+1;pose_calls.writes=0;pose_calls.flushes=0')

    def local_table(self,is_outfit,index):return self.matrix_table(self.locals_[bool(is_outfit)][index])

    def world(self,is_outfit,index):
        key=bool(is_outfit);memo=self.cache[key]
        if index not in memo:
            parent=self.samplers[key].parents[index]
            value=self.locals_[key][index] if parent is None else self.world(key,parent)@self.locals_[key][index]
            memo[index]=np.asarray(value,dtype=np.float32).astype(np.float64)
        return memo[index]

    def world_table(self,is_outfit,index):return self.matrix_table(self.world(is_outfit,index))

    def write(self,index,matrix):
        value=np.asarray([[matrix[r+1][c+1] for c in range(4)] for r in range(4)],dtype=np.float32).astype(np.float64)
        v.check_matrix(value);v.require(index in self.corrective_nodes|self.grip_nodes,'Write outside owned nodes')
        self.locals_[True][index]=value;self.written.add(index)

    def flush(self,is_outfit):self.cache[bool(is_outfit)]={}

    def worlds(self,is_outfit=True):
        return {n:self.world(is_outfit,i).copy() for n,i in self.samplers[bool(is_outfit)].indices.items()}

    def start(self):
        self.lua.execute('assert(mod._start_warlock_grip_alignment(owner,outfit,inventory));assert(mod._start_warlock_outfit_correction(owner,outfit))')

    def apply(self,grip=False,corpse=False):
        status=self.lua.globals().run_grip() if grip else 'not requested'
        self.written.clear()
        if corpse:self.lua.execute('assert(mod._handoff_warlock_outfit_correction(owner,outfit));HEALTH_ALIVE[owner]=false')
        result=self.lua.globals().mod._apply_warlock_outfit_correction(self.lua.globals().owner,self.lua.globals().outfit,corpse)
        return bool(result),status,self.lua.globals().mod._warlock_outfit_correction_status(self.lua.globals().owner)


def expected_offsets(manifest,names):
    # Derive rigid frames independently with SVD from the approved shipping
    # rest, rather than treating Blender's tiny inherited rest shear as motion.
    records=manifest['skeleton']
    v.require([r['name'] for r in records]==names,'Runtime rest bone inventory changed')
    rest={r['name']:np.asarray(r['rest'],dtype=np.float64) for r in records}
    def rigid(matrix):
        result=matrix.copy();u,_,vt=np.linalg.svd(result[:3,:3]);result[:3,:3]=u@vt
        v.require(np.linalg.det(result[:3,:3])>0,'Negative shipping rest basis')
        return result
    hi=np.linalg.inv(rigid(rest['j_hips']))
    return {n:hi@rigid(rest[n]) for n in CHANNELS}


def validate_profile(manifest,contract,body_sha,rest_manifest):
    v.require(manifest.get('schema')==1,'Unsupported runtime manifest schema')
    profile=manifest['profiles']['localized-v1-runtime']
    v.require(profile['unit']==v.UNIT and profile['accessory_skin']=='localized-v1'
              and profile['reference_bone']=='j_hips' and profile['native_bind_scale']==100,'Wrong runtime profile contract')
    v.require(profile['body_fbx_sha256']==body_sha and profile['shipping_body_sha256']==contract['shipping_sha256']
              and profile['shipping_bones_sha256']==contract['shipping_bones_sha256'],'Runtime profile bound to other assets')
    unsigned=copy.deepcopy(manifest)
    for p in unsigned['profiles'].values():p.pop('manifest_id',None)
    canonical=json.dumps(unsigned,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf8')
    v.require(hashlib.sha256(canonical).hexdigest()==profile['manifest_id'],'Runtime manifest identity does not bind its payload')
    rest_sha=hashlib.sha256(json.dumps(rest_manifest['skeleton'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    v.require(profile['rest_contract_sha256']==rest_sha,'Runtime rest contract identity changed')
    offsets=expected_offsets(rest_manifest,contract['bone_names'])
    v.require([c['bone'] for c in profile['channels']]==CHANNELS,'Runtime correction channel inventory/order changed')
    for channel in profile['channels']:
        name=channel['bone']
        v.require(channel['parent']==contract['rest_contract'][name]['parent'],'Runtime correction parent changed')
        v.require(v.matrix_error(channel['bind_offset'],offsets[name])<2e-6,'Runtime bind offset differs from approved rest')
    v.require(len(profile['manifest_id'])==64 and all(c in '0123456789abcdef' for c in profile['manifest_id']),
              'Missing runtime profile identity')
    return profile,offsets


def corrected_expectation(before,offsets):
    expected={n:m.copy() for n,m in before.items()}
    hips=before['j_hips'];scale=np.linalg.norm(hips[:3,0]);rigid=hips.copy()
    rigid[:3,:3]/=scale
    for n,offset in offsets.items():
        scaled=offset.copy();scaled[:3,3]*=scale/100
        desired=rigid@scaled
        desired[:3,:3]*=np.linalg.norm(before[n][:3,:3],axis=0)
        expected[n]=desired
    return expected


def normalized_worlds(world):
    result={n:m.copy() for n,m in world.items()}
    for matrix in result.values():matrix[:3,:3]*=.01
    return result


def probe_errors(actual,expected,names):
    head=axis=0.;worst=None
    for name in names:
        a,b=actual[name],expected[name]
        h=float(np.linalg.norm(a[:3,3]-b[:3,3]))
        p=max(float(np.linalg.norm((a[:3,3]+a[:3,k]*.001)-(b[:3,3]+b[:3,k]*.001))) for k in range(3))
        if p>axis:worst=name
        head=max(head,h);axis=max(axis,p)
    return head,axis,worst


def merge_reports(probe,directory,manifest_path,destination):
    """Accept shards only with every required pose, vertex and frozen input."""
    directory=v.validate_probe(ROOT,directory)
    expected=json.loads((probe/'original-clips.json').read_text())['clips']
    expected_names={c['clip'] for c in expected};by_clip={};reports=[]
    for path in sorted(directory.glob('*.runtime.json')):
        v.reject_redirect(path);report=json.loads(path.read_text())
        v.require(report['skin_checked'] and report['post_grip'] and not report['fidelity_errors'],
                  'Numerical shard lacks required skin/grip success: '+str(path))
        v.require(report['unit_marker_scope']=='exact strings decoded from this compiled Unit DynamicData',
                  'Numerical shard lacks actual compiled Unit profile markers')
        v.require(len(report['clips'])==1,'Expected independent single-clip shard')
        for frozen,sha in report['frozen_input_sha256'].items():
            v.require(v.digest(frozen)==sha,'Numerical shard frozen input changed: '+frozen)
        clip=report['clips'][0];name=clip['clip']
        v.require(name in expected_names and name not in by_clip,'Duplicate/unknown numerical clip shard')
        v.require(clip['pose_samples']==clip['expected_pose_samples'] and clip['weighted_vertex_samples']==clip['pose_samples']*35310,
                  'Numerical shard coverage is incomplete: '+name)
        v.require(clip['bone_comparisons']==clip['pose_samples']*138 and clip['unchanged_compiled_tracks']==138
                  and max(clip['max_head_error_m'],clip['max_axis_error_m'],clip['max_weighted_skin_error_m'])<=.002,
                  'Numerical shard exceeds fixed fidelity contract: '+name)
        for other in reports:
            for field in ('frozen_input_sha256','input_receipt_sha256','compiled_body_sha256','body',
                          'original_clip_compatibility','runtime_module_sha256','grip_module_sha256',
                          'animation_manifest_sha256','profile_manifest_id','verifier_sha256'):
                v.require(report[field]==other[field],'Numerical shards used different '+field)
        by_clip[name]=clip;reports.append(report)
    v.require(set(by_clip)==expected_names and len(reports)==13,'All thirteen complete numerical shards are required')
    require_manifest=v.digest(manifest_path)
    v.require(reports[0]['animation_manifest_sha256']==require_manifest,'Merged manifest differs')
    report=copy.deepcopy(reports[0]);report['clips']=[by_clip[c['clip']] for c in expected]
    report.update(status='runtime-lua-decoded-hierarchy-and-skin-passed',all_thirteen=True,
                  shard_reports={str(p):v.digest(p) for p in sorted(directory.glob('*.runtime.json'))})
    report['total_pose_samples']=sum(c['pose_samples'] for c in report['clips'])
    report['total_bone_comparisons']=sum(c['bone_comparisons'] for c in report['clips'])
    report['total_weighted_vertex_samples']=sum(c['weighted_vertex_samples'] for c in report['clips'])
    destination.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({k:report[k] for k in ('status','total_pose_samples','total_bone_comparisons','total_weighted_vertex_samples')},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-root',type=Path,required=True)
    parser.add_argument('--animation-manifest',type=Path,required=True)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--clip',help='Investigate one clip; incomplete reports cannot satisfy all-thirteen acceptance')
    parser.add_argument('--skin',action='store_true',help='Check every compiled body vertex at every dense key and halfway sample')
    parser.add_argument('--post-grip',action='store_true',help='Execute actual Lua grip with decoded native Ratling poses before correction')
    parser.add_argument('--max-samples',type=int,help='Bound a partial investigation; cannot satisfy integration acceptance')
    parser.add_argument('--merge-reports',type=Path,help='Strictly merge thirteen complete single-clip runtime shards')
    args=parser.parse_args();probe=v.validate_probe(ROOT,args.probe_root)
    report_path=args.report or probe/'legacy_runtime_contract.json';v.reject_redirect(report_path)
    v.require(report_path.resolve().is_relative_to(probe.resolve()),'Runtime report must stay inside its isolated probe')
    if args.merge_reports:
        merge_reports(probe,args.merge_reports,args.animation_manifest,report_path);return
    frozen={str(path.resolve()):v.digest(path) for path in (RUNTIME,GRIP,Path(__file__),args.animation_manifest,
            probe/'input_receipt.json',probe/'animation_export.json',probe/'skin_profile.json')}
    paths=v.indexed_resources(ROOT,probe,probe/'candidate/data',[v.UNIT+'.unit',v.UNIT+'.bones'])
    unit=compiled_unit_structure(paths[0].read_bytes());names=list(compiled_bones(paths[1].read_bytes()))
    original=v.verify_original_clips(probe,names)
    receipt=json.loads((probe/'input_receipt.json').read_text());contract=json.loads((probe/'animation_export.json').read_text())
    skin_profile=json.loads((probe/'skin_profile.json').read_text())
    manifest=json.loads(args.animation_manifest.read_text());profile,offsets=validate_profile(manifest,contract,receipt['body_fbx_sha256'],skin_profile)
    metadata={'warlock_rig_profile':'localized-v1-runtime','warlock_animation_manifest_id':profile['manifest_id']}
    marker_scope='injected test fixture; Unit metadata compilation not proven in this lane'
    if receipt.get('integration_manifest_sha256'):
        v.require(receipt['integration_manifest_sha256']==v.digest(args.animation_manifest),
                  'Runtime manifest differs from the compiled integration manifest')
        from compiled_integration import unit_metadata
        decoded_data=unit_metadata(paths[0].read_bytes())['data']
        v.require(decoded_data=={idstring32(k):value for k,value in metadata.items()},'Compiled Unit profile metadata differs')
        marker_scope='exact strings decoded from this compiled Unit DynamicData'
    sampler=NativePoseSampler(unit,names)
    native=compiled_unit_structure(NATIVE_UNIT.read_bytes());native_names=list(compiled_bones(NATIVE_BONES.read_bytes()))
    owner_sampler=NativePoseSampler(native,native_names)
    baseline_path=v.indexed_resources(ROOT,probe,probe/'reference/data',[v.UNIT+'.unit'])[0]
    baseline=compiled_unit_structure(baseline_path.read_bytes())
    body,skin=v.verify_body(unit,baseline,paths[0].read_bytes(),baseline_path.read_bytes(),
                           BinaryFbx(probe/f'candidate/source/{v.UNIT}.fbx'),BinaryFbx(probe/f'reference/source/{v.UNIT}.fbx'),names,skin_profile)
    mapping,weights,binds,points,source_weights=skin
    source_batch=v.weighted_batch(points,source_weights,names);native_batch=v.weighted_batch(unit.geometries[0].positions,weights,list(binds))
    object_world=contract['reference_samples'][0]['object_world']
    inverse_rest={n:v.inverse(v.matrix_multiply(object_world,contract['rest_contract'][n]['rest_matrix'])) for n in names}
    map_array=np.asarray([mapping[i] for i in range(len(mapping))])
    regions={c['vertex']:c['area'] for c in skin_profile['corrective_skin']['changes']}
    region_vertices=defaultdict(list)
    for vertex,source in mapping.items():
        region_vertices[regions.get(source,'backpack' if source_weights[source].get('j_backpack',0)>.5 else 'body')].append(vertex)
    results=[];failures=[]
    clips=[c for c in original['clips'] if not args.clip or Path(c['clip']).stem==args.clip]
    v.require(clips,'Requested legacy clip is absent')
    for clip in clips:
        stem=Path(clip['clip']).stem;resource='units/warlock_bombardier/anims/'+stem+'.animation'
        animation_path=v.indexed_resources(ROOT,probe,probe/'candidate/data',[resource])[0]
        animation=v.decode_animation(animation_path.read_bytes());sampler.set_animation(animation)
        owner_animation_path=NATIVE_ANIMS/(stem+'.animation');owner_animation=v.decode_animation(owner_animation_path.read_bytes())
        owner_sampler.set_animation(owner_animation)
        fps=960 if stem=='death_shot' or stem.startswith('stagger_') else 240
        count=round(animation['duration']*fps)+1
        scene=LuaPoseScene(sampler,owner_sampler,manifest,metadata)
        scene.reset(sampler.locals(0),owner_sampler.locals(0));scene.start()
        head=axis=skin_max=0.;skin_sum=0.;worst=None;status_counts=defaultdict(int);region_stats=defaultdict(lambda:{'max_error_m':0.,'squared_error_sum':0.,'vertex_samples':0})
        sample_count=min(count*2-1,args.max_samples) if args.max_samples else count*2-1
        v.require(sample_count>0,'Sample limit must be positive')
        for index in range(sample_count):
            time=index/(fps*2);owner_time=time/animation['duration']*owner_animation['duration']
            scene.reset(sampler.locals(time),owner_sampler.locals(owner_time))
            if args.post_grip:grip_status=scene.lua.globals().run_grip()
            else:grip_status='not requested'
            before=scene.worlds();expected=corrected_expectation(before,offsets)
            applied,_,status=scene.apply();status_counts[grip_status]+=1
            if not applied:
                failures.append(f'{stem} frame{index}/2: runtime correction rejected {status}');break
            actual=scene.worlds()
            if scene.written!=scene.corrective_nodes:
                failures.append(f'{stem}: correction did not write exactly its seven nodes');break
            h,a,bone=probe_errors(actual,expected,names)
            if a>axis:worst={'bone':bone,'time_seconds':time,'axis_error_m':a}
            head=max(head,h);axis=max(axis,a)
            if max(h,a)>.002:
                failures.append(f'{stem}: corrected hierarchy exceeds2mm at {time}s');break
            if args.skin:
                expected_metre=normalized_worlds(expected)
                expected_points=source_batch({n:v.matrix_multiply(expected_metre[n],inverse_rest[n]) for n in names})
                actual_points=native_batch({n:v.matrix_multiply(actual[n],binds[n]) for n in binds})
                errors=np.linalg.norm(actual_points-expected_points[map_array],axis=1)
                maximum=float(errors.max());skin_max=max(skin_max,maximum);skin_sum+=float(np.sum(errors*errors))
                for area,vertices in region_vertices.items():
                    e=errors[vertices];s=region_stats[area];s['max_error_m']=max(s['max_error_m'],float(e.max()));s['squared_error_sum']+=float(np.sum(e*e));s['vertex_samples']+=len(e)
                if maximum>.002:
                    failures.append(f'{stem}: actual weighted skin exceeds2mm at {time}s ({maximum}m)');break
            if index%512==511:print(json.dumps({'clip':stem,'completed_pose_samples':index+1,'expected_pose_samples':count*2-1}),flush=True)
        evaluated=index+1
        result={'clip':clip['clip'],'sample_fps':fps,'pose_samples':evaluated,'expected_pose_samples':count*2-1,
                'bone_comparisons':evaluated*138,'max_head_error_m':head,'max_axis_error_m':axis,'worst':worst,
                'weighted_vertex_samples':evaluated*len(mapping) if args.skin else 0,'max_weighted_skin_error_m':skin_max,
                'weighted_skin_rms_m':math.sqrt(skin_sum/(evaluated*len(mapping))) if args.skin else None,
                'regions':{area:{'max_error_m':x['max_error_m'],'rms_error_m':math.sqrt(x['squared_error_sum']/x['vertex_samples']),
                                 'vertex_samples':x['vertex_samples']} for area,x in region_stats.items()},
                'grip_status_counts':dict(status_counts),'compiled_animation_sha256':v.digest(animation_path),
                'native_carrier_animation_sha256':v.digest(owner_animation_path),'unchanged_compiled_tracks':138}
        results.append(result);print(json.dumps({k:x for k,x in result.items() if k not in ('regions',)}),flush=True)
    for path,sha in frozen.items():
        if v.digest(path)!=sha:failures.append('Runtime audit input changed during execution: '+path)
    complete=not failures and len(results)==13 and args.skin and args.post_grip and not args.max_samples and bool(receipt.get('integration_manifest_sha256'))
    report={'schema':1,'status':'runtime-lua-decoded-hierarchy-and-skin-passed' if complete else 'runtime-lua-decoded-incomplete-or-failed',
            'body':body,'clips':results,'fidelity_errors':failures,'fixed_tolerance_m':.002,
            'original_clip_compatibility':original,'all_thirteen':len(results)==13,'skin_checked':args.skin,'post_grip':args.post_grip,
            'native_Unit_pose_samples':0,'game_acceptance':'not performed; actual Lua with independent float32 API doubles and binary-decoded SDK scene poses',
            'input_receipt_sha256':v.digest(probe/'input_receipt.json'),'compiled_body_sha256':v.digest(paths[0]),
            'runtime_module_sha256':v.digest(RUNTIME),'grip_module_sha256':v.digest(GRIP),
            'animation_manifest_sha256':v.digest(args.animation_manifest),'profile_manifest_id':profile['manifest_id'],
            'native_carrier_unit_sha256':v.digest(NATIVE_UNIT),'native_carrier_bones_sha256':v.digest(NATIVE_BONES),
            'verifier_sha256':v.digest(Path(__file__)),'production_assets_modified':False}
    report['frozen_input_sha256']=frozen
    report['unit_marker_scope']=marker_scope
    report_path.write_text(json.dumps(report,indent=2),encoding='utf8')
    v.require(not failures,'Actual Lua correction failed; see '+str(report_path))
    if args.clip:print('Partial investigation only; all13 acceptance remains incomplete.')


if __name__=='__main__':main()
