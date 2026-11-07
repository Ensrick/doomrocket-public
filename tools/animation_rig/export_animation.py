"""Bake the evaluated animator rig onto the shipping skeleton and verify FBX.

Run with Blender 5.2, never ordinary Python::

    blender --background --disable-autoexec --python-exit-code 1 \
      --python tools/animation_rig/export_animation.py -- \
      --rig path/to/WarlockEngineer_Animator.blend --output path/to/clip.fbx \
      --start 1 --end 61 --game-armature WARLOCK_GAME

Controls, constraints, mesh, corrective shape keys and animation layers are
authoring data. Only sampled transforms of the exact 138 shipping bones leave
this script. A fresh FBX import must reproduce every head and axis probe at
every sampled frame before a clip receives a successful manifest.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile

import bpy
from mathutils import Matrix, Vector


ROOT = Path(__file__).resolve().parents[2]
UNIT = "units/warlock_bombardier/warlock_bombardier_3p"
REFERENCE_DIR = Path(__file__).resolve().parent / "reference"
SOURCE_FBX = (REFERENCE_DIR / "shipping_body.fbx" if
              (REFERENCE_DIR / "shipping_body.fbx").is_file() else ROOT / f"{UNIT}.fbx")
BONES_PATH = (REFERENCE_DIR / "game.bones" if
              (REFERENCE_DIR / "game.bones").is_file() else ROOT / f"{UNIT}.bones")
AIM_REFERENCE = Vector((0.1, 5.0, 0.6))
AXIS_PROBE_LENGTH = 0.1
# Exactly zero bypasses VT2's adaptive curve fitter and copies source keys.
# Tiny positive tolerances still fit curves. Keep the authoring prototype's
# baked timing/data; optimize only a separately verified future candidate.
SIDE_CAR = ('bones = "' + UNIT + '"\n\ntolerance = {\n'
            '    "" = [ 0 0 0 false false false ]\n}\n')
COMPRESSION_TOLERANCES = {"position": 0, "rotation_rad": 0, "scale": 0,
                          "pack_positions": False, "pack_rotations": False,
                          "pack_scales": False}
FBX_OPTIONS = {
    "use_selection": True,
    "object_types": {"ARMATURE", "EMPTY"},
    "global_scale": 1.0,
    "apply_unit_scale": True,
    "apply_scale_options": "FBX_SCALE_NONE",
    "use_space_transform": True,
    "bake_space_transform": False,
    "axis_forward": "-Y",
    "axis_up": "Z",
    "add_leaf_bones": False,
    "use_armature_deform_only": False,
    "armature_nodetype": "NULL",
    "primary_bone_axis": "Y",
    "secondary_bone_axis": "X",
    "use_custom_props": False,
    "bake_anim": True,
    "bake_anim_use_all_bones": True,
    "bake_anim_use_nla_strips": False,
    "bake_anim_use_all_actions": False,
    "bake_anim_force_startend_keying": True,
    "bake_anim_step": 1.0,
    "bake_anim_simplify_factor": 0.0,
    "use_metadata": False,
}
TEMPORARY_DATA_TYPES = ("actions", "armatures", "meshes", "curves", "materials",
                        "textures", "images", "collections")
_TEMPORARY_DATA_OWNERS = {}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_sidecar(path: Path) -> dict:
    """Read the written legacy six-slot tolerance, including all packing flags.

    VT2's optional slots 3/4/5 separately control position/rotation/scale
    packing. Four entries disable only position packing; omitted rotation
    packing defaults to true. Check the actual staged bytes, not only a
    Python constant or an intended setting in the receipt.
    """
    text = path.read_text(encoding="utf-8")
    bones = re.search(r'\bbones\s*=\s*"([^"]+)"', text)
    require(bones is not None and bones.group(1) == UNIT,
            "Animation sidecar references the wrong shipping skeleton")
    tolerance = re.search(r'tolerance\s*=\s*\{\s*""\s*=\s*\[([^\]]+)\]\s*\}', text)
    require(tolerance is not None, "Animation sidecar tolerance block is malformed")
    fields = tolerance.group(1).split()
    require(len(fields) == 6, "Animation sidecar must explicitly specify all six tolerance/packing fields")
    values = [float(value) for value in fields[:3]]
    require(all(math.isfinite(value) and value >= 0 for value in values),
            "Animation sidecar has invalid curve-fitting tolerances")
    require(fields[3:] == ["false", "false", "false"],
            "Animation sidecar must disable position, rotation and scale packing")
    result = dict(zip(("position", "rotation_rad", "scale"), values))
    result.update(pack_positions=False, pack_rotations=False, pack_scales=False)
    require(result == COMPRESSION_TOLERANCES, "Animation sidecar compression differs from audited settings")
    return {**result, "legacy_fields": fields, "field_count": len(fields),
            "curve_fitting_disabled": all(value == 0 for value in values)}


def matrix_json(value: Matrix) -> list[list[float]]:
    return [[float(v) for v in row] for row in value]


def matrix_error(a: Matrix, b: Matrix) -> float:
    return max(abs(a[r][c] - b[r][c]) for r in range(4) for c in range(4))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def required_names() -> list[str]:
    names = re.findall(r'"([^"\n]+)"', BONES_PATH.read_text(encoding="utf-8"))
    require(len(names) == 138 and len(set(names)) == 138,
            "Shipping .bones is no longer the audited 138-bone skeleton")
    return names


def validate_output_path(output: Path, source_fbx: Path) -> None:
    """Portable handoff tools must never write a production/reference asset."""
    resolved = output.resolve()
    require(all(part.casefold() != "units" for part in resolved.parts),
            "Authoring export cannot write any production units directory")
    require(not resolved.is_relative_to(REFERENCE_DIR.resolve()),
            "Authoring export cannot overwrite its approved reference directory")
    require(resolved != source_fbx.resolve(), "Cannot overwrite the approved source FBX")


def remove_flat_scratch(folder: Path) -> list[Path]:
    """Remove a tool-created scratch folder without deleting a directory tree.

    Project rule: tools never delete recursively. These scratch folders hold
    only flat files, so each regular file is removed by its explicit path and
    then the empty folder. Any other entry stays in place and is returned.
    """
    folder = Path(folder)
    leftovers = []
    for entry in sorted(folder.iterdir()):
        if entry.is_file() and not entry.is_symlink():
            entry.unlink()
        else:
            leftovers.append(entry)
    if not leftovers:
        folder.rmdir()
    return leftovers


@contextmanager
def scratch_directory(prefix: str, directory: Path | None = None):
    """A mkdtemp folder removed by remove_flat_scratch instead of rmtree."""
    folder = Path(tempfile.mkdtemp(prefix=prefix, dir=directory))
    try:
        yield str(folder)
    finally:
        try:
            leftovers = remove_flat_scratch(folder)
        except OSError as error:
            leftovers = [error]
        if leftovers:
            print(f"WARLOCK_SCRATCH_RETAINED {folder}: {leftovers}", file=sys.stderr)


def publish_bundle(staged_files: list[tuple[Path, Path]]) -> None:
    """Publish a validated file set, restoring the previous set on failure.

    Each staged file is completely written before any destination changes.
    Publish the receipt last; a consumer must check its payload hashes before
    accepting a bundle. A filesystem cannot atomically rename three files, so
    retain backups and roll back only the files whose replacement succeeded.
    """
    require(bool(staged_files), "Cannot publish an empty export bundle")
    destinations = [destination.resolve() for _, destination in staged_files]
    require(len(set(destinations)) == len(destinations), "Duplicate bundle destination")
    require(all(source.is_file() for source, _ in staged_files),
            "Export bundle has a missing staged payload or receipt")
    require(all(path.parent == destinations[0].parent for path in destinations),
            "Export bundle destinations must share one directory")
    # A context-managed TemporaryDirectory would delete the only recovery
    # copy if publication AND rollback fail. Own its lifetime explicitly.
    folder = Path(tempfile.mkdtemp(prefix="warlock-publish-", dir=destinations[0].parent))
    retain_backups = False
    try:
        backups = {}
        for index, destination in enumerate(destinations):
            backup = folder / str(index)
            if destination.exists():
                shutil.copy2(destination, backup)
                backups[destination] = backup
            else:
                backups[destination] = None
        recovery = {
            "files": [{"destination": str(destination),
                       "backup": str(backup) if backup is not None else None}
                      for destination, backup in backups.items()],
            "purpose": "Original export bundle recovery after a failed publication",
        }
        (folder / "recovery.json").write_text(json.dumps(recovery, indent=2), encoding="utf-8")
        published = []
        try:
            for (source, _), destination in zip(staged_files, destinations):
                source.replace(destination)
                published.append(destination)
        except Exception as error:
            rollback_errors = []
            for destination in reversed(published):
                try:
                    if backups[destination] is None:
                        destination.unlink(missing_ok=True)
                    else:
                        backups[destination].replace(destination)
                except Exception as rollback_error:
                    rollback_errors.append(f"{destination}: {rollback_error}")
            if rollback_errors:
                retain_backups = True
                raise RuntimeError("Export publication failed; previous bundle restoration failed: "
                                   + "; ".join(rollback_errors)
                                   + f". Recovery backups retained at {folder}") from error
            raise
    finally:
        if not retain_backups:
            remove_flat_scratch(folder)


def run_publication_checks(directory: Path) -> list[dict]:
    """Exercise missing payload, publication and rollback failures safely."""
    from unittest.mock import patch

    checks = []
    with scratch_directory("warlock-publish-test-", directory) as folder:
        root = Path(folder)
        destinations = [root / "candidate.animation", root / "candidate.fbx",
                        root / "candidate.export.json"]
        sources = [root / "staged.animation", root / "staged.fbx", root / "staged.json"]
        originals = [b"previous sidecar", b"previous FBX", b"previous matching receipt"]
        for destination, contents in zip(destinations, originals):
            destination.write_bytes(contents)
        for source in sources[1:]:
            source.write_bytes(b"new validated data")
        try:
            publish_bundle(list(zip(sources, destinations)))
        except ValueError:
            pass
        else:
            raise ValueError("Publication accepted a missing staged sidecar")
        require([path.read_bytes() for path in destinations] == originals,
                "Missing staged sidecar changed the previous export bundle")
        checks.append({"mutation": "missing staged sidecar", "rejected": True,
                       "previous_bundle_restored": True})
        sources[0].write_bytes(b"new sidecar")
        original_replace = Path.replace
        failed = False

        def fail_second_publication(source, destination):
            nonlocal failed
            if Path(destination) == destinations[1] and not failed:
                failed = True
                raise OSError("deliberate FBX publication failure after sidecar replacement")
            return original_replace(source, destination)

        try:
            with patch.object(Path, "replace", fail_second_publication):
                publish_bundle(list(zip(sources, destinations)))
        except OSError:
            pass
        else:
            raise ValueError("Publication failure mutation was not exercised")
        require(failed and [path.read_bytes() for path in destinations] == originals,
                "Publication failure left a mismatched FBX, sidecar or receipt")
        checks.append({"mutation": "FBX publish fails after sidecar", "rejected": True,
                       "previous_bundle_restored": True})
        for source in sources:
            source.write_bytes(b"new validated data")
        recovery_folders_before = set(root.glob("warlock-publish-*"))

        def fail_publication_and_rollback(source, destination):
            if Path(source) == sources[1]:
                raise OSError("deliberate FBX publication failure")
            if Path(destination) == destinations[0] and Path(source) != sources[0]:
                raise OSError("deliberate previous sidecar restoration failure")
            return original_replace(source, destination)

        try:
            with patch.object(Path, "replace", fail_publication_and_rollback):
                publish_bundle(list(zip(sources, destinations)))
        except RuntimeError as error:
            recovery_folders = set(root.glob("warlock-publish-*")) - recovery_folders_before
            require(len(recovery_folders) == 1, "Failed rollback lost its recovery directory")
            recovery_folder = recovery_folders.pop()
            require(str(recovery_folder) in str(error), "Failed rollback did not report its recovery directory")
            recovery = json.loads((recovery_folder / "recovery.json").read_text(encoding="utf-8"))
            backup = Path(recovery["files"][0]["backup"])
            require(backup.read_bytes() == originals[0], "Failed rollback deleted the only original sidecar")
            require([path.read_bytes() for path in destinations[1:]] == originals[1:],
                    "Failed publication changed untouched bundle members")
            # A user can recover the failed member using the reported mapping.
            backup.replace(destinations[0])
            require([path.read_bytes() for path in destinations] == originals,
                    "Retained recovery files cannot restore the previous bundle")
            require(not remove_flat_scratch(recovery_folder), "Recovery folder held a nested entry")
        else:
            raise ValueError("Compound publication/rollback failure mutation was not exercised")
        checks.append({"mutation": "publication and previous sidecar rollback both fail",
                       "rejected": True, "recovery_directory_reported": True,
                       "original_backup_retained": True, "manual_recovery_verified": True})
        short_sidecar = root / "incomplete-packing.animation"
        short_sidecar.write_text(SIDE_CAR.replace("false false false", "false"), encoding="utf-8")
        try:
            validate_sidecar(short_sidecar)
        except ValueError:
            pass
        else:
            raise ValueError("Sidecar validation accepted implicit rotation packing")
        checks.append({"mutation": "truncated packing fields enable rotation compression",
                       "rejected": True})
    return checks


def validate_matrix(value: Matrix, label: str) -> None:
    require(all(math.isfinite(x) for row in value for x in row),
            f"{label}: non-finite transform")
    lengths = [value.to_3x3().col[i].length for i in range(3)]
    require(min(lengths) > 1e-7, f"{label}: singular or near-zero scale")
    normalized_det = value.to_3x3().determinant() / math.prod(lengths)
    require(normalized_det > 1e-5, f"{label}: reflected or singular transform")


def validate_positive_scale(obj, names: list[str], frame: int) -> None:
    require(min(obj.scale) > 1e-7,
            f"frame {frame}: {obj.name} has negative/zero object scale")
    for name in names:
        require(min(obj.pose.bones[name].scale) > 1e-7,
                f"frame {frame}: {name} has negative/zero pose scale")


def skeleton(obj, names: list[str]) -> dict:
    require(obj is not None and obj.type == "ARMATURE", "Missing GAME armature")
    actual = list(obj.data.bones.keys())
    require(actual == names,
            f"GAME skeleton name/order drift: missing={set(names)-set(actual)}, "
            f"extra={set(actual)-set(names)}")
    return {
        name: {"parent": obj.data.bones[name].parent.name
               if obj.data.bones[name].parent else None,
               "rest_matrix": matrix_json(obj.data.bones[name].matrix_local),
               "inherit_scale": obj.data.bones[name].inherit_scale,
               "use_local_location": obj.data.bones[name].use_local_location,
               "use_inherit_rotation": obj.data.bones[name].use_inherit_rotation}
        for name in names
    }


def select_scene(scene) -> None:
    bpy.context.window.scene = scene


def register_temporary_scene(scene) -> None:
    """Protect every pre-existing user ID before this temporary stage starts."""
    require(scene not in _TEMPORARY_DATA_OWNERS, "Temporary scene already registered")
    _TEMPORARY_DATA_OWNERS[scene] = {
        "before": {kind: set(getattr(bpy.data, kind)) for kind in TEMPORARY_DATA_TYPES},
        "owned": None,
    }


def seal_temporary_scene(scene) -> None:
    """Freeze this stage's new IDs before a later import/bake stage starts."""
    record = _TEMPORARY_DATA_OWNERS.get(scene)
    if record and record["owned"] is None:
        record["owned"] = {kind: set(getattr(bpy.data, kind)) - record["before"][kind]
                           for kind in TEMPORARY_DATA_TYPES}


