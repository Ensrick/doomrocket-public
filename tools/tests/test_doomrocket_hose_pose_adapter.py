"""Independently reconstruct native hierarchy after actual hose adapter writes.

The lifecycle harness expires native temporaries and rejects source-unit writes.
This suite additionally models distinct root, static ancestor/parent, and control
poses. SDK-independent cases cover the measured 100x parent plus nontrivial
ancestor rotations/translations so a missing scale or reversed matrix product
cannot pass merely because the test parent happens to be identity.
"""

import unittest

import test_doomrocket_hose_lifecycle as lifecycle


HIERARCHY = r'''
local old_spawn=World.spawn_unit
local old_world_pose=Unit.world_pose
local function array_matrix(values)
    local result=Matrix4x4.identity()
    for r=1,4 do for c=1,4 do result[r][c]=values[r][c] end end
    return result
end
-- The decoded SDK probe has root I and hose_root world 100I. Other test cases
-- intentionally change its ancestors without changing control bind profiles.
hose_parent_values={{100,0,0,0},{0,100,0,0},{0,0,100,0},{0,0,0,1}}
hose_root_values={{1,0,0,0},{0,1,0,0},{0,0,1,0},{0,0,0,1}}
World.spawn_unit=function(w,name,position,rotation)
    local u=old_spawn(w,name,position,rotation)
    if u then
        local root=array_matrix(hose_root_values)
        Matrix4x4.set_translation(root,position)
        root.epoch=nil
        u.pose=root
    end
    return u
end
Unit.world_pose=function(u,node)
    if u.name~=hose_name then return old_world_pose(u,node) end
    assert(u.alive and u.world.alive)
    local root=Matrix4x4.copy(u.local_poses and u.local_poses[0] or u.pose)
    if node==0 then return root end
    -- Native row-vector order: local * parent, not parent * local.
    local parent=Matrix4x4.multiply(array_matrix(hose_parent_values),root)
    if node==1 then return parent end
    assert(u.local_poses and u.local_poses[node],'control has no scripted pose')
    return Matrix4x4.multiply(Matrix4x4.copy(u.local_poses[node]),parent)
end
function expected_world_frame(entry,index)
    local pose=entry.frames.poses[index]
    local frame=Matrix4x4.identity()
    Matrix4x4.set_x(frame,Vector3(unpack(pose.x_axis)))
    Matrix4x4.set_y(frame,Vector3(unpack(pose.y_axis)))
    Matrix4x4.set_z(frame,Vector3(unpack(pose.z_axis)))
    Matrix4x4.set_translation(frame,Vector3(unpack(pose.position)))
    -- This is the reviewed independent profile's control-to-native-bone map.
    return Matrix4x4.multiply(entry.nodes[index].bind:unbox(),frame)
end
function maximum_world_pose_error()
    local entry=mod._doomrocket_hose_state.entries[owner]
    assert(entry and entry.visual and entry.visual.visible,'adapter rejected valid hierarchy')
    local worst=0
    for i=1,29 do
        local actual=Unit.world_pose(entry.visual,entry.nodes[i].node)
        local expected=expected_world_frame(entry,i)
        for r=1,4 do for c=1,4 do
            worst=math.max(worst,math.abs(actual[r][c]-expected[r][c]))
        end end
    end
    local root=Unit.world_pose(entry.visual,0)
    for j=1,3 do assert(math.abs(root[j][4]-entry.pack.position[j])<1e-7,
        'visual root/bounds left behind by owner') end
    return worst
end
'''


class HosePoseAdapterTests(unittest.TestCase):
    def setUp(self):
        engine = lifecycle.HoseLifecycleTests()
        engine.setUp()
        self.lua = engine.lua
        self.lua.execute(HIERARCHY)

    def test_actual_compiled_parent_scale_is_preserved_without_double_scaling(self):
        self.lua.execute("assert(start()); tick()")
        self.assertLess(self.lua.globals().maximum_world_pose_error(), 1e-7)
        self.lua.execute("""
            local entry=mod._doomrocket_hose_state.entries[owner]
            local native=Unit.world_pose(entry.visual,entry.nodes[1].node)
            assert(math.abs(Vector3.length(Matrix4x4.x(native))-100)<.001)
            local local_pose=entry.visual.local_poses[entry.nodes[1].node]
            assert(math.abs(Vector3.length(Matrix4x4.x(local_pose))-1)<.001)
        """)

    def test_rotated_translated_parent_and_rotated_root_cancel_in_local_conversion(self):
        self.lua.execute("""
            hose_parent_values={{0,-100,0,1.5},{100,0,0,-.2},{0,0,100,.3},{0,0,0,1}}
            hose_root_values={{0,-1,0,0},{1,0,0,0},{0,0,1,0},{0,0,0,1}}
            assert(start());tick()
        """)
        self.assertLess(self.lua.globals().maximum_world_pose_error(), 1e-7)

    def test_nonuniform_parent_that_requires_sheared_local_controls_is_rejected(self):
        # The actual compiled parent is uniformly 100x. An anisotropic parent
        # combined with curved world controls requires shear, which the runtime
        # intentionally rejects rather than passing unsupported poses to native.
        self.lua.execute("""
            hose_parent_values={{80,0,0,.1},{0,100,0,.2},{0,0,120,.3},{0,0,0,1}}
            assert(start());tick()
            local entry=mod._doomrocket_hose_state.entries[owner]
            assert(entry and not entry.visual)
            assert(events.destroyed==1 and not last_hose.alive)
            assert(owner.alive and outfit.alive and weapon.alive)
        """)

    def test_runtime_world_poses_and_root_follow_translated_moving_endpoints(self):
        self.lua.execute("assert(start());tick()")
        for frame in range(1, 91):
            self.lua.globals().frame = frame
            self.lua.execute("""
                outfit.pose[1][4]=10+frame*.01
                outfit.pose[2][4]=-20
                weapon.pose[1][4]=10.5+frame*.01+.05*math.sin(frame/15)
                weapon.pose[2][4]=-20
                tick()
            """)
            self.assertLess(self.lua.globals().maximum_world_pose_error(), 1e-6)
        self.assertEqual(self.lua.eval("events.spawned"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
