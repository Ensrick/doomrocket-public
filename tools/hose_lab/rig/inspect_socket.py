import bpy,json,numpy as np,argparse,sys
from pathlib import Path
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _paths import resolve_paths
BASE,REPO=resolve_paths(blender=True)
obj=bpy.data.objects['SM_Skaven_WarlockBombardier_RcoketLauncher'];mesh=obj.data
points=np.array([tuple(obj.matrix_world@v.co) for v in mesh.vertices])
faces=[list(p.vertices) for p in mesh.polygons if 1641<=p.vertices[0]<1858]
adj={i:set() for i in range(1641,1858)}
for face in faces:
    for a,b in zip(face,face[1:]+face[:1]):adj[a].add(b);adj[b].add(a)
for i in [1749,1750,1751,1752,1761,1762,1763,1772,1773,1774,1775,1776,1797,1809,1810,1857]:
    print(i,'neighbors',sorted(adj[i]),'faces',[f for f in faces if i in f])
ring=[1749,1750,1751,1752,1761,1762,1763,1772,1773,1774,1775,1776]
pts=points[ring];center=pts.mean(0);u,s,vt=np.linalg.svd(pts-center,full_matrices=False);n=vt[-1]
if n[2]>0:n=-n
print('mouth',center,'normal out',n,'singular',s,'radii',np.linalg.norm(pts-center,axis=1))
result={'ring_indices':ring,'center':center.tolist(),'outward_normal':n.tolist(),'radii':np.linalg.norm(pts-center,axis=1).tolist(),
    'planarity_max':float(np.max(np.abs((pts-center)@n))),'pocket_cap':points[1809].tolist(),'depth':float((points[1809]-center)@(-n))}
(BASE/'socket.json').write_text(json.dumps(result,indent=2))
vertices=points[:3308].tolist();polygons=[tuple(p.vertices) for p in mesh.polygons if max(p.vertices)<3308]
bpy.ops.wm.read_factory_settings(use_empty=True)
mesh=bpy.data.meshes.new('socket_review');mesh.from_pydata(vertices,[],polygons)
ob=bpy.data.objects.new('socket_review',mesh);bpy.context.collection.objects.link(ob);ob.color=(.6,.6,.6,1)
center=Vector(center);normal=Vector(n)
bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8,radius=.004,location=center);bpy.context.object.color=(1,.1,.05,1)
bpy.ops.mesh.primitive_cylinder_add(vertices=12,radius=.0015,depth=.15,location=center+normal*.075)
bpy.context.object.rotation_euler=normal.to_track_quat('Z','Y').to_euler();bpy.context.object.color=(.05,1,.1,1)
for p in pts:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=8,ring_count=4,radius=.002,location=p);bpy.context.object.color=(1,.3,.05,1)
scene=bpy.context.scene;scene.render.image_settings.file_format='PNG';scene.render.engine='BLENDER_WORKBENCH';scene.display.shading.color_type='OBJECT';scene.display.shading.show_cavity=True
scene.display.shading.cavity_type='BOTH';scene.render.resolution_x=1000;scene.render.resolution_y=1000;scene.render.resolution_percentage=100
camdata=bpy.data.cameras.new('camera');cam=bpy.data.objects.new('camera',camdata);scene.collection.objects.link(cam);scene.camera=cam
camdata.type='ORTHO';camdata.ortho_scale=.4
for name,pos in [('socket_close',center+Vector((.25,.25,-.4))),('socket_context',center+Vector((1,-.7,-.6)))]:
    if name=='socket_context':camdata.ortho_scale=1.9
    cam.location=pos;cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler();scene.render.filepath=str(BASE/(name+'.png'))
    bpy.ops.render.render(write_still=True)
