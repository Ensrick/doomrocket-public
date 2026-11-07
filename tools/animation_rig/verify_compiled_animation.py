"""Verify an isolated animator candidate across the real VT2 SDK boundary.

The ordinary Python decoder checks the real interleaved animation, original
deform hierarchy, inverse binds and skin streams. It does not load the game.
All gates remain active under Python -O. Generated inputs/results stay below
the repository's dedicated .build probe, never in the shipping asset tree.
"""
from __future__ import annotations

import argparse
import bisect
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import shutil
import struct
import sys
import unittest

try:
    import numpy as np
except ImportError:
    np = None  # The checked scalar implementation remains available.

ROOT = Path(__file__).resolve().parents[2]
UNIT = 'units/warlock_bombardier/warlock_bombardier_3p'
CLIP = 'units/warlock_bombardier/anims/rig_diagnostic'
SDK_BINARY_SHA256='721bc354a520510ea270147c57230c87cc7e07d93f78ca1a0763d5bdb74137de'
RESERVED={'j_whip_parent','j_whip_dynamic',*(f'j_loot_sack_component{i}' for i in range(1,6))}
sys.path.insert(0, str(ROOT / 'tools/hose_lab'))
from compile_paths import validate_probe, indexed_resources, reject_redirect
sys.path.insert(0, str(ROOT / 'tools/hose_lab/compiled'))
from verifier_core import (require, check_matrix, inverse, matrix_multiply,
                           transform_point, decode_influences, weighted_point)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Cursor:
    def __init__(self, payload):
        self.data = payload
        self.at = 0

    def read(self, fmt):
        size = struct.calcsize('<' + fmt)
        require(self.at + size <= len(self.data), 'Truncated compiled animation')
        value = struct.unpack_from('<' + fmt, self.data, self.at)
        self.at += size
        return value

    def vec(self, packed=False):
        result = tuple(v * 20 / 65536 - 10 for v in self.read('3H')) if packed else self.read('3f')
        require(all(math.isfinite(v) for v in result), 'Nonfinite animation vector')
        return result

    def quat(self, packed=False):
        if not packed:
            values = self.read('4f')  # Stingray x,y,z,w.
        else:
            word, = self.read('I')
            largest = word & 3
            small = [((word >> shift) & 1023) * (1.5 / 1024) - .75 for shift in (2, 12, 22)]
            remainder = 1 - sum(v*v for v in small)
            require(remainder >= -1e-6, 'Invalid compressed quaternion')
            values = [0.] * 4
            values[largest] = math.sqrt(max(0., remainder))
            for i, value in enumerate(small):
                values[(largest + i + 1) & 3] = value
        return normalized_quaternion(values)


def normalized_quaternion(values):
    require(len(values) == 4 and all(math.isfinite(v) for v in values), 'Invalid quaternion')
    length = math.sqrt(sum(v*v for v in values))
    require(.9 < length < 1.1, 'Quaternion is not approximately normalized')
    return tuple(v / length for v in values)


def decode_animation(payload):
    """Decode packed/unpacked sync and every position, rotation and scale key."""
    c = Cursor(payload)
    header, bones, duration, size, beats = c.read('IIfII')
    require(header == 0 and 0 < bones <= 1024, 'Unsupported animation header/bone count')
    require(math.isfinite(duration) and 0 < duration <= 250, 'Invalid animation duration')
    require(size == len(payload) and beats <= 4096, 'Invalid animation size/beat count')
    for _ in range(beats):
        require(all(math.isfinite(v) for v in c.read('2f')), 'Nonfinite beat')
    sync, = c.read('H')
    require(sync in (1, 7), 'Unsupported initial pose encoding')
    tracks = [{'position': [], 'rotation': [], 'scale': []} for _ in range(bones)]
    encodings=Counter()
    track_encodings=[Counter() for _ in range(bones)]
    for bone in tracks:
        for name, value in (('position', c.vec(sync == 1)),
                            ('rotation', c.quat(sync == 1)), ('scale', c.vec(sync == 1))):
            if name == 'scale':
                require(min(value)>1e-7, 'Negative/zero initial animation scale')
            bone[name].append((0., value))
    ended = False
    while c.at < len(payload):
        tag, = c.read('H')
        kind = tag & 0xC000
        if kind:
            low, = c.read('H')
            combined = tag << 16 | low
            index = (combined >> 20) & 1023
            time = (combined & 0xFFFFF) * .001
            channel = {0x4000: 'scale', 0x8000: 'position', 0xC000: 'rotation'}[kind]
            value = c.quat(True) if channel == 'rotation' else c.vec(True)
            encodings['packed_'+channel]+=1
        elif tag in (4, 5, 6):
            index, time = c.read('Hf')
            channel = {4: 'position', 5: 'rotation', 6: 'scale'}[tag]
            value = c.quat() if channel == 'rotation' else c.vec()
            encodings['unpacked_'+channel]+=1
        elif tag == 2:
            _identifier, time = c.read('If')
            require(math.isfinite(time) and 0 <= time <= duration + .002, 'Invalid trigger time')
            continue
        elif tag == 3:
            ended = True
            break
        else:
            raise ValueError(f'Unknown interleaved animation tag {tag}')
        require(index < bones and math.isfinite(time) and 0 <= time <= duration + .002,
                'Animation key index/time out of bounds')
        track_encodings[index][('packed_' if kind else 'unpacked_')+channel]+=1
        require(time >= tracks[index][channel][-1][0], 'Animation channel time goes backwards')
        if channel == 'scale':
            require(min(value) > 1e-7, 'Negative/zero animation scale')
        tracks[index][channel].append((time, value))
    require(ended and c.at == len(payload), 'Missing animation footer or trailing bytes')
    return {'bones': bones, 'duration': duration, 'sync_encoding': sync, 'tracks': tracks,
            'key_encodings':dict(encodings), 'track_key_encodings':[dict(x) for x in track_encodings]}


def sample(keys, time, quaternion=False):
    if time <= keys[0][0]:
        return keys[0][1]
    if time >= keys[-1][0]:
        return keys[-1][1]
    index=bisect.bisect_left(keys,(time,))
    ta, a = keys[index-1]
    tb, b = keys[index]
    mix = (time-ta) / (tb-ta) if tb > ta else 1.
    if not quaternion:
        return tuple(x + (y-x)*mix for x, y in zip(a, b))
    dot = sum(x*y for x, y in zip(a, b))
    if dot < 0:
        b, dot = tuple(-v for v in b), -dot
    dot = min(1., max(-1., dot))
    if dot > .9995:
        return normalized_quaternion(tuple(x+(y-x)*mix for x, y in zip(a,b)))
    angle = math.acos(dot)
    sa, sb = math.sin((1-mix)*angle)/math.sin(angle), math.sin(mix*angle)/math.sin(angle)
    return tuple(sa*x+sb*y for x, y in zip(a,b))


def euler_quaternion(degrees):
    x, y, z = [math.radians(v)/2 for v in degrees]
    sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
    cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
    return (sx*cy*cz-cx*sy*sz, cx*sy*cz+sx*cy*sz,
            cx*cy*sz-sx*sy*cz, cx*cy*cz+sx*sy*sz)


def sample_compiled(keys,time,quaternion=False):
    """Reproduce this installed SDK's shared compiler/runtime evaluator.

    Read-only instruction analysis identified the vector Hermite primitive
    0x14077fa80 and quaternion primitive 0x14077f7c0, called by both curve fitting
    and debug-named runtime InterleavedAnimationEvaluator methods. Binary SHA:
    721bc354a520510ea270147c57230c87cc7e07d93f78ca1a0763d5bdb74137de.
    Hierarchy/composition remain decoded reconstruction; the separate Unit
    pose oracle has not captured native poses with this compiler-only SDK.
    """
    if time<=keys[0][0]: return keys[0][1]
    if time>=keys[-1][0]: return keys[-1][1]
    second=bisect.bisect_left(keys,(time,))
    if keys[second][0]==time: return keys[second][1]
    first=second-1
    indices=(max(0,first-1),first,second,min(len(keys)-1,second+1))
    times=[keys[i][0] for i in indices]
    values=[keys[i][1] for i in indices]
    if quaternion:
        for i in range(1,4):
            if sum(a*b for a,b in zip(values[i-1],values[i]))<0:
                values[i]=tuple(-v for v in values[i])
    dt=times[2]-times[1]
    require(dt>0 and times[2]>times[0] and times[3]>times[1],'Invalid Hermite key interval')
    u=(time-times[1])/dt
    h00=2*u**3-3*u**2+1;h10=u**3-2*u**2+u
    h01=-2*u**3+3*u**2;h11=u**3-u**2
    result=tuple(h00*b+h10*((c-a)*dt/(times[2]-times[0]))+h01*c+
                 h11*((d-b)*dt/(times[3]-times[1])) for a,b,c,d in zip(*values))
    if not quaternion: return result
    require(all(math.isfinite(v) for v in result),'Nonfinite Hermite quaternion')
    length=math.sqrt(sum(v*v for v in result))
    return tuple(v/length for v in result) if length else (0.,0.,0.,1.)


def transform(position, rotation, scale):
    x, y, z, w = normalized_quaternion(rotation)
    rows = ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
            (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
            (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))
    require(min(scale) > 1e-7 and all(math.isfinite(v) for v in scale), 'Invalid pose scale')
    return tuple(tuple(rows[r][c]*scale[c] for c in range(3))+(position[r],) for r in range(3))+((0.,0.,0.,1.),)


def matrix_error(a, b):
    check_matrix(a); check_matrix(b)
    return max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4))


def check_aim_reference(keys):
    require(keys and all(math.dist(value,(.001,.05,.006))<1e-6 for _,value in keys),
            'SDK did not retain the calibrated constant aim reference')


def check_inverse_binds(actual,expected):
    require(actual.keys()==expected.keys(), 'Compiled skin bone inventory changed')
    error=max(matrix_error(actual[n],expected[n]) for n in actual)
    require(error<=.0001,'Compiled inverse binds changed')
    return error


def weighted_batch(points,rows,names):
    """Prepare validated four-slot data once; evaluate float64 LBS in batches."""
    if np is None:
        return lambda transforms:[weighted_point(p,rows[i],transforms) for i,p in enumerate(points)]
    lookup={name:i for i,name in enumerate(names)}
    positions=np.asarray([tuple(p)+(1.,) for p in points],dtype=np.float64)
    ids=np.zeros((len(points),4),dtype=np.int64)
    weights=np.zeros((len(points),4),dtype=np.float64)
    require(np.isfinite(positions).all(),'Nonfinite batch skin position')
    for vertex in range(len(points)):
        require(0<len(rows[vertex])<=4,'Batch skin has invalid influence count')
        for slot,(name,weight) in enumerate(rows[vertex].items()):
            require(name in lookup and math.isfinite(weight) and 0<weight<=1,
                    'Batch skin has invalid bone/weight')
            ids[vertex,slot]=lookup[name];weights[vertex,slot]=weight
        require(abs(sum(rows[vertex].values())-1)<=.0005,'Batch skin weights do not sum to one')
    def evaluate(transforms):
        require(set(names).issubset(transforms),'Batch skin is missing a transform')
        matrices=np.asarray([transforms[n] for n in names],dtype=np.float64)
        require(matrices.shape==(len(names),4,4) and np.isfinite(matrices).all(),
                'Invalid batch skin matrices')
        # Select bone rows, multiply by vertex homogeneous positions, then add
        # four weighted slots. Do not normalize weights or homogeneous results.
        result=np.einsum('nvij,nj,nv->ni',matrices[ids],positions,weights)[:,:3]
        require(np.isfinite(result).all(),'Nonfinite batch weighted vertex')
        return result
    return evaluate