@contextmanager
def preserve_ui_state():
    """An export button may run while the animator is posing controls."""
    scene = bpy.context.scene
    active = bpy.context.view_layer.objects.active
    selected = list(bpy.context.selected_objects)
    mode = active.mode if active else "OBJECT"
    frame = scene.frame_current
    if mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    try:
        yield
    finally:
        select_scene(scene)
        scene.frame_set(frame)
        for obj in bpy.context.view_layer.objects:
            obj.select_set(obj in selected)
        bpy.context.view_layer.objects.active = active
        if active and mode != "OBJECT":
            bpy.ops.object.mode_set(mode=mode)


def independent_import(path: Path, *, animation: bool):
    previous_scene = bpy.context.scene
    scene = bpy.data.scenes.new("WARLOCK_FBX_VERIFY")
    register_temporary_scene(scene)
    # A probe scene starts with the expected rate; the importer also reads the
    # file TimeMode metadata. Use zero offset for the normalized clip timeline.
    scene.render.fps = 60
    scene.render.fps_base = 1.0
    select_scene(scene)
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.fbx(filepath=str(path), use_anim=animation,
                                 anim_offset=0.0,
                                 ignore_leaf_bones=False,
                                 automatic_bone_orientation=False)
        objects = [obj for obj in bpy.data.objects if obj not in before]
        armatures = [obj for obj in objects if obj.type == "ARMATURE"]
        require(len(armatures) == 1, "FBX must contain exactly one game armature")
        require(all(obj.type in {"ARMATURE", "EMPTY", "MESH"} for obj in objects),
                "FBX contains unexpected object types")
        seal_temporary_scene(scene)
        return scene, objects, armatures[0]
    except Exception:
        select_scene(previous_scene)
        dispose_scene(scene, [obj for obj in bpy.data.objects if obj not in before])
        raise


