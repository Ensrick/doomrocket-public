# SPDX-License-Identifier: GPL-2.0-or-later
"""Optional animator panel for WARLOCK_CTRL; install or run this script manually.

The control rig and its drivers work with Blender auto-execution disabled.
This UI never executes text datablocks from a supplied blend. Transform matching
is a reviewed subset of Blender Rigify's generated single-frame snap helpers,
adapted to the existing Warlock Rigify rig. The game armature is never edited.
"""
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper
from mathutils import Matrix, Vector

bl_info = {
    "name": "Warlock Engineer Animator Controls",
    "author": "Warlock Engineer maintainers; snap helpers from Blender Rigify",
    "version": (1, 0, 0),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar > Warlock",
    "description": "Pose controls, FK/IK matching and verified animation export",
    "category": "Animation",
}


def limb_map(side, region):
    """Exact chain mapping from the existing rig's generated Rigify UI."""
    stem = f"j_{side}"
    if region == "arm":
        return {
            "prop": stem + "arm_ctrl_parent",
            "fk": [stem + b for b in ("arm_ctrl_fk", "forearm_ctrl_fk", "hand_ctrl_fk")],
            "ik": [stem + "arm_ctrl_ik", "MCH-" + stem + "forearm_ctrl_ik",
                   "MCH-" + stem + "arm_ctrl_ik_target"],
            "ctrl": [stem + b for b in ("arm_ctrl_ik", "arm_ctrl_ik_target", "hand_ctrl_ik")],
        }
    return {
        "prop": stem + "upleg_ctrl_parent",
        "fk": [stem + b for b in ("upleg_ctrl_fk", "leg_ctrl_fk", "foot_ctrl_fk", "foot_ctrl_fk")],
        "ik": ["MCH-" + stem + b for b in
               ("upleg_ctrl_ik", "leg_ctrl_ik", "upleg_ctrl_ik_target", "upleg_ctrl_ik_target")],
        "ctrl": [stem + b for b in
                 ("upleg_ctrl_ik", "upleg_ctrl_ik_target", "foot_ctrl_heel_ik", "foot_ctrl_ik")],
    }


LIMBS = {f"{side}_{region}": limb_map(side, region)
         for side in ("left", "right") for region in ("arm", "leg")}


def rig_for_context(context):
    obj = context.active_object
    if obj and obj.type == "ARMATURE" and (
            obj.name == "WARLOCK_CTRL" or obj.get("warlock_control_manifest")):
        return obj
    return None


def control_names(rig):
    # The salvaged rig's ORG bones are normally mechanisms, but the authoring
    # builder deliberately promotes existing finger/face/accessory channels
    # to curve controls. Only the explicit manifest may make that exception.
    explicit = set()
    try:
        groups = json.loads(rig.get("warlock_control_manifest", "{}")).get("groups", {})
        if isinstance(groups, dict):
            explicit = {name for names in groups.values() if isinstance(names, list) for name in names}
    except (TypeError, ValueError):
        pass
    return [b.name for b in rig.pose.bones
            if ((b.custom_shape and (not b.name.startswith("ORG-") or b.name in explicit))
                or b.name.startswith("CTRL-"))
            and not b.name.startswith(("VIS_", "DEF-", "MCH-"))]


def control_groups(rig):
    try:
        manifest = json.loads(rig.get("warlock_control_manifest", "{}"))
        groups = manifest.get("groups", {})
        if isinstance(groups, dict) and groups:
            return {label: [name for name in names if name in rig.pose.bones]
                    for label, names in groups.items() if isinstance(names, list)}
    except (TypeError, ValueError):
        pass
    controls = control_names(rig)
    groups = {"Body": [n for n in controls if n in
              {"root", "torso", "hips", "chest"} or "spine" in n],
              "Tail": [n for n in controls if "tail" in n],
              "Accessories and fingers": [n for n in controls if n.startswith("CTRL-")],
              "Tweak": [n for n in controls if "tweak" in n]}
    for label, mapping in LIMBS.items():
        groups[label.replace("_", " ").title()] = list(dict.fromkeys(
            [mapping["prop"], *mapping["fk"], *mapping["ctrl"]]))
    return {label: names for label, names in groups.items() if names}