def fbx_tracks(fbx):
    """Read actual FBX scalar curves; reject non-linear/pivot semantics."""
    from test_warlock_weapon_pipeline import clean_fbx_name, model_local_matrix, property_vector
    objects = {n.properties[0]: n for section in fbx.nodes if section.name == 'Objects'
               for n in section.children if n.properties}
    models = {n.properties[0]: n for n in fbx.object_nodes('Model')}
    connections = [n.properties for n in fbx.descendants('C')]
    parents = {row[1]: row[2] for row in connections if len(row) >= 3 and row[0] == 'OO'
               and row[1] in models and row[2] in models}
    result = {}
    for ident, model in models.items():
        model_local_matrix(model)  # Fails closed on pre/post rotations or pivots.
        fields = {}
        for prop in ('Lcl Translation', 'Lcl Rotation', 'Lcl Scaling'):
            default = property_vector(model, prop, (1.,1.,1.) if prop == 'Lcl Scaling' else (0.,0.,0.))
            links = [row[1] for row in connections if len(row)==4 and row[0]=='OP'
                     and row[2]==ident and row[3]==prop]
            require(len(links) <= 1, 'Multiple FBX takes/channels are unsupported')
            axes = [[(0.,(v,))] for v in default]
            if links:
                for axis, name in enumerate(('d|X','d|Y','d|Z')):
                    curve_ids = [row[1] for row in connections if len(row)==4 and row[0]=='OP'
                                 and row[2]==links[0] and row[3]==name]
                    require(len(curve_ids)==1, 'Missing FBX scalar channel')
                    curve = objects[curve_ids[0]]
                    require(curve.name=='AnimationCurve', 'Unexpected FBX scalar object')
                    times = curve.child('KeyTime').properties[0]
                    values = curve.child('KeyValueFloat').properties[0]
                    require(len(times)==len(values)>0, 'Invalid FBX keys')
                    require(all(flag & 15 == 4 for flag in curve.child('KeyAttrFlags').properties[0]),
                            'FBX animation must be baked linear scalar keys')
                    axes[axis] = [(t/46186158000.,(v,)) for t,v in zip(times,values)]
                    require(all(math.isfinite(v) for v in values), 'Nonfinite source FBX key')
            fields[prop] = axes
        result[clean_fbx_name(model.properties[1])] = {
            'parent':clean_fbx_name(models[parents[ident]].properties[1]) if ident in parents else None,
            'fields':fields, 'id':ident}
    return result


def source_local(fields, time):
    values = {name:tuple(sample(keys,time)[0] for keys in axes) for name,axes in fields.items()}
    return transform(tuple(v*.01 for v in values['Lcl Translation']),
                     euler_quaternion(values['Lcl Rotation']), values['Lcl Scaling'])


def source_world(sources,names,time):
    """Evaluate FBX scalar TRS and its full model hierarchy, in game metres."""
    memo={}
    def visit(name):
        if name not in memo:
            model=sources[name];local=source_local(model['fields'],time)
            require(not model['parent'] or model['parent'] in sources,'Missing FBX parent model')
            memo[name]=matrix_multiply(visit(model['parent']),local) if model['parent'] else local
        return memo[name]
    # The shipping axis conversion is a 180-degree rotation about Z. Native
    # world bone bases include the retained armature scale100; normalize bases
    # separately from metre-space translations, just as the body/skin gates do.
    return {name:tuple(tuple(visit(name)[r][c]*(
            (.01 if c<3 else 1)*(-1 if r<2 else 1) if r<3 else 1)
            for c in range(4)) for r in range(4)) for name in names}


