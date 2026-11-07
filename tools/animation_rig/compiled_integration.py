"""Bounded decoding of actual compiled Unit metadata and ASM state bindings."""
import struct
import sys
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/tests'))
import test_warlock_weapon_pipeline as pipeline
import test_doomrocket_visible_aim as aim


def require(ok,message):
    if not ok:raise ValueError(message)


def dynamic_strings(payload):
    c=pipeline.PackedCursor(payload)
    head,kind=c.u32(),c.u32()
    if head==0xffffffff:
        require(kind==0 and c.offset==len(payload),'Invalid empty DynamicData')
        return {}
    require(head==8 and kind==0,'Unsupported DynamicData root dictionary')
    result={}
    while c.offset<len(payload):
        key,next_,kind,size=c.u32(),c.u32(),c.u32(),c.u32()
        require(key not in result and kind==3 and size<=65536 and size%4==0,'Invalid DynamicData string entry')
        raw=c.take(size);text=raw.rstrip(b'\0')
        require(b'\0' not in text,'Embedded null in DynamicData string')
        result[key]=text.decode('utf8')
        if next_==0xffffffff:
            require(c.offset==len(payload),'Trailing DynamicData bytes');break
        require(next_==c.offset,'Invalid DynamicData next offset')
    require(result,'Empty nonempty DynamicData')
    return result


def unit_metadata(payload):
    # Reuse the independently maintained exact geometry/scene parser and
    # capture its cursor after actors. No scans for strings or guessed offsets.
    original=pipeline.PackedCursor;record=[]
    class RecordingCursor(original):
        def __init__(self,value):super().__init__(value);record.append(self)
    try:
        pipeline.PackedCursor=RecordingCursor
        pipeline.compiled_unit_structure(payload)
    finally:pipeline.PackedCursor=original
    require(len(record)==1,'Unexpected Unit parser cursor count')
    c=record[0];prefix_end=c.offset
    for label in ('cameras','lights','lod','terrains','joints','movers','script_events'):
        require(c.u32()==0,'Unsupported nonempty Unit '+label)
    require(c.u8() in (0,1),'Invalid animation-blender-bones flag')
    asm=c.byte_array().rstrip(b'\0').decode('utf8')
    metadata=dynamic_strings(c.byte_array())
    return {'asm':asm,'data':metadata,'geometry_scene_actor_prefix_end':prefix_end}


def state_bindings(payload):
    # Full controller parser validates the suffix/constraints. This additional
    # traversal retains the state animations which its aim-focused reader skips.
    controller=aim.compiled_controller(payload)
    c=pipeline.PackedCursor(payload);states={}
    for _ in range(aim.count(c,32)):
        layers=aim.count(c)
        for _ in range(layers):
            name=struct.unpack('<Q',c.take(8))[0];c.skip(16)
            require(c.u32() in range(5),'Unknown compiled state type')
            animations=tuple(x[0] for x in struct.iter_unpack('<Q',aim.array(c,8)))
            aim.array(c,4);c.skip(9)
            transitions=list(struct.iter_unpack('<IIB',aim.array(c,9)))
            settings=list(struct.iter_unpack('<If5I',aim.array(c,28)))
            require(aim.count(c)==0,'Conditional transition switches are unsupported for this integration')
            aim.array(c,12);c.skip(4);aim.array(c,12);c.skip(8)
            aim.array(c,4);aim.array(c,4);c.skip(16)
            constraints=aim.words(c);c.skip(12)
            require(name not in states,'Duplicate compiled state')
            edges=[]
            for event,index,conditional in transitions:
                require(conditional==0 and index<len(settings),'Invalid compiled direct transition')
                target,blend_time,mode,on_beat,*expression=settings[index]
                require(math.isfinite(blend_time) and blend_time>=0 and mode==0 and on_beat==0,
                        'Unsupported compiled transition mode/time')
                edges.append({'event':event,'target_index':target,'blend_time':blend_time,'mode':mode,'on_beat':on_beat})
            require(len({e['event'] for e in edges})==len(edges),'Duplicate compiled transition event')
            states[name]={'animations':animations,'constraints':constraints,'transitions':edges}
        require(c.u32()<layers,'Invalid default state')
    require(set(states)==set(controller.states),'Controller state parser mismatch')
    return controller,states


def verify_sampler_states(visible,sampler):
    """The hidden sampler changes only transition duration, never pose ownership."""
    require(set(visible)==set(sampler),'Sampler state inventory differs from visible controller')
    ordered=list(visible);helper_ordered=list(sampler);checked=0
    for ident,state in visible.items():
        helper=sampler[ident]
        require(helper['animations']==state['animations'] and helper['constraints']==state['constraints'],
                'Sampler clip or constraint differs from visible controller')
        edges={e['event']:e for e in state['transitions']}
        require(len(edges)==len(state['transitions']) and
                {e['event'] for e in helper['transitions']}==set(edges),
                'Sampler transition event inventory differs')
        for edge in helper['transitions']:
            target=edge['target_index'];old=edges[edge['event']]
            require(target<len(helper_ordered) and old['target_index']<len(ordered),
                    'Sampler transition target out of bounds')
            require(helper_ordered[target]==ordered[old['target_index']] and
                    edge['mode']==old['mode'] and edge['on_beat']==old['on_beat'],
                    'Sampler changed transition semantics')
            require(edge['blend_time']==0,'Sampler failed zero-duration endpoint evaluation')
            checked+=1
    return checked


