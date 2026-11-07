"""Execute presentation blending on decoded SDK poses, not a native capture.

The actual Lua compositor and pure legacy builders run against independent
float32 scene stores. Original animation resources remain byte-identical.
Reference poses use independent shortest-arc quaternion interpolation and
hierarchical local TRS composition; all native skin vertices are compared.
"""
from __future__ import annotations
import argparse
import copy
import json
import math
from pathlib import Path
import sys
from collections import defaultdict

import numpy as np
from lupa.lua51 import LuaRuntime
import verify_runtime_outfit as r

v=r.v
COMPOSER=v.ROOT/'scripts/mods/doomrocket/extensions/doomrocket_animation_blend.lua'
CLOCK=v.ROOT/'scripts/mods/doomrocket/utils/doomrocket_animation_clock.lua'
GRIP_NAMES=['j_spine','j_spine1','j_leftshoulder','j_rightshoulder','j_leftarm','j_rightarm',
            'j_leftforearm','j_rightforearm','j_lefthand','j_righthand','j_leftforearmroll','j_rightforearmroll']
WEIGHTS=(0.,.01,.25,.5,.75,.99,1.)
SCALES=(.75,1.,1.35)


def quaternion(matrix):
    """Stable orthogonal matrix extraction independent of Lua quaternion code."""
    a=np.asarray(matrix,dtype=np.float64)[:3,:3].copy()
    scale=np.linalg.norm(a,axis=0)
    v.require(np.all(np.isfinite(scale)) and np.all(scale>0),'Invalid pose scale')
    a/=scale
    v.require(np.linalg.det(a)>0 and np.max(np.abs(a.T@a-np.eye(3)))<.001,'Non-rigid local rotation')
    # Symmetric eigenproblem avoids sharing the branch formula used by runtime.
    k=np.array([[a[0,0]-a[1,1]-a[2,2],a[1,0]+a[0,1],a[2,0]+a[0,2],a[2,1]-a[1,2]],
                [a[1,0]+a[0,1],a[1,1]-a[0,0]-a[2,2],a[2,1]+a[1,2],a[0,2]-a[2,0]],
                [a[2,0]+a[0,2],a[2,1]+a[1,2],a[2,2]-a[0,0]-a[1,1],a[1,0]-a[0,1]],
                [a[2,1]-a[1,2],a[0,2]-a[2,0],a[1,0]-a[0,1],a.trace()]])/3
    _,vectors=np.linalg.eigh(k);q=vectors[:,-1]
    return q if q[3]>=0 else -q


def slerp(a,b,weight):
    a=np.asarray(a,dtype=np.float64);b=np.asarray(b,dtype=np.float64)
    a/=np.linalg.norm(a);b/=np.linalg.norm(b)
    cosine=float(np.dot(a,b))
    if cosine<0:b=-b;cosine=-cosine
    cosine=min(1.,max(-1.,cosine))
    if cosine>.9995:result=a*(1-weight)+b*weight
    else:
        angle=math.acos(cosine)
        result=(math.sin((1-weight)*angle)*a+math.sin(weight*angle)*b)/math.sin(angle)
    return result/np.linalg.norm(result)


def blend_locals(a,b,weight,bone_indices):
    v.require(math.isfinite(weight) and 0<=weight<=1,'Invalid blend weight')
    result={i:m.copy() for i,m in b.items()}
    for index in bone_indices:
        ma,mb=a[index],b[index]
        position=ma[:3,3]*(1-weight)+mb[:3,3]*weight
        scale=np.linalg.norm(ma[:3,:3],axis=0)*(1-weight)+np.linalg.norm(mb[:3,:3],axis=0)*weight
        result[index]=np.asarray(v.transform(position,slerp(quaternion(ma),quaternion(mb),weight),scale))
    return result


def independently_correct_legacy(sampler,owner_sampler,raw,carrier,offsets):
    """Solve desired native torso worlds, then pelvis accessories, without Lua."""
    result={i:m.copy() for i,m in raw.items()}
    before=sampler.world(raw);native=owner_sampler.world(carrier)
    desired={}
    for name in GRIP_NAMES:
        target=before[name];source=native[name]
        scale=np.linalg.norm(target[:3,:3],axis=0)
        pose=np.asarray(v.transform(source[:3,3],quaternion(source),scale))
        desired[sampler.indices[name]]=pose
    memo={}
    def world(index):
        if index in desired:return desired[index]
        if index not in memo:
            parent=sampler.parents[index]
            memo[index]=result[index] if parent is None else world(parent)@result[index]
        return memo[index]
    for name in GRIP_NAMES:
        index=sampler.indices[name];parent=sampler.parents[index]
        result[index]=np.linalg.solve(world(parent),desired[index]) if parent is not None else desired[index]
    corrected=sampler.world(result)
    accessory=r.corrected_expectation(corrected,offsets)
    desired={sampler.indices[n]:accessory[n] for n in r.CHANNELS};memo={}
    for name in r.CHANNELS:
        index=sampler.indices[name];parent=sampler.parents[index]
        result[index]=np.linalg.solve(world(parent),desired[index])
    return result