def verify_midpoint_motion(unit,names,animation,fbx,manifest):
    sources=fbx_tracks(fbx);frames=manifest['reference_samples'];fps=manifest['fps']
    for index in (0,len(frames)//2,len(frames)-1):
        evaluated=source_world(sources,names,index/fps)
        require(max(matrix_error(evaluated[n],frames[index]['bones_world'][n]) for n in names)<5e-5,
                'FBX TRS evaluator failed its authored-frame coordinate anchors')
    head=axis=0.;poses=[];errors=[]
    for index in range(len(frames)-1):
        time=(index+.5)/fps
        expected=source_world(sources,names,time);world=compiled_world(unit,names,animation,time)
        frame_head=frame_axis=0.
        for name in names:
            actual=tuple(tuple(world[name][r][c]*(.01 if r<3 and c<3 else 1)
                               for c in range(4)) for r in range(4))
            frame_head=max(frame_head,math.dist(transform_point(actual,(0,0,0)),transform_point(expected[name],(0,0,0))))
            frame_axis=max(frame_axis,max(math.dist(transform_point(actual,tuple(.1 if i==a else 0 for i in range(3))),
                transform_point(expected[name],tuple(.1 if i==a else 0 for i in range(3)))) for a in range(3)))
        head=max(head,frame_head);axis=max(axis,frame_axis)
        poses.append({'time_seconds':time,'head_error_m':frame_head,'axis_probe_error_m':frame_axis})
        if max(frame_head,frame_axis)>.002:
            errors.append(f'Midpoint {time}s: decoded SDK/source-FBX motion exceeds 2 mm, head={frame_head}, axis={frame_axis}')
    return {'status':'sdk-decoded-fidelity-failed' if errors else 'sdk-compiled-and-decoded',
            'pose_samples':len(poses),'bone_comparisons':len(poses)*len(names),
            'max_head_error_m':head,'max_axis_probe_error_m':axis,'tolerance_m':.002,
            'sampling':'every halfway time between authored frames',
            'comparison':'binary-proven SDK Hermite versus evaluated source-FBX scalar TRS and complete Model hierarchy',
            'weighted_vertex_samples':0,'native_Unit_pose_samples':0,'samples':poses,'fidelity_errors':errors}


def compiled_world(unit, names, animation, time, needed=None):
    from test_warlock_weapon_pipeline import compiled_node_index
    indices = {compiled_node_index(unit,name):i for i,name in enumerate(names)}
    memo = {}
    def visit(index):
        if index in memo: return memo[index]
        node = unit.nodes[index]
        if index in indices:
            tracks = animation['tracks'][indices[index]]
            local = transform(sample_compiled(tracks['position'],time),sample_compiled(tracks['rotation'],time,True),
                              sample_compiled(tracks['scale'],time))
            parent = visit(node.parent_index) if node.parent_type==1 else ((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1))
            world = matrix_multiply(parent,local)
        else:
            world = node.world_transform
        check_matrix(world)
        memo[index]=world
        return world
    return {name:visit(compiled_node_index(unit,name)) for name in (needed or names)}


def verify_motion(unit, names, payload, fbx, manifest, runtime=None):
    animation = decode_animation(payload)
    require(animation['bones']==len(names)==138, 'Animation references a foreign skeleton')
    require(manifest['status']=='fbx-roundtrip-passed' and manifest['bone_names']==names,
            'Unverified FBX authoring manifest')
    fps = manifest['fps']; frames = manifest['reference_samples']
    require(abs(fps-60)<1e-6 and len(frames)>=2, 'Expected a 60 fps diagnostic clip')
    require(abs(animation['duration']-(len(frames)-1)/fps)<.0001, 'SDK changed clip duration')
    sources = fbx_tracks(fbx)
    require(set(names).issubset(sources), 'FBX is missing deform bones')
    compression=manifest.get('animation_compression',{})
    for channel,key in (('position','pack_positions'),('rotation','pack_rotations'),('scale','pack_scales')):
        if compression.get(key) is False:
            require(animation['sync_encoding']==7 and not animation['key_encodings'].get('packed_'+channel),
                    'SDK silently ignored the explicit no-packing sidecar for '+channel)
    max_position = max_rotation = max_scale = 0.
    fidelity_errors = []
    comparisons = 0
    for index,name in enumerate(names):
        tracks = animation['tracks'][index]
        for time,value in tracks['position']:
            fields = sources[name]['fields']
            expected = tuple(sample(keys,time)[0]*.01 for keys in fields['Lcl Translation'])
            error = math.dist(value,expected)*100
            max_position=max(max_position,error)
            if error>.0011:
                fidelity_errors.append(f'{name}: SDK position fitting error {error} m at {time} s')
            comparisons+=1
        for time,value in tracks['rotation']:
            expected=euler_quaternion(tuple(sample(keys,time)[0] for keys in sources[name]['fields']['Lcl Rotation']))
            angle=2*math.acos(min(1.,abs(sum(a*b for a,b in zip(value,expected)))))
            max_rotation=max(max_rotation,angle)
            if angle>.012:
                fidelity_errors.append(f'{name}: SDK rotation fitting error {angle} rad at {time} s')
            comparisons+=1
        for time,value in tracks['scale']:
            expected=tuple(sample(keys,time)[0] for keys in sources[name]['fields']['Lcl Scaling'])
            error=max(abs(a-b) for a,b in zip(value,expected))
            max_scale=max(max_scale,error)
            if error>.001:
                fidelity_errors.append(f'{name}: SDK scale fitting error {error} at {time} s')
            comparisons+=1
    helper = animation['tracks'][names.index('aim_target')]['position']
    check_aim_reference(helper)
    direct_sample_checks=0;constant_sample_checks=0;hermite_sample_checks=0;source_sample_checks=0;direct_time_error=0.
    if compression.get('curve_fitting_disabled'):
        # Retained keys are checked directly. The compiler can omit redundant
        # plateau samples even with fitting disabled; check every omitted sample
        # through the independently verified native Hermite primitive instead.
        # This keeps the same micro-scale fidelity bound for moving intervals.
        for index,name in enumerate(names):
            fields=sources[name]['fields'];tracks=animation['tracks'][index]
            constant={channel:all(math.dist(value,keys[0][1])<1e-9 or
                       (channel=='rotation' and abs(abs(sum(x*y for x,y in zip(value,keys[0][1])))-1)<1e-12)
                       for _,value in keys) for channel,keys in tracks.items()}
            for frame in range(len(frames)):
                time=frame/fps
                expected={
                    'position':tuple(sample(k,time)[0]*.01 for k in fields['Lcl Translation']),
                    'rotation':euler_quaternion(tuple(sample(k,time)[0] for k in fields['Lcl Rotation'])),
                    'scale':tuple(sample(k,time)[0] for k in fields['Lcl Scaling'])}
                for channel,keys in tracks.items():
                    k=bisect.bisect_left(keys,(time,))
                    nearest=min((keys[i] for i in (k-1,k) if 0<=i<len(keys)),key=lambda pair:abs(pair[0]-time))
                    delta=abs(nearest[0]-time)
                    if delta<=2e-6:
                        value=nearest[1];direct_time_error=max(direct_time_error,delta);direct_sample_checks+=1
                    elif constant[channel]:
                        value=keys[0][1];constant_sample_checks+=1
                    else:
                        value=sample_compiled(keys,time,channel=='rotation');hermite_sample_checks+=1
                    source_sample_checks+=1
                    if channel=='rotation':
                        error=2*math.acos(min(1.,abs(sum(a*b for a,b in zip(value,expected[channel])))))
                        bound=2e-5
                    elif channel=='position': error=math.dist(value,expected[channel])*100;bound=2e-6
                    else: error=max(abs(a-b) for a,b in zip(value,expected[channel]));bound=1e-6
                    if error>bound:
                        fidelity_errors.append(f'{name}/{channel}: lossless source-frame key error {error} at {time} s')
    heads=axes=0.; per_frame=[]
    for frame,snapshot in enumerate(frames):
        world=runtime[frame]['bones_world'] if runtime else compiled_world(unit,names,animation,frame/fps)
        frame_head=frame_axis=0.
        for name in names:
            actual=[list(row) for row in world[name]]
            for row in range(3):
                for col in range(3): actual[row][col]*=.01
            expected=snapshot['bones_world'][name]
            require(matrix_error(actual,actual)<1e-12, 'Invalid world sample')
            frame_head=max(frame_head,math.dist(transform_point(actual,(0,0,0)),transform_point(expected,(0,0,0))))
            frame_axis=max(frame_axis,max(math.dist(transform_point(actual,tuple(.1 if i==a else 0. for i in range(3))),
                          transform_point(expected,tuple(.1 if i==a else 0. for i in range(3)))) for a in range(3)))
        if frame_head>.002 or frame_axis>.002:
            fidelity_errors.append(f'Frame {frame}: SDK world pose mismatch head={frame_head} axis={frame_axis}')
        heads=max(heads,frame_head); axes=max(axes,frame_axis)
        per_frame.append({'frame':snapshot['frame'],'time':frame/fps,'head_error_m':frame_head,'axis_error_m':frame_axis})
    return {'duration_seconds':animation['duration'],'bones':animation['bones'],'sync_encoding':animation['sync_encoding'],
            'compiled_key_encodings':animation['key_encodings'],
            'source_frame_channel_checks':source_sample_checks,
            'direct_source_frame_channel_checks':direct_sample_checks,
            'constant_source_frame_channel_checks':constant_sample_checks,
            'native_hermite_source_frame_channel_checks':hermite_sample_checks,
            'max_direct_source_key_time_error_seconds':direct_time_error,
            'key_comparisons':comparisons,'sampled_world_bone_comparisons':len(frames)*len(names),
            'max_position_key_error_m':max_position,'max_rotation_key_error_rad':max_rotation,
            'max_scale_key_error':max_scale,'max_world_head_error_m':heads,'max_world_axis_probe_error_m':axes,
            'aim_reference_compiled':list(helper[0][1]),'frames':per_frame,
            'interpolation_method':'actual SDK Unit.world_pose samples' if runtime else 'installed SDK runtime Hermite reconstructed from binary',
            'runtime_interpolation_equivalence':'actual SDK poses sampled' if runtime else 'Hermite primitive verified in runtime binary; Unit pose oracle pending',
            'fidelity_errors':fidelity_errors}, animation


def compiled_weights(unit,payload,names):
    from test_doomrocket_chimney_anchor import compiled_skin_prefix
    from test_warlock_weapon_pipeline import compiled_node_index
    geometries,skins=compiled_skin_prefix(payload)
    require(len(geometries)==len(skins)==len(unit.geometries)==len(unit.mesh_node_indices)==1,
            'Expected exactly one body geometry/skin/mesh')
    binds,nodes,palettes=skins[0]
    require(len(nodes)==len(binds) and len(set(nodes))==len(nodes), 'Invalid skin node inventory')
    by_index={compiled_node_index(unit,n):n for n in names}
    require(all(n in by_index for n in nodes), 'Skin has an authoring/helper bone')
    streams,channels,batches=geometries[0]
    ids=[c for c in channels if c[0]==6]; weights=[c for c in channels if c[0]==7]
    require(len(ids)==len(weights)==1 and ids[0][1]==19 and weights[0][1]==17,
            'Missing real four-influence skin index/weight channels')
    require(ids[0][3]<len(streams) and weights[0][3]<len(streams), 'Skin stream index invalid')
    ib,im=streams[ids[0][3]]; wb,wm=streams[weights[0][3]]
    count=len(unit.geometries[0].positions)
    require(im[3]==4 and wm[3]==8 and len(ib)==count*4 and len(wb)==count*8, 'Skin strides/count differ')
    selected=defaultdict(set); coverage=Counter()
    triangles=unit.geometries[0].triangles
    for batch_index,(_,start,length,palette) in enumerate(batches):
        require(start+length<=len(triangles) and palette<len(palettes), 'Invalid skin batch')
        for ti in range(start,start+length):
            coverage[ti]+=1
            for vertex in triangles[ti]: selected[vertex].add(batch_index)
    require(coverage==Counter({i:1 for i in range(len(triangles))}), 'Missing/overlapping skin triangles')
    result={}
    for vertex in range(count):
        require(len(selected[vertex])==1, 'Vertex does not identify one skin batch')
        batch=batches[next(iter(selected[vertex]))]
        result[vertex]=decode_influences(struct.unpack_from('<4B',ib,vertex*4),struct.unpack_from('<4e',wb,vertex*8),
                                       palettes[batch[3]],nodes,by_index)
    return result,{by_index[n]:b for n,b in zip(nodes,binds)}


def source_skin(fbx):
    from test_warlock_weapon_pipeline import geometry_by_vertex_count,raw_geometry_points,clean_fbx_name,geometry_model,model_local_matrix
    from test_doomrocket_chimney_anchor import fbx_positive_weights
    geometry=geometry_by_vertex_count(fbx,29123)
    models={m.properties[0]:m for m in fbx.object_nodes('Model')}
    parents={r.properties[1]:r.properties[2] for r in fbx.descendants('C') if len(r.properties)>=3 and
             r.properties[0]=='OO' and r.properties[1] in models and r.properties[2] in models}
    chain=[]; node=geometry_model(fbx,geometry); seen=set()
    while node:
        require(node.properties[0] not in seen,'Cyclic mesh hierarchy');seen.add(node.properties[0]);chain.append(node)
        node=models.get(parents.get(node.properties[0]))
    world=((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1))
    for node in reversed(chain): world=matrix_multiply(world,model_local_matrix(node))
    # Accepted -Y/Z exporter uses 180-degree object-space Z conversion. The
    # SDK applies FBX centimetre metadata to positions, retaining scale100
    # on the armature. Match the actual Blender/SDK metre-space mesh here.
    convert=((- .01,0,0,0),(0,-.01,0,0),(0,0,.01,0),(0,0,0,1))
    source_world=matrix_multiply(convert,world)
    points=[transform_point(source_world,p) for p in raw_geometry_points(geometry)]
    rows={i:dict(v) for i,v in fbx_positive_weights(fbx,geometry,range(29123)).items()}
    for row in rows.values():
        require(0<len(row)<=4 and all(math.isfinite(v) and 0<v<=1 for v in row.values()) and abs(sum(row.values())-1)<1e-6,
                'Source body has invalid skin weights')
    return geometry,points,rows


def match_skin(unit,weights,points,source_weights):
    # A spatial index avoids the quadratic all-pairs search used for tiny
    # hose fixtures. It also resolves coincident seams by actual bone weights.
    step=.002; buckets=defaultdict(list)
    for i,p in enumerate(points): buckets[tuple(math.floor(v/step) for v in p)].append(i)
    mesh_world=unit.nodes[unit.mesh_node_indices[0]].world_transform
    mapping={}; maximum=weight_error=0.; covered=set()
    for vertex,p in enumerate(unit.geometries[0].positions):
        world=transform_point(mesh_world,p); key=tuple(math.floor(v/step) for v in world)
        candidates=[]
        for offset in itertools.product((-1,0,1),repeat=3):
            for source in buckets[tuple(a+b for a,b in zip(key,offset))]:
                distance=math.dist(world,points[source])
                if distance<=step: candidates.append((distance,source))
        require(candidates,f'Compiled body vertex {vertex} has no source position match')
        compatible=[]
        for distance,source in candidates:
            expected=source_weights[source]
            if weights[vertex].keys()==expected.keys():
                error=max(abs(weights[vertex][n]-v) for n,v in expected.items())
                if error<=.0006: compatible.append((distance,error,source))
        require(compatible,f'Compiled body vertex {vertex} has different positive weights')
        distance,error,source=min(compatible)
        mapping[vertex]=source;covered.add(source)
        maximum=max(maximum,distance);weight_error=max(weight_error,error)
    require(len(covered)>20000, 'Compiled geometry lost most source body positions')
    return mapping,{'compiled_vertices':len(mapping),'source_vertices':len(points),
                   'source_positions_used':len(covered),'max_geometry_position_error_m':maximum,'max_skin_weight_error':weight_error}


def verify_body(unit,baseline,payload,baseline_payload,candidate_fbx,original_fbx,names,profile):
    from test_warlock_weapon_pipeline import compiled_node_index,raw_geometry_points,uv_sets_by_vertex,material_names
    require(not unit.actors and not baseline.actors,'Body candidate unexpectedly has physics actors')
    for name in names:
        a=unit.nodes[compiled_node_index(unit,name)]; b=baseline.nodes[compiled_node_index(baseline,name)]
        require(a.parent_type==b.parent_type,'Bone parent type changed: '+name)
        parent_a=unit.nodes[a.parent_index].name_hash if a.parent_type==1 else None
        parent_b=baseline.nodes[b.parent_index].name_hash if b.parent_type==1 else None
        require(parent_a==parent_b,'Bone hierarchy changed: '+name)
    g,points,source_weights=source_skin(candidate_fbx)
    original_g,original_points,original_weights=source_skin(original_fbx)
    require(g.child('PolygonVertexIndex').properties[0]==original_g.child('PolygonVertexIndex').properties[0],
            'Candidate changed body topology')
    source_position_error=max(math.dist(a,b) for a,b in zip(points,original_points))
    require(source_position_error<=5e-5, 'Candidate changed body geometry/object transform')
    require(material_names(candidate_fbx)==material_names(original_fbx), 'Body material names changed')
    uv_a,uv_b=uv_sets_by_vertex(g),uv_sets_by_vertex(original_g)
    require(len(uv_a)==len(uv_b) and all(len(a)==len(b) and all(math.dist(x,y)<1e-6 for x,y in zip(a,b))
            for a,b in zip(uv_a,uv_b)), 'Body UV mapping changed')
    changed={i for i,row in source_weights.items() if row.keys()!=original_weights[i].keys() or
             any(abs(row[n]-original_weights[i][n])>2e-6 for n in row if n in original_weights[i])}
    if changed:
        require(profile is not None, 'Candidate skin changed without the localized accessory profile')
        correction=profile.get('corrective_skin',profile)
        planned={change['vertex']:change for change in correction['changes']}
        require(changed==set(planned),'Candidate changed weights outside the reviewed localized mask')
        for i,change in planned.items():
            require(source_weights[i].keys()==change['after'].keys() and
                    all(abs(source_weights[i][n]-v)<2e-6 for n,v in change['after'].items()),
                    'Candidate weights differ from the localized correction plan')
    weights,binds=compiled_weights(unit,payload,names)
    _,baseline_binds=compiled_weights(baseline,baseline_payload,names)
    def triangle_positions(geometry):
        counts=Counter()
        for triangle in geometry.triangles:
            points=tuple(geometry.positions[i] for i in triangle)
            counts[min(points[i:]+points[:i] for i in range(3))]+=1
        return counts
    require(triangle_positions(unit.geometries[0])==triangle_positions(baseline.geometries[0]),
            'SDK changed body triangle geometry/winding/multiplicity')
    bind_error=check_inverse_binds(binds,baseline_binds)
    mapping,geometry_report=match_skin(unit,weights,points,source_weights)
    initial_world_delta=max(matrix_error(unit.nodes[compiled_node_index(unit,n)].world_transform,
                              baseline.nodes[compiled_node_index(baseline,n)].world_transform) for n in names)
    require(initial_world_delta<=.0001, 'Weight-only body candidate changed the compiled initial activation pose')
    return {'deform_bones':len(names),'actors':len(unit.actors),'changed_skin_vertices':len(changed),
            'geometry_source_error_m':source_position_error,'max_compiled_inverse_bind_component_error':bind_error,
            'max_compiled_initial_pose_component_error':initial_world_delta,
            'compiled_triangles':len(unit.geometries[0].triangles),
            **geometry_report}, (mapping,weights,binds,points,source_weights)


def verify_deformed_samples(unit,names,animation,manifest,skin,profile=None,runtime=None):
    """Compare real SDK-weighted vertices with authoring-world skin results.

    Uses decoded SDK bone transforms and native inverse binds, not the desired
    world-transform calibration equation. Every compiled vertex is checked at
    all diagnostic frames, including each accessory pose marker and its
    transitions. Report maximum and RMS by body region.
    """
    mapping,weights,binds,points,source_weights=skin
    frames=manifest['reference_samples'];fps=manifest['fps']
    object_world=frames[0]['object_world']
    rest={n:matrix_multiply(object_world,manifest['rest_contract'][n]['rest_matrix']) for n in names}
    inverse_rest={n:inverse(m) for n,m in rest.items()}
    trials=range(len(frames))
    regions={}
    if profile:
        correction=profile.get('corrective_skin',profile)
        regions.update({change['vertex']:change['area'] for change in correction.get('changes',[])})
    for index,weights_at_vertex in source_weights.items():
        if index not in regions:
            regions[index]='backpack' if weights_at_vertex.get('j_backpack',0)>.5 else 'body'
    results=[]; fidelity_errors=[]
    source_batch=weighted_batch(points,source_weights,names)
    native_batch=weighted_batch(unit.geometries[0].positions,weights,list(binds))
    for frame in trials:
        native=runtime[frame]['bones_world'] if runtime else compiled_world(unit,names,animation,frame/fps)
        source_transforms={n:matrix_multiply(frames[frame]['bones_world'][n],inverse_rest[n]) for n in names}
        native_transforms={n:matrix_multiply(native[n],binds[n]) for n in binds}
        expected=source_batch(source_transforms)
        actuals=native_batch(native_transforms)
        maximum=0.;worst=None;region_errors=defaultdict(list)
        for vertex,actual in enumerate(actuals):
            error=math.dist(actual,expected[mapping[vertex]])
            region_errors[regions[mapping[vertex]]].append(error)
            if error>maximum: maximum,worst=error,vertex
        if maximum>.002:
            fidelity_errors.append(f'Actual SDK weighted deformation mismatch {maximum} m at frame {frame}, vertex {worst}')
        results.append({'frame':frames[frame]['frame'],'time':frame/fps,'vertices':len(mapping),
                        'max_weighted_skin_error_m':maximum,'worst_compiled_vertex':worst,
                        'regions':{name:{'vertices':len(errors),'max_error_m':max(errors),
                              'rms_error_m':math.sqrt(sum(e*e for e in errors)/len(errors))}
                              for name,errors in region_errors.items()}})
    return {'pose_samples':results,'weighted_comparisons':len(trials)*len(mapping),
            'max_weighted_skin_error_m':max(v['max_weighted_skin_error_m'] for v in results),
            'tolerance_m':.002,'sampling':'all diagnostic frames',
            'runtime_interpolation_equivalence':'actual SDK poses sampled' if runtime else 'Hermite primitive verified in runtime binary; Unit pose oracle pending',
            'fidelity_errors':fidelity_errors,
            'comparison':'decoded SDK world bone matrices × native inverse binds × native skin weights versus authoring bone world/rest skin'}


def validate_compatibility_sidecar(clip,candidate,original):
    """Allow only the audited seven-bone override of the unchanged default."""
    original_sha=hashlib.sha256(original).hexdigest();candidate_sha=hashlib.sha256(candidate).hexdigest()
    require(original_sha==clip.get('source_animation_sidecar_sha256',original_sha),
            'Shipping compatibility sidecar hash differs from its receipt')
    calibration=clip.get('native_calibration')
    if not calibration:
        require(candidate==original,'Uncalibrated candidate changed shipping compression')
    else:
        require(clip.get('calibration_mode')=='sdk-compressed-parent-local',
                'Unknown compatibility calibration mode')
        require(calibration['sdk_executable_sha256']==SDK_BINARY_SHA256
                and calibration['shipping_body_sha256']==digest(ROOT/(UNIT+'.fbx'))
                and calibration['source_fbx_sha256']==clip['source_sha256']
                and calibration['source_sidecar_sha256']==original_sha,
                'Calibrated compatibility targets belong to another source/SDK')
        text=candidate.decode('utf8');original_text=original.decode('utf8')
        for name in RESERVED:
            line='    "'+name+'" = [ 0 0 0 false false false ]\n'
            require(text.count(line)==1,'Missing/duplicate/non-lossless reserved override: '+name)
            text=text.replace(line,'',1)
        require(text==original_text,'Candidate changed compression outside the seven reserved overrides')
    require(candidate_sha==clip.get('candidate_animation_sidecar_sha256',candidate_sha),
            'Candidate compatibility sidecar hash differs from its receipt')
    return candidate_sha,original_sha


def verify_adapted_clips(probe,unit,baseline,names,manifest):
    """Cross all thirteen surgical adapters through the actual SDK.

    The 131 unreserved compiled tracks must be identical to the separately
    compiled shipping clips. The seven reserved tracks must follow the SDK's
    actual animated hips, retaining the original bind offsets. This isolates
    correction fidelity from pre-existing shipping curve compression.
    """
    bundle=json.loads((probe/'adapted-clips.json').read_text())
    rest={n:manifest['rest_contract'][n]['rest_matrix'] for n in names}
    hip_inverse=inverse(rest['j_hips'])
    results=[];failures=[]
    for clip in bundle['clips']:
        resource='units/warlock_bombardier/anims/'+Path(clip['clip']).stem
        candidate_path=indexed_resources(ROOT,probe,probe/'candidate/data',[resource+'.animation'])[0]
        baseline_path=indexed_resources(ROOT,probe,probe/'reference/data',[resource+'.animation'])[0]
        for lane,expected in (('candidate',clip['sha256']),('reference',clip['source_sha256'])):
            require(digest(probe/f'{lane}/source/{resource}.fbx')==expected,
                    'Staged compatibility clip changed: '+resource)
            sidecar_sha=clip.get('candidate_animation_sidecar_sha256') if lane=='candidate' else clip.get('source_animation_sidecar_sha256')
            sidecar_sha=sidecar_sha or digest(ROOT/(resource+'.animation'))
            require(digest(probe/f'{lane}/source/{resource}.animation')==sidecar_sha,
                    'Staged compatibility sidecar changed: '+resource)
        a=decode_animation(candidate_path.read_bytes());b=decode_animation(baseline_path.read_bytes())
        require(a['bones']==b['bones']==len(names)==138 and abs(a['duration']-b['duration'])<1e-6,
                'Compatibility clip skeleton/duration changed: '+resource)
        reserved=set(clip['reserved_bones'])
        require(reserved==RESERVED and set(clip['unchanged_bones'])==set(names)-reserved,
                'Compatibility clip changed the reserved-bone contract')
        validate_compatibility_sidecar(clip,(probe/f'candidate/source/{resource}.animation').read_bytes(),
                                      (ROOT/(resource+'.animation')).read_bytes())
        calibration=clip.get('native_calibration')
        if calibration:
            reference_unit=indexed_resources(ROOT,probe,probe/'reference/data',[UNIT+'.unit'])[0]
            require(calibration['compiled_unit_sha256']==digest(reference_unit)
                    and calibration['compiled_animation_sha256']==digest(baseline_path),
                    'Calibrated targets were sampled from another compiled reference')
            require(a['sync_encoding']==7 and not any(
                a['track_key_encodings'][names.index(name)].get('packed_'+channel)
                for name in RESERVED for channel in ('position','rotation','scale')),
                'SDK ignored a reserved per-bone no-packing override')
        for index,name in enumerate(names):
            if name not in reserved:
                require(a['tracks'][index]==b['tracks'][index],
                        'SDK changed unreserved animation track: '+resource+'/'+name)
        check_aim_reference(a['tracks'][names.index('aim_target')]['position'])
        offsets={n:matrix_multiply(hip_inverse,rest[n]) for n in reserved}
        fps=clip['sample_fps'];count=round(a['duration']*fps)+1
        head=axis=0.;worst=None
        for sample_index in range(count*2-1):
            time=sample_index/(fps*2)
            world=compiled_world(unit,names,a,time,reserved|{'j_hips'})
            # Normalize the native armature scale100 into metre-space bases.
            normalized={n:tuple(tuple(world[n][r][c]*(.01 if r<3 and c<3 else 1)
                              for c in range(4)) for r in range(4)) for n in reserved|{'j_hips'}}
            for name in reserved:
                expected=matrix_multiply(normalized['j_hips'],offsets[name])
                actual=normalized[name]
                ehead=math.dist(transform_point(actual,(0,0,0)),transform_point(expected,(0,0,0)))
                eaxis=max(math.dist(transform_point(actual,tuple(.1 if i==k else 0 for i in range(3))),
                                   transform_point(expected,tuple(.1 if i==k else 0 for i in range(3)))) for k in range(3))
                if eaxis>axis: worst={'bone':name,'time':time,'axis_error_m':eaxis}
                head=max(head,ehead);axis=max(axis,eaxis)
        if head>.002 or axis>.002:
            failures.append(f'{resource}: SDK hip-follow correction exceeds 2 mm, head={head}, axis={axis}')
        results.append({'clip':clip['clip'],'duration_seconds':a['duration'],'sample_fps':fps,
            'pose_samples':count*2-1,'authored_pose_samples':count,'interkey_pose_samples':count-1,
            'unchanged_compiled_tracks':len(names)-len(reserved),
            'reserved_bone_comparisons':(count*2-1)*len(reserved),'max_reserved_head_error_m':head,
            'max_reserved_axis_probe_error_m':axis,'worst':worst,
            'compiled_candidate_sha256':digest(candidate_path),'compiled_reference_sha256':digest(baseline_path)})
        results[-1]['reserved_compiled_key_encodings']={n:a['track_key_encodings'][names.index(n)] for n in RESERVED}
        results[-1]['calibration_mode']=clip.get('calibration_mode','raw-source-FBX hips; insufficient unless SDK gate passes')
    return {'clips':results,'all_thirteen_compiled':len(results)==13,'tolerance_m':.002,
            'fidelity_errors':failures,'game_runtime_acceptance':'not performed'}


def export_shipping_targets(probe,destination,multiplier=1):
    """Freeze calibrated targets from the separately compiled shipping lane.

    Reserved local curves must compensate for the shipping parent's native
    compression; retaining raw source-FBX hips is insufficient for that task.
    These samples reconstruct the binary-proven evaluator, never claim actual
    SDK Unit or game playback, and bind every contributing source/compiled hash.
    """
    sys.path.insert(0,str(ROOT/'tools/tests'))
    from test_warlock_weapon_pipeline import compiled_unit_structure
    from test_doomrocket_visible_aim import compiled_bones
    destination=destination.resolve()
    require(multiplier in (1,2,4),'Target sampling refinement must be 1, 2 or 4')
    validate_probe(ROOT,destination.parent);reject_redirect(destination)
    receipt=json.loads((probe/'input_receipt.json').read_text())
    require(receipt.get('sdk_executable_sha256')==SDK_BINARY_SHA256
            and digest(receipt['sdk_executable_path'])==SDK_BINARY_SHA256,
            'Shipping targets require the independently audited SDK executable')
    require('Compile resulted in success!' in (probe/'reference/compiler.stdout.log').read_text(),
            'Shipping reference compile did not succeed')
    for path,sha in receipt['production_source_sha256'].items():
        require(digest(ROOT/path)==sha,'Shipping target input changed: '+path)
    require(digest(probe/'adapted-clips.json')==receipt['adapted_clips_manifest_sha256'],
            'Compatibility inventory changed before calibration')
    manifest=json.loads((probe/'animation_export.json').read_text())
    require(digest(probe/'animation_export.json')==receipt['animation_manifest_sha256'],
            'Bind/rest contract changed before calibration')
    bundle=json.loads((probe/'adapted-clips.json').read_text())
    require(bundle['all_thirteen_adapted'] and len(bundle['clips'])==13,
            'Calibration requires the complete thirteen-clip inventory')
    unit_path,bones_path=indexed_resources(ROOT,probe,probe/'reference/data',[UNIT+'.unit',UNIT+'.bones'])
    unit=compiled_unit_structure(unit_path.read_bytes());names=list(compiled_bones(bones_path.read_bytes()))
    require(names==manifest['bone_names'],'Calibration skeleton inventory changed')
    rest={n:manifest['rest_contract'][n]['rest_matrix'] for n in names}
    hip_inverse=inverse(rest['j_hips']);entries=[]
    for clip in bundle['clips']:
        resource='units/warlock_bombardier/anims/'+Path(clip['clip']).stem
        require(digest(probe/f'reference/source/{resource}.fbx')==clip['source_sha256']
                ==digest(ROOT/(resource+'.fbx')),'Calibration reference FBX changed: '+resource)
        sidecar_sha=digest(ROOT/(resource+'.animation'))
        require(digest(probe/f'reference/source/{resource}.animation')==sidecar_sha,
                'Calibration shipping compression sidecar changed: '+resource)
        path=indexed_resources(ROOT,probe,probe/'reference/data',[resource+'.animation'])[0]
        animation=decode_animation(path.read_bytes());base_fps=clip['sample_fps'];fps=base_fps*multiplier;reserved=set(clip['reserved_bones'])
        require(animation['bones']==len(names)==138 and len(reserved)==7,
                'Calibration bone count or reserved set changed')
        offsets={n:matrix_multiply(hip_inverse,rest[n]) for n in reserved}
        parents={manifest['rest_contract'][n]['parent'] for n in reserved};frames=[];midpoints=[]
        count=round(animation['duration']*fps)+1
        for sample_index in range(count*2-1):
            frame=sample_index*.5
            world=compiled_world(unit,names,animation,frame/fps,parents|{'j_hips'})
            normalized={n:[[world[n][r][c]*(.01 if r<3 and c<3 else 1)
                           for c in range(4)] for r in range(4)] for n in parents|{'j_hips'}}
            targets={n:matrix_multiply(normalized['j_hips'],offsets[n]) for n in reserved}
            local={n:matrix_multiply(inverse(targets.get(manifest['rest_contract'][n]['parent'],
                         normalized.get(manifest['rest_contract'][n]['parent']))),targets[n]) for n in reserved}
            snapshot={'frame':frame,'seconds':frame/fps,'decoded_parent_world':normalized,
                      'reserved_world':targets,'reserved_local':local}
            (midpoints if sample_index%2 else frames).append(snapshot)
        entries.append({'clip':clip['clip'],'sample_fps':fps,'base_sample_fps':base_fps,
            'target_sample_multiplier':multiplier,'duration':animation['duration'],
            'source_fbx_sha256':clip['source_sha256'],'compiled_animation_sha256':digest(path),
            'source_sidecar_sha256':sidecar_sha,'samples':frames,'midpoint_samples':midpoints})
    output={'schema':1,'status':'decoded-shipping-hip-targets',
        'evaluator':'binary-proven current SDK runtime Hermite; no native Unit pose capture',
        'sdk_executable_sha256':SDK_BINARY_SHA256,'compiled_unit_sha256':digest(unit_path),
        'shipping_body_sha256':receipt['shipping_fbx_sha256'],
        'shipping_bones_sha256':receipt['shipping_bones_sha256'],
        'animation_manifest_sha256':receipt['animation_manifest_sha256'],
        'target_sample_multiplier':multiplier,
        'matrix_convention':'standard 4x4 rows; metre-space world bases normalized from native scale100',
        'rest_contract':manifest['rest_contract'],'clips':entries}
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(output),encoding='utf8')
    print(json.dumps({'path':str(destination),'sha256':digest(destination),
                      'clips':len(entries),'samples':sum(len(c['samples']) for c in entries)}))