def verify(unit_payload,controller_payload,manifest,profile_id,baseline_controller=None,sampler_controller=None):
    profile=manifest['profiles'][profile_id];metadata=unit_metadata(unit_payload)
    expected={pipeline.idstring32('warlock_rig_profile'):profile_id,
              pipeline.idstring32('warlock_animation_manifest_id'):profile['manifest_id']}
    require(metadata['data']==expected,'Compiled Unit profile markers differ from trusted manifest')
    require(metadata['asm']==profile['unit'],'Compiled Unit references another ASM')
    controller,states=state_bindings(controller_payload)
    aim.verify_aim(controller,tuple(profile['validation']['bone_names']) if 'bone_names' in profile['validation'] else
                   tuple(__import__('re').findall(r'"([^"\n]+)"',(ROOT/(profile['unit']+'.bones')).read_text())))
    expected_states={pipeline.murmur64a(name.encode()):name for name in profile['states']}
    require(set(states)==set(expected_states),'Compiled ASM state inventory differs from manifest')
    checked={};edge_count=cross_count=same_count=0
    ordered=list(states)
    reference=state_bindings(baseline_controller)[1] if baseline_controller is not None else None
    smooth=profile.get('cross_owner_transition_policy')=='snapshot-blend-v1'
    if smooth:
        require(reference is not None and sampler_controller is not None,
                'Smooth presentation requires original and sampler compiled controllers')
        require(profile.get('sampler_state_machine')==profile['unit']+'/presentation_sampler',
                'Unexpected sampler controller resource')
        require(profile.get('bone_names')==list(__import__('re').findall(r'"([^"\n]+)"',
                    (ROOT/(profile['unit']+'.bones')).read_text())),
                'Sampler full-bone inventory differs from shipping')
    for ident,name in expected_states.items():
        expected_state=profile['states'][name];actual=states[ident]
        require(actual['animations']==(pipeline.murmur64a(expected_state['clip'].encode()),),
                'Compiled ASM animation resource differs: '+name)
        expected_constraints=(0,) if expected_state['visible_aim'] else ()
        require(actual['constraints']==expected_constraints,'Compiled ASM aim ownership differs: '+name)
        expected_edges={pipeline.idstring32(event):(event,entry) for event,entry in expected_state['transitions'].items()}
        require({e['event'] for e in actual['transitions']}==set(expected_edges),'Compiled ASM transition inventory differs: '+name)
        ref_edges={e['event']:e for e in reference[ident]['transitions']} if reference else {}
        edges=[]
        for edge in actual['transitions']:
            event,spec=expected_edges[edge['event']]
            require(edge['target_index']<len(ordered),'Compiled transition target is out of bounds')
            target=expected_states[ordered[edge['target_index']]]
            require(target==spec['to'] and abs(edge['blend_time']-spec['blend_time'])<1e-7,
                    'Compiled transition destination/time differs: '+name+'/'+event)
            cross=expected_state['owner']!=profile['states'][target]['owner']
            if profile.get('cross_owner_transition_policy')=='cut':
                require(not cross or edge['blend_time']==0,'Compiled cross-owner transition failed mandatory cut')
                if reference:
                    old=ref_edges[edge['event']]
                    require(edge['target_index']==old['target_index'] and edge['mode']==old['mode']
                            and edge['on_beat']==old['on_beat'],'Compiled cut altered original transition semantics')
                    require(cross or edge['blend_time']==old['blend_time'],'Compiled cut altered same-owner transition blend')
            elif smooth:
                old=ref_edges[edge['event']]
                require(edge==old,'Smooth visible controller altered original transition semantics or duration')
            edges.append({'event':event,'to':target,'blend_time':edge['blend_time'],'cross_owner':cross})
            edge_count+=1;cross_count+=cross;same_count+=not cross
        checked[name]={'clip':expected_state['clip'],'constraints':list(actual['constraints']),
                       'owner':expected_state['owner'],'transitions':edges}
    result={'status':'compiled-unit-markers-and-asm-bindings-passed',
            'profile_id':profile_id,'manifest_id':profile['manifest_id'],'unit_markers':{
                'warlock_rig_profile':profile_id,'warlock_animation_manifest_id':profile['manifest_id']},
            'own_asm':metadata['asm'],'states':checked,'compiled_transition_edges':edge_count,
            'cross_owner_edges':cross_count,'same_owner_edges':same_count,
            'same_owner_blends_compared_to_shipping':reference is not None,'native_Unit_pose_samples':0}
    if smooth:
        sampler,helper_states=state_bindings(sampler_controller)
        aim.verify_aim(sampler,tuple(profile['bone_names']))
        result['presentation_sampler']={'resource':profile['sampler_state_machine'],
            'status':'compiled-full-skeleton-zero-edge-sampler-passed',
            'compiled_transition_edges':verify_sampler_states(states,helper_states),
            'deform_bones':len(profile['bone_names']),
            'visible_transition_durations_preserved':True,
            'hidden_runtime_evaluation':'not captured; requires in-game evaluation'}
    return result