def dispose_scene(scene, objects) -> None:
    seal_temporary_scene(scene)
    record = _TEMPORARY_DATA_OWNERS.pop(scene, None)
    for obj in objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.scenes.remove(scene)
    if record:
        # FBX imports deliberately fake-user their actions. Removing only the
        # objects leaves those large actions in an animator's next saved file.
        # Remove only this stage's new orphan IDs; even unused pre-existing
        # user assets are protected by the snapshot, and still-used IDs stay.
        for kind in TEMPORARY_DATA_TYPES:
            collection = getattr(bpy.data, kind)
            for block in record["owned"][kind]:
                if block.users <= int(block.use_fake_user):
                    block.use_fake_user = False
                    collection.remove(block)


def parent_chain(obj) -> list:
    chain = []
    current = obj.parent
    while current:
        require(current.type == "EMPTY" and obj.parent_type == "OBJECT",
                "Only audited EMPTY object wrappers may precede GAME")
        chain.insert(0, current)
        obj = current
        current = current.parent
    return chain


def probe_points(value: Matrix) -> list[Vector]:
    origin = value.translation
    return [origin.copy()] + [value @ (Vector((0, 0, 0)) +
        Vector(tuple(AXIS_PROBE_LENGTH if k == axis else 0 for k in range(3))))
        for axis in range(3)]


