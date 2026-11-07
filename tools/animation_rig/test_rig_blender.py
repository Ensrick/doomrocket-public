"""Executable behavior checks and diagnostic poses for the Warlock authoring rig.

Run with Blender 5.2 --background --disable-autoexec <rig.blend> --python
this_file -- --output <validation directory> [--render]. For a separate smooth
SDK diagnostic, open the frozen diagnostic and add --continuous. This tests
evaluated skin and bones rather than the presence of controls. It never saves
the input.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def update():
    CTRL.update_tag()
    bpy.context.view_layer.update()


def reset():
    if CTRL.animation_data:
        CTRL.animation_data.action = None
    for pb in CTRL.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    for name, values in DEFAULTS.items():
        for prop, value in values.items():
            CTRL.pose.bones[name][prop] = value
    update()


def prop(name, key, value):
    CTRL.pose.bones[name][key] = value


def rotate(name, axis, degrees):
    pb = CTRL.pose.bones[name]
    pb.rotation_mode = 'XYZ'
    pb.rotation_euler[axis] = math.radians(degrees)


def move(name, delta):
    CTRL.pose.bones[name].location = Vector(delta)


def sample():
    update()
    dg = bpy.context.evaluated_depsgraph_get()
    eg = GAME.evaluated_get(dg)
    em = MESH.evaluated_get(dg)
    temp = em.to_mesh()
    vertices = [(em.matrix_world @ v.co).copy() for v in temp.vertices]
    em.to_mesh_clear()
    return {
        'vertices': vertices,
        'bones': {pb.name: (eg.matrix_world @ pb.matrix).copy() for pb in eg.pose.bones},
    }


def displacement(before, after, indices=None):
    ids = list(indices) if indices is not None else range(len(before['vertices']))
    distances = [(after['vertices'][i] - before['vertices'][i]).length for i in ids]
    return {
        'max_m': max(distances, default=0.0),
        'rms_m': math.sqrt(sum(d * d for d in distances) / max(1, len(distances))),
        'moved_vertices': sum(d > 1e-5 for d in distances),
        'vertices': len(distances),
    }


def rotation_delta(before, after, bone):
    a, b = before['bones'][bone], after['bones'][bone]
    delta = a.to_quaternion().rotation_difference(b.to_quaternion()).angle
    return math.degrees(min(delta, 2 * math.pi - delta))


def bone_delta(before, after, bone):
    return (before['bones'][bone].translation - after['bones'][bone].translation).length


def verify(name, condition, **evidence):
    REPORT['tests'].append({'name': name, 'passed': bool(condition), **evidence})
    print(('PASS ' if condition else 'FAIL ') + name, json.dumps(evidence, default=str))


def finiteness(snapshot):
    finite = all(math.isfinite(float(x)) for v in snapshot['vertices'] for x in v)
    finite = finite and all(math.isfinite(float(x)) for m in snapshot['bones'].values() for row in m for x in row)
    scales = [m.to_scale() for m in snapshot['bones'].values()]
    minimum = min(min(s) for s in scales)
    maximum = max(max(s) for s in scales)
    local_errors={}
    object_inverse=GAME.matrix_world.inverted()
    for name,world in snapshot['bones'].items():
        bone=GAME.data.bones[name]
        kwargs={}
        if bone.parent:
            kwargs={'parent_matrix':object_inverse@snapshot['bones'][bone.parent.name],
                'parent_matrix_local':bone.parent.matrix_local}
        basis=bone.convert_local_to_pose(object_inverse@world,bone.matrix_local,
            invert=True,**kwargs)
        location,rotation,scale=basis.decompose()
        reconstructed=Matrix.LocRotScale(location,rotation,scale)
        local_errors[name]=max(abs(basis[r][c]-reconstructed[r][c]) for r in range(4) for c in range(4))
    worst=max(local_errors,key=local_errors.get)
    return {'finite': finite, 'minimum_world_scale': minimum, 'maximum_world_scale': maximum,
        'local_TRS_max_error':local_errors[worst],'local_TRS_worst_bone':worst}


def skin_indices(bones, visible_only=False):
    group_indices = {g.index for g in MESH.vertex_groups if g.name in set(bones)}
    used={i for p in MESH.data.polygons for i in p.vertices} if visible_only else None
    return [v.index for v in MESH.data.vertices if (used is None or v.index in used)
        and any(g.group in group_indices and g.weight > 1e-4 for g in v.groups)]


def source_baseline():
    """Independent import supplies topology and neutral evaluated mesh reference."""
    # Prefer the handoff's pinned reference over any unrelated local checkout.
    # Absolute provenance paths need not exist on Arnaud's computer.
    source=Path(__file__).resolve().parent/'reference'/'shipping_body.fbx'
    if not source.is_file():
        source=Path(MANIFEST['sources']['body_fbx'])
    if not source.is_file():
        raise FileNotFoundError('Missing shipping FBX reference for independent neutral comparison')
    actual_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    if actual_sha!=MANIFEST['sources']['body_sha256']:
        raise ValueError('Shipping FBX reference differs from the rig source contract')
    original_objects = set(bpy.data.objects)
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False,
        automatic_bone_orientation=False, ignore_leaf_bones=False)
    imported = [o for o in bpy.data.objects if o not in original_objects]
    mesh = next(o for o in imported if o.type == 'MESH')
    armature = next(o for o in imported if o.type == 'ARMATURE')
    armature.animation_data_clear()
    for pb in armature.pose.bones:
        pb.matrix_basis=Matrix.Identity(4)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    evaluated = mesh.evaluated_get(dg)
    temp = evaluated.to_mesh()
    vertices = [(evaluated.matrix_world @ v.co).copy() for v in temp.vertices]
    evaluated.to_mesh_clear()
    result = {'vertices': vertices,
        'topology': [list(p.vertices) for p in mesh.data.polygons],
        'raw_vertices': [list(v.co) for v in mesh.data.vertices],
        'bones': {pb.name:(armature.matrix_world @ pb.matrix).copy() for pb in armature.pose.bones},
        'object_matrix': [list(row) for row in armature.matrix_world],
        'mesh_matrix': [list(row) for row in mesh.matrix_world],
        'materials': [m.name.removesuffix('.001') if m else None for m in mesh.data.materials]}
    for obj in imported:
        bpy.data.objects.remove(obj, do_unlink=True)
    return result


def test_structure_and_neutral():
    reset()
    expected = json.loads(GAME['original_skeleton'])
    current = [{'name': b.name, 'parent': b.parent.name if b.parent else None,
        'rest': [list(row) for row in b.matrix_local], 'inherit_scale': b.inherit_scale}
        for b in GAME.data.bones]
    verify('original_skeleton_preserved', current == expected and len(current) == 138,
        bone_count=len(current), parent=GAME.parent.name if GAME.parent else None)
    verify('control_and_game_skeletons_separate', CTRL is not GAME and all(not b.use_deform for b in CTRL.data.bones),
        control_bones=len(CTRL.data.bones))
    invalid_constraints = [f'{o.name}/{pb.name}/{c.name}' for o in (CTRL,GAME)
        for pb in o.pose.bones for c in pb.constraints if not c.is_valid and c.influence > 0 and not c.mute]
    invalid_drivers = [f'{o.name}/{d.data_path}' for o in (CTRL,GAME)
        if o.animation_data for d in o.animation_data.drivers if not d.driver.is_valid]
    verify('constraints_and_drivers_evaluate', not invalid_constraints and not invalid_drivers,
        invalid_constraints=invalid_constraints, invalid_drivers=invalid_drivers)
    source = source_baseline()
    reset()
    neutral = sample()
    topology = [list(p.vertices) for p in MESH.data.polygons]
    coords = [list(v.co) for v in MESH.data.vertices]
    verify('shipping_mesh_geometry_preserved', topology == source['topology'] and coords == source['raw_vertices'],
        vertices=len(coords), polygons=len(topology))
    rest_error = displacement(source, neutral)
    verify('neutral_matches_shipping_skin', rest_error['max_m'] < 0.0001, **rest_error)
    errors = {n:bone_delta(source,neutral,n) for n in source['bones'] if n != 'aim_target'}
    verify('neutral_game_joint_positions_match', max(errors.values()) < 0.00001,
        maximum_m=max(errors.values()), worst_bone=max(errors,key=errors.get))
    angle_errors={n:rotation_delta(source,neutral,n) for n in source['bones'] if n!='aim_target'}
    verify('neutral_game_joint_rotations_match',max(angle_errors.values())<.001,
        maximum_deg=max(angle_errors.values()),worst_bone=max(angle_errors,key=angle_errors.get))
    REPORT['neutral_reference']={'source_armature_matrix':source['object_matrix'],
        'source_mesh_matrix':source['mesh_matrix'],
        'rig_armature_matrix':[list(r) for r in GAME.matrix_world],
        'rig_mesh_matrix':[list(r) for r in MESH.matrix_world],
        'worst_rotation_source':[list(r) for r in source['bones'][max(angle_errors,key=angle_errors.get)]],
        'worst_rotation_rig':[list(r) for r in neutral['bones'][max(angle_errors,key=angle_errors.get)]]}
    expected_aim=Vector((.1,5.,.6))
    # Engine helper is intentionally held at its calibrated animation reference.
    aim_local=(GAME.data.bones['root_point'].matrix_local.inverted()
        @ GAME.pose.bones['aim_target'].matrix).translation
    verify('aim_target_calibrated_constant', (aim_local-expected_aim).length < 1e-5,
        local_position=list(aim_local))
    correction=MANIFEST.get('corrective_skin',{})
    if correction.get('controls'):
        verify('corrective_skin_is_explicit', correction.get('requires_candidate_body_export') is True
            and correction.get('outside_mask_unchanged') is True
            and correction.get('max_affected_influences',99) <= 4
            and correction.get('max_affected_normalization_error',99) < 1e-6,
            affected_vertices=correction.get('affected_vertices'), profile=correction.get('profile'))
    return neutral


def test_root(neutral):
    reset()
    move('root',(.1,0,0))
    posed=sample()
    error=max((b-a-Vector((.1,0,0))).length for a,b in zip(neutral['vertices'],posed['vertices']))
    verify('root_translates_skin_once_100mm', error < 2e-5,
        maximum_translation_error_m=error, **displacement(neutral,posed))


def test_limbs(neutral):
    for side in ('left','right'):
        for limb,base,end,fk_control,ik_control in (
            ('arm','arm','hand',f'j_{side}arm_ctrl_fk',f'j_{side}hand_ctrl_ik'),
            ('leg','upleg','foot',f'j_{side}upleg_ctrl_fk',f'j_{side}foot_ctrl_ik')):
            reset()
            prop(f'j_{side}{base}_ctrl_parent','IK_FK',1.)
            update()
            before=sample()
            rotate(fk_control,0,20)
            posed=sample()
            distance=bone_delta(before,posed,f'j_{side}{end}')
            skin=displacement(before,posed,skin_indices([f'j_{side}{base}',f'j_{side}{end}']))
            verify(f'{side}_{limb}_FK_moves_endpoint_and_skin', distance > .025 and skin['max_m'] > .02,
                endpoint_m=distance, **skin)
            reset()
            # IK endpoint move uses a reachable displacement, not a stretched pose.
            prop(f'j_{side}{base}_ctrl_parent','IK_FK',0.)
            prop(f'j_{side}{base}_ctrl_parent','IK_Stretch',0.)
            before=sample()
            move(ik_control,(.035,0,.02))
            posed=sample()
            target_distance=math.sqrt(.035**2+.02**2)
            distance=bone_delta(before,posed,f'j_{side}{end}')
            finite=finiteness(posed)
            verify(f'{side}_{limb}_IK_moves_endpoint_and_skin', distance > .01 and distance < .12
                and finite['finite'], endpoint_m=distance, requested_control_m=target_distance,
                **displacement(before,posed,skin_indices([f'j_{side}{base}',f'j_{side}{end}'])), **finite)
        reset()
        before=sample()
        rotate(f'j_{side}foot_ctrl_heel_ik',0,20)
        posed=sample()
        verify(f'{side}_heel_roll_affects_foot_skin', rotation_delta(before,posed,f'j_{side}foot') > 5
            and displacement(before,posed,skin_indices([f'j_{side}foot',f'j_{side}toebase']))['max_m'] > .005,
            foot_rotation_deg=rotation_delta(before,posed,f'j_{side}foot'))
        reset()
        before=sample()
        rotate(f'j_{side}toebase_ctrl',0,20)
        posed=sample()
        verify(f'{side}_toe_roll_affects_toe_skin', rotation_delta(before,posed,f'j_{side}toebase') > 5,
            toe_rotation_deg=rotation_delta(before,posed,f'j_{side}toebase'),
            **displacement(before,posed,skin_indices([f'j_{side}toebase'])))


def test_fingers_and_twist(neutral):
    for side in ('left','right'):
        finger_names=[f'j_{side}hand{digit}{seg}' for digit in ('index','middle','ring','pinky') for seg in (1,2,3)]
        # Imported shipping geometry retains an isolated vertex weighted to a
        # ring fingertip and a leg. Preserve it, but evaluate visible surfaces.
        ids=skin_indices(finger_names+[f'j_{side}handthumb1',f'j_{side}handthumb2'],visible_only=True)
        for key,value in (('curl',.7),('spread',.7),('curl_thumb',.7)):
            reset()
            prop(f'CTRL-hand-settings-{side}',key,value)
            posed=sample()
            stats=displacement(neutral,posed,ids)
            verify(f'{side}_finger_{key}_moves_weighted_vertices', stats['max_m'] > .001
                and stats['max_m'] < .16 and stats['moved_vertices'] > 0, **stats)
        reset()
        prop(f'j_{side}arm_ctrl_parent','IK_FK',1.)
        prop(f'CTRL-forearm-twist-{side}','auto_twist',.5)
        before=sample()
        rotate(f'j_{side}hand_ctrl_fk',1,60)
        posed=sample()
        angle=rotation_delta(before,posed,f'j_{side}forearmroll')
        wrist=bone_delta(before,posed,f'j_{side}hand')
        verify(f'{side}_automatic_forearm_twist', angle > 5 and angle < 65 and wrist < .0001,
            forearm_roll_deg=angle, wrist_translation_m=wrist,
            **displacement(before,posed,skin_indices([f'j_{side}forearmroll'])))
        reset()
        before=sample()
        rotate(f'CTRL-forearm-twist-{side}',1,20)
        posed=sample()
        angle=rotation_delta(before,posed,f'j_{side}forearmroll')
        verify(f'{side}_manual_forearm_twist', angle > 10 and bone_delta(before,posed,f'j_{side}hand') < .0001,
            forearm_roll_deg=angle, **displacement(before,posed,skin_indices([f'j_{side}forearmroll'])))


def test_accessories(neutral):
    reset()
    move('ORG-j_backpack',(.025,0,0))
    posed=sample()
    backpack=skin_indices(['j_backpack'])
    other=set(range(len(MESH.data.vertices)))-set(backpack)
    response=displacement(neutral,posed,backpack)
    outside=displacement(neutral,posed,other)
    verify('backpack_control_moves_backpack_only', response['max_m'] > .01 and outside['max_m'] < 1e-5,
        backpack=response, unrelated=outside)
    all_indices=set(range(len(MESH.data.vertices)))
    corrections=MANIFEST.get('corrective_skin',{})
    for item in corrections.get('controls',[]):
        reset()
        move(item['control'],(.025,0,0))
        posed=sample()
        ids=item['weighted_vertex_indices']
        mask=displacement(neutral,posed,ids)
        outside=displacement(neutral,posed,all_indices-set(ids))
        verify('localized_'+item['control'], mask['max_m'] > .001 and mask['moved_vertices'] > 0
            and outside['max_m'] < 1e-5, expected_bone=item['bone'], masked=mask, unrelated=outside)


def test_launcher_reference(neutral):
    weapon=bpy.data.objects.get('WARLOCK_LAUNCHER_REFERENCE')
    if weapon is None:
        return
    reset()
    references=[o for o in bpy.data.objects if o.get('authoring_reference_only')]
    meshes=[o for o in references if o.type=='MESH']
    verify('launcher_is_separate_approved_authoring_reference', weapon is not GAME
        and weapon.get('authoring_reference_only') is True
        and sorted(len(o.data.vertices) for o in meshes)==[622,3308]
        and all(not any(m.type=='ARMATURE' and m.object==GAME for m in o.modifiers) for o in meshes),
        reference_objects=[o.name for o in references],
        mesh_vertex_counts=[len(o.data.vertices) for o in meshes])
    def weapon_snapshot():
        update()
        dg=bpy.context.evaluated_depsgraph_get()
        eg=GAME.evaluated_get(dg)
        attach=eg.matrix_world@eg.pose.bones['j_leftweaponattach'].matrix
        ew=weapon.evaluated_get(dg)
        points=[]
        for obj in meshes:
            eo=obj.evaluated_get(dg)
            temp=eo.to_mesh()
            points.extend([(eo.matrix_world@v.co).copy() for v in temp.vertices])
            eo.to_mesh_clear()
        return attach.copy(),ew.matrix_world.copy(),points
    attach_before,root_before,points_before=weapon_snapshot()
    matrix_error=max(abs(attach_before[r][c]-root_before[r][c]) for r in range(4) for c in range(4))
    verify('launcher_root_matches_game_attachment_frame',matrix_error<1e-5,
        maximum_matrix_error=matrix_error,
        boundary='Attachment-frame agreement does not prove fingers touch the semantic grip in the neutral bind pose.')
    move('ORG-j_leftweaponattach',(.03,0,0))
    attach_after,root_after,points_after=weapon_snapshot()
    delta=attach_after.translation-attach_before.translation
    mesh_error=max((b-a-delta).length for a,b in zip(points_before,points_after))
    skin=displacement(neutral,sample())
    verify('launcher_attachment_curve_moves_prop_without_body_skin',delta.length>.01
        and mesh_error<1e-5 and skin['max_m']<1e-5,
        attachment_translation_m=delta.length, maximum_prop_translation_error_m=mesh_error,
        body_skin=skin)
    reset()


def test_stretch_squash(neutral):
    for name in MANIFEST['groups'].get('Stretch and squash',[]):
        for length in (.75,1.35):
            reset()
            prop(name,'length',length)
            prop(name,'volume',1.)
            posed=sample()
            finite=finiteness(posed)
            stats=displacement(neutral,posed)
            verify(f'{name}_length_{length}_real_finite_skin', finite['finite']
                and finite['minimum_world_scale'] > 0 and finite['maximum_world_scale'] < 2.
                and finite['local_TRS_max_error'] < 2e-5
                and stats['max_m'] > .001, **stats, **finite)
    reset()
    # Combined controls exercise interaction, not merely isolated scale channels.
    prop('j_leftarm_ctrl_parent','IK_FK',1.)
    rotate('j_leftarm_ctrl_fk',0,35)
    prop('CTRL-shape-j_leftarm_scale','length',1.2)
    prop('CTRL-shape-j_leftarm_scale','volume',1.)
    finite=finiteness(sample())
    verify('combined_bend_and_stretch_stays_finite', finite['finite']
        and finite['minimum_world_scale'] > 0 and finite['maximum_world_scale'] < 2.
        and finite['local_TRS_max_error'] < 2e-5, **finite)


def diagnostic_pose(label):
    if label=='crouch':
        move('torso',(0,0,-.13))
        rotate('j_spine_ctrl_fk',0,12)
    elif label=='FK reach':
        for side in ('left','right'):
            prop(f'j_{side}arm_ctrl_parent','IK_FK',1.)
            rotate(f'j_{side}arm_ctrl_fk',0,-30)
            rotate(f'j_{side}forearm_ctrl_fk',0,25)
    elif label=='IK reach':
        move('j_lefthand_ctrl_ik',(.08,.04,.06))
        move('j_righthand_ctrl_ik',(-.05,.02,.08))
    elif label=='foot rolls':
        rotate('j_leftfoot_ctrl_heel_ik',0,25)
        rotate('j_righttoebase_ctrl',0,20)
    elif label=='fingers and twist':
        prop('j_leftarm_ctrl_parent','IK_FK',1.)
        rotate('j_lefthand_ctrl_fk',1,60)
        prop('CTRL-hand-settings-left','curl',.7)
        prop('CTRL-hand-settings-right','spread',.7)
    elif label=='stretch and squash':
        prop('CTRL-shape-j_spine_scale','length',.85)
        prop('CTRL-shape-j_spine_scale','volume',1.)
        prop('CTRL-shape-j_leftarm_scale','length',1.2)
    elif label=='backpack cloth belt':
        rotate('ORG-j_backpack',0,12)
        for item in MANIFEST.get('corrective_skin',{}).get('controls',[]):
            delta=(.02 if item.get('kind')=='belt' else .035,0,.005)
            move(item['control'],delta)
            if item.get('kind')=='cloth': rotate(item['control'],0,10)
    update()


def prepare_camera():
    scene=bpy.context.scene
    scene.render.engine='BLENDER_WORKBENCH'
    scene.render.resolution_x=600
    scene.render.resolution_y=720
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.render.film_transparent=False
    display=scene.display.shading
    display.light='STUDIO'
    display.studio_light='paint.sl'
    display.color_type='MATERIAL'
    display.show_shadows=True
    display.show_cavity=True
    display.cavity_type='BOTH'
    display.show_object_outline=True
    display.background_type='WORLD'
    display.background_color=(.06,.07,.09)
    for material in MESH.data.materials:
        if material is None: continue
        low=material.name.lower()
        color=(.57,.62,.65,1)
        if 'body' in low: color=(.48,.4,.38,1)
        elif 'fur' in low: color=(.23,.17,.13,1)
        elif 'backpack' in low: color=(.28,.36,.29,1)
        material.diffuse_color=color
    camera_data=bpy.data.cameras.new('Rig validation camera')
    camera=bpy.data.objects.new('Rig validation camera',camera_data)
    scene.collection.objects.link(camera)
    target=Vector((0,-.2,.92))
    camera.location=Vector((3.8,5.2,2.6))
    camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
    camera_data.type='ORTHO'
    camera_data.ortho_scale=3.3 if bpy.data.objects.get('WARLOCK_LAUNCHER_REFERENCE') else 2.7
    scene.camera=camera
    scene.world.color=(.065,.075,.095)
    return camera


def fit_pose_camera(records):
    """Use one view containing all tested body and existing reference poses."""
    scene=bpy.context.scene
    camera=scene.camera
    inverse=camera.matrix_world.inverted()
    points=[]
    for item in records:
        scene.frame_set(item['frame'])
        update()
        graph=bpy.context.evaluated_depsgraph_get()
        for obj in scene.objects:
            if obj.type!='MESH' or obj.hide_render or not obj.visible_get(): continue
            if obj!=MESH and not obj.get('authoring_reference_only'): continue
            evaluated=obj.evaluated_get(graph)
            mesh=evaluated.to_mesh()
            points.extend(inverse @ (evaluated.matrix_world @ v.co) for v in mesh.vertices)
            evaluated.to_mesh_clear()
    minimum=Vector((min(p.x for p in points),min(p.y for p in points),0))
    maximum=Vector((max(p.x for p in points),max(p.y for p in points),0))
    camera.location+=camera.matrix_world.to_quaternion() @ ((minimum+maximum)/2)
    aspect=scene.render.resolution_x/scene.render.resolution_y
    camera.data.ortho_scale=max(maximum.y-minimum.y,(maximum.x-minimum.x)/aspect)*1.12


def diagnostic(output,render):
    labels=['neutral','crouch','FK reach','IK reach','foot rolls','fingers and twist',
        'stretch and squash','backpack cloth belt','neutral return']
    record=[]
    if render: prepare_camera()
    key_bones=[pb for pb in CTRL.pose.bones if pb.custom_shape]
    bpy.context.scene.frame_start=1
    bpy.context.scene.frame_end=97
    bpy.context.scene.render.fps=60
    # Establish every control's rotation mode before inserting the first key.
    # Otherwise a later Euler edit can leave the initial quaternion channels
    # inactive and extrapolate an unrelated first Euler key into frame one.
    for label in labels:
        reset()
        diagnostic_pose(label)
    reset()
    neutral_reference=sample()
    authored=[]
    # Each pose is independently reset. Hold keys avoid accidental unsampled mixes.
    action=None
    for i,label in enumerate(labels):
        reset()
        frame=1+i*12
        bpy.context.scene.frame_set(frame)
        diagnostic_pose('neutral' if label=='neutral return' else label)
        authored.append(sample())
        if action:
            CTRL.animation_data.action=action
        for pb in key_bones:
            for field in ('location','scale'):
                if CTRL.animation_data and any(fc.data_path==pb.path_from_id(field) for fc in CTRL.animation_data.drivers):
                    continue
                pb.keyframe_insert(data_path=field,frame=frame,group=pb.name)
            field='rotation_quaternion' if pb.rotation_mode=='QUATERNION' else 'rotation_euler'
            pb.keyframe_insert(data_path=field,frame=frame,group=pb.name)
            for key in DEFAULTS.get(pb.name,{}):
                pb.keyframe_insert(data_path='["'+key+'"]',frame=frame,group=pb.name)
        action=CTRL.animation_data.action
        action.name='Warlock_Rig_Diagnostic'
        current=sample()
        record.append({'label':label,'frame':frame,'finite':finiteness(current),
            'bones':{n:[list(r) for r in m] for n,m in current['bones'].items()}})
    # Set all exported control curves to constant holds for exact test poses.
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for key in fc.keyframe_points: key.interpolation='CONSTANT'
    CTRL.animation_data.action=action
    # Evaluate the completed action independently. Later key insertion must
    # never change a previously authored marker through mode/extrapolation.
    for i,item in enumerate(record):
        bpy.context.scene.frame_set(item['frame'])
        evaluated=sample()
        matrix_error=max(abs(authored[i]['bones'][name][r][c]-matrix[r][c])
            for name,matrix in evaluated['bones'].items() for r in range(4) for c in range(4))
        skin=displacement(authored[i],evaluated)
        verify('diagnostic_marker_matches_authored_'+item['label'].replace(' ','_'),
            matrix_error<1e-6 and skin['max_m']<1e-6,bones=len(evaluated['bones']),
            frame=item['frame'],max_matrix_error=matrix_error,**skin)
        if i in (0,8):
            neutral_skin=displacement(neutral_reference,evaluated)
            neutral_bones=max(abs(neutral_reference['bones'][name][r][c]-matrix[r][c])
                for name,matrix in evaluated['bones'].items() for r in range(4) for c in range(4))
            verify('diagnostic_'+item['label'].replace(' ','_')+'_matches_main_neutral',
                neutral_bones<1e-6 and neutral_skin['max_m']<1e-6,
                max_matrix_error=neutral_bones,**neutral_skin)
    if render:
        fit_pose_camera(record)
        for i,item in enumerate(record):
            bpy.context.scene.frame_set(item['frame'])
            update()
            bpy.context.scene.render.filepath=str(output/f'pose_{i+1:02}_{item["label"].replace(" ","_")}.png')
            bpy.ops.render.render(write_still=True)
    bpy.context.scene.frame_set(1)
    update()
    for i,label in enumerate(labels):
        bpy.context.scene.timeline_markers.new(label,frame=1+i*12)
    bpy.ops.object.select_all(action='DESELECT')
    CTRL.hide_set(False)
    CTRL.select_set(True)
    bpy.context.view_layer.objects.active=CTRL
    bpy.ops.object.mode_set(mode='POSE')
    path=output.parent/'WarlockEngineer_Rig_Diagnostic.blend'
    if bpy.data.filepath and path.resolve()==Path(bpy.data.filepath).resolve():
        raise ValueError('Diagnostic output cannot overwrite the input')
    bpy.ops.wm.save_as_mainfile(filepath=str(path),compress=True,check_existing=False)
    (output/'diagnostic_samples.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    REPORT['diagnostic']={'file':str(path),'action':action.name,'frame_start':1,'frame_end':97,
        'fps':60,'poses':[{'label':r['label'],'frame':r['frame']} for r in record],
        'renders':render}


def continuous_diagnostic(options):
    """Preserve the step stress case; verify a separate paced authoring action."""
    global CTRL,GAME,MESH,MANIFEST,REPORT
    CTRL=bpy.data.objects['WARLOCK_CTRL']
    GAME=bpy.data.objects['WARLOCK_GAME']
    MESH=next(o for o in bpy.data.objects if o.type=='MESH'
        and any(m.type=='ARMATURE' and m.object==GAME for m in o.modifiers))
    MANIFEST=json.loads(CTRL['warlock_control_manifest'])
    scene=bpy.context.scene
    output=options.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    input_path=Path(bpy.data.filepath)
    input_sha=hashlib.sha256(input_path.read_bytes()).hexdigest()
    frozen_action=CTRL.animation_data.action
    if not frozen_action or frozen_action.name!='Warlock_Rig_Diagnostic':
        raise ValueError('--continuous requires the frozen Warlock_Rig_Diagnostic scene')
    markers=sorted(scene.timeline_markers,key=lambda m:m.frame)
    if len(markers)!=9 or [m.frame for m in markers]!=list(range(1,98,12)):
        raise ValueError('Expected the nine original diagnostic markers at frames 1–97')
    REPORT={'schema':1,'source_step_file':str(input_path),'source_step_sha256':input_sha,
        'blender':bpy.app.version_string,'tests':[],
        'note':'The separate step diagnostic is retained as an abrupt-transition stress case.',
        'limitation':'The launcher is a calibrated attachment reference; hand grip fit and in-game playback remain unverified.'}
    # Capture all original marker bones and actual evaluated skin before edits.
    frozen=[]
    for marker in markers:
        scene.frame_set(marker.frame)
        frozen.append({'label':marker.name,'old_frame':marker.frame,'sample':sample()})
    source=source_baseline()
    neutral_skin=displacement(source,frozen[0]['sample'])
    neutral_heads=max(bone_delta(source,frozen[0]['sample'],name)
        for name in source['bones'] if name!='aim_target')
    neutral_rotations=max(rotation_delta(source,frozen[0]['sample'],name)
        for name in source['bones'] if name!='aim_target')
    verify('continuous_start_is_true_shipping_neutral',neutral_skin['max_m']<1e-4
        and neutral_heads<1e-5 and neutral_rotations<.001,
        maximum_joint_position_m=neutral_heads,maximum_joint_rotation_deg=neutral_rotations,**neutral_skin)
    return_skin=displacement(frozen[0]['sample'],frozen[-1]['sample'])
    return_matrix=max(abs(frozen[0]['sample']['bones'][name][r][c]-matrix[r][c])
        for name,matrix in frozen[-1]['sample']['bones'].items() for r in range(4) for c in range(4))
    verify('continuous_return_matches_true_neutral',return_skin['max_m']<1e-6 and return_matrix<1e-6,
        max_matrix_error=return_matrix,**return_skin)
    action=frozen_action.copy()
    action.name='Warlock_Rig_Continuous'
    CTRL.animation_data.action=action
    curves=[]
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                curves.extend(bag.fcurves)
    incomplete=[]
    for curve in curves:
        # The frozen file contains both Euler and quaternion channels for
        # controls whose mode changed during pose authoring. Sample each curve
        # at every marker, including held/extrapolated values, to preserve the
        # actual saved-scene poses rather than invent missing keys.
        if len(curve.keyframe_points)!=9:
            incomplete.append({'path':curve.data_path,'index':curve.array_index,
                'original_keys':len(curve.keyframe_points)})
        values=[(float(item['old_frame']),float(curve.evaluate(item['old_frame']))) for item in frozen]
        curve.keyframe_points.clear()
        for i,(_,value) in enumerate(values):
            for frame in (1+i*72,13+i*72):
                key=curve.keyframe_points.insert(frame,value,options={'FAST'})
                key.interpolation='LINEAR'
                key.handle_left_type=key.handle_right_type='VECTOR'
        curve.update()
    for marker in list(scene.timeline_markers): scene.timeline_markers.remove(marker)
    for i,item in enumerate(frozen):
        scene.timeline_markers.new(item['label'],frame=1+i*72)
    scene.frame_start=1
    scene.frame_end=589
    scene.render.fps=60
    REPORT['held_or_extrapolated_source_curves']=incomplete
    verify('continuous_reuses_all_existing_control_curves',bool(curves),curves=len(curves),
        holds_frames=12,transition_frames=60,fps=60)
    for i,item in enumerate(frozen):
        frame=1+i*72
        scene.frame_set(frame)
        current=sample()
        matrix_error=max(abs(item['sample']['bones'][name][r][c]-matrix[r][c])
            for name,matrix in current['bones'].items() for r in range(4) for c in range(4))
        skin=displacement(item['sample'],current)
        verify('continuous_marker_matches_frozen_'+item['label'].replace(' ','_'),
            len(current['bones'])==138 and matrix_error<1e-6 and skin['max_m']<1e-6,
            frame=frame,frozen_frame=item['old_frame'],bones=len(current['bones']),
            max_matrix_error=matrix_error,**skin)
    used=sorted({index for polygon in MESH.data.polygons for index in polygon.vertices})
    records=[]
    previous=None
    all_finite=True
    minimum_scale=float('inf')
    maximum_scale=0.
    max_trs=0.
    max_skin_step=0.
    max_head_step=0.
    max_output_axis_dot=0.
    max_output_scale_error=0.
    worst_trs=None
    worst_step=None
    for frame in range(1,590):
        scene.frame_set(frame)
        current=sample()
        checks=finiteness(current)
        all_finite=all_finite and checks['finite'] and len(current['bones'])==138
        minimum_scale=min(minimum_scale,checks['minimum_world_scale'])
        maximum_scale=max(maximum_scale,checks['maximum_world_scale'])
        if checks['local_TRS_max_error']>max_trs:
            max_trs=checks['local_TRS_max_error']
            worst_trs={'frame':frame,'bone':checks['local_TRS_worst_bone']}
        if previous:
            step=displacement(previous,current,used)
            max_head_step=max(max_head_step,max(bone_delta(previous,current,name)
                for name in current['bones']))
            if step['max_m']>max_skin_step:
                max_skin_step=step['max_m']
                worst_step={'from_frame':frame-1,'to_frame':frame}
        evaluated_output=bpy.data.objects['WARLOCK_OUTPUT'].evaluated_get(bpy.context.evaluated_depsgraph_get())
        for pb in evaluated_output.pose.bones:
            columns=[(evaluated_output.matrix_world@pb.matrix).to_3x3().col[i].copy() for i in range(3)]
            max_output_scale_error=max(max_output_scale_error,max(abs(column.length-1) for column in columns))
            max_output_axis_dot=max(max_output_axis_dot,max(abs(columns[a].normalized().dot(columns[b].normalized()))
                for a,b in ((0,1),(0,2),(1,2))))
        records.append({'frame':frame,'finite':checks,
            'bones':{name:[list(row) for row in matrix] for name,matrix in current['bones'].items()}})
        previous=current
        if frame%60==0: print('CONTINUOUS_FRAME',frame,flush=True)
    verify('continuous_every_frame_has_138_finite_bones_and_finite_skin',all_finite,
        frames=589,bone_frames=589*138,vertices_per_frame=len(MESH.data.vertices))
    verify('continuous_every_frame_positive_bounded_scale',minimum_scale>0 and maximum_scale<2,
        minimum_world_scale=minimum_scale,maximum_world_scale=maximum_scale)
    verify('continuous_every_frame_preserves_exportable_local_TRS',max_trs<2e-5,
        local_TRS_max_error=max_trs,worst=worst_trs)
    verify('continuous_visible_skin_has_no_frame_discontinuity',max_skin_step<.03,
        max_visible_vertex_step_m=max_skin_step,worst=worst_step,visible_vertices=len(used))
    verify('continuous_game_heads_have_no_frame_discontinuity',max_head_step<.03,
        maximum_game_head_step_m=max_head_step)
    verify('continuous_solver_outputs_stay_rigid_without_world_shear',
        max_output_scale_error<2e-5 and max_output_axis_dot<1e-5,
        max_output_scale_error=max_output_scale_error,max_normalized_output_axis_dot=max_output_axis_dot)
    scene.frame_set(1)
    update()
    path=output.parent/'WarlockEngineer_Rig_Continuous.blend'
    if path.resolve()==input_path.resolve(): raise ValueError('Continuous output cannot overwrite the input')
    bpy.ops.object.select_all(action='DESELECT')
    CTRL.hide_set(False)
    CTRL.select_set(True)
    bpy.context.view_layer.objects.active=CTRL
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.wm.save_as_mainfile(filepath=str(path),compress=True,check_existing=False)
    REPORT['diagnostic']={'file':str(path),'action':action.name,'frame_start':1,'frame_end':589,
        'fps':60,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'markers':[{'label':item['label'],'frame':1+i*72} for i,item in enumerate(frozen)]}
    unchanged=hashlib.sha256(input_path.read_bytes()).hexdigest()==input_sha
    verify('frozen_step_diagnostic_file_is_unchanged',unchanged,sha256=input_sha)
    REPORT['passed']=all(t['passed'] for t in REPORT['tests'])
    REPORT['counts']={'passed':sum(t['passed'] for t in REPORT['tests']),
        'failed':sum(not t['passed'] for t in REPORT['tests'])}
    (output/'continuous_samples.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    (output/'continuous_behavior_report.json').write_text(json.dumps(REPORT,indent=2)+'\n',encoding='utf-8')
    print('WARLOCK_CONTINUOUS_BEHAVIOR',json.dumps({'passed':REPORT['passed'],'counts':REPORT['counts'],
        'output':str(path),'sha256':REPORT['diagnostic']['sha256']}),flush=True)
    if not REPORT['passed']: raise RuntimeError('Continuous diagnostic validation failed; inspect continuous_behavior_report.json')


def main(options):
    global CTRL,GAME,MESH,MANIFEST,DEFAULTS,REPORT
    CTRL=bpy.data.objects['WARLOCK_CTRL']
    GAME=bpy.data.objects['WARLOCK_GAME']
    MESH=next(o for o in bpy.data.objects if o.type=='MESH'
        and any(m.type=='ARMATURE' and m.object==GAME for m in o.modifiers))
    MANIFEST=json.loads(CTRL['warlock_control_manifest'])
    DEFAULTS=json.loads(CTRL['warlock_control_defaults'])
    output=options.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    REPORT={'schema':1,'rig_file':bpy.data.filepath,'blender':bpy.app.version_string,
        'rig_sha256':hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest(),
        'source_fbx_sha256':GAME['source_fbx_sha256'],'tests':[],
        'isolated_source_vertices':sorted(set(range(len(MESH.data.vertices)))-
            {i for p in MESH.data.polygons for i in p.vertices}),
        'limitation':'Blender behavior and FBX/SDK validation do not establish an in-game visual verdict.'}
    try:
        neutral=test_structure_and_neutral()
        test_root(neutral)
        test_limbs(neutral)
        test_fingers_and_twist(neutral)
        test_accessories(neutral)
        test_launcher_reference(neutral)
        test_stretch_squash(neutral)
        reset()
        returned=sample()
        stats=displacement(neutral,returned)
        verify('neutral_is_recoverable_after_all_edits',stats['max_m']<1e-5,**stats)
        diagnostic(output,options.render)
    except Exception as exc:
        import traceback
        REPORT['exception']={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
        print(REPORT['exception']['traceback'])
    REPORT['passed']=bool(REPORT['tests']) and all(t['passed'] for t in REPORT['tests']) and 'exception' not in REPORT
    REPORT['counts']={'passed':sum(t['passed'] for t in REPORT['tests']),
        'failed':sum(not t['passed'] for t in REPORT['tests'])}
    (output/'rig_behavior_report.json').write_text(json.dumps(REPORT,indent=2)+'\n',encoding='utf-8')
    print('WARLOCK_RIG_BEHAVIOR',json.dumps({'passed':REPORT['passed'],'counts':REPORT['counts'],'output':str(output)}))
    if not REPORT['passed']: raise RuntimeError('Warlock rig behavior validation failed; inspect rig_behavior_report.json')


if __name__=='__main__':
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--render',action='store_true')
    parser.add_argument('--continuous',action='store_true',
        help='Create and verify a separate smooth diagnostic from the frozen step diagnostic.')
    options=parser.parse_args(argv)
    if options.continuous: continuous_diagnostic(options)
    else: main(options)
