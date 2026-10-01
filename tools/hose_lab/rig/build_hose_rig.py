"""Isolated rig candidate. Run on the SHA-pinned artist scene, --disable-autoexec.

Never saves source art or writes shipping resources. No actors, live engine,
animation controller, constraint bytes or physics implementation are included.
"""
import bpy,bmesh,json,hashlib,math,sys,argparse
import numpy as np
from pathlib import Path
from mathutils import Vector,Matrix

sys.path.insert(0,str(Path(__file__).resolve().parent))
from _paths import resolve_paths
BASE,REPO=resolve_paths(blender=True)
SOURCE_SHA='ab6ebc9ef45cea6e402bbd0415c2d40716824552c2ab514947902d1eac06c1b2'
source_path=Path(bpy.data.filepath)
assert hashlib.sha256(source_path.read_bytes()).hexdigest()==SOURCE_SHA
source=bpy.data.objects['SM_Skaven_WarlockBombardier_RcoketLauncher']
backpack=bpy.data.objects['SM_Skaven_WarlockBombardier_Backpack']
sections=json.loads((BASE/'sections.json').read_text())
topology=json.loads((BASE/'topology.json').read_text())
socket=json.loads((BASE/'socket.json').read_text())
assert len(source.data.vertices)==4916 and len(source.data.polygons)==4973
assert not source.parent and not source.vertex_groups and not source.modifiers
assert [len(s['rings']) for s in sections]==[15]*7
grip=Vector((-0.00002098033,-0.91097664833,0.06153465062))
points=[source.matrix_world@v.co for v in source.data.vertices]
source_world=source.matrix_world.copy();backpack_world=backpack.matrix_world.copy()

def make_frame(center,tangent,radial):
    y=Vector(tangent).normalized();x=Vector(radial);x=(x-y*x.dot(y)).normalized()
    z=x.cross(y).normalized();x=y.cross(z).normalized()
    m=Matrix.Identity(4)
    for i in range(3):m[i][0]=x[i];m[i][1]=y[i];m[i][2]=z[i]
    m.translation=Vector(center)
    return m

# Reverse each section to follow the measured pack -> weapon direction.
# Corresponding open rings are merged by identity within 0.5 micrometres.
all_rings=[];control_ids=[];section_records=[];ring_positions={}
for si,section in enumerate(sections):
    rings=list(reversed(section['rings']));centers=[sum((points[i] for i in r),Vector())/12 for r in rings]
    ids=[]
    for ri,(ring,center) in enumerate(zip(rings,centers)):
        if si and ri==0:
            idx=len(all_rings)-1
            assert (center-Vector(all_rings[-1]['center'])).length<5e-7
            all_rings[-1]['source_indices'].extend(ring)
        else:
            idx=len(all_rings);all_rings.append({'source_indices':list(ring),'center':list(center)})
        ids.append(idx)
        for vi in ring:ring_positions[vi]=(si,ri)
        if ri in (0,4,7,10,14) and idx not in control_ids:control_ids.append(idx)
    section_records.append({'source_start':section['start'],'ordered_rings':rings,'global_ring_indices':ids})
assert len(all_rings)==99 and len(control_ids)==29
for ri,ring in enumerate(all_rings):
    pts=np.array([tuple(points[i]) for i in ring['source_indices'][:12]])
    _,sv,vt=np.linalg.svd(pts-np.array(ring['center']),full_matrices=False)
    tangent=Vector(all_rings[min(98,ri+1)]['center'])-Vector(all_rings[max(0,ri-1)]['center'])
    normal=Vector(vt[-1]);normal=normal if normal.dot(tangent)>0 else -normal
    radial=points[ring['source_indices'][0]]-Vector(ring['center'])
    ring['frame']=[list(r) for r in make_frame(ring['center'],normal,radial)]