def sample_game(scene, game, names, frames):
    select_scene(scene)
    chain = parent_chain(game)
    samples = []
    for frame in frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = game.evaluated_get(depsgraph)
        validate_positive_scale(evaluated, names, frame)
        validate_matrix(evaluated.matrix_world, f"frame {frame} GAME object")
        worlds = {name: evaluated.matrix_world @ evaluated.pose.bones[name].matrix
                  for name in names}
        # The own-skeleton engine aim constraint reads this named constant
        # positional reference. Preserve bone bind/rest, calibrate only the
        # evaluated helper track on the export copy (as shipping clips do).
        root = worlds["root_point"]
        helper_local = root.inverted() @ worlds["aim_target"]
        helper_local.translation = AIM_REFERENCE
        worlds["aim_target"] = root @ helper_local
        for name, value in worlds.items():
            validate_matrix(value, f"frame {frame} {name}")
        samples.append({
            "frame": frame,
            "object": evaluated.matrix_world.copy(),
            "wrappers": [obj.evaluated_get(depsgraph).matrix_world.copy() for obj in chain],
            "bones": worlds,
        })
    return chain, samples


def set_transform(value, matrix: Matrix, label: str) -> None:
    validate_matrix(matrix, label)
    location, rotation, scale = matrix.decompose()
    require(min(scale) > 1e-7, f"{label}: negative/zero decomposed scale")
    reconstructed = Matrix.LocRotScale(location, rotation, scale)
    require(matrix_error(matrix, reconstructed) < 2e-5,
            f"{label}: non-TRS shear cannot be represented in an FBX channel")
    value.rotation_mode = "QUATERNION"
    # Maintain quaternion sign continuity (identical rotation with q/-q may
    # otherwise introduce unnecessary curve crossings on interpolation).
    if value.rotation_quaternion.dot(rotation) < 0:
        rotation.negate()
    value.location, value.rotation_quaternion, value.scale = location, rotation, scale