def key_control(bone):
    """Key unlocked channels and animator custom properties, respecting mode."""
    for path, locks in (("location", bone.lock_location), ("scale", bone.lock_scale)):
        if path == "location" and bone.bone.use_connect:
            continue
        for axis, locked in enumerate(locks):
            if not locked:
                bone.keyframe_insert(path, index=axis, group=bone.name)
    path = {"QUATERNION": "rotation_quaternion",
            "AXIS_ANGLE": "rotation_axis_angle"}.get(bone.rotation_mode, "rotation_euler")
    locks = list(bone.lock_rotation)
    if path != "rotation_euler":
        locks = ([bone.lock_rotation_w, *locks] if bone.lock_rotations_4d
                 else [all(locks)] * 4)
    for axis, locked in enumerate(locks):
        if not locked:
            bone.keyframe_insert(path, index=axis, group=bone.name)
    for prop in bone.keys():
        if isinstance(bone[prop], (int, float, bool)) and not prop.startswith("_"):
            bone.keyframe_insert("[" + json.dumps(prop) + "]", group=bone.name)


# Small audited subset of the generated Rigify transformation/snap utilities.
def target_matrix(con):
    obj = con.target
    if obj and obj.type == "ARMATURE" and con.subtarget in obj.pose.bones:
        bone = obj.pose.bones[con.subtarget]
        return obj.convert_space(pose_bone=bone, matrix=bone.matrix,
                                 from_space="POSE", to_space=con.target_space)
    if obj:
        return obj.convert_space(matrix=obj.matrix_world, from_space="WORLD",
                                 to_space=con.target_space)
    return Matrix.Identity(4)


def undo_scale(bone, matrix):
    for con in reversed(bone.constraints):
        if (con.type != "COPY_SCALE" or con.mute or not con.is_valid or
                con.influence == 0 or not con.use_offset or con.use_add):
            continue
        target = target_matrix(con)
        scale = list(target.to_scale())
        use = (con.use_x, con.use_y, con.use_z)
        if con.use_make_uniform:
            total = target.determinant() if all(use) else math.prod(
                value for value, enabled in zip(scale, use) if enabled)
            scale = [abs(total) ** (1 / 3)] * 3
        else:
            scale = [value if enabled else 1 for value, enabled in zip(scale, use)]
        factors = [1 / (1 + (value ** con.power - 1) * con.influence) for value in scale]
        matrix = matrix @ Matrix.Diagonal([*factors, 1])
    return matrix


def set_transform(rig, name, matrix, *, no_rot=False, no_scale=False,
                  undo_copy_scale=False, local=False):
    bone = rig.pose.bones[name]
    paths = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")
    old = {path: tuple(getattr(bone, path)) for path in paths}
    if not local:
        matrix = rig.convert_space(pose_bone=bone, matrix=matrix,
                                   from_space="POSE", to_space="LOCAL")
    if undo_copy_scale:
        matrix = undo_scale(bone, matrix)
    bone.matrix_basis = matrix
    active_rot = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}.get(
        bone.rotation_mode, "rotation_euler")
    for path in paths:
        if path.startswith("rotation_") and path != active_rot:
            setattr(bone, path, old[path])
            continue
        locks = bone.lock_location if path == "location" else bone.lock_scale if path == "scale" else bone.lock_rotation
        if path == active_rot and path != "rotation_euler":
            locks = ([bone.lock_rotation_w, *locks] if bone.lock_rotations_4d
                     else [all(locks)] * 4)
        whole = (path == "location" and bone.bone.use_connect) or (
            path == "scale" and no_scale) or (path == active_rot and no_rot)
        values = list(getattr(bone, path))
        setattr(bone, path, [saved if whole or lock else current
                            for current, saved, lock in zip(values, old[path], locks)])


def rest_delta(matrix, source, target):
    return matrix @ source.bone.matrix_local.inverted() @ target.bone.matrix_local


def pose_delta(matrix, source, target):
    return matrix @ source.matrix.inverted() @ target.matrix


