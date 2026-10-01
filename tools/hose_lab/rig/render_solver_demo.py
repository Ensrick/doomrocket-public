"""Drive the real exported rig using recorded Lua physics points; offline only."""
import bpy,json,sys,math
from pathlib import Path
from mathutils import Matrix,Vector
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _paths import resolve_paths
BASE,REPO=resolve_paths(blender=True)
contract=json.loads((BASE/'rig_contract.json').read_text())
trajectory=json.loads((REPO/'.build/hose_solver_probe/trajectory.json').read_text())
bpy.ops.wm.open_mainfile(filepath=str(BASE/'warlock_hose_pose_preview.blend'),use_scripts=False)
rig=bpy.data.objects['warlock_hose_rig'];ob=bpy.data.objects['warlock_hose'];weapon=bpy.data.objects['weapon_reference']
frames=trajectory['frames'];rest_points=[v.co.copy() for v in ob.data.vertices]
expected_lengths=contract['control_rest_lengths_m'];output=BASE/'demo_frames';output.mkdir(exist_ok=True)

def frame(center,tangent,radial):
    y=Vector(tangent).normalized();x=Vector(radial);x=(x-y*x.dot(y)).normalized();z=x.cross(y).normalized();x=y.cross(z).normalized()
    m=Matrix.Identity(4)
    for i in range(3):m[i][0]=x[i];m[i][1]=y[i];m[i][2]=z[i]
    m.translation=Vector(center);return m

scene=bpy.context.scene;scene.render.engine='BLENDER_WORKBENCH';scene.render.image_settings.file_format='PNG'
scene.display.shading.color_type='OBJECT';scene.display.shading.show_cavity=True;scene.display.shading.cavity_type='BOTH'
scene.display.shading.background_type='WORLD';scene.world.color=(.045,.045,.045)
scene.render.resolution_x=1000;scene.render.resolution_y=850;scene.render.resolution_percentage=100
camdata=bpy.data.cameras.new('demo_camera');cam=bpy.data.objects.new('demo_camera',camdata);scene.collection.objects.link(cam);scene.camera=cam
camdata.type='ORTHO';camdata.ortho_scale=3.1;cam.location=(3,2.5,2.0);target=Vector((0,.2,1.05))
cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
for name,text,y,size in [('heading','OFFLINE RIG + LUA PHYSICS',1.13,.056),('caption','Blender demonstration - not in-game acceptance',1.04,.036)]:
    data=bpy.data.curves.new(name,'FONT');data.body=text;data.align_x='CENTER';data.size=size
    label=bpy.data.objects.new(name,data);scene.collection.objects.link(label);label.parent=cam;label.location=(0,y,-4);label.color=(1,1,1,1)
status_data=bpy.data.curves.new('phase','FONT');status_data.align_x='CENTER';status_data.size=.04
status=bpy.data.objects.new('phase',status_data);scene.collection.objects.link(status);status.parent=cam;status.location=(0,-1.15,-4);status.color=(1,1,1,1)

report={'frames':len(frames),'vertices_per_frame':1608,'max_endpoint_error_m':0.,'max_seam_error_m':0.,'max_collar_pair_distance_error_m':0.,'max_lbs_error_m':0.,'max_control_length_error_m':0.}
last_frames=[Matrix(c['frame']) for c in contract['controls']]
for fi,sample in enumerate(frames):
    status_data.body='Weapon moving' if fi<30 else 'Weapon held still - hose continues swinging'
    points=[Vector(p) for p in sample['points']];endframes=[Matrix(m) for m in sample['endpoint_frames']]
    assert len(points)==29
    matrices=[]
    for i,c in enumerate(contract['controls']):
        if i==0:m=endframes[0]
        elif i==28:m=endframes[1]
        else:
            tangent=(points[i+1]-points[i-1]).normalized();previous=last_frames[i]
            swing=previous.to_3x3().col[1].rotation_difference(tangent)
            m=frame(points[i],tangent,swing@previous.to_3x3().col[0])
        m.translation=points[i];rig.pose.bones[c['name']].matrix=m;matrices.append(m)
    last_frames=matrices
    weapon.matrix_world=endframes[1]@Matrix(contract['endpoints']['weapon']['target_canonical_frame_m']).inverted()
    bpy.context.view_layer.update();ev=ob.evaluated_get(bpy.context.evaluated_depsgraph_get());em=ev.to_mesh()
    actual=[v.co.copy() for v in em.vertices];ev.to_mesh_clear()
    transforms=[m@Matrix(c['frame']).inverted() for m,c in zip(matrices,contract['controls'])]
    for vi,p in enumerate(rest_points):
        target=sum((transforms[ci]@p*w for ci,w in contract['weights'][str(vi)]),Vector())
        report['max_lbs_error_m']=max(report['max_lbs_error_m'],(actual[vi]-target).length)
    for a,b in contract['seam_vertex_pairs']:report['max_seam_error_m']=max(report['max_seam_error_m'],(actual[a]-actual[b]).length)
    for collar in contract['collars']:
        ids=[i-3308 for i in collar['source_indices']];anchor=ids[0]
        for i in ids:report['max_collar_pair_distance_error_m']=max(report['max_collar_pair_distance_error_m'],abs((actual[i]-actual[anchor]).length-(rest_points[i]-rest_points[anchor]).length))
    for ring,target in [(contract['sections'][0]['ordered_rings'][0],points[0]),(contract['sections'][-1]['ordered_rings'][-1],points[-1])]:
        center=sum((actual[i-3308] for i in ring),Vector())/len(ring)
        report['max_endpoint_error_m']=max(report['max_endpoint_error_m'],(center-target).length)
    report['max_control_length_error_m']=max(report['max_control_length_error_m'],max(abs((a-b).length-length) for a,b,length in zip(points,points[1:],expected_lengths)))
    scene.render.filepath=str(output/f'{fi:04d}.png');bpy.ops.render.render(write_still=True)
for key in ('max_endpoint_error_m','max_seam_error_m','max_collar_pair_distance_error_m','max_lbs_error_m'):assert report[key]<4e-6,(key,report[key])
report['note']='Actual recorded Lua solver -> original rig weights -> Blender evaluated vertices. No native engine or collision acceptance.'
(BASE/'solver_demo_checks.json').write_text(json.dumps(report,indent=2));print('SOLVER_RIG_DEMO_CHECKS',json.dumps(report))