def verify_original_clips(probe,names):
    """Prove all thirteen legacy inputs and all 138 native tracks are retained.

    This establishes the unmodified animation boundary for a separate runtime
    correction audit. It does not claim the new weighted body is corrected.
    """
    receipt=json.loads((probe/'input_receipt.json').read_text())
    require(digest(probe/'original-clips.json')==receipt['original_clips_manifest_sha256'],
            'Original legacy clip receipt changed')
    manifest=json.loads((probe/'original-clips.json').read_text())
    expected={p.name for p in (ROOT/'units/warlock_bombardier/anims').glob('*.fbx')}
    require(len(manifest['clips'])==13 and {clip['clip'] for clip in manifest['clips']}==expected,
            'Original legacy clip inventory differs from the complete thirteen')
    results=[]
    for clip in manifest['clips']:
        resource='units/warlock_bombardier/anims/'+Path(clip['clip']).stem
        for suffix,key in (('.fbx','fbx_sha256'),('.animation','sidecar_sha256')):
            require(digest(ROOT/(resource+suffix))==clip[key],'Original legacy input changed: '+resource)
            for lane in ('candidate','reference'):
                require(digest(probe/f'{lane}/source/{resource}{suffix}')==clip[key],
                        'Staged original legacy input changed: '+lane+'/'+resource)
        candidate=indexed_resources(ROOT,probe,probe/'candidate/data',[resource+'.animation'])[0]
        reference=indexed_resources(ROOT,probe,probe/'reference/data',[resource+'.animation'])[0]
        a=decode_animation(candidate.read_bytes());b=decode_animation(reference.read_bytes())
        require(a['bones']==b['bones']==len(names)==138 and a['duration']==b['duration'],
                'Original legacy skeleton/duration changed: '+resource)
        require(a==b,'One of the original 138 compiled tracks changed: '+resource)
        require(candidate.read_bytes()==reference.read_bytes(),'Original compiled animation bytes changed: '+resource)
        results.append({'clip':clip['clip'],'duration_seconds':a['duration'],
                        'unchanged_compiled_tracks':138,'compiled_bytes_identical':True,
                        'compiled_candidate_sha256':digest(candidate),'compiled_reference_sha256':digest(reference),
                        'source_fbx_sha256':clip['fbx_sha256'],'source_sidecar_sha256':clip['sidecar_sha256']})
    return {'status':'all-thirteen-original-compiled-clips-identical','clips':results,
            'all_thirteen_compiled':True,'unchanged_tracks_per_clip':138,
            'runtime_correction_acceptance':'requires separate executed runtime/hierarchy/skin audit',
            'native_Unit_pose_samples':0}