def rotation_difference(a, b):
    angle = 2 * math.acos(max(-1, min(1, a.to_quaternion().dot(b.to_quaternion()))))
    return min(angle, 2 * math.pi - angle)


def correct_rotation(view, bone, matrix, control):
    axis = matrix.to_3x3().col[1].normalized()
    if control.rotation_mode in {"QUATERNION", "AXIS_ANGLE"}:
        control.rotation_mode = "ZXY"

    def error(angle):
        control.rotation_euler.y = angle
        view.update()
        # Vector distance retains precision close to alignment; dot products
        # round to 1 early and caused a measurable snap pop in this rig.
        return (bone.vector.normalized() - axis).length_squared

    start = control.rotation_euler.y
    step = math.pi / 8
    center = start
    for _ in range(33):
        if error(center) <= min(error(center - step), error(center + step)):
            break
        center += step
    left, right = center - step, center + step
    for _ in range(60):
        if right - left < 1e-7:
            break
        a, b = left + (right - left) / 3, right - (right - left) / 3
        if error(a) > error(b):
            left = a
        else:
            right = b
    control.rotation_euler.y = (left + right) / 2
    view.update()


def correct_scale(view, bone, matrix, control):
    desired = matrix.to_scale()
    for _ in range(5):
        current = bone.matrix.to_scale()
        control.scale = [value * want / got for value, want, got in
                         zip(control.scale, desired, current)]
        view.update()
        if max(abs(got - want) for got, want in zip(bone.matrix.to_scale(), desired)) < 1e-6:
            break


def match_pole(view, first, last, pole, matrix):
    a, b = first.matrix.translation, last.matrix.translation + last.vector
    axis = b - a
    other = Vector((1, 0, 0)) if abs(axis.x) < abs(axis.y) else Vector((0, 1, 0))
    perpendicular = axis.cross(other).normalized() * (first.length + last.length)

    def place(offset):
        local = pole.id_data.convert_space(pose_bone=pole,
            matrix=Matrix.Translation(a + axis / 2 + offset), from_space="POSE", to_space="LOCAL")
        pole.location = local.translation
        view.update()

    place(perpendicular)
    angle = rotation_difference(first.matrix, matrix)
    one, two = (Matrix.Rotation(sign * angle, 4, axis) @ perpendicular for sign in (1, -1))
    place(one)
    error_one = rotation_difference(first.matrix, matrix)
    place(two)
    if error_one < rotation_difference(first.matrix, matrix):
        place(one)


def snap_to_ik(context, rig, mapping):
    """Match IK controls to the evaluated FK chain before switching to IK."""
    matrices = [rig.pose.bones[name].matrix.copy() for name in mapping["fk"]]
    ik = [rig.pose.bones[name] for name in mapping["ik"]]
    ctrl = [rig.pose.bones[name] for name in mapping["ctrl"]]
    use_pole = bool(rig.pose.bones[mapping["prop"]].get("pole_vector", False))
    context.view_layer.update()
    end = pose_delta(matrices[-1], ik[-1], ctrl[-1])
    set_transform(rig, ctrl[-1].name, end, undo_copy_scale=True)
    ctrl[0].matrix_basis = Matrix.Identity(4)
    set_transform(rig, ctrl[0].name, matrices[0], no_scale=True, no_rot=use_pole)

    def middle(lock):
        for matrix, src, dst in reversed(list(zip(matrices[2:-1], ik[2:-1], ctrl[2:-1]))):
            dst.bone.use_inherit_rotation = not lock
            dst.bone.inherit_scale = "NONE" if lock else "FULL"
            context.view_layer.update()
            set_transform(rig, dst.name, rest_delta(matrix, src, dst))

    middle(True)
    context.view_layer.update()
    if use_pole:
        match_pole(context.view_layer, ik[0], ik[1], ctrl[1], matrices[0])
    else:
        correct_rotation(context.view_layer, ik[0], matrices[0], ctrl[0])
    correct_scale(context.view_layer, ik[0], matrices[0], ctrl[0])
    middle(False)


