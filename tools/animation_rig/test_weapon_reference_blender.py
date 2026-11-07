"""Repair only the posing reference in a new copy and check its engine policy.

Blender 5.2 --background --factory-startup --disable-autoexec --python-exit-code 1
  --python test_weapon_reference_blender.py -- --rig <frozen.blend>
  --output <new-copy.blend> --report <new-validation.json>

Never overwrites inputs. GAME rest/pose/skin and every existing action are hashed
before and after. Quaternion math mirrors the installed SDK's normalized-axis
matrix conversion, with the runtime's explicit final quaternion normalization.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def rows(matrix):
    return [list(row) for row in matrix]


def actions():
    result = []
    for action in sorted(bpy.data.actions, key=lambda value: value.name):
        layers = []
        for layer in action.layers:
            strips = []
            for strip in layer.strips:
                bags = []
                for bag in getattr(strip, 'channelbags', ()):
                    curves = []
                    for curve in bag.fcurves:
                        curves.append({'path': curve.data_path, 'index': curve.array_index,
                            'extrapolation': curve.extrapolation,
                            'keys': [{'co': list(k.co), 'left': list(k.handle_left),
                                      'right': list(k.handle_right), 'left_type': k.handle_left_type,
                                      'right_type': k.handle_right_type, 'interpolation': k.interpolation,
                                      'easing': k.easing, 'amplitude': k.amplitude,
                                      'back': k.back, 'period': k.period}
                                     for k in curve.keyframe_points],
                            'sampled': [list(p.co) for p in curve.sampled_points]})
                    bags.append({'slot': bag.slot_handle, 'curves': curves})
                strips.append({'type': strip.type, 'bags': bags})
            layers.append({'name': layer.name, 'strips': strips})
        result.append({'name': action.name, 'slots': [(slot.identifier, slot.handle)
                       for slot in action.slots], 'layers': layers})
    return result


def protected(game):
    skeleton = [{'name': b.name, 'parent': b.parent.name if b.parent else None,
                 'rest': rows(b.matrix_local), 'inherit_scale': b.inherit_scale,
                 'deform': b.use_deform, 'connected': b.use_connect}
                for b in game.data.bones]
    pose = [{'name': b.name, 'basis': rows(b.matrix_basis),
             'rotation_mode': b.rotation_mode} for b in game.pose.bones]
    skins = []
    for obj in sorted(bpy.data.objects, key=lambda value: value.name):
        if obj.type == 'MESH' and any(m.type == 'ARMATURE' and m.object == game for m in obj.modifiers):
            skins.append({'name': obj.name, 'matrix': rows(obj.matrix_world),
                          'vertices': [(list(v.co), [(g.group, g.weight) for g in v.groups])
                                       for v in obj.data.vertices],
                          'groups': [g.name for g in obj.vertex_groups],
                          'polygons': [list(p.vertices) for p in obj.data.polygons]})
    return {'game_bones': len(skeleton), 'skeleton_sha256': digest(skeleton),
            'game_pose_sha256': digest(pose), 'body_skin_sha256': digest(skins),
            'actions_sha256': digest(actions()), 'actions': len(bpy.data.actions)}


def sdk_quaternion(matrix):
    rotation = matrix.to_3x3().copy()
    for column in range(3):
        axis = rotation.col[column]
        assert axis.length > 1e-8
        rotation.col[column] = axis / axis.length
    a, b, c = rotation[0][0], rotation[1][1], rotation[2][2]
    trace = a + b + c
    if trace > 0:
        s = 2 * math.sqrt(1 + trace)
        q = Quaternion((s/4, (rotation[2][1]-rotation[1][2])/s,
                        (rotation[0][2]-rotation[2][0])/s, (rotation[1][0]-rotation[0][1])/s))
    elif a > b and a > c:
        s = 2 * math.sqrt(1+a-b-c)
        q = Quaternion(((rotation[2][1]-rotation[1][2])/s, s/4,
                        (rotation[0][1]+rotation[1][0])/s, (rotation[0][2]+rotation[2][0])/s))
    elif b > c:
        s = 2 * math.sqrt(1+b-a-c)
        q = Quaternion(((rotation[0][2]-rotation[2][0])/s,
                        (rotation[0][1]+rotation[1][0])/s, s/4, (rotation[1][2]+rotation[2][1])/s))
    else:
        s = 2 * math.sqrt(1+c-a-b)
        q = Quaternion(((rotation[1][0]-rotation[0][1])/s,
                        (rotation[0][2]+rotation[2][0])/s, (rotation[1][2]+rotation[2][1])/s, s/4))
    return q.normalized()


def sample(game, reference, meshes):
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    eg, er = game.evaluated_get(dg), reference.evaluated_get(dg)
    hand = eg.matrix_world @ eg.pose.bones['j_leftweaponattach'].matrix
    actual = er.matrix_world.copy()
    q = sdk_quaternion(hand)
    expected = q.to_matrix()
    rigid_actual = actual.to_3x3()
    error = max((expected.col[i]-rigid_actual.col[i]).length for i in range(3))
    bounds = {}
    inverse = actual.inverted()
    for mesh in meshes:
        em = mesh.evaluated_get(dg)
        evaluated_mesh = em.to_mesh()
        vertices = [inverse @ (em.matrix_world @ v.co) for v in evaluated_mesh.vertices]
        em.to_mesh_clear()
        bounds[mesh.name] = [max(v[i] for v in vertices)-min(v[i] for v in vertices) for i in range(3)]
    axes = [hand.to_3x3().col[i].normalized() for i in range(3)]
    return {'position_error_m': (actual.translation-hand.translation).length,
            'axis_endpoint_error_mm_at_1m': error*1000,
            'reference_scale': list(actual.to_scale()),
            'hand_scale': list(hand.to_scale()),
            'hand_axis_dots': [axes[0].dot(axes[1]), axes[0].dot(axes[2]), axes[1].dot(axes[2])],
            'rigid_mesh_dimensions_m': bounds}


def run(args):
    source, output, report_path = args.rig.resolve(), args.output.resolve(), args.report.resolve()
    assert source != output and not output.exists() and not report_path.exists(), 'Use new output paths'
    input_sha = sha(source)
    bpy.ops.wm.open_mainfile(filepath=str(source), use_scripts=False)
    rig, game, reference = [bpy.data.objects[name] for name in
                            ('WARLOCK_CTRL', 'WARLOCK_GAME', 'WARLOCK_LAUNCHER_REFERENCE')]
    initial = protected(game)
    assert initial['game_bones'] == 138
    manifest = json.loads(rig['warlock_control_manifest'])
    sources = {}
    for name, key in (('body_fbx', 'body_sha256'), ('controls_file', 'controls_sha256'),
                      ('weapon_reference_fbx', 'weapon_reference_sha256')):
        path = Path(manifest['sources'][name])
        assert path.is_file() and sha(path) == manifest['sources'][key], 'Pinned source differs: ' + str(path)
        sources[str(path)] = sha(path)
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    assert not any(o.name.startswith('WARLOCK_WEAPON_REFERENCE_') for o in bpy.data.objects), 'Already repaired'
    module_path = Path(__file__).resolve().with_name('build_rig.py')
    spec = importlib.util.spec_from_file_location('warlock_reference_builder', module_path)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    constraint, = [c for c in reference.constraints if c.type == 'CHILD_OF']
    assert constraint.target == game and constraint.subtarget == 'j_leftweaponattach'
    constraint.use_scale_x = constraint.use_scale_y = constraint.use_scale_z = False
    constraint.use_rotation_x = constraint.use_rotation_y = constraint.use_rotation_z = False
    builder.weapon_reference_rotation(reference, game)
    meshes = [o for o in bpy.data.objects if o.type == 'MESH' and o.get('authoring_reference_only')]
    assert len(meshes) == 2
    shape_names = ('CTRL-shape-j_spine_scale', 'CTRL-shape-j_leftarm_scale')
    saved = {name: {key: rig.pose.bones[name][key] for key in ('length', 'volume')} for name in shape_names}
    saved_frame = bpy.context.scene.frame_current
    cases = []
    try:
        for name, length in (('neutral', 1.0), ('maximum_stretch', 1.35), ('maximum_squash', .75)):
            for bone in shape_names:
                rig.pose.bones[bone]['length'] = length
                rig.pose.bones[bone]['volume'] = 1.0
            rig.update_tag()
            bpy.context.scene.frame_set(saved_frame+1)
            evidence = sample(game, reference, meshes)
            evidence['case'] = name
            cases.append(evidence)
            assert evidence['position_error_m'] < 2e-6, evidence
            assert evidence['axis_endpoint_error_mm_at_1m'] < .02, evidence
            assert max(abs(value-1) for value in evidence['reference_scale']) < 2e-6, evidence
            if len(cases) > 1:
                for mesh in cases[0]['rigid_mesh_dimensions_m']:
                    assert max(abs(a-b) for a,b in zip(cases[0]['rigid_mesh_dimensions_m'][mesh],
                                                      evidence['rigid_mesh_dimensions_m'][mesh])) < 2e-6, evidence
    finally:
        for bone, values in saved.items():
            for key, value in values.items():
                rig.pose.bones[bone][key] = value
        rig.update_tag()
        bpy.context.scene.frame_set(saved_frame)
        bpy.context.view_layer.update()
    assert all(f.driver.is_valid for o in bpy.data.objects if o.animation_data
               for f in o.animation_data.drivers), 'Invalid driver'
    after = protected(game)
    assert initial == after, 'Existing GAME skeleton, skin, pose or action payload changed'
    assert sha(source) == input_sha and all(sha(path) == value for path,value in sources.items())
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=False, compress=True)
    assert sha(source) == input_sha
    bpy.ops.wm.open_mainfile(filepath=str(output), use_scripts=False)
    reloaded = protected(bpy.data.objects['WARLOCK_GAME'])
    assert reloaded == initial, 'Saved copy changed protected payload'
    result = {'schema': 1, 'status': 'PASS', 'blender': bpy.app.version_string,
              'source': str(source), 'source_sha256_before': input_sha, 'source_sha256_after': sha(source),
              'output': str(output), 'output_sha256': sha(output), 'builder_sha256': sha(module_path),
              'test_sha256': sha(__file__), 'protected_before': initial, 'protected_after': reloaded,
              'source_asset_hashes': sources, 'cases': cases, 'controls_restored': saved,
              'rotation_policy': 'Normalize world axes, SDK matrix-to-quaternion, then normalize quaternion',
              'native_scope': 'Installed API disassembly plus Blender behavior; no engine launch or in-game verdict'}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print('WARLOCK_WEAPON_REFERENCE_PASS', json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rig', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    argv = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    run(parser.parse_args(argv))