def key_transform(value, frame: int) -> None:
    for channel in ("location", "rotation_quaternion", "scale"):
        value.keyframe_insert(data_path=channel, frame=frame)


def action_curves(action, obj):
    # Blender 5 uses layered actions/slots; the legacy fcurves accessor was
    # removed. Export only this object's action slot, not a compatible action
    # belonging to an animator control armature.
    if not action:
        return []
    slot = obj.animation_data.action_slot
    return [curve for layer in action.layers for strip in layer.strips
            if strip.type == "KEYFRAME"
            for bag in [strip.channelbag(slot, ensure=False)] if bag
            for curve in bag.fcurves]


def bake_copy(source, chain, samples, names, export_name, source_scene, tracked_scenes=None):
    scene = bpy.data.scenes.new("WARLOCK_ANIMATION_BAKE")
    register_temporary_scene(scene)
    created_objects = []
    if tracked_scenes is not None:
        tracked_scenes.append((scene, created_objects))
    scene.render.fps = source_scene.render.fps
    scene.render.fps_base = source_scene.render.fps_base
    scene.unit_settings.system = source_scene.unit_settings.system
    scene.unit_settings.scale_length = source_scene.unit_settings.scale_length
    scene.frame_start = 0
    scene.frame_end = len(samples) - 1
    select_scene(scene)
    copies = []
    for source_wrapper in chain:
        wrapper = source_wrapper.copy()
        wrapper.animation_data_clear()
        for constraint in list(wrapper.constraints):
            wrapper.constraints.remove(constraint)
        scene.collection.objects.link(wrapper)
        created_objects.append(wrapper)
        wrapper.parent = copies[-1] if copies else None
        wrapper.matrix_parent_inverse = Matrix.Identity(4)
        copies.append(wrapper)
    rig = source.copy()
    rig.data = source.data.copy()
    rig.animation_data_clear()
    rig.name = export_name
    require(rig.name == export_name, f"Export object name is occupied: {export_name}")
    rig.data.name = export_name
    scene.collection.objects.link(rig)
    created_objects.append(rig)
    rig.hide_viewport = rig.hide_render = False
    rig.hide_set(False)
    rig.parent = copies[-1] if copies else None
    rig.matrix_parent_inverse = Matrix.Identity(4)
    for constraint in list(rig.constraints):
        rig.constraints.remove(constraint)
    for modifier in list(rig.modifiers):
        rig.modifiers.remove(modifier)
    for bone in rig.pose.bones:
        for constraint in list(bone.constraints):
            bone.constraints.remove(constraint)
    for frame, sample in enumerate(samples):
        scene.frame_set(frame)
        previous = Matrix.Identity(4)
        for wrapper, world in zip(copies, sample["wrappers"]):
            set_transform(wrapper, previous.inverted() @ world, f"{frame} wrapper")
            key_transform(wrapper, frame)
            previous = world
        set_transform(rig, previous.inverted() @ sample["object"], f"{frame} object")
        key_transform(rig, frame)
        armature_inverse = sample["object"].inverted()
        armature_poses = {name: armature_inverse @ sample["bones"][name] for name in names}
        for name in names:
            bone = rig.data.bones[name]
            pose = rig.pose.bones[name]
            kwargs = {}
            if bone.parent:
                kwargs = {"parent_matrix": armature_poses[bone.parent.name],
                          "parent_matrix_local": bone.parent.matrix_local}
            basis = bone.convert_local_to_pose(
                armature_poses[name], bone.matrix_local, invert=True, **kwargs)
            set_transform(pose, basis, f"{frame} {name} basis")
            key_transform(pose, frame)
        bpy.context.view_layer.update()
        evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
        for name in names:
            actual = evaluated.matrix_world @ evaluated.pose.bones[name].matrix
            require(matrix_error(actual, sample["bones"][name]) < 5e-5,
                    f"Bake changed evaluated {name} at frame {frame}")
    for obj in copies + [rig]:
        for curve in action_curves(obj.animation_data.action, obj):
            for point in curve.keyframe_points:
                point.interpolation = "LINEAR"
    seal_temporary_scene(scene)
    return scene, copies + [rig], rig