controls=[{'name':f'j_hose_{i:02d}','ring_index':ri,'frame':all_rings[ri]['frame']} for i,ri in enumerate(control_ids)]
weights={}
arc=[0.0]
for a,b in zip(all_rings,all_rings[1:]):arc.append(arc[-1]+(Vector(a['center'])-Vector(b['center'])).length)
for ri,ring in enumerate(all_rings):
    if ri in control_ids:influences=[(control_ids.index(ri),1.0)]
    else:
        hi=next(i for i,x in enumerate(control_ids) if x>ri);lo=hi-1
        t=(arc[ri]-arc[control_ids[lo]])/(arc[control_ids[hi]]-arc[control_ids[lo]])
        influences=[(lo,1-t),(hi,t)]
    for vi in ring['source_indices']:weights[vi-3308]=influences
collars=[]
for comp in topology[source.name]['components']:
    if comp['count']==180:continue
    center=Vector(comp['center'])
    options=sorted(((center-Vector(all_rings[ri]['center'])).length,ci,ri) for ci,ri in enumerate(control_ids) if ri in (14,28,42,56,70,84))
    dist,ci,ri=options[0];assert dist<.005 and options[1][0]>.25
    for vi in comp['indices']:weights[vi-3308]=[(ci,1.0)]
    collars.append({'source_indices':comp['indices'],'control':controls[ci]['name'],'ring_index':ri,'center_distance_m':dist})
assert set(weights)==set(range(1608));assert len(collars)==6

mesh=source.data.copy();mesh.transform(source_world)
bm=bmesh.new();bm.from_mesh(mesh);bm.verts.ensure_lookup_table()
bmesh.ops.delete(bm,geom=list(bm.verts[:3308]),context='VERTS');bm.to_mesh(mesh);bm.free();mesh.update()
assert len(mesh.vertices)==1608 and len(mesh.polygons)==1608
assert max((v.co-points[v.index+3308]).length for v in mesh.vertices)<5e-7
source_faces=[p for p in source.data.polygons if min(p.vertices)>=3308]
for old,new in zip(source_faces,mesh.polygons):
    assert list(new.vertices)==[i-3308 for i in old.vertices]
    assert old.material_index==new.material_index
    for before,after in zip(old.loop_indices,new.loop_indices):
        assert tuple(source.data.uv_layers.active.data[before].uv)==tuple(mesh.uv_layers.active.data[after].uv)

# Store small reference copies before clearing the artist scene from memory.
bp_vertices=[tuple(backpack.matrix_world@v.co) for v in backpack.data.vertices]
bp_faces=[tuple(p.vertices) for p in backpack.data.polygons]
weapon_vertices=[tuple(p+grip) for p in points[:3308]]
weapon_faces=[tuple(p.vertices) for p in source.data.polygons if max(p.vertices)<3308]
bp_center_local=backpack.data.vertices[5426].co.copy()*.01

for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
for action in list(bpy.data.actions):bpy.data.actions.remove(action)
for text in list(bpy.data.texts):bpy.data.texts.remove(text)
rig_data=bpy.data.armatures.new('warlock_hose_rig');rig=bpy.data.objects.new('warlock_hose_rig',rig_data)
bpy.context.scene.collection.objects.link(rig);bpy.context.view_layer.objects.active=rig;rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
root=rig_data.edit_bones.new('hose_root');root.head=(0,0,0);root.tail=(0,.1,0);root.use_deform=False
for control in controls:
    bone=rig_data.edit_bones.new(control['name']);bone.parent=root;bone.use_connect=False
    frame=Matrix(control['frame']);bone.head=frame.translation;bone.tail=frame.translation+frame.to_3x3().col[1]*.045
    bone.matrix=frame
bpy.ops.object.mode_set(mode='OBJECT');rig.show_in_front=True
ob=bpy.data.objects.new('warlock_hose',mesh);bpy.context.scene.collection.objects.link(ob);ob.parent=rig
ob.matrix_parent_inverse=Matrix.Identity(4);ob.matrix_local=Matrix.Identity(4)
for control in controls:ob.vertex_groups.new(name=control['name'])
for vi,influences in weights.items():
    for ci,w in influences:ob.vertex_groups[ci].add([vi],w,'REPLACE')