def stage(args,probe):
    require(args.animation_fbx and args.body_fbx and args.manifest, 'Stage requires animation/body FBX and manifest')
    overlay=getattr(args,'integration_overlay',None)
    legacy=bool(getattr(args,'original_legacy_clips',False))
    require(not overlay or legacy,'Integration overlay requires original legacy clips')
    require(not (legacy and args.adapted_clips),'Original legacy clips cannot be combined with adapted replacements')
    manifest=json.loads(args.manifest.read_text(encoding='utf8'))
    require(manifest['status']=='fbx-roundtrip-passed' and digest(args.animation_fbx)==manifest['fbx_sha256'],
            'Animation FBX differs from its independently verified export')
    require(manifest['shipping_sha256']==digest(ROOT/f'{UNIT}.fbx'), 'Animation used another shipping skeleton')
    require(manifest['shipping_bones_sha256']==digest(ROOT/f'{UNIT}.bones'), 'Animation bone inventory changed')
    material='parent_material = "core/stingray_renderer/shader_import/standard"\nvariables = {\n    base_color = { type = "vector3" value = [ 0.3 0.5 0.6 ] }\n    roughness = { type = "scalar" value = 0.8 }\n    metallic = { type = "scalar" value = 0 }\n}\n'
    sidecar=args.animation_fbx.with_suffix('.animation')
    require(sidecar.is_file(), 'Animation sidecar is missing')
    if manifest.get('animation_sha256'):
        require(digest(sidecar)==manifest['animation_sha256'],'Animation sidecar differs from the export receipt')
    extra=None
    if args.adapted_clips:
        extra=json.loads((args.adapted_clips/'adapted-clips.json').read_text())
        require(extra['status']=='adapted-fbx-roundtrip-passed' and extra['all_thirteen_adapted']
                and len(extra['clips'])==13,'Adapted thirteen-clip bundle is incomplete')
        require(extra['shipping_body_sha256']==digest(ROOT/f'{UNIT}.fbx'),
                'Adapted clips used another body skeleton')
        expected={p.name for p in (ROOT/'units/warlock_bombardier/anims').glob('*.fbx')}
        require({clip['clip'] for clip in extra['clips']}==expected,
                'Adapted clip inventory differs from the shipping inventory')
        for clip in extra['clips']:
            name=clip['clip']; candidate=args.adapted_clips/name
            original=ROOT/'units/warlock_bombardier/anims'/name
            require(clip['status']=='adapted-fbx-roundtrip-passed' and clip['unreserved_payload_bytes_identical'],
                    'Adapted clip is not independently verified: '+name)
            require(digest(candidate)==clip['sha256'] and digest(original)==clip['source_sha256'],
                    'Adapted clip inputs changed: '+name)
            validate_compatibility_sidecar(clip,candidate.with_suffix('.animation').read_bytes(),
                                          original.with_suffix('.animation').read_bytes())
    # Invalidate a previous pass before compilation starts. The SDK is allowed
    # to reuse its cache, but a failed new invocation cannot leave a pass receipt.
    (probe/'compiled_animation_contract.json').write_text(json.dumps({
        'schema':1,'status':'staged-not-validated',
        'game_runtime_acceptance':'not performed','production_units_modified':False,
        'deployed':False,'uploaded':False},indent=2),encoding='utf8')
    for lane,body in [('candidate',args.body_fbx),('reference',ROOT/f'{UNIT}.fbx')]:
        source=probe/lane/'source'; destination=source/UNIT
        destination.parent.mkdir(parents=True,exist_ok=True)
        (source/'units/warlock_bombardier/anims').mkdir(parents=True,exist_ok=True)
        (source/'materials').mkdir(parents=True,exist_ok=True)
        shutil.copyfile(body,destination.with_suffix('.fbx'))
        for extension in ('.bones','.dcc_asset'):
            shutil.copyfile(ROOT/f'{UNIT}{extension}',destination.with_suffix(extension))
        unit=(ROOT/f'{UNIT}.unit').read_text()
        unit=re.sub(r'"materials/warlock_bombardier/[^"]+"','"materials/animation_probe"',unit)
        destination.with_suffix('.unit').write_text(unit,encoding='utf8',newline='\n')
        controller=(ROOT/f'{UNIT}.state_machine').read_text()
        if not extra and not legacy:
            controller=re.sub(r'"units/warlock_bombardier/anims/[^"]+"','"'+CLIP+'"',controller)
        destination.with_suffix('.state_machine').write_text(controller,encoding='utf8',newline='\n')
        (source/'materials/animation_probe.material').write_text(material,encoding='utf8',newline='\n')
        shutil.copyfile(args.animation_fbx,source/f'{CLIP}.fbx')
        shutil.copyfile(sidecar,source/f'{CLIP}.animation')
        if extra:
            for clip in extra['clips']:
                for suffix in ('.fbx','.animation'):
                    origin=(args.adapted_clips if lane=='candidate' else ROOT/'units/warlock_bombardier/anims')/clip['clip']
                    target=source/'units/warlock_bombardier/anims'/clip['clip']
                    shutil.copyfile(origin.with_suffix(suffix),target.with_suffix(suffix))
        if legacy:
            for origin in sorted((ROOT/'units/warlock_bombardier/anims').glob('*.fbx')):
                for suffix in ('.fbx','.animation'):
                    target=source/'units/warlock_bombardier/anims'/origin.name
                    shutil.copyfile(origin.with_suffix(suffix),target.with_suffix(suffix))
    overlay_receipt=None
    if overlay:
        overlay=validate_probe(ROOT,overlay)
        overlay_receipt=json.loads((overlay/'integration_receipt.json').read_text())
        require(overlay_receipt['status']=='isolated-integration-staged'
                and overlay_receipt['legacy_sources_unchanged'] is True,'Integration overlay is not validated staging')
        for relative,item in overlay_receipt['payload_files'].items():
            path=overlay/relative;reject_redirect(path)
            require(path.resolve().is_relative_to(overlay.resolve()) and digest(path)==item['sha256'],
                    'Integration payload changed: '+relative)
        for source,sha in overlay_receipt['source_inputs_sha256'].items():
            require(digest(source)==sha,'Integration source input changed: '+source)
        source=probe/'candidate/source'
        require(digest(overlay/f'{UNIT}.fbx')==digest(args.body_fbx),'Integration overlay body differs')
        for relative in overlay_receipt['payload_files']:
            if not relative.startswith('units/') or relative==UNIT+'.unit':continue
            origin=overlay/relative;target=source/relative;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(origin,target)
        unit=(overlay/f'{UNIT}.unit').read_text()
        unit=re.sub(r'"materials/warlock_bombardier/[^\"]+"','"materials/animation_probe"',unit)
        (source/f'{UNIT}.unit').write_text(unit,encoding='utf8',newline='\n')
        for name in ('integration_receipt.json','integration_manifest.json'):
            shutil.copyfile(overlay/name,probe/name)
    shutil.copyfile(args.manifest,probe/'animation_export.json')
    if args.skin_profile: shutil.copyfile(args.skin_profile,probe/'skin_profile.json')
    if extra: shutil.copyfile(args.adapted_clips/'adapted-clips.json',probe/'adapted-clips.json')
    legacy_manifest=None
    if legacy:
        clips=[]
        for path in sorted((ROOT/'units/warlock_bombardier/anims').glob('*.fbx')):
            require(path.with_suffix('.animation').is_file(),'Original legacy clip sidecar missing')
            clips.append({'clip':path.name,'fbx_sha256':digest(path),
                          'sidecar_sha256':digest(path.with_suffix('.animation'))})
        require(len(clips)==13,'Expected the complete thirteen original legacy clips')
        legacy_manifest={'schema':1,'status':'original-clips-staged-not-validated','clips':clips}
        (probe/'original-clips.json').write_text(json.dumps(legacy_manifest,indent=2),encoding='utf8')
    production={f'{UNIT}{suffix}':digest(ROOT/f'{UNIT}{suffix}')
                for suffix in ('.fbx','.bones','.unit','.dcc_asset','.state_machine')}
    if extra:
        production.update({f'units/warlock_bombardier/anims/{Path(clip["clip"]).stem}{suffix}':
             digest(ROOT/f'units/warlock_bombardier/anims/{Path(clip["clip"]).stem}{suffix}')
             for clip in extra['clips'] for suffix in ('.fbx','.animation')})
    if legacy:
        production.update({f'units/warlock_bombardier/anims/{Path(clip["clip"]).stem}{suffix}':
             digest(ROOT/f'units/warlock_bombardier/anims/{Path(clip["clip"]).stem}{suffix}')
             for clip in legacy_manifest['clips'] for suffix in ('.fbx','.animation')})
    (probe/'input_receipt.json').write_text(json.dumps({'schema':1,'animation_fbx_sha256':digest(args.animation_fbx),
        'animation_sidecar_sha256':digest(sidecar),
        'body_fbx_sha256':digest(args.body_fbx),'shipping_fbx_sha256':digest(ROOT/f'{UNIT}.fbx'),
        'shipping_bones_sha256':digest(ROOT/f'{UNIT}.bones'),'animation_manifest_sha256':digest(args.manifest),
        'skin_profile_sha256':digest(args.skin_profile) if args.skin_profile else None,
        'production_source_sha256':production,
        'sdk_executable_path':str(args.sdk_executable.resolve()) if args.sdk_executable else None,
        'sdk_executable_sha256':digest(args.sdk_executable) if args.sdk_executable else None,
        'adapted_clips_manifest_sha256':digest(args.adapted_clips/'adapted-clips.json') if extra else None,
        'original_clips_manifest_sha256':digest(probe/'original-clips.json') if legacy else None,
        'integration_receipt_sha256':digest(probe/'integration_receipt.json') if overlay else None,
        'integration_manifest_sha256':digest(probe/'integration_manifest.json') if overlay else None,
        'integration_staged_inputs':{str(p.relative_to(probe)):digest(p)
             for p in (probe/'candidate/source/units').rglob('*') if p.is_file()} if overlay else None,
        'production_units_modified':False},indent=2),encoding='utf8')


