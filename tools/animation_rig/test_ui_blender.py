"""Exercise the actual animator rig and optional UI in Blender 5.2.

blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python test_ui_blender.py -- --rig WarlockEngineer_AnimationRig.blend \
  --output ui_test.json

Loads with embedded scripts disabled and changes only the in-memory scene.
It never saves the supplied blend. Adjacent warlock_rig_ui.py is the only UI
module loaded. Reports measured errors for all 138 shipping GAME bones.
"""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import bpy
from mathutils import Matrix


@contextmanager
def flat_scratch(prefix, directory=None):
    """mkdtemp folder whose flat files are removed by explicit path; never rmtree."""
    folder = Path(tempfile.mkdtemp(prefix=prefix, dir=directory))
    try:
        yield str(folder)
    finally:
        for entry in folder.iterdir():
            if entry.is_file() and not entry.is_symlink():
                entry.unlink()
        folder.rmdir()


class RigUITests:
    def __init__(self, args):
        self.rig_path = args.rig.resolve()
        self.rig_sha256 = hashlib.sha256(self.rig_path.read_bytes()).hexdigest()
        bpy.ops.wm.open_mainfile(filepath=str(args.rig.resolve()), use_scripts=False)
        module_path = Path(__file__).resolve().with_name("warlock_rig_ui.py")
        spec = importlib.util.spec_from_file_location("warlock_ui_tested", module_path)
        self.ui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ui)
        self.rig = bpy.data.objects["WARLOCK_CTRL"]
        game = bpy.data.objects[self.rig.get("warlock_game_armature", "WARLOCK_GAME")]
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in bpy.context.scene.objects:
            obj.select_set(False)
        self.rig.hide_set(False)
        self.rig.select_set(True)
        bpy.context.view_layer.objects.active = self.rig
        bpy.ops.object.mode_set(mode="POSE")
        for obj in (self.rig, game):
            if obj.animation_data:
                obj.animation_data.action = None
        for bone in self.rig.pose.bones:
            bone.matrix_basis = Matrix.Identity(4)
        self.rig.update_tag()
        bpy.context.view_layer.update()
        self.neutral = self.ui.snapshot_controls(self.rig)
        self.groups = self.ui.control_groups(self.rig)
        assert self.groups, "The animator rig has no control groups"
        self.ui.register()
        self.ui.register()  # Manual Run Script must remain repeatable.
        self.results = {"blender": bpy.app.version_string,
                        "rig": str(args.rig.resolve()), "ui_script": str(module_path),
                        "rig_sha256": self.rig_sha256,
                        "ui_sha256": hashlib.sha256(module_path.read_bytes()).hexdigest(),
                        "tests": [], "failures": [], "game_bones_checked": len(game.data.bones)}

    def reset(self):
        if self.rig.animation_data:
            self.rig.animation_data.action = None
        bpy.context.scene.tool_settings.use_keyframe_insert_auto = False
        self.ui.restore_controls(self.rig, self.neutral)

    def run(self, name, function):
        try:
            detail = function()
            result = {"name": name, "passed": True, "detail": detail}
        except Exception as error:
            result = {"name": name, "passed": False, "error": str(error)}
            self.results["failures"].append(name)
        self.results["tests"].append(result)
        print("WARLOCK_UI_TEST", json.dumps(result))

    def switch_test(self, limb, source, pole):
        self.reset()
        rig, ui = self.rig, self.ui
        mapping = ui.LIMBS[limb]
        rig.pose.bones[mapping["prop"]]["IK_FK"] = 0.0 if source == "IK" else 1.0
        rig.pose.bones[mapping["prop"]]["pole_vector"] = pole
        rig.pose.bones["root"].location.x = .17
        rig.pose.bones["torso"].rotation_mode = "XYZ"
        rig.pose.bones["torso"].rotation_euler.z = .13
        if source == "IK":
            end = rig.pose.bones[mapping["ctrl"][-1]]
            end.location = (.05, -.05, .04)
            end.rotation_mode = "XYZ"
            end.rotation_euler.z = .11
            if limb.endswith("leg"):
                heel = rig.pose.bones[mapping["ctrl"][2]]
                heel.rotation_mode = "XYZ"
                heel.rotation_euler.x = .17
        else:
            for index, name in enumerate(dict.fromkeys(mapping["fk"])):
                bone = rig.pose.bones[name]
                bone.rotation_mode = "XYZ"
                bone.rotation_euler.x = (.25, .37, -.13)[index]
                # Keep the elbow/knee on its hinge; the separate negative
                # test verifies that nonrepresentable FK poses roll back.
                bone.rotation_euler.z = .16 if index == 0 else .24 if index == 2 else 0
        rig.update_tag()
        bpy.context.view_layer.update()
        before = ui.game_pose(rig)
        target = "FK" if source == "IK" else "IK"
        error = ui.switch_limb(bpy.context, rig, limb, target)
        actual = ui.pose_error(before, ui.game_pose(rig))
        assert actual < .0005, f"Game probe error {actual} exceeds 0.5 mm"
        assert rig.pose.bones[mapping["prop"]]["IK_FK"] == (1.0 if target == "FK" else 0.0)
        return {"reported_pose_error_m": error, "measured_game_error_m": actual,
                "game_bones_checked": len(before)}

    def select_group(self, label):
        assert bpy.ops.warlock.select_controls(group=label) == {"FINISHED"}
        selected = {bone.name for bone in self.rig.pose.bones if bone.select}
        visible = {bone.name for bone in bpy.context.selected_pose_bones or []}
        expected = set(self.ui.control_names(self.rig) if label == "All" else self.groups[label])
        assert selected == expected, f"{label}: selected {selected ^ expected} incorrectly"
        # Rigify's pole visibility is driven by its solving mode. Selecting a
        # group must not activate a disabled pole and change the current pose.
        disabled_poles = {mapping["ctrl"][1] for mapping in self.ui.LIMBS.values()
                          if not self.rig.pose.bones[mapping["prop"]]["pole_vector"]}
        manipulable = expected - disabled_poles
        assert visible == manipulable, f"{label}: active controls cannot be manipulated: {visible ^ manipulable}"
        return {"group": label, "expected_count": len(expected), "selected_count": len(selected),
                "selected_controls": sorted(selected),
                "inactive_poles": sorted(expected & disabled_poles)}

    def active_pole_selection(self):
        self.reset()
        for mapping in self.ui.LIMBS.values():
            self.rig.pose.bones[mapping["prop"]]["pole_vector"] = True
        self.rig.update_tag()
        bpy.context.view_layer.update()
        detail = self.select_group("All")
        assert not detail["inactive_poles"]
        return {**detail, "every_enabled_pole_manipulable": True}

    def group_for(self, bone_name):
        return next(label for label, names in self.groups.items() if bone_name in names)

    def selected_reset(self):
        self.reset()
        name = "j_leftarm_ctrl_fk"
        detail = self.select_group(self.group_for(name))
        target = self.rig.pose.bones[name]
        target.location.x = .1
        root = self.rig.pose.bones["root"]
        root.location.x = .23
        assert not root.select
        assert bpy.ops.warlock.reset_controls(all_controls=False) == {"FINISHED"}
        assert target.location.length < 1e-8, "Selected control was not reset"
        assert abs(root.location.x - .23) < 1e-7, "Unselected root was modified"
        return {**detail, "unselected_root_retained": True}

    def reset_all(self):
        self.reset()
        self.rig.pose.bones["root"].location.x = .2
        self.rig.pose.bones["j_lefthand_ctrl_ik"].location.y = .15
        settings = self.rig.pose.bones.get("CTRL-hand-settings-left")
        defaults = json.loads(self.rig.get("warlock_control_defaults", "{}"))
        tested_props = []
        if settings:
            for prop in settings.keys():
                if isinstance(settings[prop], (float, int, bool)):
                    settings[prop] = .3
                    tested_props.append(prop)
        assert bpy.ops.warlock.reset_controls(all_controls=True) == {"FINISHED"}
        for name in self.ui.control_names(self.rig):
            matrix = self.rig.pose.bones[name].matrix_basis
            assert max(abs(value - (1 if row == column else 0))
                       for row, values in enumerate(matrix) for column, value in enumerate(values)) < 1e-6, name
        for prop in tested_props:
            default = defaults.get(settings.name, {}).get(prop,
                      settings.id_properties_ui(prop).as_dict().get("default"))
            assert abs(settings[prop] - default) < 1e-6, f"{settings.name} {prop} default incorrect"
        return {"transforms_reset": len(self.ui.control_names(self.rig)),
                "custom_defaults_checked": tested_props}

    def curves(self):
        action = self.rig.animation_data.action
        assert action is not None, "Key controls did not create an action"
        slot = self.rig.animation_data.action_slot
        return [curve for layer in action.layers for strip in layer.strips
                for curve in strip.channelbag(slot).fcurves]

    def key_selected(self):
        self.reset()
        name = "j_leftarm_ctrl_fk"
        detail = self.select_group(self.group_for(name))
        settings = self.rig.pose.bones[self.ui.LIMBS["left_arm"]["prop"]]
        # Settings curves are intentionally separate from the combined FK
        # group in the handoff manifest. Select it explicitly to key the switch.
        settings.select = True
        assert bpy.ops.warlock.key_controls() == {"FINISHED"}
        curves = self.curves()
        assert any("IK_FK" in curve.data_path for curve in curves)
        assert any(name in curve.data_path for curve in curves)
        selected = {bone.name for bone in self.rig.pose.bones if bone.select}
        for curve in curves:
            assert any(curve.data_path.startswith('pose.bones[' + json.dumps(bone) + ']')
                       for bone in selected), f"Keyed an unselected control: {curve.data_path}"
        return {**detail, "curve_count": len(curves), "keyed_switch": True,
                "only_selected_controls_keyed": True}

    def key_all(self):
        self.reset()
        assert bpy.ops.warlock.key_controls(all_controls=True) == {"FINISHED"}
        curves = self.curves()
        assert any("j_leftarm_ctrl_parent" in curve.data_path and "IK_FK" in curve.data_path
                   for curve in curves)
        assert any("j_rightarm_ctrl_parent" in curve.data_path and "IK_FK" in curve.data_path
                   for curve in curves)
        missing = [name for name in self.ui.control_names(self.rig)
                   if not any(curve.data_path.startswith('pose.bones[' + json.dumps(name) + ']')
                              for curve in curves)]
        assert not missing, "All controls omitted " + ", ".join(missing)
        return {"curve_count": len(curves), "all_controls_keyed": len(self.ui.control_names(self.rig))}

    def rollback(self):
        self.reset()
        rig, ui = self.rig, self.ui
        mapping = ui.LIMBS["left_arm"]
        rig.pose.bones[mapping["prop"]]["IK_FK"] = 1.0
        bone = rig.pose.bones["j_leftforearm_ctrl_fk"]
        bone.rotation_mode = "XYZ"
        bone.rotation_euler.z = .2
        rig.update_tag()
        bpy.context.view_layer.update()
        before = ui.game_pose(rig)
        saved = ui.snapshot_controls(rig)
        try:
            ui.switch_limb(bpy.context, rig, "left_arm", "IK")
        except RuntimeError as error:
            assert "undoing switch" in str(error), error
        else:
            raise AssertionError("Nonrepresentable FK pose was silently changed")
        assert rig.pose.bones[mapping["prop"]]["IK_FK"] == 1.0
        assert ui.pose_error(before, ui.game_pose(rig)) < 1e-6
        for name, state in saved.items():
            assert max(abs(a - b) for row_a, row_b in zip(state[0], rig.pose.bones[name].matrix_basis)
                       for a, b in zip(row_a, row_b)) < 1e-6, name
            assert rig.pose.bones[name].rotation_mode == state[1]
            for prop, value in state[4].items():
                assert rig.pose.bones[name][prop] == value, f"{name} {prop} not restored"
        return {"nonrepresentable_pose_rejected": True, "all_controls_restored": True}

    def autokey_operator(self):
        self.reset()
        rig, ui = self.rig, self.ui
        mapping = ui.LIMBS["right_arm"]
        rig.pose.bones[mapping["ctrl"][-1]].location.x = .06
        rig.update_tag()
        bpy.context.view_layer.update()
        before = ui.game_pose(rig)
        bpy.context.scene.tool_settings.use_keyframe_insert_auto = True
        try:
            assert bpy.ops.warlock.switch_limb(limb="right_arm", mode="FK") == {"FINISHED"}
        finally:
            bpy.context.scene.tool_settings.use_keyframe_insert_auto = False
        error = ui.pose_error(before, ui.game_pose(rig))
        # The calibrated world/local chain uses Blender float32 matrices.
        # Give this nearly exact IK->FK case 5 micrometres of numerical room;
        # the full limb suite independently enforces the 0.5 mm snap contract.
        pose_tolerance = 5e-6
        assert error < pose_tolerance, error
        switch = next(curve for curve in self.curves() if "j_rightarm_ctrl_parent" in curve.data_path
                      and "IK_FK" in curve.data_path)
        assert abs(switch.keyframe_points[0].co.y - 1.0) < 1e-6
        return {"operator_dispatch": True, "switch_keyed_at_fk": True,
                "game_pose_error_m": error, "pose_tolerance_m": pose_tolerance}

    def relocated_exporter_path(self):
        original_file = self.ui.__file__
        original_directory = self.rig.get("warlock_tools_directory")
        try:
            with flat_scratch("warlock-ui-relocation-") as directory:
                relocated = Path(directory)
                exporter = relocated / "export_animation.py"
                # Path resolution only; this stub is never imported or run.
                exporter.write_text("# relocation path fixture\n", encoding="utf-8")
                self.ui.__file__ = str(relocated / "warlock_rig_ui.py")
                self.rig["warlock_tools_directory"] = str(relocated / "old-missing-workstation")
                actual = self.ui.exporter_path(self.rig)
                assert actual == exporter, f"Moved handoff used stale directory: {actual}"
                return {"adjacent_exporter_preferred": True,
                        "missing_original_workstation_ignored": True}
        finally:
            self.ui.__file__ = original_file
            if original_directory is None:
                del self.rig["warlock_tools_directory"]
            else:
                self.rig["warlock_tools_directory"] = original_directory

    def execute(self):
        for limb in self.ui.LIMBS:
            for source in ("IK", "FK"):
                for pole in (False, True):
                    self.run(f"{limb}_{source}_pole_{pole}",
                             lambda l=limb, s=source, p=pole: self.switch_test(l, s, p))
        for label in self.groups:
            self.run("selection_" + label, lambda group=label: self.select_group(group))
        self.run("selection_all", lambda: self.select_group("All"))
        self.run("enabled_poles_visible_and_selectable", self.active_pole_selection)
        self.run("selected_reset_retains_unselected_controls", self.selected_reset)
        self.run("all_controls_reset_including_custom_defaults", self.reset_all)
        self.run("key_selected_controls_and_switch", self.key_selected)
        self.run("key_all_controls", self.key_all)
        self.run("nonrepresentable_pose_rolls_back_every_control", self.rollback)
        self.run("snap_operator_autokey", self.autokey_operator)
        self.run("relocated_package_uses_adjacent_exporter", self.relocated_exporter_path)
        self.run("source_blend_bytes_unchanged", self.source_unchanged)
        self.reset()
        self.ui.unregister()
        self.results["passed"] = not self.results["failures"]
        return self.results

    def source_unchanged(self):
        assert hashlib.sha256(self.rig_path.read_bytes()).hexdigest() == self.rig_sha256, (
            "Input blend changed while tests ran; rerun against a stable saved file")
        return {"source_sha256": self.rig_sha256, "source_blend_not_saved_by_test": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rig", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    results = RigUITests(args).execute()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print("WARLOCK_UI_TEST_REPORT", args.output, "PASSED", results["passed"])
    if not results["passed"]:
        raise RuntimeError("Rig UI tests failed: " + ", ".join(results["failures"]))


if __name__ == "__main__":
    main()