modifier=ob.modifiers.new('Hose skin only','ARMATURE');modifier.object=rig
modifier.use_deform_preserve_volume=False
rig['prototype_only']=True;rig['simulation']='NONE: static deform rig, awaiting separate validated solver'
rig['endpoint_review']='Weapon grip-base inlet inferred from geometry fit; not artist-confirmed.'
rig['coordinate_contract']='Identity object transforms; Blender metres, same Y-forward/Z-up FBX export convention as accepted weapon.'
for c in controls:
    actual=rig_data.bones[c['name']].matrix_local
    error=max(abs(actual[i][j]-c['frame'][i][j]) for i in range(4) for j in range(4))
    if error>=2e-6:print('BONE_FRAME_ERROR',c['name'],error,'actual',actual,'expected',Matrix(c['frame']))
    assert error<2e-6

def hash_file(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def export(path):
    bpy.ops.object.select_all(action='DESELECT');rig.select_set(True);ob.select_set(True);bpy.context.view_layer.objects.active=rig
    bpy.ops.export_scene.fbx(filepath=str(path),use_selection=True,object_types={'ARMATURE','MESH'},add_leaf_bones=False,bake_anim=False,
        use_armature_deform_only=False,axis_forward='Y',axis_up='Z',use_mesh_modifiers=False)

# The independent mesh rest pose is the untouched artist hose in Blender metres,
# not translated into the rigid weapon grip frame. A solver drives each control.
for datablocks in (bpy.data.meshes,bpy.data.armatures,bpy.data.actions,bpy.data.materials,bpy.data.images):
    for item in list(datablocks):
        if item.users==1 and item.use_fake_user:item.use_fake_user=False
bpy.data.orphans_purge(do_local_ids=True,do_linked_ids=True,do_recursive=True)
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(BASE/'warlock_hose_rig.blend'),check_existing=False,compress=True)
export(BASE/'warlock_hose.fbx')
expected_positions=np.array([tuple(v.co) for v in mesh.vertices])
expected_weights={vi:list(inf) for vi,inf in weights.items()}

# Rest-pose skin and seam consistency checks run in Blender, not only algebra.
dg=bpy.context.evaluated_depsgraph_get();evaluated=ob.evaluated_get(dg);evaluated_mesh=evaluated.to_mesh()
rest_error=max((evaluated_mesh.vertices[i].co-mesh.vertices[i].co).length for i in range(1608));evaluated.to_mesh_clear()
assert rest_error<2e-6
seam_pairs=[]
for si in range(6):
    left=section_records[si]['ordered_rings'][-1];right=section_records[si+1]['ordered_rings'][0]
    for a in left:
        b=min(right,key=lambda i:(points[a]-points[i]).length)
        assert (points[a]-points[b]).length<5e-7 and weights[a-3308]==weights[b-3308]
        seam_pairs.append((a-3308,b-3308))

# Derive endpoint local frames against shipping FBX/compiled-node contracts.
fixture=json.loads((REPO/'tools/fixtures/warlock_chimney_anchor.json').read_text())
bind=Matrix(fixture['compiled_inverse_bind_column_matrix'])
pack_frame_source=Matrix(controls[0]['frame'])
body_world_to_mesh=Matrix.Scale(.01,4)@backpack_world.inverted()
pack_local=bind@body_world_to_mesh@pack_frame_source
pack_local.translation=bind@bp_center_local
socket_out=Vector(socket['outward_normal'])
socket_center=Vector(socket['center'])+grip-socket_out*.001
weapon_frame=make_frame(socket_center,-socket_out,Vector((1,0,0)))

compiled_weapon=json.loads((BASE/'compiled_weapon_node.json').read_text())
weapon_node_world=Matrix(compiled_weapon['world'])
weapon_local=weapon_node_world.inverted()@weapon_frame