def compare_roundtrip(scene, rig, names, rest, samples, tolerance):
    select_scene(scene)
    actual_rest = skeleton(rig, names)
    max_rest_error = 0.0
    for name in names:
        require(actual_rest[name]["parent"] == rest[name]["parent"],
                f"FBX changed {name} parent")
        error = matrix_error(Matrix(actual_rest[name]["rest_matrix"]),
                             Matrix(rest[name]["rest_matrix"]))
        max_rest_error = max(max_rest_error, error)
        require(error <= tolerance, f"FBX changed {name} rest matrix by {error}")
    max_head = max_axis = max_component = 0.0
    worst = {}
    # Export has an explicit zero-start timeline and import uses anim_offset=0.
    # Compare temporal indices, including both first and last frame.
    for index, sample in enumerate(samples):
        imported_frame = index
        scene.frame_set(imported_frame)
        bpy.context.view_layer.update()
        evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
        validate_positive_scale(evaluated, names, imported_frame)
        for name in names:
            actual = evaluated.matrix_world @ evaluated.pose.bones[name].matrix
            expected = sample["bones"][name]
            validate_matrix(actual, f"imported {imported_frame} {name}")
            differences = [(a - b).length for a, b in
                           zip(probe_points(actual), probe_points(expected))]
            head, axes = differences[0], max(differences[1:])
            if max(head, axes) > max(max_head, max_axis):
                worst = {"bone": name, "authored_frame": sample["frame"],
                         "imported_frame": imported_frame, "head_error_m": head,
                         "axis_tip_error_m": axes}
            max_head = max(max_head, head)
            max_axis = max(max_axis, axes)
            max_component = max(max_component, matrix_error(actual, expected))
    result = {"frames": len(samples), "bones_per_frame": len(names),
              "comparisons": len(samples) * len(names),
              "max_rest_matrix_component_error": max_rest_error,
              "max_head_error_m": max_head, "max_axis_tip_error_m": max_axis,
              "max_pose_matrix_component_error": max_component, "worst": worst}
    require(max_head <= tolerance and max_axis <= tolerance,
            f"Independent FBX roundtrip changed pose: {result}")
    return result


def write_animation_fbx(path: Path) -> None:
    """Use bind/rest defaults for bone Models; retain sampled animation curves.

    Blender's animation-only FBX has no mesh-generated BindPose record. Its
    stock Model writer uses the *current* pose as the default joint transform,
    so an independent importer interprets an animated frame as the skeleton
    rest. The official exporter already provides rest=True conversion (used
    for BindPose); scope that conversion to Model writing only. Animation
    sampling and FBX axis/unit conversion remain the official implementation.
    Nothing is changed in Blender's installed exporter files.
    """
    from io_scene_fbx import export_fbx_bin, fbx_utils

    original_writer = export_fbx_bin.fbx_data_object_elements
    original_tx = fbx_utils.ObjectWrapper.fbx_object_tx

    def rest_tx(obj, scene_data, *args, **kwargs):
        if obj.is_bone:
            kwargs["rest"] = True
        return original_tx(obj, scene_data, *args, **kwargs)

    def write_rest_model(root, obj, scene_data):
        fbx_utils.ObjectWrapper.fbx_object_tx = rest_tx
        try:
            return original_writer(root, obj, scene_data)
        finally:
            fbx_utils.ObjectWrapper.fbx_object_tx = original_tx

    export_fbx_bin.fbx_data_object_elements = write_rest_model
    try:
        bpy.ops.export_scene.fbx(filepath=str(path), **FBX_OPTIONS)
    finally:
        export_fbx_bin.fbx_data_object_elements = original_writer
        fbx_utils.ObjectWrapper.fbx_object_tx = original_tx