def snap_to_fk(context, rig, mapping):
    """Match FK controls to evaluated IK result before switching to FK."""
    matrices = [rig.pose.bones[name].matrix.copy() for name in mapping["ik"]]
    for name, matrix in zip(mapping["fk"], matrices):
        set_transform(rig, name, matrix)
        context.view_layer.update()


def snapshot_controls(rig):
    result = {}
    for name in control_names(rig):
        bone = rig.pose.bones[name]
        result[name] = (bone.matrix_basis.copy(), bone.rotation_mode,
                       bone.bone.use_inherit_rotation, bone.bone.inherit_scale,
                       {p: bone[p] for p in bone.keys() if isinstance(bone[p], (int, float, bool))})
    return result


def restore_controls(rig, saved):
    for name, (matrix, mode, inherit_rot, inherit_scale, props) in saved.items():
        bone = rig.pose.bones[name]
        bone.rotation_mode = mode
        bone.bone.use_inherit_rotation = inherit_rot
        bone.bone.inherit_scale = inherit_scale
        bone.matrix_basis = matrix
        for prop, value in props.items():
            bone[prop] = value
    rig.update_tag()
    bpy.context.view_layer.update()


def game_pose(rig):
    game = bpy.data.objects.get(rig.get("warlock_game_armature", "WARLOCK_GAME"))
    if game is None:
        game = bpy.data.objects.get("armature object.008")
    if game is None or game.type != "ARMATURE":
        raise RuntimeError("The preserved Warlock GAME armature is missing")
    evaluated = game.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return {b.name: (evaluated.matrix_world @ b.matrix).copy() for b in evaluated.pose.bones}


def pose_error(a, b):
    """Compare all game heads and three 10 cm axis probes, in metres."""
    probes = (Vector((0, 0, 0)), Vector((.1, 0, 0)), Vector((0, .1, 0)), Vector((0, 0, .1)))
    return max(((a[name] @ point) - (b[name] @ point)).length
               for name in a for point in probes)


def switch_limb(context, rig, limb, mode):
    mapping = LIMBS[limb]
    desired = 0.0 if mode == "IK" else 1.0
    prop = rig.pose.bones[mapping["prop"]]
    if abs(prop["IK_FK"] - desired) < 1e-8:
        return 0.0
    saved = snapshot_controls(rig)
    before = game_pose(rig)
    toe_name = "j_" + limb.split("_", 1)[0] + "toebase_ctrl"
    toe_matrix = (rig.pose.bones[toe_name].matrix.copy()
                  if limb.endswith("_leg") and toe_name in rig.pose.bones else None)
    try:
        (snap_to_ik if mode == "IK" else snap_to_fk)(context, rig, mapping)
        prop["IK_FK"] = desired
        rig.update_tag()
        context.view_layer.update()
        # The inherited generated UI omitted its separately parented toe
        # control. Match its visual frame after the parent switches modes.
        if toe_matrix is not None:
            set_transform(rig, toe_name, toe_matrix)
            rig.update_tag()
            context.view_layer.update()
        error = pose_error(before, game_pose(rig))
        # Fail closed: a pose that cannot be matched must not silently jump.
        if error > .0005:
            raise RuntimeError(f"{limb} could not preserve the pose ({error * 1000:.3f} mm); undoing switch")
        if context.scene.tool_settings.use_keyframe_insert_auto:
            for name in set(mapping["fk"] + mapping["ctrl"] + [mapping["prop"]]
                            + ([toe_name] if toe_matrix is not None else [])):
                key_control(rig.pose.bones[name])
        return error
    except Exception:
        restore_controls(rig, saved)
        raise