def runtime_samples(path,receipt,manifest,names,unit_sha,animation_sha):
    """Accept only a complete native oracle bound to these exact assets."""
    native=json.loads(path.read_text(encoding='utf8'))
    provenance=native.get('provenance',native)
    for key in ('body_fbx_sha256','animation_fbx_sha256','animation_sidecar_sha256'):
        require(provenance.get(key)==receipt[key],'Native pose receipt is stale or missing '+key)
    require(provenance.get('author_manifest_sha256')==receipt['animation_manifest_sha256'],
            'Native poses were sampled against another authoring receipt')
    require(provenance.get('compiled_unit_sha256')==unit_sha and
            provenance.get('compiled_animation_sha256')==animation_sha,
            'Native oracle loaded other compiled body/animation bytes')
    samples=native['samples']
    require(len(samples)==len(manifest['reference_samples']),'Native oracle did not sample all authored frames')
    for index,snapshot in enumerate(samples):
        require(snapshot['sample_index']==index and snapshot['frame']==manifest['reference_samples'][index]['frame']
                and abs(snapshot['time_seconds']-index/manifest['fps'])<1e-6,
                'Native oracle changed sample order/frame/time')
        for kind in ('bones_world','bones_local'):
            require(set(snapshot[kind])==set(names),'Native oracle has another skeleton or incomplete '+kind)
            for matrix in snapshot[kind].values(): check_matrix(matrix)
    return native,samples


