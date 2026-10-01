"""Read-only artist topology and cross-section inspection; Blender --disable-autoexec."""
import bpy, json, hashlib, argparse, sys
import numpy as np
from pathlib import Path

import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from _paths import resolve_paths
OUT,REPO=resolve_paths(blender=True)
SOURCE='SM_Skaven_WarlockBombardier_RcoketLauncher'
assert hashlib.sha256(Path(bpy.data.filepath).read_bytes()).hexdigest() == 'ab6ebc9ef45cea6e402bbd0415c2d40716824552c2ab514947902d1eac06c1b2'

def components(mesh, start=0):
    adjacency={i:set() for i in range(start,len(mesh.vertices))}
    for edge in mesh.edges:
        a,b=edge.vertices
        if a in adjacency and b in adjacency:
            adjacency[a].add(b);adjacency[b].add(a)
    output=[]; unseen=set(adjacency)
    while unseen:
        todo=[min(unseen)];seen=set(todo);unseen-=seen
        while todo:
            for i in adjacency[todo.pop()] & unseen:
                unseen.remove(i);seen.add(i);todo.append(i)
        output.append(sorted(seen))
    return output

result={}
for name,start in [(SOURCE,3308),('SM_Skaven_WarlockBombardier_Backpack',0),('SM_Skaven_WarlockBombardier_Tube',0)]:
    obj=bpy.data.objects[name]; mesh=obj.data
    local=np.array([v.co[:] for v in mesh.vertices]); world=np.array([tuple(obj.matrix_world @ v.co) for v in mesh.vertices])
    items=[]
    for indices in components(mesh,start):
        pts=world[indices];center=pts.mean(0);u,s,vt=np.linalg.svd(pts-center,full_matrices=False)
        edges=[tuple(e.vertices) for e in mesh.edges if all(i in indices for i in e.vertices)]
        faces=[list(p.vertices) for p in mesh.polygons if p.vertices[0] in indices]
        edge_counts={tuple(sorted(e)):0 for e in edges}
        for face in faces:
            for a,b in zip(face,face[1:]+face[:1]):edge_counts[tuple(sorted((a,b)))]+=1
        boundary=[list(e) for e,c in edge_counts.items() if c==1]
        item={'indices':indices,'count':len(indices),'center':center.tolist(),'bounds':[pts.min(0).tolist(),pts.max(0).tolist()],
              'pca_axes':vt.tolist(),'singular_values':s.tolist(),'boundary':boundary,'polygons':faces}
        items.append(item)
    result[name]={'world':[[float(x) for x in r] for r in obj.matrix_world], 'local':local.tolist(),'points':world.tolist(),'components':items,
        'materials':[m.name for m in mesh.materials], 'parent':obj.parent.name if obj.parent else None,
        'groups':[g.name for g in obj.vertex_groups]}
    print(name, 'components',len(items))
    if start:
        for c in items: print(c['indices'][0],c['count'],'center',c['center'],'sv',c['singular_values'],'boundary',len(c['boundary']))
(OUT/'topology.json').write_text(json.dumps(result,indent=2))