class WARLOCK_OT_switch_limb(bpy.types.Operator):
    bl_idname = "warlock.switch_limb"
    bl_label = "Match and switch FK/IK"
    bl_options = {"REGISTER", "UNDO"}
    limb: EnumProperty(items=[(name, name.replace("_", " ").title(), "") for name in LIMBS])
    mode: EnumProperty(items=[("IK", "Use IK", "Match IK to current pose, then use IK"),
                              ("FK", "Use FK", "Match FK to current pose, then use FK")])

    @classmethod
    def poll(cls, context):
        return rig_for_context(context) is not None and context.mode == "POSE"

    def execute(self, context):
        try:
            error = switch_limb(context, rig_for_context(context), self.limb, self.mode)
            self.report({"INFO"}, f"{self.limb}: {self.mode}, game pose error {error * 1000:.3f} mm")
            return {"FINISHED"}
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class WARLOCK_OT_select_controls(bpy.types.Operator):
    bl_idname = "warlock.select_controls"
    bl_label = "Select animator controls"
    bl_options = {"REGISTER", "UNDO"}
    group: StringProperty(default="All")
    extend: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return WARLOCK_OT_switch_limb.poll(context)

    def execute(self, context):
        rig = rig_for_context(context)
        groups = control_groups(rig)
        if self.group != "All" and self.group not in groups:
            self.report({"WARNING"}, f"Unknown control group: {self.group}")
            return {"CANCELLED"}
        names = control_names(rig) if self.group == "All" else groups[self.group]
        if not self.extend:
            for bone in rig.pose.bones:
                bone.select = False
        for name in names:
            bone = rig.data.bones[name]
            for collection in bone.collections:
                collection.is_visible = True
            bone.hide = False
            rig.pose.bones[name].select = True
        if names:
            rig.data.bones.active = rig.data.bones[names[0]]
        return {"FINISHED"}


class WARLOCK_OT_reset_controls(bpy.types.Operator):
    bl_idname = "warlock.reset_controls"
    bl_label = "Reset controls to neutral"
    bl_description = "Reset current control transforms/properties; existing keys remain"
    bl_options = {"REGISTER", "UNDO"}
    all_controls: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return WARLOCK_OT_switch_limb.poll(context)

    def execute(self, context):
        rig = rig_for_context(context)
        names = control_names(rig)
        if not self.all_controls:
            names = [name for name in names if rig.pose.bones[name].select]
        try:
            defaults = json.loads(rig.get("warlock_control_defaults", "{}"))
        except (ValueError, TypeError):
            defaults = {}
        for name in names:
            bone = rig.pose.bones[name]
            bone.matrix_basis = Matrix.Identity(4)
            for prop in bone.keys():
                if isinstance(bone[prop], (float, int, bool)):
                    default = defaults.get(name, {}).get(prop,
                        bone.id_properties_ui(prop).as_dict().get("default", bone[prop]))
                    bone[prop] = default
            if context.scene.tool_settings.use_keyframe_insert_auto:
                key_control(bone)
        rig.update_tag()
        context.view_layer.update()
        return {"FINISHED"}


class WARLOCK_OT_key_controls(bpy.types.Operator):
    bl_idname = "warlock.key_controls"
    bl_label = "Key selected controls"
    bl_options = {"REGISTER", "UNDO"}
    all_controls: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return WARLOCK_OT_switch_limb.poll(context)

    def execute(self, context):
        rig = rig_for_context(context)
        for name in control_names(rig):
            if self.all_controls or rig.pose.bones[name].select:
                key_control(rig.pose.bones[name])
        return {"FINISHED"}


def exporter_path(rig):
    # Handoff folders are intended to move to another workstation. Prefer
    # their adjacent audited tools over paths remembered on this workstation.
    candidates = []
    if "__file__" in globals():
        candidates.append(Path(__file__).resolve().with_name("export_animation.py"))
    if bpy.data.filepath:
        candidates.append(Path(bpy.data.filepath).parent / "export_animation.py")
    directory = rig.get("warlock_tools_directory")
    if directory:
        candidates.append(Path(directory) / "export_animation.py")
    return next((path for path in candidates if path.is_file()),
                candidates[0] if candidates else Path("export_animation.py"))


