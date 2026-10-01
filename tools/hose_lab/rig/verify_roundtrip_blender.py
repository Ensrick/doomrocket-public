"""FBX importer/rest-bind and deformed-vertex equivalence tests, read-only."""
import bpy,json,math
from pathlib import Path
from mathutils import Matrix,Vector
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _paths import resolve_paths
BASE,REPO=resolve_paths(blender=True)
c=json.loads((BASE/'rig_contract.json').read_text());topology=json.loads((BASE/'topology.json').read_text())
expected=[Vector(p) for p in topology[c['source_mesh']]['points'][3308:]]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(BASE/'warlock_hose.fbx'),use_anim=False)
rig=next(o for o in bpy.data.objects if o.type=='ARMATURE');mesh=next(o for o in bpy.data.objects if o.type=='MESH')
assert len(bpy.data.objects)==2 and len(rig.data.bones)==30
frame_error=0.
for control in c['controls']:
    actual=rig.matrix_world@rig.data.bones[control['name']].matrix_local
    frame_error=max(frame_error,max(abs(actual[r][col]-control['frame'][r][col]) for r in range(4) for col in range(4)))
assert frame_error<4e-6

def evaluated_points():
    bpy.context.view_layer.update();ev=mesh.evaluated_get(bpy.context.evaluated_depsgraph_get());em=ev.to_mesh()
    points=[ev.matrix_world@v.co for v in em.vertices];ev.to_mesh_clear();return points

rest_error=max((a-b).length for a,b in zip(evaluated_points(),expected));assert rest_error<4e-6
max_error=0.;seam_error=0.;collar_error=0.
for trial in range(3):
    transforms={}
    for ci,control in enumerate(c['controls']):
        rest=Matrix(control['frame']);angle=math.sin(ci*.35+trial)*(.25+.1*trial)
        desired=Matrix.Translation(Vector((.01*math.sin(ci+trial),.03*math.sin(ci*.2),.04*math.cos(ci*.2+trial))))@rest@Matrix.Rotation(angle,4,'X')
        rig.pose.bones[control['name']].matrix=rig.matrix_world.inverted()@desired
        transforms[ci]=desired@rest.inverted()
    actual=evaluated_points()
    for vi,base in enumerate(expected):
        target=sum((transforms[ci]@base*w for ci,w in c['weights'][str(vi)]),Vector())
        max_error=max(max_error,(actual[vi]-target).length)
    for a,b in c['seam_vertex_pairs']:seam_error=max(seam_error,(actual[a]-actual[b]).length)
    for collar in c['collars']:
        ids=[i-3308 for i in collar['source_indices']];anchor=ids[0]
        for i in ids:collar_error=max(collar_error,abs((actual[i]-actual[anchor]).length-(expected[i]-expected[anchor]).length))
assert max_error<4e-6 and seam_error<4e-6 and collar_error<4e-6
result={'trials':3,'controls':29,'vertices_per_trial':1608,'rest_frame_max_component_error':frame_error,
    'rest_vertex_error_m':rest_error,'deformed_lbs_max_error_m':max_error,'deformed_seam_max_error_m':seam_error,'rigid_collar_distance_error_m':collar_error}
(BASE/'roundtrip_checks.json').write_text(json.dumps(result,indent=2))
print('FBX_ROUNDTRIP_CHECKS',json.dumps(result))