def run_mutation_checks(scene, rig, names, rest, samples, tolerance):
    """Prove the acceptance gate notices the integration mistakes it guards."""
    checks = []

    def rejected(label, callback):
        try:
            callback()
        except ValueError as error:
            checks.append({"mutation": label, "rejected": True, "reason": str(error)})
        else:
            raise ValueError(f"Validation accepted deliberate mutation: {label}")

    select_scene(scene)
    for label, missing in (("missing shipping bone", True), ("extra control bone", False)):
        mutant = rig.copy()
        mutant.data = rig.data.copy()
        scene.collection.objects.link(mutant)
        bpy.context.view_layer.objects.active = mutant
        mutant.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        if missing:
            mutant.data.edit_bones.remove(mutant.data.edit_bones["aim_target"])
        else:
            bone = mutant.data.edit_bones.new("AUTHORING_HELPER_MUST_NOT_EXPORT")
            bone.head, bone.tail = (0, 0, 0), (0, 0, 0.1)
        bpy.ops.object.mode_set(mode="OBJECT")
        rejected(label, lambda: skeleton(mutant, names))
        mutant_data = mutant.data
        bpy.data.objects.remove(mutant, do_unlink=True)
        bpy.data.armatures.remove(mutant_data)
    bone = rig.pose.bones["j_rightarm"]
    original_scale = bone.scale.copy()
    try:
        # Two negative axes have a positive determinant; the explicit local
        # scale check must reject them as well as an ordinary reflection.
        bone.scale = (-1, -1, 1)
        rejected("two negative scale axes", lambda: validate_positive_scale(rig, names, 0))
    finally:
        bone.scale = original_scale
    singular = Matrix.Identity(4)
    singular[1][1] = 0
    rejected("singular scale", lambda: validate_matrix(singular, "mutation"))
    nonfinite = Matrix.Identity(4)
    nonfinite[0][3] = float("nan")
    rejected("non-finite transform", lambda: validate_matrix(nonfinite, "mutation"))
    original_root = ROOT
    globals()["ROOT"] = Path.home() / "portable-handoff-without-checkout"
    try:
        rejected("production units outside portable ROOT", lambda: validate_output_path(
            Path.home() / "other-project" / "Units" / "candidate.fbx", SOURCE_FBX))
    finally:
        globals()["ROOT"] = original_root
    rejected("portable approved reference overwrite", lambda: validate_output_path(
        REFERENCE_DIR / "candidate.fbx", SOURCE_FBX))
    hypothetical_source = Path.home() / "approved-artist-source.fbx"
    rejected("approved source FBX overwrite", lambda: validate_output_path(
        hypothetical_source, hypothetical_source))
    for label, kind in (("head translation mismatch", "translation"),
                        ("orientation mismatch with unchanged head", "rotation"),
                        ("scale mismatch with unchanged head", "scale")):
        worlds = {name: value.copy() for name, value in samples[0]["bones"].items()}
        reference = worlds["j_rightarm"]
        if kind == "translation":
            reference.translation.x += 0.01
        else:
            change = Matrix.Rotation(0.2, 4, "Y") if kind == "rotation" else Matrix.Diagonal((1.2, 0.9, 1.0, 1.0))
            worlds["j_rightarm"] = reference @ change
        mutated = [{**samples[0], "bones": worlds}]
        rejected(label, lambda: compare_roundtrip(scene, rig, names, rest, mutated, tolerance))
    return checks