class WARLOCK_OT_export_animation(bpy.types.Operator, ExportHelper):
    bl_idname = "warlock.export_animation"
    bl_label = "Export verified animation FBX"
    bl_description = "Bake only GAME bones and independently verify the FBX roundtrip"
    filename_ext = ".fbx"
    filter_glob: StringProperty(default="*.fbx", options={"HIDDEN"})
    start: IntProperty(name="Start frame", default=1)
    end: IntProperty(name="End frame", default=61)

    @classmethod
    def poll(cls, context):
        return rig_for_context(context) is not None

    def invoke(self, context, event):
        self.start = context.scene.frame_start
        self.end = context.scene.frame_end
        return super().invoke(context, event)

    def draw(self, context):
        self.layout.prop(self, "start")
        self.layout.prop(self, "end")

    def execute(self, context):
        rig = rig_for_context(context)
        path = exporter_path(rig)
        if not path.is_file():
            self.report({"ERROR"}, f"Place export_animation.py beside this UI script: {path}")
            return {"CANCELLED"}
        try:
            spec = importlib.util.spec_from_file_location("warlock_verified_exporter", path)
            exporter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(exporter)
            reference = path.parent / "reference" / "shipping_body.fbx"
            source = reference if reference.is_file() else rig.get("warlock_shipping_fbx")
            args = SimpleNamespace(rig=None, output=Path(self.filepath), start=self.start,
                end=self.end, game_armature=rig.get("warlock_game_armature", "WARLOCK_GAME"),
                source_fbx=Path(source) if source else exporter.SOURCE_FBX, tolerance=5e-5)
            exporter.export_animation(args)
            self.report({"INFO"}, "Animation FBX roundtrip passed; runtime acceptance is still pending")
            return {"FINISHED"}
        except Exception as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}


class WARLOCK_PT_animator(bpy.types.Panel):
    bl_label = "Warlock Engineer"
    bl_idname = "WARLOCK_PT_animator"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Warlock"

    @classmethod
    def poll(cls, context):
        return rig_for_context(context) is not None

    def draw(self, context):
        layout = self.layout
        rig = rig_for_context(context)
        if context.mode != "POSE":
            layout.label(text="Enter Pose Mode to animate", icon="INFO")
            return
        row = layout.row(align=True)
        row.operator("warlock.select_controls", text="Select all").group = "All"
        row.operator("warlock.key_controls", text="Key selected")
        row = layout.row(align=True)
        row.operator("warlock.reset_controls", text="Reset selected")
        row.operator("warlock.reset_controls", text="Reset all").all_controls = True
        layout.label(text="FK/IK buttons preserve the current pose")
        for name, mapping in LIMBS.items():
            box = layout.box()
            box.label(text=name.replace("_", " ").title())
            settings = rig.pose.bones.get(mapping["prop"])
            if settings is None:
                continue
            box.prop(settings, '["IK_FK"]', text="Blend (0 IK / 1 FK)", slider=True)
            row = box.row(align=True)
            for mode in ("IK", "FK"):
                button = row.operator("warlock.switch_limb", text=f"Use {mode}")
                button.limb, button.mode = name, mode
            for prop, label in (("IK_Stretch", "IK stretch"), ("FK_limb_follow", "FK follow")):
                if prop in settings:
                    box.prop(settings, "[" + json.dumps(prop) + "]", text=label, slider=True)
        box = layout.box()
        box.label(text="Select control group")
        for label in control_groups(rig):
            box.operator("warlock.select_controls", text=label).group = label
        selected = context.active_pose_bone
        if selected and selected.name in control_names(rig):
            box = layout.box()
            box.label(text=selected.name)
            for prop in selected.keys():
                if isinstance(selected[prop], (int, float, bool)) and not prop.startswith("_"):
                    box.prop(selected, "[" + json.dumps(prop) + "]", text=prop.replace("_", " "))
        layout.separator()
        layout.operator("warlock.export_animation", icon="EXPORT")


CLASSES = (WARLOCK_OT_switch_limb, WARLOCK_OT_select_controls, WARLOCK_OT_reset_controls,
           WARLOCK_OT_key_controls, WARLOCK_OT_export_animation, WARLOCK_PT_animator)


def register():
    # Manual Run Script can be repeated without duplicate registration errors.
    for cls in CLASSES:
        old = getattr(bpy.types, cls.__name__, None)
        if old:
            bpy.utils.unregister_class(old)
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        old = getattr(bpy.types, cls.__name__, None)
        if old:
            bpy.utils.unregister_class(old)


if __name__ == "__main__":
    register()