contract={'schema':1,'prototype_only':True,'source_scene_sha256':SOURCE_SHA,
    'source_mesh':'SM_Skaven_WarlockBombardier_RcoketLauncher','source_hose_vertex_range':[3308,4915],
    'geometry_vertices':1608,'geometry_polygons':1608,'material':'DoomRocket_Weapon','units':'metres',
    'fbx_axes':{'axis_forward':'Y','axis_up':'Z'},'bind_shape':'Unmodified source-world hose; not the detached rigid launcher grip bake.',
    'hierarchy':'hose_root with 29 sibling deform bones; ordered chain below is the solver topology, not an engine physics actor chain.',
    'bone_axis_convention':'Column-vector matrices; +Y tangent pack-to-weapon, +X radial; explicit local inverse bind required after SDK compile.',
    'controls':controls,'control_rest_lengths_m':[(Vector(a['frame'][r][3] for r in range(3))-Vector(b['frame'][r][3] for r in range(3))).length for a,b in zip(controls,controls[1:])],
    'source_ring_arc_length_m':arc[-1], 'sections':section_records,'collars':collars,'seam_vertex_pairs':seam_pairs,
    'weights':{str(k):v for k,v in weights.items()},
    'endpoints':{'pack':{'bone':'j_hose_00','target_resource':'units/warlock_bombardier/warlock_bombardier_3p','target_node':'j_backpack',
        'source_cap_vertex':5426,'source_cap_mesh_cm':list(bp_center_local*100),
        'source_world_frame':controls[0]['frame'],'target_local_frame':[list(r) for r in pack_local],
        'body_fbx_sha256':fixture['shipping_fbx_sha256'],'body_unit_sha256':fixture['compiled_unit_sha256'],
        'evidence':'Authored hose end coincides with rigid j_backpack-weighted cap center within 0.23 micrometres.'},
      'weapon':{'bone':'j_hose_28','target_resource':'units/rocket/pRocketLauncher','target_node':'pRocketLauncher',
        'socket_ring_source_indices':socket['ring_indices'],'socket_source_world_center':socket['center'],'socket_outward_normal':socket['outward_normal'],
        'insertion_m':.001,'inference':'Lower cylindrical grip-base inlet inferred from radius/orientation/visible geometry. Not artist-confirmed.',
        'target_canonical_frame_m':[list(r) for r in weapon_frame],'target_local_frame':[list(r) for r in weapon_local],
        'weapon_fbx_sha256':hash_file(REPO/'units/rocket/pRocketLauncher.fbx'),'weapon_unit_sha256':compiled_weapon['sha256']}},
    'offline_checks':{'rest_skin_max_error_m':rest_error,'geometry_uv_material_identity':True,'seam_weights_identical':True,'actors':0},
    'outputs':{'fbx_sha256':hash_file(BASE/'warlock_hose.fbx'),'blend_sha256':hash_file(BASE/'warlock_hose_rig.blend')}}
(BASE/'rig_contract.json').write_text(json.dumps(contract,indent=2))
print('RIG_EXPORTED',json.dumps({'vertices':1608,'bones':len(rig.data.bones),'rest_error_m':rest_error,'arc_length_m':arc[-1],'output':str(BASE/'warlock_hose.fbx')}))

# Static pose demo only: a clear explicit weapon world transform independent of
# an artist hand-bone inverse. Keeps source geometry/UVs and all cap meshes.
preview_weapon_world=Matrix.Translation(Vector((0,.95,1.15)))
weapon_target=preview_weapon_world@weapon_frame
control_pos=np.array([[c['frame'][r][3] for r in range(3)] for c in controls])
original_pos=control_pos.copy();target_start=control_pos[0].copy();target_end=np.array(weapon_target.translation)
lengths=np.array(contract['control_rest_lengths_m'])
fractions=np.linspace(0,1,len(control_pos));control_pos+=(target_end-control_pos[-1])[None,:]*fractions[:,None]
# Offline projection to a static preview, not claimed to be a physics solver.
for iteration in range(3000):
    control_pos[0]=target_start;control_pos[-1]=target_end
    for i in range(len(lengths)):
        d=control_pos[i+1]-control_pos[i];size=np.linalg.norm(d);correction=d*((size-lengths[i])/size)
        if i==0:control_pos[i+1]-=correction
        elif i==len(lengths)-1:control_pos[i]+=correction
        else:control_pos[i]+=.5*correction;control_pos[i+1]-=.5*correction
