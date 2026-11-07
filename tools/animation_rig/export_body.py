"""Export an isolated body candidate with animator-approved corrective weights.

This does not replace production unit files. The vertex positions, topology,
UVs, materials, object transforms and 138-bone bind skeleton must match a fresh
import of the shipping body. Only changed SkinCluster index/weight arrays may
differ; the approved activation take and every other decoded FBX element remain
identical. An independent reimport verifies the skin and every exported weight.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import tempfile

import bpy
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_animation as bridge


def skin_weights(mesh, names):
    groups = {group.index: group.name for group in mesh.vertex_groups}
    weights = []
    for vertex in mesh.data.vertices:
        skin = {groups[group.group]: float(group.weight) for group in vertex.groups
                if group.weight > 1e-7}
        bridge.require(set(skin) <= set(names),
                       f"Vertex {vertex.index} references non-shipping bones")
        bridge.require(1 <= len(skin) <= 4,
                       f"Vertex {vertex.index}: {len(skin)} influences, expected 1..4")
        bridge.require(abs(sum(skin.values()) - 1.0) < 2e-5,
                       f"Vertex {vertex.index}: weights are not normalized")
        weights.append(skin)
    return weights


def material_names(mesh):
    return [material.name if material else None for material in mesh.data.materials]


def same_material(actual, expected):
    # Independently imported materials receive Blender ID collision suffixes.
    return actual == expected or (isinstance(actual, str) and isinstance(expected, str)
                                 and re.sub(r"\.\d{3}$", "", actual) ==
                                 re.sub(r"\.\d{3}$", "", expected))


def compare_geometry(mesh, baseline, tolerance=5e-5):
    a, b = mesh.data, baseline.data
    bridge.require(len(a.vertices) == len(b.vertices) == 29123,
                   "Body vertex count changed from the approved 29,123")
    bridge.require(len(a.polygons) == len(b.polygons), "Body polygon count changed")
    bridge.require(len(a.loops) == len(b.loops), "Body loop count changed")
    vertex_error = max((va.co - vb.co).length for va, vb in zip(a.vertices, b.vertices))
    bridge.require(vertex_error <= tolerance, f"Body geometry changed by {vertex_error}")
    for pa, pb in zip(a.polygons, b.polygons):
        bridge.require(tuple(pa.vertices) == tuple(pb.vertices),
                       f"Body face topology changed at polygon {pa.index}")
        bridge.require(pa.material_index == pb.material_index,
                       f"Body material assignment changed at polygon {pa.index}")
    bridge.require(len(a.uv_layers) == len(b.uv_layers), "Body UV layer count changed")
    uv_error = 0.0
    for la, lb in zip(a.uv_layers, b.uv_layers):
        bridge.require(la.name == lb.name, "Body UV layer name changed")
        uv_error = max(uv_error, max((ua.uv - ub.uv).length
                                     for ua, ub in zip(la.data, lb.data)))
    bridge.require(uv_error <= 2e-6, f"Body UV changed by {uv_error}")
    bridge.require(len(a.corner_normals) == len(b.corner_normals), "Body normal count changed")
    normal_error = max((na.vector - nb.vector).length
                       for na, nb in zip(a.corner_normals, b.corner_normals))
    bridge.require(normal_error <= 5e-5, f"Body surface normals changed by {normal_error}")
    expected_materials = material_names(baseline)
    actual_materials = material_names(mesh)
    bridge.require(len(expected_materials) == len(actual_materials) == 5,
                   "Body must retain its five material slots")
    bridge.require(all(same_material(actual, expected) or same_material(expected, actual)
                       for actual, expected in zip(actual_materials, expected_materials)),
                   f"Body material identities changed: {actual_materials}")
    transform_error = bridge.matrix_error(mesh.matrix_world, baseline.matrix_world)
    bridge.require(transform_error <= 2e-6,
                   f"Body mesh object conversion changed by {transform_error}")
    return {"vertices": len(a.vertices), "polygons": len(a.polygons),
            "loops": len(a.loops), "uv_layers": len(a.uv_layers),
            "max_vertex_error_source_units": vertex_error,
            "max_uv_error": uv_error, "max_normal_component_error": normal_error,
            "max_mesh_transform_component_error": transform_error}


def evaluated_vertices(mesh):
    bpy.context.view_layer.update()
    evaluated = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
    temporary = evaluated.to_mesh()
    try:
        return [evaluated.matrix_world @ vertex.co for vertex in temporary.vertices]
    finally:
        evaluated.to_mesh_clear()


def write_weight_only_candidate(path, expected_weights, baseline_weights):
    """Keep every approved FBX element except changed SkinCluster weights.

    Re-exporting a mesh needlessly requantizes Blender's packed custom normals
    and recomputes Maya/FBX bind metadata. Instead, use the official binary FBX
    parser/writer to preserve the approved model, bind matrices, materials,
    geometry, normal/UV arrays and existing activation take exactly as decoded.
    Existing empty clusters already provide binds for all 138 named joints.
    """
    from io_scene_fbx import encode_bin, parse_fbx

    tree, version = parse_fbx.parse(str(bridge.SOURCE_FBX))
    methods = {"B": "add_bool", "C": "add_char", "Z": "add_int8", "Y": "add_int16",
               "I": "add_int32", "L": "add_int64", "F": "add_float32", "D": "add_float64",
               "R": "add_bytes", "S": "add_string", "i": "add_int32_array",
               "l": "add_int64_array", "f": "add_float32_array", "d": "add_float64_array",
               "b": "add_bool_array", "c": "add_byte_array"}

    def encoded(node):
        output = encode_bin.FBXElem(node.id)
        for kind, value in zip(node.props_type, node.props):
            getattr(output, methods[chr(kind)])(value)
        output.elems = [encoded(child) for child in node.elems]
        return output

    def semantic_digest(root):
        digest = hashlib.sha256()

        def visit(node, in_cluster=False):
            if in_cluster and node.id in {b"Indexes", b"Weights"}:
                return
            value = encoded(node)
            digest.update(struct.pack("<I", len(node.id)) + node.id)
            digest.update(bytes(value.props_type))
            for prop in value.props:
                digest.update(struct.pack("<I", len(prop)) + prop)
            cluster = node.id == b"Deformer" and node.props[-1] == b"Cluster"
            for child in node.elems:
                visit(child, cluster)
        visit(root)
        return digest.hexdigest()

    before_digest = semantic_digest(tree)
    output_root = encoded(tree)
    source_objects = next(node for node in tree.elems if node.id == b"Objects")
    output_objects = next(node for node in output_root.elems if node.id == b"Objects")
    model_names = {node.props[0]: node.props[1].split(b"\x00\x01", 1)[0].decode()
                   for node in source_objects.elems if node.id == b"Model"}
    clusters = {node.props[0]: node for node in source_objects.elems
                if node.id == b"Deformer" and node.props[-1] == b"Cluster"}
    output_nodes = {source.props[0]: target for source, target in
                    zip(source_objects.elems, output_objects.elems) if source.props}
    connections = next(node for node in tree.elems if node.id == b"Connections")
    cluster_bones = {node.props[2]: model_names[node.props[1]] for node in connections.elems
                     if node.id == b"C" and node.props[0] == b"OO"
                     and node.props[1] in model_names and node.props[2] in clusters}
    bridge.require(len(cluster_bones) == 138 and set(cluster_bones.values()) == set(bridge.required_names()),
                   "Shipping FBX must retain all 138 existing SkinCluster bind records")
    changed_vertices = [index for index, (actual, baseline) in
                        enumerate(zip(expected_weights, baseline_weights)) if actual != baseline]
    changed_clusters = []
    for identifier, bone in cluster_bones.items():
        source = clusters[identifier]
        indices = next((node.props[0] for node in source.elems if node.id == b"Indexes"), [])
        weights = next((node.props[0] for node in source.elems if node.id == b"Weights"), [])
        desired = dict(zip(indices, weights))
        original = dict(desired)
        for vertex in changed_vertices:
            desired.pop(vertex, None)
            if bone in expected_weights[vertex]:
                desired[vertex] = expected_weights[vertex][bone]
        if desired == original:
            continue
        changed_clusters.append(bone)
        target = output_nodes[identifier]
        target.elems = [node for node in target.elems if node.id not in {b"Indexes", b"Weights"}]
        index_node = encode_bin.FBXElem(b"Indexes")
        weight_node = encode_bin.FBXElem(b"Weights")
        ordered = sorted(desired)
        index_node.add_int32_array(ordered)
        weight_node.add_float64_array([desired[index] for index in ordered])
        target.elems.extend((index_node, weight_node))
    # Preserve approved FileId/CreationTime too; the stock writer's timestamp
    # convenience rewrite is unrelated to this weight-only operation.
    timestamp_writer = encode_bin._write_timedate_hack
    encode_bin._write_timedate_hack = lambda root: None
    try:
        encode_bin.write(str(path), output_root, version)
    finally:
        encode_bin._write_timedate_hack = timestamp_writer
    reimported, output_version = parse_fbx.parse(str(path))
    after_digest = semantic_digest(reimported)
    bridge.require(version == output_version and before_digest == after_digest,
                   "Weight-only FBX operation changed an approved non-weight element")
    return {"changed_vertices": len(changed_vertices), "changed_skin_clusters": changed_clusters,
            "approved_non_weight_semantic_sha256": before_digest,
            "candidate_non_weight_semantic_sha256": after_digest,
            "preserved": ["geometry", "topology", "normals", "UVs", "materials", "skeleton",
                          "bind_matrices", "object_wrappers", "animation_takes", "metadata"]}


def _export_body(args, source_dirty_at_start=False):
    source_scene = bpy.context.scene
    source_frame = source_scene.frame_current
    game = bpy.data.objects.get(args.game_armature)
    names = bridge.required_names()
    rest = bridge.skeleton(game, names)
    if game.get("source_fbx_sha256"):
        bridge.require(game["source_fbx_sha256"] == bridge.sha256(bridge.SOURCE_FBX),
                       "Approved reference body FBX no longer matches GAME provenance")
    meshes = [obj for obj in source_scene.objects if obj.type == "MESH" and
              any(mod.type == "ARMATURE" and mod.object == game for mod in obj.modifiers)]
    bridge.require(len(meshes) == 1, "Expected one skinned shipping body mesh")
    mesh = meshes[0]
    expected_weights = skin_weights(mesh, names)
    baseline_scene, baseline_objects, baseline = bridge.independent_import(
        bridge.SOURCE_FBX, animation=True)
    try:
        baseline_scene.frame_set(0)
        bpy.context.view_layer.update()
        evaluated_baseline = baseline.evaluated_get(bpy.context.evaluated_depsgraph_get())
        approved_initial_pose = {name: evaluated_baseline.pose.bones[name].matrix.copy() for name in names}
        baseline_meshes = [obj for obj in baseline_objects if obj.type == "MESH"]
        bridge.require(len(baseline_meshes) == 1, "Shipping FBX mesh inventory drifted")
        shipping_geometry = compare_geometry(mesh, baseline_meshes[0], tolerance=1e-6)
        baseline_weights = skin_weights(baseline_meshes[0], names)
        baseline_rest = bridge.skeleton(baseline, names)
        for name in names:
            bridge.require(rest[name] == baseline_rest[name],
                           f"Authoring body rest/hierarchy changed: {name}")
        bridge.require(bridge.matrix_error(game.matrix_world, baseline.matrix_world) < 1e-6,
                       "Body GAME object transform differs from shipping")
    finally:
        bridge.select_scene(source_scene)
        bridge.dispose_scene(baseline_scene, baseline_objects)
    output = args.output.resolve()
    bridge.require(output.suffix.lower() == ".fbx", "Body output must be an FBX file")
    bridge.validate_output_path(output, bridge.SOURCE_FBX)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": 1, "status": "pending", "purpose": "isolated corrective-weight body candidate",
                "source_rig": bpy.data.filepath, "blender_version": bpy.app.version_string,
                "source_rig_disk_sha256": bridge.sha256(Path(bpy.data.filepath)) if bpy.data.filepath else None,
                "source_scene_contains_unsaved_changes": source_dirty_at_start,
                "export_script_sha256": bridge.sha256(Path(__file__)),
                "shipping_fbx_sha256": bridge.sha256(bridge.SOURCE_FBX),
                "bone_names": names, "rest_contract": rest,
                "approved_geometry_comparison": shipping_geometry,
                "material_names": [re.sub(r"\.\d{3}$", "", name) for name in material_names(mesh)],
                "authoring_material_ids": material_names(mesh),
                "weight_changes_only": True,
                "activation_take": "approved shipping body animation take preserved without re-export",
                "production_units_modified": False,
                "game_runtime_acceptance": "pending; SDK compilation is a separate gate"}
    scenes = []
    reservations = []
    for name in ("armature object.008", "warlock_bombardier"):
        obj = bpy.data.objects.get(name)
        if obj:
            reservations.append((obj, obj.name))
            obj.name = "AUTHORING_RESERVED_" + name
    try:
        scene = bpy.data.scenes.new("WARLOCK_BODY_CANDIDATE")
        bridge.register_temporary_scene(scene)
        created_objects = []
        scenes.append((scene, created_objects))
        scene.render.fps = 60
        scene.frame_start, scene.frame_end = 0, 1
        scene.unit_settings.system = source_scene.unit_settings.system
        scene.unit_settings.scale_length = source_scene.unit_settings.scale_length
        bridge.select_scene(scene)
        rig = game.copy()
        rig.data = game.data.copy()
        rig.animation_data_clear()
        rig.name = "armature object.008"
        rig.data.name = "armature object.008"
        rig.parent = None
        rig.matrix_parent_inverse = Matrix.Identity(4)
        rig.matrix_world = game.matrix_world.copy()
        scene.collection.objects.link(rig)
        created_objects.append(rig)
        rig.hide_viewport = rig.hide_render = False
        rig.hide_set(False)
        for constraint in list(rig.constraints):
            rig.constraints.remove(constraint)
        for bone in rig.pose.bones:
            for constraint in list(bone.constraints):
                bone.constraints.remove(constraint)
            bone.matrix_basis = Matrix.Identity(4)
        for frame in (0, 1):
            scene.frame_set(frame)
            for name in names:
                bone = rig.data.bones[name]
                kwargs = {"parent_matrix": approved_initial_pose[bone.parent.name],
                          "parent_matrix_local": bone.parent.matrix_local} if bone.parent else {}
                basis = bone.convert_local_to_pose(approved_initial_pose[name],
                    bone.matrix_local, invert=True, **kwargs)
                bridge.set_transform(rig.pose.bones[name], basis, f"body first-frame {name}")
                bridge.key_transform(rig.pose.bones[name], frame)
        body = mesh.copy()
        body.data = mesh.data.copy()
        body.animation_data_clear()
        body.name = "warlock_bombardier"
        scene.collection.objects.link(body)
        created_objects.append(body)
        body.parent = rig
        body.matrix_world = mesh.matrix_world.copy()
        body.hide_viewport = body.hide_render = False
        body.hide_set(False)
        for constraint in list(body.constraints):
            body.constraints.remove(constraint)
        for modifier in body.modifiers:
            bridge.require(modifier.type == "ARMATURE", "Unexpected body authoring modifier")
            modifier.object = rig
        scene.frame_set(0)
        neutral_vertices = evaluated_vertices(body)
        for obj in scene.objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bridge.seal_temporary_scene(scene)
        with bridge.scratch_directory("warlock-body-", output.parent) as temporary:
            temporary_fbx = Path(temporary) / output.name
            temporary_manifest = Path(temporary) / output.with_suffix(".body-export.json").name
            manifest["weight_only_operation"] = write_weight_only_candidate(
                temporary_fbx, expected_weights, baseline_weights)
            imported_scene, imported_objects, imported_rig = bridge.independent_import(
                temporary_fbx, animation=True)
            scenes.append((imported_scene, imported_objects))
            imported_scene.frame_set(0)
            bpy.context.view_layer.update()
            imported_meshes = [obj for obj in imported_objects if obj.type == "MESH"]
            bridge.require(len(imported_meshes) == 1, "Body candidate mesh inventory changed")
            imported_body = imported_meshes[0]
            roundtrip_rest = bridge.skeleton(imported_rig, names)
            rest_error = 0.0
            for name in names:
                bridge.require(roundtrip_rest[name]["parent"] == rest[name]["parent"],
                               f"Body FBX changed {name} parent")
                rest_error = max(rest_error, bridge.matrix_error(
                    Matrix(roundtrip_rest[name]["rest_matrix"]), Matrix(rest[name]["rest_matrix"])))
            bridge.require(rest_error <= 5e-5, f"Body FBX bind/rest changed by {rest_error}")
            geometry = compare_geometry(imported_body, body)
            actual_weights = skin_weights(imported_body, names)
            weight_error = 0.0
            for index, (actual, expected) in enumerate(zip(actual_weights, expected_weights)):
                bridge.require(actual.keys() == expected.keys(), f"Body FBX changed vertex {index} bone names")
                weight_error = max(weight_error, max(abs(actual[name] - value)
                                                    for name, value in expected.items()))
            bridge.require(weight_error <= 2e-6, f"Body FBX skin weights changed by {weight_error}")
            actual_vertices = evaluated_vertices(imported_body)
            neutral_error = max((a-b).length for a, b in zip(actual_vertices, neutral_vertices))
            bridge.require(neutral_error <= 5e-5, f"Body FBX neutral skin changed by {neutral_error} m")
            manifest.update(status="body-roundtrip-passed", fbx_path=str(output),
                fbx_sha256=bridge.sha256(temporary_fbx), fbx_bytes=temporary_fbx.stat().st_size,
                roundtrip={"geometry": geometry, "max_rest_matrix_component_error": rest_error,
                           "max_weight_error": weight_error, "max_neutral_skin_error_m": neutral_error})
            temporary_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
            bridge.publish_bundle([(temporary_fbx, output),
                                   (temporary_manifest, output.with_suffix(".body-export.json"))])
    except Exception as error:
        manifest.update(status="failed", failure=str(error))
        output.with_suffix(".body-export.failure.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
        raise
    finally:
        bridge.select_scene(source_scene)
        for scene, objects in reversed(scenes):
            bridge.dispose_scene(scene, objects)
        for obj, name in reservations:
            obj.name = name
        source_scene.frame_set(source_frame)
    print("WARLOCK_BODY_EXPORT", json.dumps({key: value for key, value in manifest.items()
          if key not in {"bone_names", "rest_contract"}}))
    return manifest


def export_body(args):
    if args.rig:
        bpy.ops.wm.open_mainfile(filepath=str(args.rig.resolve()), use_scripts=False)
    # Blender marks a file opened headless as dirty before any edit, so a
    # freshly opened --rig cannot carry unsaved changes.
    source_dirty_at_start = False if args.rig else bpy.data.is_dirty
    with bridge.preserve_ui_state():
        return _export_body(args, source_dirty_at_start)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rig", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--game-armature", default="WARLOCK_GAME")
    argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    export_body(parser.parse_args(argv))


if __name__ == "__main__":
    main()