def audit_midpoints_only(probe):
    """Extend an unchanged completed diagnostic receipt without redoing skin."""
    sys.path.insert(0,str(ROOT/'tools/tests'))
    from test_warlock_weapon_pipeline import compiled_unit_structure,BinaryFbx
    from test_doomrocket_visible_aim import compiled_bones
    destination=probe/'compiled_animation_contract.json';reject_redirect(destination)
    report=json.loads(destination.read_text());receipt=json.loads((probe/'input_receipt.json').read_text())
    require(report.get('diagnostic_status')=='sdk-compiled-and-decoded'
            and report['input_receipt']==receipt,'A completed unchanged diagnostic receipt is required')
    require(receipt['sdk_executable_sha256']==SDK_BINARY_SHA256
            and digest(receipt['sdk_executable_path'])==SDK_BINARY_SHA256,'SDK evaluator binary changed')
    for path,sha in receipt['production_source_sha256'].items():
        require(digest(ROOT/path)==sha,'Production input changed before midpoint extension: '+path)
    for lane in ('candidate','reference'):
        require('Compile resulted in success!' in (probe/lane/'compiler.stdout.log').read_text(),
                'Prior SDK success marker is missing')
        require(digest(probe/f'{lane}/source/{CLIP}.fbx')==receipt['animation_fbx_sha256']
                and digest(probe/f'{lane}/source/{CLIP}.animation')==receipt['animation_sidecar_sha256'],
                'Diagnostic FBX/sidecar changed before midpoint extension')
    require(digest(probe/'animation_export.json')==receipt['animation_manifest_sha256'],
            'Authored samples changed before midpoint extension')
    if receipt.get('skin_profile_sha256'):
        require(digest(probe/'skin_profile.json')==receipt['skin_profile_sha256'],'Skin profile changed')
    paths=indexed_resources(ROOT,probe,probe/'candidate/data',[UNIT+'.unit',UNIT+'.bones',CLIP+'.animation'])
    require(digest(paths[0])==report['compiled_unit_sha256']
            and digest(paths[2])==report['compiled_animation_sha256'],
            'Compiled diagnostic assets changed before midpoint extension')
    names=list(compiled_bones(paths[1].read_bytes()));manifest=json.loads((probe/'animation_export.json').read_text())
    require(names==manifest['bone_names'],'Diagnostic skeleton changed')
    midpoint=verify_midpoint_motion(compiled_unit_structure(paths[0].read_bytes()),names,
        decode_animation(paths[2].read_bytes()),BinaryFbx(probe/f'candidate/source/{CLIP}.fbx'),manifest)
    report['midpoint_motion']=midpoint
    if midpoint['fidelity_errors']:
        report['diagnostic_status']=report['status']='sdk-decoded-fidelity-failed'
    destination.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({key:value for key,value in midpoint.items() if key!='samples'},indent=2))
    require(not midpoint['fidelity_errors'],'Midpoint motion failed; see '+str(destination))


def audit(probe,runtime_path=None,midpoint_motion=False):
    sys.path.insert(0,str(ROOT/'tools/tests'))
    from test_warlock_weapon_pipeline import compiled_unit_structure,BinaryFbx,compiled_node_index
    from test_doomrocket_visible_aim import compiled_bones,compiled_controller,verify_aim
    receipt=json.loads((probe/'input_receipt.json').read_text())
    if not runtime_path:
        require(receipt.get('sdk_executable_sha256')==SDK_BINARY_SHA256,
                'Decoded Hermite playback requires the audited SDK executable or a bound native Unit pose oracle')
    if receipt.get('sdk_executable_path'):
        require(digest(receipt['sdk_executable_path'])==receipt['sdk_executable_sha256'],
                'SDK executable changed during the probe')
    require(digest(ROOT/f'{UNIT}.fbx')==receipt['shipping_fbx_sha256'],
            'Shipping body changed during probe')
    for path,sha in receipt.get('production_source_sha256',{}).items():
        require(digest(ROOT/path)==sha,'Production source changed during probe: '+path)
    for lane in ('candidate','reference'):
        require('Compile resulted in success!' in (probe/lane/'compiler.stdout.log').read_text(),
                lane+' SDK success marker is missing')
        require(digest(probe/f'{lane}/source/{CLIP}.fbx')==receipt['animation_fbx_sha256'],
                lane+' staged animation changed during compilation')
        require(digest(probe/f'{lane}/source/{CLIP}.animation')==receipt['animation_sidecar_sha256'],
                lane+' staged compression sidecar changed during compilation')
    require(digest(probe/f'candidate/source/{UNIT}.fbx')==receipt['body_fbx_sha256'],
            'Staged candidate body changed during compilation')
    require(digest(probe/'animation_export.json')==receipt['animation_manifest_sha256'],
            'Staged authoring reference changed during compilation')
    if receipt.get('skin_profile_sha256'):
        require(digest(probe/'skin_profile.json')==receipt['skin_profile_sha256'],
                'Staged localized weight profile changed during compilation')
    if receipt.get('adapted_clips_manifest_sha256'):
        require(digest(probe/'adapted-clips.json')==receipt['adapted_clips_manifest_sha256'],
                'Staged compatibility clip receipt changed during compilation')
    if receipt.get('original_clips_manifest_sha256'):
        require(digest(probe/'original-clips.json')==receipt['original_clips_manifest_sha256'],
                'Staged original legacy clip receipt changed during compilation')
    resources=[f'{UNIT}.unit',f'{UNIT}.bones',f'{UNIT}.state_machine',f'{CLIP}.animation']
    paths=indexed_resources(ROOT,probe,probe/'candidate/data',resources)
    reference=indexed_resources(ROOT,probe,probe/'reference/data',[f'{UNIT}.unit'])[0]
    unit_payload,bone_payload,sm_payload,anim_payload=[path.read_bytes() for path in paths]
    baseline_payload=reference.read_bytes()
    unit=compiled_unit_structure(unit_payload);baseline=compiled_unit_structure(baseline_payload)
    names=compiled_bones(bone_payload)
    require(names==tuple(re.findall(r'"([^"\n]+)"',(ROOT/f'{UNIT}.bones').read_text())), 'Compiled bone names/order changed')
    verify_aim(compiled_controller(sm_payload),names)
    names=list(names)
    manifest=json.loads((probe/'animation_export.json').read_text())
    profile=json.loads((probe/'skin_profile.json').read_text()) if receipt.get('skin_profile_sha256') else None
    fbx=BinaryFbx(probe/f'candidate/source/{CLIP}.fbx')
    require(digest(fbx.path)==manifest['fbx_sha256'],'Staged animation FBX differs from manifest')
    native=None;runtime=None
    if runtime_path:
        native,runtime=runtime_samples(runtime_path,receipt,manifest,names,digest(paths[0]),digest(paths[3]))
    motion,animation=verify_motion(unit,names,anim_payload,fbx,manifest,runtime)
    midpoints=verify_midpoint_motion(unit,names,animation,fbx,manifest) if midpoint_motion else None
    body,skin=verify_body(unit,baseline,unit_payload,baseline_payload,BinaryFbx(probe/f'candidate/source/{UNIT}.fbx'),
                          BinaryFbx(probe/f'reference/source/{UNIT}.fbx'),names,profile)
    deformation=verify_deformed_samples(unit,names,animation,manifest,skin,profile,runtime)
    compatibility=verify_adapted_clips(probe,unit,baseline,names,manifest) if receipt.get('adapted_clips_manifest_sha256') else None
    original=verify_original_clips(probe,names) if receipt.get('original_clips_manifest_sha256') else None
    integration=None
    if receipt.get('integration_receipt_sha256'):
        require(digest(probe/'integration_receipt.json')==receipt['integration_receipt_sha256']
                and digest(probe/'integration_manifest.json')==receipt['integration_manifest_sha256'],
                'Integration receipt/manifest changed during compile')
        for relative,sha in receipt['integration_staged_inputs'].items():
            require(digest(probe/relative)==sha,'Integration staged source changed: '+relative)
        from compiled_integration import verify as verify_integration
        registration=json.loads((probe/'integration_receipt.json').read_text())
        baseline_sm=indexed_resources(ROOT,probe,probe/'reference/data',[UNIT+'.state_machine'])[0]
        runtime_manifest=json.loads((probe/'integration_manifest.json').read_text())
        integration_profile=runtime_manifest['profiles'][registration['profile_id']]
        sampler_payload=None
        if integration_profile.get('cross_owner_transition_policy')=='snapshot-blend-v1':
            sampler_path=indexed_resources(ROOT,probe,probe/'candidate/data',
                [integration_profile['sampler_state_machine']+'.state_machine'])[0]
            sampler_payload=sampler_path.read_bytes()
        integration=verify_integration(unit_payload,sm_payload,runtime_manifest,
            registration['profile_id'],baseline_sm.read_bytes(),sampler_payload)
        if sampler_payload is not None:
            integration['presentation_sampler']['compiled_sha256']=digest(sampler_path)
        authored=[]
        exports=runtime_manifest['profiles'][registration['profile_id']]['validation']['authored_exports']
        for name,export in exports.items():
            fbx_path=probe/'candidate/source'/(export['resource']+'.fbx')
            sidecar_path=fbx_path.with_suffix('.animation')
            require(digest(fbx_path)==export['fbx_sha256'] and digest(sidecar_path)==export['sidecar_sha256'],
                    'Registered authored clip changed: '+name)
            compiled=indexed_resources(ROOT,probe,probe/'candidate/data',[export['resource']+'.animation'])[0]
            decoded=decode_animation(compiled.read_bytes())
            require(decoded['bones']==138,'Registered authored clip has another skeleton')
            prior=json.loads((Path(registration['output'])/f'integration_evidence/{name}.sdk.json').read_text())
            require(digest(compiled)==prior['compiled_animation_sha256'],
                    'Registered authored compilation differs from its full diagnostic gate: '+name)
            authored.append({'name':name,'resource':export['resource'],'bones':138,
                'compiled_animation_sha256':digest(compiled),'full_diagnostic_compilation_identical':True})
        integration['authored_clips']=authored
    diagnostic_errors=motion['fidelity_errors']+deformation['fidelity_errors']+(midpoints['fidelity_errors'] if midpoints else [])
    fidelity_errors=diagnostic_errors+(compatibility['fidelity_errors'] if compatibility else [])
    report={'schema':1,'status':'sdk-decoded-fidelity-failed' if fidelity_errors else 'sdk-compiled-and-decoded',
            'diagnostic_status':'sdk-decoded-fidelity-failed' if diagnostic_errors else 'sdk-compiled-and-decoded',
            'adapted_clip_status':('sdk-decoded-fidelity-failed' if compatibility['fidelity_errors']
                                  else 'sdk-compiled-and-decoded') if compatibility else 'not requested',
            'purpose':'isolated animator asset validation',
            'body':body,'animation':motion,'deformation':deformation,'midpoint_motion':midpoints,
            'adapted_clip_compatibility':compatibility,
            'original_clip_compatibility':original,
            'compiled_integration':integration,
            'input_receipt':receipt,
            'native_pose_oracle':{'path':str(runtime_path),'sha256':digest(runtime_path),
                'provenance':native.get('provenance',{})} if native else 'not sampled; runtime Hermite reconstructed from binary',
            'own_state_machine_aim':'verified on the exact 138-bone skeleton',
            'compiled_unit_sha256':digest(paths[0]),'compiled_animation_sha256':digest(paths[3]),
            'game_runtime_acceptance':'not performed; compilation/decoded transforms do not establish rendered in-game acceptance',
            'production_units_modified':False,'deployed':False,'uploaded':False}
    destination=probe/'compiled_animation_contract.json';reject_redirect(destination)
    destination.write_text(json.dumps(report,indent=2),encoding='utf8')
    regions=defaultdict(list)
    for pose in deformation['pose_samples']:
        for name,value in pose['regions'].items(): regions[name].append(value)
    summary={name:{'maximum_error_m':max(v['max_error_m'] for v in values),
              'rms_error_m':math.sqrt(sum(v['vertices']*v['rms_error_m']**2 for v in values)/sum(v['vertices'] for v in values)),
              'vertex_samples':sum(v['vertices'] for v in values)} for name,values in regions.items()}
    print(json.dumps({'status':report['status'],'body':body,
        'animation':{k:v for k,v in motion.items() if k not in ('frames','fidelity_errors')},
        'deformation':{k:v for k,v in deformation.items() if k not in ('pose_samples','fidelity_errors')},
        'regions':summary,'fidelity_error_count':len(fidelity_errors),'first_fidelity_errors':fidelity_errors[:8]},indent=2))
    require(not fidelity_errors,f'{len(fidelity_errors)} SDK fidelity checks failed; see {destination}')
    return report