control_pos[0]=target_start;control_pos[-1]=target_end
max_length_error=float(max(abs(np.linalg.norm(np.diff(control_pos,axis=0),axis=1)-lengths)))
assert max_length_error<1e-5
for i,c in enumerate(controls):
    if i==0:m=Matrix(c['frame']);m.translation=Vector(control_pos[i])
    elif i==28:m=weapon_target
    else:
        tangent=Vector(control_pos[min(28,i+1)]-control_pos[max(0,i-1)])
        old=Matrix(c['frame']);old_y=old.to_3x3().col[1]
        rotation=old_y.rotation_difference(tangent.normalized());radial=rotation@old.to_3x3().col[0]
        m=make_frame(control_pos[i],tangent,radial)
    rig.pose.bones[c['name']].matrix=m
bpy.context.view_layer.update()
evaluated=ob.evaluated_get(bpy.context.evaluated_depsgraph_get());em=evaluated.to_mesh()
seam_error=max((em.vertices[a].co-em.vertices[b].co).length for a,b in seam_pairs)
collar_error=0.0
for collar in collars:
    ids=[i-3308 for i in collar['source_indices']];origin=ids[0]
    for i in ids:
        collar_error=max(collar_error,abs((em.vertices[i].co-em.vertices[origin].co).length-(mesh.vertices[i].co-mesh.vertices[origin].co).length))
assert seam_error<3e-6 and collar_error<3e-6
endpoint_error=max((sum((em.vertices[i-3308].co for i in all_rings[ri]['source_indices']),Vector())/len(all_rings[ri]['source_indices'])-Vector(target)).length for ri,target in [(0,target_start),(98,target_end)])
assert endpoint_error<3e-6
evaluated.to_mesh_clear()
for name,vertices,faces,transform in [('backpack_reference',bp_vertices,bp_faces,Matrix.Identity(4)),('weapon_reference',weapon_vertices,weapon_faces,preview_weapon_world)]:
    refmesh=bpy.data.meshes.new(name);refmesh.from_pydata(vertices,[],faces)
    ref=bpy.data.objects.new(name,refmesh);bpy.context.scene.collection.objects.link(ref);ref.matrix_world=transform;ref.color=(.4,.4,.4,1)
ob.color=(.2,.65,.9,1)
bpy.ops.wm.save_as_mainfile(filepath=str(BASE/'warlock_hose_pose_preview.blend'),check_existing=False,compress=True)
scene=bpy.context.scene;scene.render.engine='BLENDER_WORKBENCH';scene.display.shading.color_type='OBJECT';scene.display.shading.show_cavity=True
scene.render.image_settings.file_format='PNG'
scene.display.shading.cavity_type='BOTH';scene.render.resolution_x=1100;scene.render.resolution_y=1100;scene.render.resolution_percentage=100
camdata=bpy.data.cameras.new('preview_camera');cam=bpy.data.objects.new('preview_camera',camdata);scene.collection.objects.link(cam);scene.camera=cam
camdata.type='ORTHO';camdata.ortho_scale=2.5;target=Vector((0,.15,1.0));cam.location=(3,2.5,2.0)
cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();scene.render.filepath=str(BASE/'rig_pose_preview.png');bpy.ops.render.render(write_still=True)
contract['offline_checks'].update({'preview_control_length_max_error_m':max_length_error,'preview_seam_max_error_m':seam_error,
    'preview_collar_pair_distance_max_error_m':collar_error,'preview_endpoint_max_error_m':endpoint_error})
contract['preview_weapon_world']=[list(r) for r in preview_weapon_world]
contract['preview_note']='Illustrative manually selected weapon pose, not game animation acceptance. Static projection only; no inertial simulation.'
(BASE/'rig_contract.json').write_text(json.dumps(contract,indent=2))
compact={k:v for k,v in contract.items() if k not in ('weights','sections','collars','seam_vertex_pairs')}
(BASE/'runtime_contract.json').write_text(json.dumps(compact,separators=(',',':')))
print('RIG_CHECKS',json.dumps(contract['offline_checks']))
assert hash_file(source_path)==SOURCE_SHA