def _export_animation(args, source_dirty_at_start=False) -> dict:
    require(0 < args.tolerance <= 5e-5, "Roundtrip tolerance must not exceed 50 micrometres")
    source_scene = bpy.context.scene
    initial_frame = source_scene.frame_current
    game = bpy.data.objects.get(args.game_armature)
    names = required_names()
    rest = skeleton(game, names)
    require(args.end >= args.start, "Clip end precedes its start")
    fps = source_scene.render.fps / source_scene.render.fps_base
    require(abs(fps - 60) < 1e-6, f"Animator scene must be 60 fps, got {fps}")
    require(abs(source_scene.unit_settings.scale_length - 1.0) < 1e-6,
            "Animator scene units must retain the approved 1.0 scale")
    source_fbx = args.source_fbx.resolve()
    if game.get("source_fbx_sha256"):
        require(game["source_fbx_sha256"] == sha256(source_fbx),
                "Approved reference FBX no longer matches GAME provenance")
    # Establish a fresh shipping-FBX import, rather than trusting a manifest
    # supplied by the scene being validated.
    baseline_scene, baseline_objects, baseline = independent_import(source_fbx, animation=False)
    try:
        baseline_rest = skeleton(baseline, names)
        # Object identity is independently audited; Blender import collisions
        # must not leak a .001 suffix into the exported FBX wrapper.
        export_name = "armature object.008"
        for name in names:
            require(rest[name]["parent"] == baseline_rest[name]["parent"],
                    f"Animator GAME hierarchy differs from shipping: {name}")
            require(matrix_error(Matrix(rest[name]["rest_matrix"]),
                                 Matrix(baseline_rest[name]["rest_matrix"])) < 1e-6,
                    f"Animator GAME bind/rest differs from shipping: {name}")
            for setting in ("inherit_scale", "use_local_location", "use_inherit_rotation"):
                require(rest[name][setting] == baseline_rest[name][setting],
                        f"Animator changed {name} {setting}")
        require(game.parent is None and baseline.parent is None,
                "Shipping GAME has no object parent; animator added an export wrapper")
        require(matrix_error(game.matrix_world, baseline.matrix_world) < 1e-6,
                "Animator GAME object wrapper differs from shipping")
    finally:
        select_scene(source_scene)
        dispose_scene(baseline_scene, baseline_objects)
    chain, samples = sample_game(source_scene, game, names,
                                 range(args.start, args.end + 1))
    output = args.output.resolve()
    if output.suffix.lower() != ".fbx":
        output = output / "warlock_animation_probe.fbx"
    validate_output_path(output, source_fbx)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output.with_suffix(".export.json")
    manifest = {
        "schema": 1, "status": "pending", "purpose": "isolated animator animation export",
        "blender_version": bpy.app.version_string, "source_rig": bpy.data.filepath,
        "source_rig_disk_sha256": sha256(Path(bpy.data.filepath)) if bpy.data.filepath else None,
        "source_scene_contains_unsaved_changes": source_dirty_at_start,
        "export_script_sha256": sha256(Path(__file__)),
        "shipping_fbx": str(source_fbx), "shipping_sha256": sha256(source_fbx),
        "shipping_bones_sha256": sha256(BONES_PATH), "bone_names": names,
        "export_armature_name": export_name, "fps": fps,
        "frame_start": args.start, "frame_end": args.end,
        "exported_frame_start": 0, "exported_frame_end": len(samples) - 1,
        "rest_contract": rest, "position_tolerance_m": args.tolerance,
        "axis_probe_length_m": AXIS_PROBE_LENGTH,
        "aim_reference": {"bone": "aim_target", "parent": "root_point",
                          "constant_local_translation": list(AIM_REFERENCE),
                          "bind_rest_unchanged": True},
        "fbx_options": {key: sorted(value) if isinstance(value, set) else value
                        for key, value in FBX_OPTIONS.items()},
        "fbx_model_defaults": "official exporter rest=True bone transforms; animation curves unchanged",
        "animation_compression": COMPRESSION_TOLERANCES,
        "compression_reference": "https://help.autodesk.com/cloudhelp/ENU/Stingray-Help/stingray_help/animation/anim_clip_properties.html",
        "reference_samples": [{"frame": s["frame"], "object_world": matrix_json(s["object"]),
            "bones_world": {name: matrix_json(s["bones"][name]) for name in names}}
            for s in samples],
        "game_runtime_acceptance": "pending; FBX and SDK checks cannot establish in-game appearance",
    }
    temporary_scenes = []
    occupied = bpy.data.objects.get(export_name)
    occupied_name = occupied.name if occupied else None
    if occupied:
        occupied.name = "AUTHORING_RESERVED_EXPORT_IDENTITY"
    try:
        with scratch_directory("warlock-animation-", output.parent) as temporary:
            temporary_fbx = Path(temporary) / output.name
            temporary_sidecar = Path(temporary) / output.with_suffix(".animation").name
            temporary_manifest = Path(temporary) / manifest_path.name
            temporary_sidecar.write_text(SIDE_CAR, encoding="utf-8", newline="\n")
            manifest["animation_compression"] = validate_sidecar(temporary_sidecar)
            bake_scene, bake_objects, baked = bake_copy(
                game, chain, samples, names, export_name, source_scene, temporary_scenes)
            select_scene(bake_scene)
            for obj in bake_scene.objects:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = baked
            write_animation_fbx(temporary_fbx)
            roundtrip_scene, imported, reimported = independent_import(temporary_fbx, animation=True)
            temporary_scenes.append((roundtrip_scene, imported))
            require(all(obj.type != "MESH" for obj in imported),
                    "Animation FBX unexpectedly contains a mesh")
            manifest["roundtrip"] = compare_roundtrip(
                roundtrip_scene, reimported, names, rest, samples, args.tolerance)
            manifest["mutation_checks"] = run_mutation_checks(
                roundtrip_scene, reimported, names, rest, samples, args.tolerance)
            manifest["publication_checks"] = run_publication_checks(output.parent)
            manifest["fbx_sha256"] = sha256(temporary_fbx)
            manifest["fbx_bytes"] = temporary_fbx.stat().st_size
            manifest["animation_path"] = str(output.with_suffix(".animation"))
            manifest["animation_sha256"] = sha256(temporary_sidecar)
            manifest["status"] = "fbx-roundtrip-passed"
            manifest["fbx_path"] = str(output)
            temporary_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
            publish_bundle([(temporary_sidecar, output.with_suffix(".animation")),
                            (temporary_fbx, output), (temporary_manifest, manifest_path)])
    except Exception as error:
        manifest["status"] = "failed"
        manifest["failure"] = str(error)
        # A failed attempt must not replace the previous successful receipt.
        output.with_suffix(".export.failure.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
        raise
    finally:
        select_scene(source_scene)
        for scene, objects in reversed(temporary_scenes):
            dispose_scene(scene, objects)
        if occupied:
            occupied.name = occupied_name
        source_scene.frame_set(initial_frame)
    print("WARLOCK_ANIMATION_EXPORT", json.dumps({key: value for key, value in manifest.items()
          if key not in {"reference_samples", "rest_contract", "bone_names", "fbx_options"}}))
    return manifest


def export_animation(args) -> dict:
    if args.rig:
        bpy.ops.wm.open_mainfile(filepath=str(args.rig.resolve()), use_scripts=False)
    # Blender marks a file opened headless as dirty before any edit, so a
    # freshly opened --rig cannot carry unsaved changes.
    source_dirty_at_start = False if args.rig else bpy.data.is_dirty
    with preserve_ui_state():
        return _export_animation(args, source_dirty_at_start)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rig", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=61)
    parser.add_argument("--game-armature", default="WARLOCK_GAME")
    parser.add_argument("--source-fbx", type=Path, default=SOURCE_FBX)
    parser.add_argument("--tolerance", type=float, default=5e-5)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parser.parse_args(argv)
    require(0 < args.tolerance <= 5e-5, "Roundtrip tolerance must not exceed 50 micrometres")
    export_animation(args)


if __name__ == "__main__":
    main()