class DecoderMutations(unittest.TestCase):
    def sidecar_fixture(self):
        source=('bones = "'+UNIT+'"\ntolerance = {\n    "" = [ 0.00001 0.01 0 false ]\n}\n').encode()
        overrides=''.join('    "'+name+'" = [ 0 0 0 false false false ]\n' for name in sorted(RESERVED))
        candidate=source.decode().replace('}\n',overrides+'}\n').encode()
        clip={'source_sha256':'source-fbx','calibration_mode':'sdk-compressed-parent-local',
              'native_calibration':{'sdk_executable_sha256':SDK_BINARY_SHA256,
                'shipping_body_sha256':digest(ROOT/(UNIT+'.fbx')),'source_fbx_sha256':'source-fbx',
                'source_sidecar_sha256':hashlib.sha256(source).hexdigest()},
              'source_animation_sidecar_sha256':hashlib.sha256(source).hexdigest(),
              'candidate_animation_sidecar_sha256':hashlib.sha256(candidate).hexdigest()}
        return clip,candidate,source
    def test_reserved_sidecar_policy_accepts_only_seven_overrides(self):
        clip,candidate,source=self.sidecar_fixture()
        validate_compatibility_sidecar(clip,candidate,source)
    def test_reserved_sidecar_default_change_rejected(self):
        clip,candidate,source=self.sidecar_fixture()
        with self.assertRaises(ValueError):
            validate_compatibility_sidecar(clip,candidate.replace(b'0.00001',b'0.000001'),source)
    def test_reserved_sidecar_packing_change_rejected(self):
        clip,candidate,source=self.sidecar_fixture()
        with self.assertRaises(ValueError):
            validate_compatibility_sidecar(clip,candidate.replace(b'false false false',b'false true false',1),source)
    def test_reserved_sidecar_hash_change_rejected(self):
        clip,candidate,source=self.sidecar_fixture();clip['candidate_animation_sidecar_sha256']='wrong'
        with self.assertRaises(ValueError): validate_compatibility_sidecar(clip,candidate,source)
    def fixture(self):
        sync=struct.pack('<H3f4f3f',7,0,0,0,0,0,0,1,1,1,1)
        data=sync+struct.pack('<H',3)
        return struct.pack('<IIfII',0,1,1.,20+len(data),0)+data
    def test_valid_complete_stream(self): self.assertEqual(decode_animation(self.fixture())['bones'],1)
    def packed_fixture(self):
        # Independent encoding of the SDK's largest-component quaternion:
        # largest index=w, x=y=z=0 (ten-bit midpoint), w reconstructed as 1.
        quaternion=3 | (512<<2) | (512<<12) | (512<<22)
        zero=struct.pack('<3H',32768,32768,32768)
        one=struct.pack('<3H',36045,36045,36045)
        sync=struct.pack('<H',1)+zero+struct.pack('<I',quaternion)+one
        word=0xC0000000 | 1000  # bone zero, rotation at 1.000 seconds.
        key=struct.pack('<HHI',word>>16,word&65535,quaternion)
        data=sync+key+struct.pack('<H',3)
        return struct.pack('<IIfII',0,1,1.,20+len(data),0)+data
    def test_valid_packed_stream(self):
        track=decode_animation(self.packed_fixture())['tracks'][0]
        self.assertEqual(track['position'][0],(0.,(0.,0.,0.)))
        self.assertEqual(track['rotation'][-1],(1.,(0.,0.,0.,1.)))
        self.assertAlmostEqual(track['scale'][0][1][0],1.,delta=.0001)
    def test_invalid_packed_quaternion_rejected(self):
        data=bytearray(self.packed_fixture())
        # Three maximum components cannot describe a unit quaternion.
        struct.pack_into('<I',data,28,3 | (1023<<2) | (1023<<12) | (1023<<22))
        with self.assertRaises(ValueError): decode_animation(data)
    def test_truncated_stream(self):
        with self.assertRaises(ValueError): decode_animation(self.fixture()[:-1])
    def test_bad_size(self):
        data=bytearray(self.fixture());struct.pack_into('<I',data,12,len(data)+1)
        with self.assertRaises(ValueError): decode_animation(data)
    def test_nonfinite_position(self):
        data=bytearray(self.fixture());struct.pack_into('<f',data,22,math.nan)
        with self.assertRaises(ValueError): decode_animation(data)
    def test_invalid_quaternion(self):
        data=bytearray(self.fixture());struct.pack_into('<4f',data,34,0,0,0,0)
        with self.assertRaises(ValueError): decode_animation(data)
    def test_footer_rejected(self):
        data=bytearray(self.fixture());struct.pack_into('<H',data,len(data)-2,88)
        with self.assertRaises(ValueError): decode_animation(data)
    def test_scale_zero_rejected(self):
        with self.assertRaises(ValueError): transform((0,0,0),(0,0,0,1),(0,1,1))
    def test_initial_scale_zero_rejected(self):
        data=bytearray(self.fixture());struct.pack_into('<f',data,50,0)
        with self.assertRaises(ValueError): decode_animation(data)
    def test_unused_weight_nan_rejected(self):
        with self.assertRaises(ValueError): decode_influences((0,0,0,0),(1,0,math.nan,0),(0,),(0,),{0:'root'})
    def test_wrong_skin_palette_rejected(self):
        with self.assertRaises(ValueError): decode_influences((0,1,0,0),(1,0,0,0),(0,),(0,),{0:'root'})
    def test_singular_inverse_rejected(self):
        with self.assertRaises(ValueError): inverse(((0,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)))
    def test_centimetre_aim_reference_rejected(self):
        with self.assertRaises(ValueError): check_aim_reference([(0.,(.1,5.,.6))])
    def test_old_aim_reference_rejected(self):
        with self.assertRaises(ValueError): check_aim_reference([(0.,(0.,.03,.0125))])
    def test_nonconstant_aim_reference_rejected(self):
        with self.assertRaises(ValueError): check_aim_reference([(0.,(.001,.05,.006)),(1.,(.001,.1,.006))])
    def test_inverse_bind_scale_drift_rejected(self):
        identity=((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1))
        bad=((100,0,0,0),(0,100,0,0),(0,0,100,0),(0,0,0,1))
        with self.assertRaises(ValueError): check_inverse_binds({'bone':bad},{'bone':identity})
    def test_inverse_bind_missing_bone_rejected(self):
        identity=((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1))
        with self.assertRaises(ValueError): check_inverse_binds({}, {'bone':identity})
    def test_missing_positive_skin_bone_rejected(self):
        with self.assertRaises(ValueError): decode_influences((0,0,0,0),(1,0,0,0),(0,),(0,),{})
    def test_batch_weighted_transform_matches_scalar(self):
        points=[(1.,2.,3.),(-2.,.1,4.)]
        rows={0:{'a':.25,'b':.75},1:{'b':1.}}
        transforms={'a':((2,0,.1,4),(0,1,0,2),(0,.2,1,3),(0,0,0,1)),
                    'b':((1,0,0,-2),(0,3,0,1),(0,0,.5,-1),(0,0,0,1))}
        actual=weighted_batch(points,rows,['a','b'])(transforms)
        for i,p in enumerate(points):
            self.assertLess(math.dist(actual[i],weighted_point(p,rows[i],transforms)),1e-12)
        self.assertLess(math.dist(actual[0],(.825,6.25,1.975)),1e-12)
    def test_batch_missing_bone_rejected(self):
        with self.assertRaises(ValueError): weighted_batch([(0,0,0)],{0:{'missing':1.}},['a'])({})
    def test_hermite_implicit_derivative(self):
        keys=[(0.,(0.,)),(1.,(1.,)),(2.,(0.,)),(3.,(0.,))]
        self.assertAlmostEqual(sample_compiled(keys,1.5)[0],.5625)
        self.assertEqual(sample_compiled(keys,1.),(1.,))
    def test_hermite_quaternion_sign_alignment(self):
        keys=[(0.,(0,0,0,1)),(1.,(0,0,0,-1)),(2.,(0,0,0,1)),(3.,(0,0,0,-1))]
        self.assertEqual(sample_compiled(keys,1.5,True),(0.,0.,0.,1.))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-root',type=Path,default=ROOT/'.build/animation_sdk_probe')
    parser.add_argument('--stage',action='store_true')
    parser.add_argument('--animation-fbx',type=Path)
    parser.add_argument('--body-fbx',type=Path)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--skin-profile',type=Path)
    parser.add_argument('--adapted-clips',type=Path)
    parser.add_argument('--original-legacy-clips',action='store_true')
    parser.add_argument('--integration-overlay',type=Path)
    parser.add_argument('--runtime-poses',type=Path)
    parser.add_argument('--midpoint-motion',action='store_true')
    parser.add_argument('--midpoint-motion-only',action='store_true',
                        help='Extend an unchanged completed receipt; skip repeat weighted skin checks')
    parser.add_argument('--export-shipping-targets',type=Path)
    parser.add_argument('--target-sample-multiplier',type=int,default=1,choices=(1,2,4))
    parser.add_argument('--sdk-executable',type=Path)
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:
        result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(DecoderMutations))
        return 0 if result.wasSuccessful() else 1
    probe=validate_probe(ROOT,args.probe_root)
    if args.midpoint_motion_only:
        require(not args.stage and not args.runtime_poses,'Midpoint-only audit cannot stage or replace native samples')
        audit_midpoints_only(probe)
    elif args.export_shipping_targets:
        export_shipping_targets(probe,args.export_shipping_targets,args.target_sample_multiplier)
    elif args.stage:
        probe.mkdir(parents=True,exist_ok=True);stage(args,probe)
    else: audit(probe,args.runtime_poses,args.midpoint_motion)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
