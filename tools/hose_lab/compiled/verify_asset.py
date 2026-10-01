"""Read-only compiled cosmetic-hose audit; no native simulation is exercised.

All acceptance gates use non-removable require(), including under Python -O.
Importing this module requires no artist assets, SDK, Blender or test packages.
"""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import hashlib
import json
import math
import struct
import sys

from verifier_core import (require, check_matrix, inverse, matrix_multiply,
    transform_point, parse_faces, weld_positions, map_positions, validate_topology,
    decode_influences, validate_deformation)

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compile_paths import lexical_path, validate_probe, reject_redirect


def audit(unit_path, fbx_path, contract_path):
    # Heavy parsers are only needed for real assets, not synthetic helper tests.
    sys.path.insert(0, str(ROOT / 'tools/tests'))
    from test_warlock_weapon_pipeline import (compiled_unit_structure, compiled_node_index,
        BinaryFbx, geometry_by_vertex_count, raw_geometry_points, geometry_model, model_world_matrix)
    from test_doomrocket_chimney_anchor import compiled_skin_prefix, fbx_positive_weights

    contract = json.loads(contract_path.read_text(encoding='utf-8'))
    require(hashlib.sha256(fbx_path.read_bytes()).hexdigest() == contract['outputs']['fbx_sha256'], 'FBX differs from reviewed rig contract')
    payload = unit_path.read_bytes()
    require(len(payload) >= 4 and struct.unpack_from('<I', payload)[0] == 189, 'Unreviewed unit format')
    unit = compiled_unit_structure(payload)
    geometry, skins = compiled_skin_prefix(payload)
    actor_count = len(unit.actors)
    require(actor_count == 0, f'Cosmetic hose must have no actors; found {actor_count}')
    require(len(skins) == len(geometry) == len(unit.geometries) == len(unit.mesh_node_indices) == 1, 'Expected one mesh, geometry and skin')
    binds, skin_nodes, matrix_sets = skins[0]
    require(len(skin_nodes) == len(binds) == 30 and len(set(skin_nodes)) == 30, 'Expected 29 controls and unused root skin entry')
    require(compiled_node_index(unit, 'hose_root') in skin_nodes, 'Unused root cluster missing')
    controls = contract['controls']
    require([c['name'] for c in controls] == [f'j_hose_{i:02d}' for i in range(29)], 'Unexpected deform controls')

    fbx = BinaryFbx(fbx_path)
    fbx_geometry = geometry_by_vertex_count(fbx, 1608)
    raw = raw_geometry_points(fbx_geometry)
    fbx_world = model_world_matrix(fbx, geometry_model(fbx, fbx_geometry))
    source_points = [tuple(v*.01 for v in transform_point(fbx_world, p)) for p in raw]
    source_weights = {i: dict(weights) for i, weights in fbx_positive_weights(fbx, fbx_geometry, range(len(raw))).items()}
    canonical, members, source_mapping = weld_positions(source_points)
    require(len(raw) == 1608 and len(canonical) == 1536, 'Reviewed source vertex/seam count changed')
    for group in members:
        require(all(source_weights[j] == source_weights[group[0]] for j in group), 'Coincident seam weights differ')
    for weights in source_weights.values():
        require(weights and all(math.isfinite(w) and 0 <= w <= 1 for w in weights.values()), 'Invalid source weights')
        require(abs(sum(weights.values())-1) < 1e-6, 'Source weights do not sum to one')

    positions = unit.geometries[0].positions
    triangles = unit.geometries[0].triangles
    mesh_bind_world = unit.nodes[unit.mesh_node_indices[0]].world_transform
    check_matrix(mesh_bind_world)
    world_points = [transform_point(mesh_bind_world, p) for p in positions]
    compiled_mapping, max_position_error = map_positions(world_points, canonical)
    faces = parse_faces(fbx_geometry.child('PolygonVertexIndex').properties[0], len(raw))
    topology = validate_topology(faces, source_mapping, triangles, compiled_mapping)
    require(topology['triangles'] == 3024, 'Reviewed triangle count changed')

    profiles, parent_ids = [], set()
    for control in controls:
        check_matrix(control['frame'])
        index = compiled_node_index(unit, control['name'])
        require(index in skin_nodes, 'Control absent from skin')
        parent_ids.add(unit.nodes[index].parent_index)
        bind = binds[skin_nodes.index(index)]
        rest_to_bone = matrix_multiply(matrix_multiply(inverse(control['frame']), mesh_bind_world), inverse(bind))
        check_matrix(unit.nodes[index].world_transform)
        native_rest_skin = matrix_multiply(unit.nodes[index].world_transform, bind)
        require(max(abs(native_rest_skin[r][c]-mesh_bind_world[r][c]) for r in range(4) for c in range(4)) < 1e-4, 'Native rest skin differs from mesh bind')
        profiles.append({'name': control['name'], 'scene_node': index,
                         'compiled_inverse_bind': bind, 'control_to_compiled_bone': rest_to_bone})
    require(len(parent_ids) == 1 and next(iter(parent_ids)) == compiled_node_index(unit, 'hose_root'), 'Flat controls must have hose_root as common parent')

    streams, channels, batches = geometry[0]
    index_channels = [c[3] for c in channels if c[0] == 6 and c[1] == 19]
    weight_channels = [c[3] for c in channels if c[0] == 7 and c[1] == 17]
    require(len(index_channels) == len(weight_channels) == 1, 'Expected unique skin index/weight channels')
    index_stream, weight_stream = index_channels[0], weight_channels[0]
    require(0 <= index_stream < len(streams) and 0 <= weight_stream < len(streams), 'Skin stream index out of bounds')
    index_bytes, index_meta = streams[index_stream]
    weight_bytes, weight_meta = streams[weight_stream]
    require(index_meta[3] == 4 and weight_meta[3] == 8, 'Unexpected skin strides')
    require(len(index_bytes) == len(positions)*4 and len(weight_bytes) == len(positions)*8, 'Skin stream vertex count mismatch')
    vertex_batches, covered_triangles = defaultdict(set), Counter()
    for batch_i, (_, start, count, palette_id) in enumerate(batches):
        require(0 <= start <= len(triangles) and 0 <= count <= len(triangles)-start, 'Batch triangle range out of bounds')
        require(0 <= palette_id < len(matrix_sets), 'Batch skin matrix set out of bounds')
        for ti in range(start, start+count):
            covered_triangles[ti] += 1
            for vertex in triangles[ti]:
                vertex_batches[vertex].add(batch_i)
    require(covered_triangles == Counter({i: 1 for i in range(len(triangles))}), 'Missing or overlapping triangle batches')
    node_names = {p['scene_node']: p['name'] for p in profiles}
    compiled_weights, max_weight_error = {}, 0.0
    for vertex in range(len(positions)):
        require(len(vertex_batches[vertex]) == 1, 'Vertex must identify one skin batch')
        batch = batches[next(iter(vertex_batches[vertex]))]
        indices = struct.unpack_from('<4B', index_bytes, vertex*4)
        weights = struct.unpack_from('<4e', weight_bytes, vertex*8)
        positive = decode_influences(indices, weights, matrix_sets[batch[3]], skin_nodes, node_names)
        expected = source_weights[members[compiled_mapping[vertex]][0]]
        require(positive.keys() == expected.keys(), f'Positive bone assignments differ at vertex {vertex}')
        max_weight_error = max(max_weight_error, *(abs(positive[k]-v) for k, v in expected.items()))
        compiled_weights[vertex] = positive
    require(max_weight_error <= .0005, 'Weights exceed half-float tolerance')
    deformation_errors = validate_deformation(source_points, source_weights, positions, compiled_weights,
        compiled_mapping, members, controls, profiles)
    return {'compiled_unit_sha256': hashlib.sha256(payload).hexdigest(), 'actors': actor_count,
        'deforming_controls': len(controls), 'skin_palette_entries': len(skin_nodes), 'compiled_vertices': len(positions),
        'source_vertices': len(raw), 'topology': topology,
        'maximum_position_error_m': max_position_error, 'maximum_weight_error': max_weight_error,
        'weighted_deformation_pose_errors_m': deformation_errors, 'weighted_deformation_tolerance_m': .002,
        'mesh_bind_world': mesh_bind_world,
        'profile_formula': 'W_bone = W_control * inverse(rest_control) * mesh_bind_world * inverse(compiled_inverse_bind)',
        'controls': profiles}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit', type=Path, required=True, help='Raw SDK unit, not a bundle')
    parser.add_argument('--fbx', type=Path, required=True)
    parser.add_argument('--contract', type=Path, default=ROOT/'tools/hose_lab/rig/runtime_contract.json')
    parser.add_argument('--report', type=Path, help='Optional JSON output in ignored .build')
    args = parser.parse_args(argv)
    destination = None
    if args.report:
        destination = lexical_path(args.report, Path.cwd())
        validate_probe(ROOT, destination.parent)
        reject_redirect(destination)
    report = audit(args.unit, args.fbx, args.contract)
    if destination:
        validate_probe(ROOT, destination.parent)
        reject_redirect(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'controls'}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
