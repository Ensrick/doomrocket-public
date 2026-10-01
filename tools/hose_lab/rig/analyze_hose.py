"""Derive rings using mesh topology, not vertex number or a guessed centreline."""
import json,argparse
import numpy as np
from pathlib import Path
from _paths import resolve_paths
BASE,REPO=resolve_paths()
data=json.loads((BASE/'topology.json').read_text())
hose=data['SM_Skaven_WarlockBombardier_RcoketLauncher'];points=np.array(hose['points'])
backpack=data['SM_Skaven_WarlockBombardier_Backpack'];bp=np.array(backpack['points'])

def loops(edges):
    adj={}
    for a,b in edges:adj.setdefault(a,set()).add(b);adj.setdefault(b,set()).add(a)
    assert all(len(n)==2 for n in adj.values())
    result=[];unseen=set(adj)
    while unseen:
        seed=min(unseen);ring=[seed];previous=None;current=seed
        while True:
            following=min(adj[current]-{previous})
            if following==seed:break
            ring.append(following);previous,current=current,following
        result.append(ring);unseen-=set(ring)
    return result

output=[]
for component in hose['components']:
    if component['count']!=180:continue
    boundaries=loops(component['boundary']);assert [len(x) for x in boundaries]==[12,12]
    adjacency={i:set() for i in component['indices']}
    for face in component['polygons']:
        assert len(face)==4
        for a,b in zip(face,face[1:]+face[:1]):adjacency[a].add(b);adjacency[b].add(a)
    rings=[boundaries[0]];visited=set(rings[0])
    while len(visited)<180:
        following=[list(adjacency[i]-visited) for i in rings[-1]]
        assert all(len(x)==1 for x in following)
        ring=[x[0] for x in following];assert len(set(ring))==12
        rings.append(ring);visited.update(ring)
    assert set(rings[-1])==set(boundaries[1]);assert len(rings)==15
    centers=np.array([points[r].mean(0) for r in rings]);lengths=np.linalg.norm(np.diff(centers,axis=0),axis=1)
    print('SECTION',component['indices'][0],'centers',centers[0],centers[-1],'length',sum(lengths))
    endpoints=[]
    for ri in [0,14]:
        ring=rings[ri];pts=points[ring];center=centers[ri]
        _,singular,axes=np.linalg.svd(pts-center,full_matrices=False)
        normal=axes[-1];outward=centers[0]-centers[1] if ri==0 else centers[-1]-centers[-2]
        if normal@outward<0:normal=-normal
        near=np.linalg.norm(bp-center,axis=1);nearest=int(near.argmin())
        rigidnear=np.linalg.norm(points[:3308]-center,axis=1);rigidnearest=int(rigidnear.argmin())
        print(' endpoint',ri,'normal',normal,'planarity',singular[-1], 'bpnearest',nearest,near[nearest],'rigid',rigidnearest,rigidnear[rigidnearest])
        endpoints.append({'ring':ring,'center':center.tolist(),'outward_normal':normal.tolist(),'planarity_singular':float(singular[-1]),
            'nearest_backpack_vertex':nearest,'distance_backpack':float(near[nearest]),'nearest_rigid_vertex':rigidnearest,'distance_rigid':float(rigidnear[rigidnearest])})
    output.append({'start':component['indices'][0],'rings':rings,'centers':centers.tolist(),'length':float(sum(lengths)),'endpoints':endpoints})

for si,section in enumerate(output):
    for ei,end in enumerate(section['endpoints']):
        nearest=sorted((float(np.linalg.norm(np.array(end['center'])-e2['center'])),sj,ej)
            for sj,s2 in enumerate(output) if sj!=si for ej,e2 in enumerate(s2['endpoints']))
        print('END MATCH',si,ei,nearest[:2])
(BASE/'sections.json').write_text(json.dumps(output,indent=2))
