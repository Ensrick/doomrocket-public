"""Independent source/FBX contract checks; no Blender or SDK needed."""
import hashlib,json,sys,unittest
from pathlib import Path
import numpy as np
from _paths import resolve_paths
BASE,REPO=resolve_paths()
sys.path.insert(0,str(REPO/'tools/tests'))
from test_warlock_weapon_pipeline import (BinaryFbx,geometry_by_vertex_count,canonical_geometry_points,source_points_to_engine,
    uv_sets_by_vertex,model_names,model_parent_ids,clean_fbx_name,material_names)
from test_doomrocket_chimney_anchor import fbx_positive_weights
contract=json.loads((BASE/'rig_contract.json').read_text());topology=json.loads((BASE/'topology.json').read_text())
fbx=BinaryFbx(BASE/'warlock_hose.fbx');geo=geometry_by_vertex_count(fbx,1608)
actual=np.array(source_points_to_engine(canonical_geometry_points(fbx,1608)))
source=np.array(topology[contract['source_mesh']]['points'][3308:])
weights=fbx_positive_weights(fbx,geo,range(1608))

class HoseFbxChecks(unittest.TestCase):
    def test_frozen_fbx_hash(self):
        self.assertEqual(hashlib.sha256((BASE/'warlock_hose.fbx').read_bytes()).hexdigest(),contract['outputs']['fbx_sha256'])
    def test_world_axis_scale_and_positions_match_source(self):
        self.assertLess(float(np.linalg.norm(actual-source,axis=1).max()),1e-6)
    def test_material_and_uvs_unchanged(self):
        source_fbx=BinaryFbx(REPO.parent/'_warlock_bombardier_art/warlock_rocketlauncher.fbx')
        source_geo=geometry_by_vertex_count(source_fbx,4916)
        self.assertEqual(uv_sets_by_vertex(geo),uv_sets_by_vertex(source_geo)[3308:])
        self.assertEqual(material_names(fbx),{'DoomRocket_Weapon'})
    def test_only_independent_flat_hose_nodes(self):
        expected={'warlock_hose_rig','hose_root','warlock_hose'}|{c['name'] for c in contract['controls']}
        self.assertEqual(model_names(fbx),expected)
        models={n.properties[0]:clean_fbx_name(n.properties[1]) for n in fbx.object_nodes('Model')}
        parents={n.properties[1]:n.properties[2] for n in fbx.descendants('C') if n.properties[0]=='OO' and n.properties[1] in models and n.properties[2] in models}
        for identifier,name in models.items():
            if name.startswith('j_hose_'):self.assertEqual(models[parents[identifier]],'hose_root')
    def test_exported_weights_exact_recipe_and_normalized(self):
        for vi,inf in weights.items():
            expected=[(contract['controls'][ci]['name'],w) for ci,w in contract['weights'][str(vi)]]
            self.assertEqual([n for n,w in inf],[n for n,w in expected])
            self.assertLessEqual(len(inf),2);self.assertAlmostEqual(sum(w for n,w in inf),1,delta=1e-7)
            for (n,w),(n2,w2) in zip(inf,expected):self.assertAlmostEqual(w,w2,delta=1e-7)
    def test_all_six_collars_rigid_and_seams_coincident(self):
        for c in contract['collars']:
            for vi in c['source_indices']:self.assertEqual(weights[vi-3308],[(c['control'],1.)])
        for a,b in contract['seam_vertex_pairs']:
            self.assertLess(float(np.linalg.norm(actual[a]-actual[b])),1e-6);self.assertEqual(weights[a],weights[b])
    def test_actual_nonuniform_rest_lengths(self):
        centers=np.array([[c['frame'][r][3] for r in range(3)] for c in contract['controls']])
        lengths=np.linalg.norm(np.diff(centers,axis=0),axis=1)
        self.assertLess(float(np.max(abs(lengths-contract['control_rest_lengths_m']))),1e-8)
        self.assertAlmostEqual(sum(lengths),2.3238061919335924,delta=1e-7)
    def test_weapon_socket_matches_shipping_cap_geometry(self):
        w=contract['endpoints']['weapon'];ship=BinaryFbx(REPO/'units/rocket/pRocketLauncher.fbx')
        ship_points=np.array(source_points_to_engine(canonical_geometry_points(ship,3308)))
        center=ship_points[w['socket_ring_source_indices']].mean(0)-np.array(w['socket_outward_normal'])*w['insertion_m']
        frame=np.array(w['target_canonical_frame_m'])
        self.assertLess(float(np.linalg.norm(center-frame[:3,3])),1e-6)
        compiled=json.loads((BASE/'compiled_weapon_node.json').read_text())
        composite=np.array(compiled['world'])@np.array(w['target_local_frame'])
        self.assertLess(float(np.max(abs(composite-frame))),2e-7)
        self.assertLess(float(np.max(abs(np.linalg.norm(composite[:3,:3],axis=0)-1))),1e-6)
    def test_pack_socket_same_compiled_skin_equation(self):
        p=contract['endpoints']['pack'];fixture=json.loads((REPO/'tools/fixtures/warlock_chimney_anchor.json').read_text())
        bind=np.array(fixture['compiled_inverse_bind_column_matrix'])
        center=np.array([*p['source_cap_mesh_cm'],100])/100
        self.assertLess(float(np.linalg.norm((bind@center)[:3]-np.array(p['target_local_frame'])[:3,3])),1e-8)
        body=np.array(fixture['compiled_pose_column_matrix']);world=body@np.array(p['target_local_frame'])
        self.assertLess(float(np.max(abs(np.linalg.norm(world[:3,:3],axis=0)-1))),3e-6)
    def test_pack_cap_is_present_and_rigid_in_shipping_body(self):
        p=contract['endpoints']['pack'];body=BinaryFbx(REPO/'units/warlock_bombardier/warlock_bombardier_3p.fbx')
        geometry=geometry_by_vertex_count(body,29123);index=p['source_cap_vertex']+12846
        self.assertEqual(fbx_positive_weights(body,geometry,[index])[index],[('j_backpack',1.0)])
        values=geometry.child('Vertices').properties[0]
        self.assertLess(float(np.linalg.norm(np.array(values[index*3:index*3+3])-p['source_cap_mesh_cm'])),2e-5)

if __name__=='__main__':unittest.main(argv=[sys.argv[0]],verbosity=2)
