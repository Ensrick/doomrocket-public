"""Build an animator scene; never overwrite the artist master or game sources.

Run with Blender 5.2 --background --factory-startup --disable-autoexec --python.
The separate Rigify mechanisms drive the exact imported shipping skeleton.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import sys
from pathlib import Path
import bpy
from mathutils import Matrix, Vector

BODY = 'units/warlock_bombardier/warlock_bombardier_3p.fbx'
READY_SHA = '0f23c954bf9bb0a68d4d5ecc22ee5f8a7f69e99e242b5f3812e857f9853574d1'

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def matrix_list(m):
    return [list(row) for row in m]

def custom_property(bone, name, value, low, high, description):
    bone[name] = value
    bone.id_properties_ui(name).update(min=low, max=high, soft_min=low,
        soft_max=high, default=value, description=description)

def driver(owner, field, expression, variables, index=None):
    fc = owner.driver_add(field) if index is None else owner.driver_add(field, index)
    d = fc.driver
    d.type = 'SCRIPTED'
    d.expression = expression
    for name, target, path in variables:
        v = d.variables.new(); v.name = name; v.type = 'SINGLE_PROP'
        v.targets[0].id = target; v.targets[0].data_path = path
    return d

def weapon_reference_rotation(reference, game):
    """Match the engine's normalized-axis quaternion policy, including shear.

    Child Of removes scale using Blender's decomposition, whose rotation differs
    from Unit.world_rotation under anatomical stretch. These reference-only
    scalar drivers use ordinary math expressions and work with autoexec disabled.
    Separate dependency stages keep evaluated pose reads ahead of the reference.
    """
    helpers = []
    for suffix in ('WORLD', 'AXES', 'QUATERNION'):
        obj = bpy.data.objects.new('WARLOCK_WEAPON_REFERENCE_' + suffix, None)
        bpy.context.scene.collection.objects.link(obj)
        obj['authoring_reference_only'] = True
        obj.hide_render = True
        obj.hide_set(True)
        helpers.append(obj)
    world, axes, quaternion = helpers
    bone = 'pose.bones["j_leftweaponattach"].matrix'
    for row in range(3):
        for column in range(3):
            key = 'm%d%d' % (row, column)
            world[key] = 0.0
            variables = []
            for k in range(4):
                # RNA driver paths index matrix storage by column, unlike
                # mathutils' Python row indexing used by the validation oracle.
                variables.extend(((chr(97 + 2*k), game, 'matrix_world[%d][%d]' % (k, row)),
                                  (chr(98 + 2*k), game, bone + '[%d][%d]' % (column, k))))
            driver(world, '["' + key + '"]', 'a*b+c*d+e*f+g*h', variables)
            axes[key] = 0.0
            driver(axes, '["' + key + '"]', 'a/sqrt(a*a+b*b+c*c)',
                   [(name, world, '["m%d%d"]' % (r, column))
                    for name, r in zip('abc', (row, (row+1) % 3, (row+2) % 3))])
    variables = [(name, axes, '["m%d%d"]' % cell)
                 for name, cell in zip('abcdefghi',
                     ((0,0),(1,1),(2,2),(2,1),(1,2),(0,2),(2,0),(1,0),(0,1)))]
    expressions = (
        'sqrt(1+a+b+c)/2 if a+b+c>0 else (d-e)/(2*sqrt(1+a-b-c)) if a>b and a>c else (f-g)/(2*sqrt(1+b-a-c)) if b>c else (h-i)/(2*sqrt(1+c-a-b))',
        '(d-e)/(2*sqrt(1+a+b+c)) if a+b+c>0 else sqrt(1+a-b-c)/2 if a>b and a>c else (i+h)/(2*sqrt(1+b-a-c)) if b>c else (f+g)/(2*sqrt(1+c-a-b))',
        '(f-g)/(2*sqrt(1+a+b+c)) if a+b+c>0 else (i+h)/(2*sqrt(1+a-b-c)) if a>b and a>c else sqrt(1+b-a-c)/2 if b>c else (d+e)/(2*sqrt(1+c-a-b))',
        '(h-i)/(2*sqrt(1+a+b+c)) if a+b+c>0 else (f+g)/(2*sqrt(1+a-b-c)) if a>b and a>c else (d+e)/(2*sqrt(1+b-a-c)) if b>c else sqrt(1+c-a-b)/2',
    )
    for component, expression in zip('wxyz', expressions):
        quaternion[component] = 0.0
        driver(quaternion, '["' + component + '"]', expression, variables)
    reference.rotation_mode = 'QUATERNION'
    for index, component in enumerate('wxyz'):
        driver(reference, 'rotation_quaternion', component + '/sqrt(w*w+x*x+y*y+z*z)',
               [(name, quaternion, '["' + name + '"]') for name in 'wxyz'], index=index)
    return helpers

def widget(name, kind):
    # Geometry is in bone-local units. Object transforms are deliberately identity.
    if kind == 'diamond':
        points = [(0,.6,0),(.6,0,0),(0,-.6,0),(-.6,0,0)]
    elif kind == 'box':
        points = [(-.7,-.4,0),(.7,-.4,0),(.7,.4,0),(-.7,.4,0)]
    elif kind == 'belt':
        points = [(-.7,-.2,0),(.7,-.2,0),(.7,.2,0),(-.7,.2,0)]
    elif kind == 'cloth':
        points = [(-.5,.4,0),(.5,.4,0),(.4,-.6,0),(-.4,-.6,0)]
    else:
        points = [(math.cos(t*math.tau/32)*.65, math.sin(t*math.tau/32)*.65,0) for t in range(32)]
    edges = [(i,(i+1)%len(points)) for i in range(len(points))]
    mesh = bpy.data.meshes.new('WGT-'+name); mesh.from_pydata(points,edges,[])
    obj = bpy.data.objects.new(mesh.name, mesh); WIDGETS.objects.link(obj)
    obj.hide_render = True
    return obj

def add_bone(name, matrix, parent=None, length=.1, collection=None):
    bone = RIG.data.edit_bones.new(name)
    # A newly created EditBone has zero length. Its matrix assignment cannot
    # orient that zero vector; establish length before applying the frame.
    bone.length = length; bone.matrix = matrix
    if parent: bone.parent = RIG.data.edit_bones[parent]
    bone.use_deform = False
    if collection: collection.assign(bone)
    return bone

def offset_constraint(owner, target, bone, rest):
    c = owner.constraints.new('CHILD_OF'); c.name = 'Rest calibrated output'
    c.target = target; c.subtarget = bone
    c.owner_space = 'WORLD'; c.target_space = 'WORLD'
    c.inverse_matrix = rest.inverted()
    return c

def make_curve(name, kind, size, group, color=(.9,.7,.15)):
    pb = RIG.pose.bones[name]
    RIG.data.collections['Warlock additions'].assign(pb.bone)
    pb.custom_shape = widget(name,kind); pb.use_custom_shape_bone_size = False
    pb.custom_shape_scale_xyz = (size,size,size)
    pb.color.palette = 'CUSTOM'
    pb.color.custom.normal = color; pb.color.custom.select = (1,.85,.3)
    pb.color.custom.active = (1,1,.65)
    pb.rotation_mode = 'XYZ'
    # Native Rigify ORG channels were protected before promotion. A widget alone
    # must not leave a seemingly usable controller locked in the animator UI.
    pb.lock_location=(False,False,False);pb.lock_rotation=(False,False,False)
    pb.lock_scale=(False,False,False);pb.lock_rotation_w=False;pb.lock_rotations_4d=False
    GROUPS.setdefault(group,[]).append(name)
    return pb

def build(options):
    global RIG, WIDGETS, GROUPS
    root = Path(__file__).resolve().parents[2]
    controls = options.controls.resolve(); body = (root/BODY).resolve()
    out = options.output.resolve()
    if any(part.casefold()=='units' for part in out.parts):
        raise RuntimeError('Authoring output must be outside every production units directory')
    out.mkdir(parents=True,exist_ok=True)
    if controls.parent == out or controls == out/'WarlockEngineer_AnimationRig.blend':
        raise RuntimeError('Build inputs must be distinct from handoff outputs')
    if digest(controls) != READY_SHA:
        raise RuntimeError('Control seed differs from the independently audited Rigify scene')
    bpy.ops.wm.open_mainfile(filepath=str(controls), use_scripts=False)
    RIG = bpy.data.objects['rig_skaven_stormvermin']
    keep = {RIG} | {b.custom_shape for b in RIG.pose.bones if b.custom_shape}
    for obj in list(bpy.data.objects):
        if obj not in keep: bpy.data.objects.remove(obj,do_unlink=True)
    RIG.name = 'WARLOCK_CTRL'; RIG.data.name = 'WARLOCK_CONTROLS'
    # Rigify's FK/IK and mechanism drivers are part of the rig, not an action.
    # Clearing animation_data would silently delete its solver switches.
    if RIG.animation_data:
        RIG.animation_data.action = None
        for track in list(RIG.animation_data.nla_tracks): RIG.animation_data.nla_tracks.remove(track)
    for pb in RIG.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
        for key in pb.keys():
            if key in ('IK_FK','IK_Stretch'): pb[key] = 0.
    for bone in RIG.data.bones: bone.use_deform = False
    # Replace inherited generated UI text with the reviewed optional add-on.
    for text in list(bpy.data.texts): bpy.data.texts.remove(text)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(body),use_anim=False,
        automatic_bone_orientation=False,ignore_leaf_bones=False)
    imported = [o for o in bpy.data.objects if o not in before]
    game = next(o for o in imported if o.type=='ARMATURE')
    game.name = 'WARLOCK_GAME'
    game.animation_data_clear(); game.show_in_front = False
    meshes = [o for o in imported if o.type=='MESH']
    assert len(game.data.bones)==138 and len(meshes)==1 and len(meshes[0].data.vertices)==29123
    for pb in game.pose.bones: pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    signature = [{'name':b.name,'parent':b.parent.name if b.parent else None,
        'rest':matrix_list(b.matrix_local),'inherit_scale':b.inherit_scale} for b in game.data.bones]
    RIG['warlock_game_armature'] = game.name
    RIG['warlock_tools_directory'] = str(out)
    RIG['warlock_rig_version'] = '1.0'
    RIG['engine_boundary'] = 'Authoring controls are never exported. Bake WARLOCK_GAME only.'
    game['source_fbx_sha256'] = digest(body)
    game['original_skeleton'] = json.dumps(signature)
    GROUPS = {'Body':['root','torso','hips','chest','j_spine_ctrl_fk','j_spine1_ctrl_fk'],
        'Arms FK':[], 'Arms IK':[], 'Legs FK':[], 'Legs IK':[], 'Fingers':[],
        'Face':[], 'Tail':[f'j_tail{i}_ctrl' for i in range(1,7)],
        'Twist':[], 'Accessories':[], 'Cloth':[], 'Belt corrections':[], 'Stretch and squash':[]}
    WIDGETS = bpy.data.collections.new('Warlock custom curve widgets')
    bpy.context.scene.collection.children.link(WIDGETS)
    # Existing Rigify controls and separated mechanism chains were behavior-audited.
    for side in ('left','right'):
        for group,bones in (
            ('Arms FK',[f'j_{side}{part}_ctrl_fk' for part in ('arm','forearm','hand')]),
            ('Arms IK',[f'j_{side}hand_ctrl_ik',f'j_{side}arm_ctrl_ik_target']),
            ('Legs FK',[f'j_{side}{part}_ctrl_fk' for part in ('upleg','leg','foot')]),
            ('Legs IK',[f'j_{side}foot_ctrl_ik',f'j_{side}upleg_ctrl_ik_target',f'j_{side}foot_ctrl_heel_ik',f'j_{side}toebase_ctrl'])):
            GROUPS[group].extend(bones)
    # Curve controls for existing previously inert ORG channels.
    bpy.context.view_layer.objects.active = RIG
    RIG.select_set(True); bpy.ops.object.mode_set(mode='EDIT')
    extra = RIG.data.collections.new('Warlock additions')
    mechanisms = RIG.data.collections.new('Warlock extra mechanisms')
    mechanisms.is_visible = False
    finger_records = []
    for side in ('left','right'):
        hand = 'ORG-j_'+side+'hand'
        settings = 'CTRL-hand-settings-'+side
        add_bone(settings,RIG.data.edit_bones[hand].matrix,hand,.07,extra)
        for digit in ('thumb','index','middle','ring','pinky'):
            names = ([f'j_{side}inhandthumb',f'j_{side}handthumb1',f'j_{side}handthumb2'] if digit=='thumb'
                else [f'j_{side}hand{digit}{i}' for i in range(1,4)])
            for segment,original in enumerate(names):
                native = RIG.data.edit_bones['ORG-'+original]
                parent = native.parent.name if native.parent else None
                mch = 'MCH-curl-'+original
                add_bone(mch,native.matrix,parent,.045,mechanisms)
                native.parent = RIG.data.edit_bones[mch]
                finger_records.append((side,digit,segment,native.name,mch,settings))
        forearm = 'ORG-j_'+side+'forearm'; handbone = 'ORG-j_'+side+'hand'
        elbow = RIG.data.edit_bones[forearm].head.copy()
        wrist = RIG.data.edit_bones[handbone].head.copy()
        rotation = (wrist-elbow).to_track_quat('Y','Z').to_matrix().to_4x4()
        rotation.translation = wrist
        add_bone('MCH-wrist-twist-'+side,rotation,forearm,.1,mechanisms)
        rotation.translation = RIG.data.edit_bones['ORG-j_'+side+'forearmroll'].head
        auto = 'MCH-auto-twist-'+side; add_bone(auto,rotation,forearm,.1,mechanisms)
        add_bone('CTRL-forearm-twist-'+side,rotation,auto,.1,extra)
        roll = RIG.data.edit_bones['ORG-j_'+side+'forearmroll']; roll.parent = None
    # Add useful head / neck / accessory curves on the actual native channels.
    bpy.ops.object.mode_set(mode='OBJECT')
    for side in ('left','right'):
        settings = make_curve('CTRL-hand-settings-'+side,'box',.09,'Fingers')
        settings.lock_location=(True,True,True);settings.lock_rotation=(True,True,True);settings.lock_scale=(True,True,True)
        custom_property(settings,'curl',0.,-1.,1.,'All fingers: close/open with individual overrides')
        custom_property(settings,'spread',0.,-1.,1.,'Fan fingers in their calibrated local spaces')
        for digit in ('thumb','index','middle','ring','pinky'):
            custom_property(settings,'curl_'+digit,0.,-1.,1.,'Additive individual finger curl')
        twist = make_curve('CTRL-forearm-twist-'+side,'circle',.075,'Twist')
        twist.lock_location=(True,True,True);twist.lock_rotation=(True,False,True);twist.lock_scale=(True,True,True)
        custom_property(twist,'auto_twist',.5,0.,1.,'Share wrist twist with the existing forearm roll bone')
        wrist_pb = RIG.pose.bones['MCH-wrist-twist-'+side]
        offset_constraint(wrist_pb,RIG,'ORG-j_'+side+'hand',
            RIG.matrix_world @ RIG.data.bones['ORG-j_'+side+'hand'].matrix_local)
        auto_pb = RIG.pose.bones['MCH-auto-twist-'+side]; auto_pb.rotation_mode='XYZ'
        d=driver(auto_pb,'rotation_euler','twist * share',[
            ('share',RIG,f'pose.bones["{twist.name}"]["auto_twist"]')],1)
        v=d.variables.new();v.name='twist';v.type='TRANSFORMS';t=v.targets[0]
        t.id=RIG;t.bone_target=wrist_pb.name;t.transform_type='ROT_Y'
        t.transform_space='LOCAL_SPACE';t.rotation_mode='SWING_TWIST_Y'
        offset_constraint(RIG.pose.bones['ORG-j_'+side+'forearmroll'],RIG,twist.name,
            RIG.matrix_world @ RIG.data.bones[twist.name].matrix_local)
    for side,digit,segment,native,mch,settings in finger_records:
        segment_control=make_curve(native,'circle',.027,'Fingers',(.3,.65,1) if side=='left' else (1,.35,.3))
        segment_control.lock_location=(True,True,True);segment_control.lock_scale=(True,True,True)
        pb=RIG.pose.bones[mch];pb.rotation_mode='XYZ'
        path=f'pose.bones["{settings}"]'
        # Local X is the bend axis; segment controls remain free for correction.
        factor=(.5,.85,1.0)[segment] if digit=='thumb' else (.7,1.,.85)[segment]
        driver(pb,'rotation_euler',f'(curl + individual) * {factor}',[
            ('curl',RIG,path+'["curl"]'),('individual',RIG,path+f'["curl_{digit}"]')],0)
        if segment==0:
            factor={'thumb':-.35,'index':-.25,'middle':0.,'ring':.2,'pinky':.4}[digit]
            driver(pb,'rotation_euler',f'spread * {factor}',[('spread',RIG,path+'["spread"]')],2)
    for name in ('j_neck','j_neck_1','j_head','j_jaw','j_leftear','j_rightear','j_nose',
        'j_lefteyelidtop','j_righteyelidtop','j_lefteyebrow1','j_righteyebrow1'):
        make_curve('ORG-'+name,'circle',.13 if name=='j_head' else .045,'Face')
    make_curve('ORG-j_backpack','box',.28,'Accessories')
    make_curve('ORG-j_leftweaponattach','box',.065,'Accessories')
    # Local stretch/squash on existing native scale channels; positive and bounded.
    # This is kept as real animated bone TRS, not a viewport-only B-Bone effect.
    bpy.ops.object.mode_set(mode='EDIT')
    scale_records=[]
    for name in ('j_spine_scale','j_tail1_scale','j_leftarm_scale','j_rightarm_scale','j_leftupleg_scale','j_rightupleg_scale'):
        org='ORG-'+name; pb=RIG.data.edit_bones[org]
        ctrl='CTRL-shape-'+name
        add_bone(ctrl,pb.matrix,pb.parent.name,.1,extra)
        pb.parent=RIG.data.edit_bones[ctrl]
        scale_records.append((org,ctrl))
    bpy.ops.object.mode_set(mode='OBJECT')
    for org,ctrl in scale_records:
        pb=make_curve(ctrl,'diamond',.07,'Stretch and squash')
        pb.lock_location=(True,True,True);pb.lock_rotation=(True,True,True);pb.lock_scale=(True,True,True)
        custom_property(pb,'length',1.,.75,1.35,'Positive local bone-axis length; bake and roundtrip are required')
        custom_property(pb,'volume',.5,0.,1.,'Transverse volume compensation, independently adjustable per region')
        path=f'pose.bones["{ctrl}"]'
        for axis in (0,2): driver(pb,'scale','length ** (-0.5 * volume)',[
            ('length',RIG,path+'["length"]'),('volume',RIG,path+'["volume"]')],axis)
        driver(pb,'scale','length',[('length',RIG,path+'["length"]')],1)
    # Optional localized re-skinning uses only existing unused game channels.
    corrections = {'enabled':False,'reason':'Shipping skin unchanged'}
    if options.correct_accessories:
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        from accessory_weights import apply_accessory_weights
        corrections = apply_accessory_weights(meshes[0],game)
        bpy.ops.object.mode_set(mode='EDIT')
        for item in corrections['controls']:
            m=Matrix.Identity(4);m.translation=Vector(item['center'])
            add_bone(item['control'],m,'ORG-'+item['follow_bone'],.1,extra)
            RIG.data.edit_bones['ORG-'+item['bone']].parent=None
        bpy.ops.object.mode_set(mode='OBJECT')
        for item in corrections['controls']:
            pb=make_curve(item['control'],'belt' if item['kind']=='belt' else 'cloth',.075,
                'Belt corrections' if item['kind']=='belt' else 'Cloth')
            if item.get('translation_only'): pb.lock_rotation=(True,True,True);pb.lock_scale=(True,True,True)
            else: pb.lock_scale=(True,True,True)
            offset_constraint(RIG.pose.bones['ORG-'+item['bone']],RIG,pb.name,
                RIG.matrix_world @ RIG.data.bones[pb.name].matrix_local)
    # Offset outputs map calibrated control-space transforms to exact GAME rest axes.
    output_data=bpy.data.armatures.new('WARLOCK_OUTPUT_DATA')
    output=bpy.data.objects.new('WARLOCK_OUTPUT',output_data)
    bpy.context.scene.collection.objects.link(output)
    bpy.ops.object.mode_set(mode='OBJECT');bpy.ops.object.select_all(action='DESELECT')
    output.select_set(True);bpy.context.view_layer.objects.active=output
    bpy.ops.object.mode_set(mode='EDIT')
    for bone in game.data.bones:
        b=output_data.edit_bones.new(bone.name)
        b.length=.1;b.matrix=game.matrix_world @ bone.matrix_local;b.use_deform=False
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.update()
    neutral_rig=RIG.evaluated_get(bpy.context.evaluated_depsgraph_get())
    rigid_neutral={}
    for bone in game.data.bones:
        if bone.name=='aim_target': continue
        m=neutral_rig.matrix_world @ neutral_rig.pose.bones['ORG-'+bone.name].matrix
        location,rotation,_=m.decompose()
        rigid_neutral[bone.name]=Matrix.LocRotScale(location,rotation,Vector((1,1,1)))
    for bone in game.data.bones:
        source='ORG-'+bone.name
        # aim_target is a locked engine helper, not an artist look-at control.
        if bone.name=='aim_target':
            root_rest=game.data.bones['root_point'].matrix_local
            desired=root_rest.inverted() @ bone.matrix_local
            desired.translation=Vector((.1,5.,.6))
            game.pose.bones[bone.name].matrix=root_rest @ desired
            continue
        c=offset_constraint(output.pose.bones[bone.name],RIG,source,
            rigid_neutral[bone.name])
        # Rigify's spine solver can introduce small world-space shear even
        # during ordinary continuous torso motion. Export only its position
        # and rotation; anatomical scaling has explicit native local controls.
        c.use_scale_x=False;c.use_scale_y=False;c.use_scale_z=False
    # Resolve world-space solver output on an unchanged hierarchical copy first.
    # GAME receives its actual local TRS, then native local squash/stretch.
    # Applying nonuniform world scales directly would require unexportable shear
    # when child world constraints cancel their parent's scale.
    local_data=game.data.copy();local_data.name='WARLOCK_LOCAL_REFERENCE_DATA'
    local=bpy.data.objects.new('WARLOCK_LOCAL_REFERENCE',local_data)
    bpy.context.scene.collection.objects.link(local);local.matrix_world=game.matrix_world.copy()
    bpy.context.view_layer.update()
    for bone in game.data.bones:
        if bone.name=='aim_target':
            local.pose.bones[bone.name].matrix_basis=game.pose.bones[bone.name].matrix_basis.copy()
            continue
        c=local.pose.bones[bone.name].constraints.new('COPY_TRANSFORMS')
        c.target=output;c.subtarget=bone.name;c.owner_space='WORLD';c.target_space='WORLD'
        c=game.pose.bones[bone.name].constraints.new('COPY_TRANSFORMS')
        c.target=local;c.subtarget=bone.name;c.owner_space='LOCAL';c.target_space='LOCAL'
    for org,ctrl in scale_records:
        weighted=org.removeprefix('ORG-').removesuffix('_scale')
        c=game.pose.bones[weighted].constraints.new('COPY_SCALE');c.name='Native local stretch and squash'
        c.target=RIG;c.subtarget=ctrl;c.owner_space='LOCAL';c.target_space='LOCAL';c.use_offset=True
    local.hide_set(True);local.hide_render=True
    output.hide_set(True);output.hide_render=True;game.hide_set(True)
    # The approved detached launcher/warhead is a posing reference. It follows
    # the visible hand attachment and is excluded from body/animation exports.
    weapon_source=root/'units/rocket/pRocketLauncher.fbx'
    before_weapon=set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(weapon_source),use_anim=False,automatic_bone_orientation=False)
    weapon_objects=[o for o in bpy.data.objects if o not in before_weapon]
    weapon_rig=next(o for o in weapon_objects if o.type=='ARMATURE')
    weapon_rig.name='WARLOCK_LAUNCHER_REFERENCE';weapon_rig.animation_data_clear()
    weapon_rig.matrix_world=Matrix.Identity(4)
    c=weapon_rig.constraints.new('CHILD_OF');c.target=game;c.subtarget='j_leftweaponattach';c.inverse_matrix=Matrix.Identity(4)
    c.use_scale_x=False;c.use_scale_y=False;c.use_scale_z=False
    c.use_rotation_x=False;c.use_rotation_y=False;c.use_rotation_z=False
    weapon_reference_rotation(weapon_rig,game)
    weapon_rig['authoring_reference_only']=True;weapon_rig.hide_set(True)
    for obj in weapon_objects: obj['authoring_reference_only']=True
    WIDGETS.hide_viewport=True
    for obj in keep-{RIG}:
        if obj.name in bpy.context.view_layer.objects: obj.hide_set(True)
    for col in RIG.data.collections:
        if col.name.startswith(('ORG','DEF','MCH')) or col.name=='Warlock extra mechanisms': col.is_visible=False
    defaults={pb.name:{k:pb[k] for k in pb.keys() if isinstance(pb[k],(int,float))}
        for pb in RIG.pose.bones}
    manifest={'schema':1,'version':'1.0','groups':GROUPS,'sources':{
        'controls_file':str(controls),'controls_sha256':digest(controls),
        'body_fbx':str(body),'body_sha256':digest(body),
        'weapon_reference_fbx':str(weapon_source),'weapon_reference_sha256':digest(weapon_source)},'skeleton':signature,
        'corrective_skin':corrections,'engine_helper':{'aim_target':[.1,5.,.6]},
        'export_axes':{'forward':'-Y','up':'Z'},
        'limits':'No new game skeleton bones; B-Bone interpolation and implicit solver scale are not exported. Anatomical scale uses CTRL-shape properties.'}
    RIG['warlock_control_manifest']=json.dumps(manifest)
    RIG['warlock_control_defaults']=json.dumps(defaults)
    scene=bpy.context.scene;scene.render.fps=60;scene.frame_start=1;scene.frame_end=120
    scene.frame_set(1);bpy.context.view_layer.update()
    RIG.show_in_front=True
    bpy.ops.object.select_all(action='DESELECT');RIG.hide_set(False);RIG.select_set(True)
    bpy.context.view_layer.objects.active=RIG;bpy.ops.object.mode_set(mode='POSE')
    for area in bpy.context.screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.region_3d.view_distance=3.5
            area.spaces.active.region_3d.view_location=Vector((0,0,.85))
            area.spaces.active.shading.type='MATERIAL'
    readme=bpy.data.texts.new('START HERE - Warlock animation rig')
    readme.write('Animate WARLOCK_CTRL. Select body-part curves; do not edit WARLOCK_GAME bones.\n'
        'Install or Run Script warlock_rig_ui.py for snap buttons and export.\n'
        'FK/IK: 0 = IK, 1 = FK. Foot heel/toe controls are under Legs IK.\n'
        'Finger curl/spread: CTRL-hand-settings-left/right. Twist: CTRL-forearm-twist-left/right.\n'
        'Stretch/squash: CTRL-shape-* properties length / volume; bounded .75..1.35.\n'
        'Cloth/belt controls change existing geometry through revised weights: body FBX update is required.\n'
        'Use the supplied evaluated-bone exporter, not normal Export All or Apply Pose as Rest.\n'
        'Roundtrip / SDK checks are separate from an in-game visual verdict.\n')
    bpy.context.preferences.filepaths.save_version=0
    path=out/'WarlockEngineer_AnimationRig.blend'
    manifest_path=out/'rig_manifest.json'
    # A rebuild into an existing handoff folder must not erase saved animation
    # work: keep the previous rig and manifest under a timestamped .bak name.
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for previous in (path,manifest_path):
        if previous.exists():
            backup=previous.with_name(previous.name+'.bak.'+stamp)
            if backup.exists(): raise FileExistsError(f'Backup already exists: {backup}')
            previous.rename(backup)
            print('WARLOCK_RIG_PREVIOUS_KEPT',backup)
    bpy.ops.wm.save_as_mainfile(filepath=str(path),check_existing=False,compress=True)
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    print('WARLOCK_RIG_BUILT',path)

if __name__=='__main__':
    argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    parser=argparse.ArgumentParser()
    parser.add_argument('--controls',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--correct-accessories',action='store_true')
    build(parser.parse_args(argv))