LUA_SCENE=r.LUA_SCENE.split('world={};')[0]+r'''
Quaternion=setmetatable({
 x=function(q) return q[1] end,y=function(q) return q[2] end,
 z=function(q) return q[3] end,w=function(q) return q[4] end,
 identity=function() return {0,0,0,1} end,
 from_elements=function(x,y,z,w) return {x,y,z,w} end,
 to_elements=function(q) return q[1],q[2],q[3],q[4] end,
 normalize=function(q) local n=math.sqrt(q[1]^2+q[2]^2+q[3]^2+q[4]^2);assert(n>0)
  return {q[1]/n,q[2]/n,q[3]/n,q[4]/n} end,
 is_valid=function(q) for i=1,4 do if q[i]~=q[i] or math.abs(q[i])==math.huge then return false end end;return true end,
}, {__call=function(_,x,y,z,w) return {x,y,z,w} end})
Matrix4x4.rotation=function(p) return py_quaternion(p) end
Matrix4x4.from_quaternion_position=function(q,p) return py_transform(q,p) end
Matrix4x4.set_scale=function(p,s)
 for i,axis in ipairs({'x','y','z'}) do local a=Matrix4x4[axis](p);local n=Vector3.length(a)
  Matrix4x4['set_'..axis](p,Vector3(a.x/n*s[i],a.y/n*s[i],a.z/n*s[i])) end
end
world={};owner={alive=true,name='carrier',key='owner'}
outfit={alive=true,name='units/warlock_bombardier/warlock_bombardier_3p',key='outfit'}
helper={alive=true,name=outfit.name,key='helper'}
callbacks={};pose_calls={writes=0,flushes=0,spawned=0,destroyed=0,builders=0}
local function checked(u) assert(u and u.alive,'dead native unit');return u end
local function pose(u,n) checked(u);return py_local(u.key,n) end
local function wp(u,n) checked(u);return py_world(u.key,n) end
Unit={alive=function(u) return u and u.alive end,world=function(u) checked(u);return world end,
 get_data=function(u,k) checked(u);if k=='unit_name' then return u.name end;return u.metadata and u.metadata[k] end,
 has_node=function(u,n) checked(u);return n==0 or u.nodes[n]~=nil end,
 node=function(u,n) checked(u);return assert(u.nodes[n],'unsafe node lookup') end,
 scene_graph_parent=function(u,n) checked(u);return u.parents[n] end,
 num_actors=function(u) checked(u);return 0 end,
 num_meshes=function(u) checked(u);return 1 end,
 set_mesh_visibility=function(u,i,v,slot) assert(u==helper and i==0 and v==false and (slot=='default' or slot=='shadow_caster')) end,
 local_pose=pose,world_pose=wp,
 local_position=function(u,n) return Matrix4x4.translation(pose(u,n)) end,
 local_rotation=function(u,n) return Matrix4x4.rotation(pose(u,n)) end,
 local_scale=function(u,n) local p=pose(u,n)
  return Vector3(Vector3.length(Matrix4x4.x(p)),Vector3.length(Matrix4x4.y(p)),Vector3.length(Matrix4x4.z(p))) end,
 world_position=function(u,n) return Matrix4x4.translation(wp(u,n)) end,
 world_rotation=function(u,n) return Matrix4x4.rotation(wp(u,n)) end,
 set_local_position=function(u,n,p) checked(u);py_write_component(u.key,n,'position',p);pose_calls.writes=pose_calls.writes+1 end,
 set_local_rotation=function(u,n,q) checked(u);py_write_component(u.key,n,'rotation',q);pose_calls.writes=pose_calls.writes+1 end,
 set_local_scale=function(u,n,s) checked(u);py_write_component(u.key,n,'scale',s);pose_calls.writes=pose_calls.writes+1 end,
 set_local_pose=function() error('raw pose setter forbidden') end,
 set_unit_visibility=function(u,v) assert(u==helper and v==false);u.visible=v end,
 set_animation_state_machine=function(u,s) assert(u==helper and s==profile.sampler_state_machine);u.asm=s end,
 enable_animation_state_machine=function(u) assert(u==helper);u.enabled=true end,
 disable_animation_state_machine=function() error('helper must animate') end,
 set_animation_bone_mode=function(u,m) assert(u==helper and m=='transform') end,
 set_bones_lod=function(u,l) assert(u==helper and l==0) end,
 set_root_mode=function(u,m) assert(u==helper and m=='ignore') end,
 set_animation_root_mode=function(u,m) assert(u==helper and m=='ignore') end,
 animation_event=function(u,e) assert(u==helper);u.event=e end,
 has_animation_event=function(u,e) checked(u);return true end,
 has_animation_state_machine=function(u) checked(u);return true end,
 animation_get_state=function(u) checked(u);assert(u==helper or u==outfit);return 17 end,
 animation_layer_info=function(u,l) checked(u);assert(l==0)
  if u==outfit then return visible_time,visible_length end
  assert(u==helper);return helper_time,helper_length end,
 animation_has_variable=function() return true end,
 animation_find_variable=function(u,n) return n end,
 animation_get_variable=function() return 1 end,
 animation_set_variable=function(u,n,val) assert(u==helper);u.variable=val end,
 animation_has_constraint_target=function() return true end,
 animation_find_constraint=function(u,n) return n end,
 animation_find_constraint_target=function(u,n) return n end,
 animation_get_constraint_target=function(u,n) assert(u==owner);return Vector3(0,5,1) end,
 animation_set_constraint_target=function(u,n,p) assert(u==helper) end,
}
World={update_unit=function(w,u) assert(w==world);checked(u);py_flush(u.key);pose_calls.flushes=pose_calls.flushes+1 end,
 spawn_unit=function(w,n,...) assert(w==world and n==outfit.name);helper.alive=true;pose_calls.spawned=pose_calls.spawned+1;return helper end,
 destroy_unit=function(w,u) assert(w==world and u==helper);helper.alive=false;pose_calls.destroyed=pose_calls.destroyed+1 end,
 link_unit=function(w,u,node,p,source) assert(w==world and u==helper and node==0 and source==owner.nodes.root_point and p==owner) end,
}
Application={can_get=function(kind,n) return kind=='state_machine' and n==loaded_sampler end,
 time_since_launch=function() return helper_time end}
HEALTH_ALIVE={[owner]=true};mod={_warlock_outfits={[owner]=outfit}}
function mod:pcall(fn,...) local ok,result=pcall(fn,...);if not ok then self.last_error=result end;return ok,result end
function get_mod(n) assert(n=='doomrocket');return mod end
inventory={inventory_item_units={}}
animation={add_safe_animation_callback=function(self,fn) callbacks[#callbacks+1]=fn end}
Managers={state={entity={system=function(self,name) assert(name=='animation_system');return animation end}}}
function mod._warlock_animation_ownership() return {accessories=ownership_mode,
 upper_body=ownership_mode=='authored' and 'authored' or 'legacy',weapon='legacy'} end
helper_time=0;helper_length=10;visible_time=0;visible_length=10;ownership_mode='legacy-pelvis'
'''


class LuaBlendScene:
    """Native-like independent stores; Lua cannot borrow expected pose values."""
    def __init__(self,sampler,owner_sampler,manifest,profile):
        self.samplers={'outfit':sampler,'helper':sampler,'owner':owner_sampler}
        self.locals_={};self.cache={key:{} for key in self.samplers};self.writes=defaultdict(int)
        self.lua=LuaRuntime(unpack_returned_tuples=True);g=self.lua.globals()
        g.py_local=self.local_table;g.py_world=self.world_table;g.py_flush=self.flush
        g.py_write_component=self.write_component;g.py_quaternion=self.quaternion_table;g.py_transform=self.transform_table
        self.lua.execute(LUA_SCENE)
        for key,s in self.samplers.items():
            unit=g[key];unit.nodes=self.to_lua(s.indices);unit.parents=self.to_lua({i:p if p is not None else 0 for i,p in s.parents.items()})
        g.mod._warlock_animation_manifest=self.to_lua(manifest)
        g.profile=g.mod._warlock_animation_manifest.profiles['localized-v1-runtime']
        g.loaded_sampler=profile['sampler_state_machine']
        g.outfit.metadata=self.to_lua({'warlock_rig_profile':'localized-v1-runtime','warlock_animation_manifest_id':profile['manifest_id']})
        g.helper.metadata=g.outfit.metadata
        g.mod._warlock_animation_clock=self.lua.execute(CLOCK.read_text(encoding='utf8'))
        for path in (r.GRIP,r.RUNTIME,COMPOSER):self.lua.execute(path.read_text(encoding='utf8'))

    def to_lua(self,value):
        if isinstance(value,dict):return self.lua.table_from({k:self.to_lua(x) for k,x in value.items()})
        if isinstance(value,(list,tuple,np.ndarray)):return self.lua.table_from([self.to_lua(x) for x in value])
        return value

    def array(self,value):return np.asarray([[value[a+1][b+1] for b in range(4)] for a in range(4)],dtype=np.float64)
    def matrix_table(self,value):return self.to_lua(np.asarray(value).tolist())
    def local_table(self,key,index):return self.matrix_table(self.locals_[key][index])
    def world(self,key,index):
        memo=self.cache[key]
        if index not in memo:
            parent=self.samplers[key].parents[index];matrix=self.locals_[key][index]
            memo[index]=np.asarray(matrix if parent is None else self.world(key,parent)@matrix,dtype=np.float32).astype(np.float64)
        return memo[index]
    def world_table(self,key,index):return self.matrix_table(self.world(key,index))
    def quaternion_table(self,matrix):return self.to_lua(quaternion(self.array(matrix)).tolist())
    def transform_table(self,q,p):return self.matrix_table(v.transform([p[i] for i in range(1,4)],[q[i] for i in range(1,5)],[1,1,1]))
    def flush(self,key):self.cache[key]={}
    def set_poses(self,outfit,helper,owner):
        self.locals_={k:{i:np.asarray(m,dtype=np.float32).astype(np.float64) for i,m in data.items()}
                      for k,data in (('outfit',outfit),('helper',helper),('owner',owner))}
        self.cache={key:{} for key in self.samplers};self.writes.clear()
        self.lua.execute('epoch=epoch+1;pose_calls.writes=0;pose_calls.flushes=0')
    def write_component(self,key,index,channel,value):
        v.require(key in ('outfit','helper'),'Carrier pose overwrite')
        if index!=0:v.require(index in self.samplers[key].indices.values(),'Write outside 138-bone contract')
        old=self.locals_[key][index];position=old[:3,3].copy();scale=np.linalg.norm(old[:3,:3],axis=0);q=quaternion(old)
        if channel=='position':position=np.asarray([value[i] for i in range(1,4)],dtype=np.float64)
        elif channel=='rotation':q=np.asarray([value[i] for i in range(1,5)],dtype=np.float64);q/=np.linalg.norm(q)
        elif channel=='scale':scale=np.asarray([value[i] for i in range(1,4)],dtype=np.float64)
        else:raise ValueError('Unknown native setter')
        self.locals_[key][index]=np.asarray(v.transform(position,q,scale),dtype=np.float32).astype(np.float64)
        self.writes[key]+=1
    def start(self):
        self.lua.execute('assert(mod._start_warlock_grip_alignment(owner,outfit,inventory));assert(mod._start_warlock_outfit_correction(owner,outfit))')
        # Public compositor API names are checked against the final module.
        self.lua.execute('assert(mod._start_warlock_animation_blend(owner,outfit,profile))')
    def worlds(self):return {n:self.world('outfit',i) for n,i in self.samplers['outfit'].indices.items()}
    def correct_displayed(self):
        self.lua.execute('''mod._queue_warlock_grip_alignment(world,1/60)
          local todo=callbacks;callbacks={};for _,fn in ipairs(todo) do fn() end
          assert(not mod.last_error,mod.last_error)
          assert(mod._warlock_grip_alignment_status(owner)=='active')
          assert(mod._apply_warlock_outfit_correction(owner,outfit))''')
    def event(self,event,from_,to,dt=.25):
        g=self.lua.globals()
        result=g.mod._note_warlock_animation_blend_event(g.owner,event,from_,to,dt)
        v.require(bool(result),'Compositor rejected event '+event+': '+str(g.mod._warlock_animation_blend_status(g.owner)))
    def tick(self,dt,time,length=10):
        g=self.lua.globals();g.helper_time=time;g.helper_length=length
        g.visible_time=time;g.visible_length=length
        g.mod._update_warlock_animation_blend(g.world,dt)
        active=g.mod._apply_warlock_animation_blend(g.owner,g.outfit)
        v.require(g.mod._warlock_animation_blend_status(g.owner) in ('ready','native','blending'),
                  'Compositor failed: '+str(g.mod._warlock_animation_blend_status(g.owner)))
        return bool(active)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-root',type=Path,required=True)
    parser.add_argument('--animation-manifest',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--clip',help='One complete clip; only strict 13-shard merge grants full acceptance')
    parser.add_argument('--merge',type=Path,help='Merge thirteen complete frozen clip reports')
    args=parser.parse_args()
    if args.merge:merge(args)
    else:run(args)


def scaled(locals_,scale):
    result={i:m.copy() for i,m in locals_.items()}
    angle=.31;c,s=math.cos(angle),math.sin(angle)
    global_=np.array([[c*scale,-s*scale,0,.2],[s*scale,c*scale,0,-.1],[0,0,scale,.05],[0,0,0,1.]])
    result[0]=global_@result[0]
    return result


def run(args):
    probe=v.validate_probe(v.ROOT,args.probe_root)
    report_path=v.validate_probe(v.ROOT,args.report.parent)/args.report.name
    v.reject_redirect(report_path);report_path.parent.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(args.animation_manifest.read_text());profile=manifest['profiles']['localized-v1-runtime']
    v.require(profile['cross_owner_transition_policy']=='snapshot-blend-v1','Expected smooth presentation profile')
    resources=[v.UNIT+'.unit',v.UNIT+'.bones','units/warlock_bombardier/anims/authored/continuous.animation']
    paths=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',resources)
    unit=r.compiled_unit_structure(paths[0].read_bytes());names=list(r.compiled_bones(paths[1].read_bytes()))
    v.require(profile['bone_names']==names and len(names)==138,'Compositor bone inventory changed')
    original=v.verify_original_clips(probe,names)
    skin_profile=json.loads((probe/'skin_profile.json').read_text())
    contract=json.loads((probe/'animation_export.json').read_text())
    r.validate_profile(manifest,contract,v.digest(probe/f'candidate/source/{v.UNIT}.fbx'),skin_profile)
    offsets=r.expected_offsets(skin_profile,names)
    sampler=r.NativePoseSampler(unit,names);authored_sampler=r.NativePoseSampler(unit,names)
    authored=v.decode_animation(paths[2].read_bytes());authored_sampler.set_animation(authored)
    native=r.compiled_unit_structure(r.NATIVE_UNIT.read_bytes());native_names=list(r.compiled_bones(r.NATIVE_BONES.read_bytes()))
    owner_sampler=r.NativePoseSampler(native,native_names)
    weights,binds=v.compiled_weights(unit,paths[0].read_bytes(),names)
    v.require(len(weights)==35310,'Native skin inventory changed')
    skin=v.weighted_batch(unit.geometries[0].positions,weights,list(binds))
    def skin_points(world):return skin({n:world[n]@np.asarray(binds[n]) for n in binds})
    inputs=[]
    for clip in original['clips']:
        stem=Path(clip['clip']).stem
        animation=v.indexed_resources(v.ROOT,probe,probe/'candidate/data',
            ['units/warlock_bombardier/anims/'+stem+'.animation'])[0]
        inputs.append((stem,animation,r.NATIVE_ANIMS/(stem+'.animation')))
    frozen_paths=paths+[args.animation_manifest,COMPOSER,CLOCK,r.GRIP,r.RUNTIME,Path(__file__),Path(r.__file__),Path(v.__file__),
          r.NATIVE_UNIT,r.NATIVE_BONES,probe/'input_receipt.json',probe/'original-clips.json',probe/'skin_profile.json',probe/'animation_export.json']
    frozen_paths +=[path for _,a,b in inputs for path in (a,b)]
    for clip in original['clips']:
        resource='units/warlock_bombardier/anims/'+Path(clip['clip']).stem
        for suffix in ('.fbx','.animation'):
            frozen_paths +=[v.ROOT/(resource+suffix),probe/f'candidate/source/{resource}{suffix}',
                           probe/f'reference/source/{resource}{suffix}']
    frozen={str(path.resolve()):v.digest(path) for path in frozen_paths}
    report_path.write_text(json.dumps({'schema':1,'status':'running-not-validated',
        'scope':'actual Lua numerical contract, not native Unit capture',
        'frozen_input_sha256':frozen},indent=2),encoding='utf8')
    aggregate=defaultdict(float);clips=[];interruptions=[];full_authored_checks=0;custom_target_checks=0
    bone_indices=list(sampler.indices.values())

    def measure(actual,expected):
        aw=sampler.world(actual);ew=sampler.world(expected)
        head,axis,_=r.probe_errors(aw,ew,names)
        local=max(float(np.max(np.abs(actual[i]-expected[i]))) for i in bone_indices)
        errors=np.linalg.norm(skin_points(aw)-skin_points(ew),axis=1)
        v.require(max(head,axis,float(errors.max()))<=.002,'Actual Lua blend exceeds fixed2mm fidelity gate')
        return {'max_head_error_m':head,'max_axis_error_m':axis,'max_local_matrix_error':local,
                'max_weighted_skin_error_m':float(errors.max()),'skin_squared_error_sum':float(np.dot(errors,errors)),
                'bone_comparisons':138,'weighted_vertex_samples':35310}

    for stem,animation_path,owner_path in inputs:
        if args.clip and stem!=args.clip:continue
        animation=v.decode_animation(animation_path.read_bytes());sampler.set_animation(animation)
        owner_animation=v.decode_animation(owner_path.read_bytes());owner_sampler.set_animation(owner_animation)
        samples=[];builder_head=builder_axis=0.;builder_poses=0
        for scale in SCALES:
            for direction in ('legacy-to-authored','authored-to-legacy'):
                for phase in (0.,.5,.999):
                    legacy_base=animation['duration']*phase if direction=='legacy-to-authored' else .125
                    authored_base=.125 if direction=='legacy-to-authored' else authored['duration']*phase
                    raw=scaled(sampler.locals(legacy_base),scale)
                    carrier=scaled(owner_sampler.locals(legacy_base/animation['duration']*owner_animation['duration']),scale)
                    custom=scaled(authored_sampler.locals(authored_base),scale)
                    expected_legacy=independently_correct_legacy(sampler,owner_sampler,raw,carrier,offsets)
                    source=expected_legacy if direction=='legacy-to-authored' else custom
                    target=custom if direction=='legacy-to-authored' else raw
                    scene=LuaBlendScene(sampler,owner_sampler,manifest,profile)
                    scene.set_poses(raw if direction=='legacy-to-authored' else custom,target,carrier);scene.start()
                    if direction=='legacy-to-authored':
                        scene.event('attack_shoot_start','base/idle','base/shoot_loop')
                        scene.correct_displayed()
                        measured=measure(scene.locals_['outfit'],expected_legacy)
                        builder_head=max(builder_head,measured['max_head_error_m']);builder_axis=max(builder_axis,measured['max_axis_error_m']);builder_poses+=1
                    scene.tick(0,0)
                    source_actual=copy.deepcopy(scene.locals_['outfit'])
                    if direction=='legacy-to-authored':scene.event('idle','base/shoot_loop','base/idle')
                    else:scene.event('attack_shoot_start','base/idle','base/shoot_loop')
                    previous=0.
                    for weight in WEIGHTS:
                        elapsed=weight*.25
                        lt=min(animation['duration'],legacy_base+elapsed)
                        at=min(authored['duration'],authored_base+elapsed)
                        raw_target=scaled(sampler.locals(lt),scale)
                        carrier_target=scaled(owner_sampler.locals(lt/animation['duration']*owner_animation['duration']),scale)
                        custom_target=scaled(authored_sampler.locals(at),scale)
                        expected_legacy_target=independently_correct_legacy(sampler,owner_sampler,raw_target,carrier_target,offsets)
                        target_expected=custom_target if direction=='legacy-to-authored' else expected_legacy_target
                        target_raw=custom_target if direction=='legacy-to-authored' else raw_target
                        # Model the engine's pure endpoint on the finishing frame;
                        # ordinary legacy correction owns that frame after release.
                        visible=target_raw if weight==1 else blend_locals(source_actual,target_raw,weight,bone_indices)
                        scene.set_poses(visible,target_raw,carrier_target)
                        active=scene.tick(elapsed-previous,elapsed);previous=elapsed
                        if weight==1 and direction=='authored-to-legacy':scene.correct_displayed()
                        expected=blend_locals(source_actual,target_expected,weight,bone_indices)
                        measured=measure(scene.locals_['outfit'],expected)
                        v.require(active==(weight<1),'Bridge active interval changed')
                        if direction=='legacy-to-authored':
                            v.require(scene.writes['helper']==3,'Authored helper bones received legacy corrections')
                            custom_target_checks+=1
                        if weight==1 and direction=='legacy-to-authored':
                            v.require(scene.writes['outfit']==0 and scene.writes['helper']==3,'Full authored endpoint received legacy/blend writes')
                            full_authored_checks+=1
                        samples.append({'direction':direction,'global_scale':scale,'source_phase':phase,'weight':weight,**measured})
                    # Reproduce an in-flight half blend, then interrupt it.
                    # The engine's new raw transition pose is deliberately
                    # substituted after the event, exposing snapshot ordering.
                    interrupted=LuaBlendScene(sampler,owner_sampler,manifest,profile)
                    interrupted.set_poses(raw if direction=='legacy-to-authored' else custom,target,carrier);interrupted.start()
                    if direction=='legacy-to-authored':
                        interrupted.event('attack_shoot_start','base/idle','base/shoot_loop');interrupted.correct_displayed()
                    interrupted.tick(0,0)
                    if direction=='legacy-to-authored':interrupted.event('idle','base/shoot_loop','base/idle')
                    else:interrupted.event('attack_shoot_start','base/idle','base/shoot_loop')
                    mid_legacy_time=min(animation['duration'],legacy_base+.125)
                    mid_carrier=scaled(owner_sampler.locals(mid_legacy_time/animation['duration']*owner_animation['duration']),scale)
                    mid_raw=scaled(sampler.locals(mid_legacy_time),scale)
                    mid_custom=scaled(authored_sampler.locals(min(authored['duration'],authored_base+.125)),scale)
                    mid_target=mid_custom if direction=='legacy-to-authored' else mid_raw
                    interrupted.set_poses(blend_locals(source_actual,mid_target,.5,bone_indices),mid_target,mid_carrier)
                    interrupted.tick(.125,.125)
                    displayed=copy.deepcopy(interrupted.locals_['outfit'])
                    if direction=='legacy-to-authored':interrupted.event('attack_shoot_start','base/idle','base/shoot_loop')
                    else:interrupted.event('idle','base/shoot_loop','base/idle')
                    previous_interrupt=0.
                    for weight in WEIGHTS:
                        elapsed=.25*weight
                        lt=min(animation['duration'],mid_legacy_time+elapsed)
                        at=min(authored['duration'],authored_base+.125+elapsed)
                        next_raw=scaled(sampler.locals(lt),scale)
                        next_custom=scaled(authored_sampler.locals(at),scale)
                        next_carrier=scaled(owner_sampler.locals(lt/animation['duration']*owner_animation['duration']),scale)
                        next_corrected=independently_correct_legacy(sampler,owner_sampler,next_raw,next_carrier,offsets)
                        reverse_target=next_corrected if direction=='legacy-to-authored' else next_custom
                        reverse_raw=next_raw if direction=='legacy-to-authored' else next_custom
                        interrupted.set_poses(reverse_raw,reverse_raw,next_carrier)
                        active=interrupted.tick(elapsed-previous_interrupt,elapsed);previous_interrupt=elapsed
                        if weight==1 and direction=='legacy-to-authored':interrupted.correct_displayed()
                        expected=blend_locals(displayed,reverse_target,weight,bone_indices)
                        measured=measure(interrupted.locals_['outfit'],expected)
                        v.require(active==(weight<1),'Interrupted active interval changed')
                        if direction=='authored-to-legacy':
                            v.require(interrupted.writes['helper']==3,'Interrupted authored helper received legacy corrections')
                            custom_target_checks+=1
                        if weight==0:
                            continuity=measure(interrupted.locals_['outfit'],displayed)
                            v.require(continuity['max_weighted_skin_error_m']<.00001,
                                      'Interrupted bridge failed displayed-pose continuity')
                        interruptions.append({'clip':stem,'direction':direction,'global_scale':scale,
                            'source_phase':phase,'weight':weight,**measured})
                    # Full custom playback remains untouched after completion.
                    if direction=='legacy-to-authored':
                        scene.set_poses(custom_target,custom_target,carrier_target);scene.tick(.01,.26)
                        v.require(scene.writes['outfit']==0,'Pure authored playback received pose writes')
                        full_authored_checks+=1
        clip_report={'clip':stem,'samples':samples,'compiled_animation_sha256':v.digest(animation_path),
                     'native_carrier_animation_sha256':v.digest(owner_path),'unchanged_compiled_tracks':138,
                     'legacy_builder_pose_checks':builder_poses,'legacy_builder_max_head_error_m':builder_head,
                     'legacy_builder_max_axis_error_m':builder_axis}
        clips.append(clip_report)
        for row in samples:
            for field in ('bone_comparisons','weighted_vertex_samples','skin_squared_error_sum'):aggregate[field]+=row[field]
            for field in ('max_head_error_m','max_axis_error_m','max_local_matrix_error','max_weighted_skin_error_m'):
                aggregate[field]=max(aggregate[field],row[field])
        print(json.dumps({'clip':stem,'pose_samples':len(samples),'max_skin_error_m':max(s['max_weighted_skin_error_m'] for s in samples)}),flush=True)
    for row in interruptions:
        for field in ('bone_comparisons','weighted_vertex_samples','skin_squared_error_sum'):aggregate[field]+=row[field]
        for field in ('max_head_error_m','max_axis_error_m','max_local_matrix_error','max_weighted_skin_error_m'):
            aggregate[field]=max(aggregate[field],row[field])
    for path,sha in frozen.items():v.require(v.digest(path)==sha,'Frozen numerical input changed: '+path)
    v.require(v.verify_original_clips(probe,names)==original,'Original 138-track lane changed during numerical run')
    count=1 if args.clip else 13
    v.require(len(clips)==count and all(len(c['samples'])==126 for c in clips)
              and len(interruptions)==count*126 and full_authored_checks==count*18 and custom_target_checks==count*126,
              'Required complete transition/interrupt/custom-write coverage is missing')
    report={'schema':1,'status':'actual-lua-partial-snapshot-blend-and-skin-passed' if args.clip else
            'actual-lua-snapshot-blend-and-skin-passed','fixed_tolerance_m':.002,
        'native_Unit_pose_samples':0,'SDK_runs':0,'game_acceptance':'not performed',
        'scope':'Actual Lua compositor/builders with independent float32 API doubles and decoded native Hermite poses',
        'helper_clock_scope':'API-double clock advanced independently; sampled target poses injected for endpoint phase coverage',
        'outgoing_semantics':'Frozen displayed corrected local pose; incoming target advances',
        'weights':list(WEIGHTS),'global_scales':list(SCALES),'source_phases':[0.,.5,.999],
        'original_clip_compatibility':original,'clip_count':len(clips),
        'pose_samples':sum(len(c['samples']) for c in clips)+len(interruptions),
        'ordinary_transition_pose_samples':sum(len(c['samples']) for c in clips),
        'interrupted_transition_pose_samples':len(interruptions),
        'bone_comparisons':int(aggregate['bone_comparisons']),'weighted_vertex_samples':int(aggregate['weighted_vertex_samples']),
        'maxima':{k:x for k,x in aggregate.items() if k.startswith('max_')},
        'weighted_skin_rms_m':math.sqrt(aggregate['skin_squared_error_sum']/aggregate['weighted_vertex_samples']),
        'pure_authored_zero_write_checks':full_authored_checks,'interruptions':interruptions,
        'authored_helper_no_legacy_bone_write_checks':custom_target_checks,
        'frozen_input_sha256':frozen,'clips':clips}
    report_path.write_text(json.dumps(report,indent=2),encoding='utf8');print('REPORT_SHA256 '+v.digest(report_path))


def validate_shard(report,expected_stems):
    """Derive exact row coverage instead of accepting asserted totals."""
    v.require(report['status']=='actual-lua-partial-snapshot-blend-and-skin-passed' and
              report['fixed_tolerance_m']==.002 and report['clip_count']==1 and
              report['native_Unit_pose_samples']==0 and report['SDK_runs']==0,
              'Incomplete or incorrectly scoped blend shard')
    v.require(report['weights']==list(WEIGHTS) and report['global_scales']==list(SCALES) and
              report['source_phases']==[0.,.5,.999],'Blend shard sampling policy differs')
    v.require(len(report['clips'])==1,'Blend shard must contain one complete clip')
    clip=report['clips'][0];stem=clip['clip']
    v.require(stem in expected_stems and clip['unchanged_compiled_tracks']==138,'Unknown or altered original clip')
    v.require(clip['legacy_builder_pose_checks']==9 and
              all(math.isfinite(clip[key]) and 0<=clip[key]<=.002 for key in
                  ('legacy_builder_max_head_error_m','legacy_builder_max_axis_error_m')),
              'Complete independently checked legacy builder endpoints required')
    expected={(direction,scale,phase,weight) for direction in ('legacy-to-authored','authored-to-legacy')
              for scale in SCALES for phase in (0.,.5,.999) for weight in WEIGHTS}
    for label,rows in (('ordinary',clip['samples']),('interrupted',report['interruptions'])):
        keys=[(row['direction'],row['global_scale'],row['source_phase'],row['weight']) for row in rows]
        v.require(len(keys)==126 and set(keys)==expected,'Incomplete/duplicate '+label+' blend pose coverage')
        for row in rows:
            if label=='interrupted':v.require(row['clip']==stem,'Interrupted sample belongs to another clip')
            v.require(row['bone_comparisons']==138 and row['weighted_vertex_samples']==35310,
                      'Incomplete full-skeleton/full-skin blend row')
            for field in ('max_head_error_m','max_axis_error_m','max_local_matrix_error',
                          'max_weighted_skin_error_m','skin_squared_error_sum'):
                v.require(math.isfinite(row[field]) and row[field]>=0,'Nonfinite/negative blend measurement')
            v.require(max(row['max_head_error_m'],row['max_axis_error_m'],row['max_weighted_skin_error_m'])<=.002,
                      'Blend shard exceeds fixed two-millimetre gate')
    v.require(report['pose_samples']==252 and report['ordinary_transition_pose_samples']==126 and
              report['interrupted_transition_pose_samples']==126 and report['bone_comparisons']==252*138 and
              report['weighted_vertex_samples']==252*35310 and report['pure_authored_zero_write_checks']==18 and
              report['authored_helper_no_legacy_bone_write_checks']==126,
              'Blend shard summary coverage differs from complete rows')
    return stem


def merge(args):
    probe=v.validate_probe(v.ROOT,args.probe_root);directory=v.validate_probe(v.ROOT,args.merge)
    names=list(r.compiled_bones(v.indexed_resources(v.ROOT,probe,probe/'candidate/data',[v.UNIT+'.bones'])[0].read_bytes()))
    original=v.verify_original_clips(probe,names)
    expected={Path(clip['clip']).stem for clip in original['clips']};reports={};files={}
    for path in sorted(directory.glob('*.blend.json')):
        report=json.loads(path.read_text());stem=validate_shard(report,expected)
        v.require(report['original_clip_compatibility']==original,'Blend shard original clip proof is stale')
        v.require(stem not in reports,'Duplicate complete blend shard')
        for frozen,sha in report['frozen_input_sha256'].items():
            v.require(v.digest(frozen)==sha,'Frozen blend shard input changed: '+frozen)
        v.require(report['frozen_input_sha256'].get(str(args.animation_manifest.resolve()))==v.digest(args.animation_manifest),
                  'Blend shard used another trusted manifest')
        for prior in reports.values():
            for field in ('frozen_input_sha256','original_clip_compatibility','scope','helper_clock_scope','outgoing_semantics'):
                v.require(report[field]==prior[field],'Blend shard inputs or declared semantics differ: '+field)
        reports[stem]=report;files[str(path.resolve())]=v.digest(path)
    v.require(set(reports)==expected and len(reports)==13,'All thirteen complete numerical blend shards required')
    result=next(iter(reports.values())).copy()
    result['clips']=[reports[Path(c['clip']).stem]['clips'][0] for c in original['clips']]
    result['interruptions']=[row for c in original['clips'] for row in reports[Path(c['clip']).stem]['interruptions']]
    rows=[row for clip in result['clips'] for row in clip['samples']]+result['interruptions']
    result.update(status='actual-lua-snapshot-blend-and-skin-passed',clip_count=13,pose_samples=len(rows),
        ordinary_transition_pose_samples=1638,interrupted_transition_pose_samples=1638,
        bone_comparisons=sum(row['bone_comparisons'] for row in rows),
        weighted_vertex_samples=sum(row['weighted_vertex_samples'] for row in rows),
        pure_authored_zero_write_checks=234,authored_helper_no_legacy_bone_write_checks=1638,
        maxima={field:max(row[field] for row in rows) for field in
                ('max_head_error_m','max_axis_error_m','max_local_matrix_error','max_weighted_skin_error_m')},
        weighted_skin_rms_m=math.sqrt(sum(row['skin_squared_error_sum'] for row in rows)/(len(rows)*35310)),
        shard_reports=files)
    destination=v.validate_probe(v.ROOT,args.report.parent)/args.report.name;v.reject_redirect(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({'status':result['status'],'pose_samples':len(rows),'report_sha256':v.digest(destination)}))


if __name__=='__main__':main()
