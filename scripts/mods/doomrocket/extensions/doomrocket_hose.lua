local mod = get_mod("doomrocket")
local PROFILE = mod._doomrocket_hose_profile
local Solver = mod._doomrocket_hose_solver
local Frames = mod._doomrocket_hose_frames
local OUTFIT = "units/warlock_bombardier/warlock_bombardier_3p"
local WEAPON = "units/rocket/pRocketLauncher"
local CHILD_PACKAGE = "resource_packages/doomrocket/warlock_child"
local MAX_ACTIVE, MAX_DISTANCE = 8, 40

if mod._reset_warlock_hose then mod._reset_warlock_hose("module_reload") end
local state = mod._doomrocket_hose_state or {entries={},outfits={},blocked=setmetatable({}, {__mode="k"}),
    unknown_worlds={},releasing_worlds={},epoch=0,sequence=0,pending=false}
mod._doomrocket_hose_state = state

local function active_world()
    local manager=Managers.world
    if manager and manager:has_world("level_world") then return manager:world("level_world") end
end
local function known_world(world)
    local manager=Managers.world
    return world and manager and (world==active_world()
        or manager._disabled_worlds and manager._disabled_worlds.level_world==world)
end
local function live_in(unit,world)
    return unit and Unit.alive(unit) and Unit.world(unit)==world
end
-- One record per reason, capped per owner. Never turn a per-frame rejection
-- into log spam; retain the last reason/counters for the terminal summary.
local function diagnose(entry,reason,detail)
    entry.last_reason=reason
    entry.diagnostics=entry.diagnostics or {}
    if entry.diagnostics[reason] or (entry.diagnostic_count or 0)>=16 then return end
    entry.diagnostics[reason]=true
    entry.diagnostic_count=(entry.diagnostic_count or 0)+1
    printf("[doomrocket:HOSE] phase=diagnostic id=%d reason=%s updates=%d writes=%d %s",
        entry.id,reason,entry.updates or 0,entry.written_frames or 0,detail or "")
end
local function pose_summary(pose)
    if not Matrix4x4.is_valid(pose) then return "matrix_valid=false" end
    local x,y,z,p=Matrix4x4.x(pose),Matrix4x4.y(pose),Matrix4x4.z(pose),Matrix4x4.translation(pose)
    return string.format("scale=%.6g,%.6g,%.6g position=%.6g,%.6g,%.6g",
        Vector3.length(x),Vector3.length(y),Vector3.length(z),p[1],p[2],p[3])
end
local function destroy_visual(entry)
    local visual=entry.visual
    entry.visual=nil
    if visual then entry.visual_removals=(entry.visual_removals or 0)+1 end
    if visual and not state.releasing_worlds[entry.world] then
        if not known_world(entry.world) then
            -- Do not touch a world no longer registered with the manager, or later
            -- create a duplicate if that still-live world becomes visible again.
            state.unknown_worlds[entry.world]=true
        elseif live_in(visual,entry.world) then
            World.destroy_unit(entry.world,visual)
        end
    end
    entry.solver,entry.frames,entry.nodes=nil,nil,nil
end
local function stop(owner,reason)
    local entry=state.entries[owner]
    if reason and reason:sub(1,6)=="death_" then state.blocked[owner]=true end
    if not entry then return false end
    state.entries[owner]=nil
    if state.outfits[entry.outfit]==owner then state.outfits[entry.outfit]=nil end
    destroy_visual(entry)
    printf("[doomrocket:HOSE] phase=stop id=%d reason=%s callbacks=%d updates=%d writes=%d spawns=%d removals=%d last_reason=%s pending=%s",
        entry.id,tostring(reason),entry.callbacks or 0,entry.updates or 0,entry.written_frames or 0,
        entry.spawn_attempts or 0,entry.visual_removals or 0,tostring(entry.last_reason),tostring(state.pending))
    return true
end

local function native_pose(frame)
    local m=Matrix4x4.identity()
    Matrix4x4.set_x(m,Vector3(unpack(frame.x_axis)))
    Matrix4x4.set_y(m,Vector3(unpack(frame.y_axis)))
    Matrix4x4.set_z(m,Vector3(unpack(frame.z_axis)))
    Matrix4x4.set_translation(m,Vector3(unpack(frame.position)))
    return m
end
local function matrix_valid(m)
    if not Matrix4x4.is_valid(m) then return false end
    local x,y,z=Matrix4x4.x(m),Matrix4x4.y(m),Matrix4x4.z(m)
    local norm=Vector3.length(x)*Vector3.length(y)*Vector3.length(z)
    return norm>1e-10 and norm<1e15 and math.abs(Vector3.dot(x,Vector3.cross(y,z)))/norm>.999
end
local function new_frame() return {x_axis={},y_axis={},z_axis={},position={}} end
local function numbers(m,frame)
    if not matrix_valid(m) then return false end
    local x,y,z,p=Matrix4x4.x(m),Matrix4x4.y(m),Matrix4x4.z(m),Matrix4x4.translation(m)
    local sx,sy,sz=Vector3.length(x),Vector3.length(y),Vector3.length(z)
    -- The endpoint profile cancels the exported 100x wrapper, but the cloned
    -- Ratling breed also applies size_variation_range={1.1,1.1} on host/husk.
    -- Accept only the unscaled attachment frame or that native uniform size.
    -- Solver frames need rotation alone; the translated outlet/inlet already
    -- includes the owner's scale and must stay in its exact world position.
    if math.abs(sx-sy)>.001 or math.abs(sx-sz)>.001
        or not ((math.abs(sx-1)<=.01 and math.abs(sy-1)<=.01 and math.abs(sz-1)<=.01)
            or (math.abs(sx-1.1)<=.01 and math.abs(sy-1.1)<=.01 and math.abs(sz-1.1)<=.01))
        or Vector3.dot(x,Vector3.cross(y,z))<=0
        or math.abs(Vector3.dot(x,y)/(sx*sy))>.001
        or math.abs(Vector3.dot(x,z)/(sx*sz))>.001
        or math.abs(Vector3.dot(y,z)/(sy*sz))>.001 then return false end
    for i=1,3 do if math.abs(p[i])>1e6 then return false end end
    for i=1,3 do
        frame.x_axis[i],frame.y_axis[i],frame.z_axis[i],frame.position[i]=x[i]/sx,y[i]/sy,z[i]/sz,p[i]
    end
    return true
end
local function resources_ready()
    if not Application.can_get("unit",PROFILE.unit) then return false,"unit_unavailable" end
    if not mod.package_status or mod:package_status(CHILD_PACKAGE)~="loaded" then return false,"child_package_pending" end
    if not Application.can_get("material",PROFILE.material_child) then return false,"material_unavailable" end
    for i=1,#PROFILE.textures do
        if not Application.can_get("texture",PROFILE.textures[i]) then return false,PROFILE.textures[i] end
    end
    return true
end
local function carried(entry)
    local inventory=entry.inventory
    if inventory.dropped or inventory.unit~=entry.owner or inventory.world~=entry.world then return false end
    local found=false
    for _,unit in pairs(inventory.inventory_item_units or {}) do
        if unit==entry.weapon then found=true; break end
    end
    if not found then return false end
    local item=ScriptUnit.has_extension(entry.weapon,"ai_inventory_item_system")
    return item and not item.dropped and item.wielding_unit==entry.owner
end
local function valid_entry(entry)
    return known_world(entry.world) and live_in(entry.owner,entry.world)
        and live_in(entry.outfit,entry.world) and live_in(entry.weapon,entry.world)
        and mod._warlock_outfits and mod._warlock_outfits[entry.owner]==entry.outfit and carried(entry)
end
local function create_visual(entry)
    if entry.failed then return false end
    local ready,reason=resources_ready()
    if not ready then
        if entry.wait_reason~=reason then printf("[doomrocket:HOSE] phase=wait id=%d reason=%s",entry.id,reason) end
        entry.wait_reason=reason
        return false
    end
    entry.wait_reason=nil
    entry.spawn_attempts=(entry.spawn_attempts or 0)+1
    local visual=World.spawn_unit(entry.world,PROFILE.unit,Vector3(unpack(entry.pack.position)))
    if not visual or not Unit.alive(visual) then
        entry.failed=true
        printf("[doomrocket:HOSE] phase=reject id=%d reason=spawn_failed",entry.id)
        return false
    end
    entry.visual=visual
    Unit.set_unit_visibility(visual,false)
    if Unit.num_actors(visual)~=0 or not Unit.has_node(visual,PROFILE.parent_node) then
        diagnose(entry,"asset_actors_or_parent")
        entry.failed=true; destroy_visual(entry); return false
    end
    local parent=Unit.node(visual,PROFILE.parent_node)
    local nodes={}
    for i=1,#PROFILE.controls do
        local control=PROFILE.controls[i]
        if not Unit.has_node(visual,control.name) then
            diagnose(entry,"control_missing","node="..control.name)
            entry.failed=true; destroy_visual(entry); return false
        end
        local node=Unit.node(visual,control.name)
        if Unit.scene_graph_parent(visual,node)~=parent then
            diagnose(entry,"control_parent","node="..control.name)
            entry.failed=true; destroy_visual(entry); return false
        end
        nodes[i]={node=node,bind=Matrix4x4Box(native_pose(control.bind))}
    end
    local root_pose,parent_pose=Unit.world_pose(visual,0),Unit.world_pose(visual,parent)
    if not matrix_valid(root_pose) or not matrix_valid(parent_pose) then
        diagnose(entry,"bind_pose_invalid","root_"..pose_summary(root_pose).." parent_"..pose_summary(parent_pose))
        entry.failed=true; destroy_visual(entry); return false
    end
    entry.root_bind=Matrix4x4Box(root_pose)
    entry.parent_to_root=Matrix4x4Box(Matrix4x4.multiply(parent_pose,Matrix4x4.inverse(root_pose)))
    entry.nodes=nodes
    entry.solver=Solver.new(PROFILE.lengths,nil,5.0)
    entry.frames=Frames.new(PROFILE)
    -- This skin has no animation blender. Animation LOD/mode APIs are not
    -- applicable (set_bones_lod asserts on spawn, #20); update_entry writes
    -- its scene-graph control poses directly, with no animation to suppress.
    Unit.set_material(visual,PROFILE.material_slot,PROFILE.material_child)
    printf("[doomrocket:HOSE] phase=start id=%d controls=%d actors=0 semi_rigid=true collision=none",entry.id,#nodes)
    return true
end
local function update_entry(entry,dt)
    entry.updates=(entry.updates or 0)+1
    local pack_pose=Matrix4x4.multiply(entry.pack_local:unbox(),Unit.world_pose(entry.outfit,entry.pack_node))
    local weapon_pose=Matrix4x4.multiply(entry.weapon_local:unbox(),Unit.world_pose(entry.weapon,entry.weapon_node))
    if not numbers(pack_pose,entry.pack) then
        diagnose(entry,"pack_pose_rejected",pose_summary(pack_pose))
        destroy_visual(entry); return
    end
    if not numbers(weapon_pose,entry.weapon_frame) then
        diagnose(entry,"weapon_pose_rejected",pose_summary(weapon_pose))
        destroy_visual(entry); return
    end
    if not entry.visual and not create_visual(entry) then return end
    if not live_in(entry.visual,entry.world) then
        diagnose(entry,Unit.alive(entry.visual) and "visual_wrong_world" or "visual_dead")
        entry.failed=true; destroy_visual(entry); return
    end
    local solver,frames=entry.solver,entry.frames
    if not frames:shape(solver,entry.pack,entry.weapon_frame) then
        diagnose(entry,"shape_rejected"); destroy_visual(entry); return
    end
    local a,b=entry.pack.position,entry.weapon_frame.position
    if not entry.endpoints_reported then
        entry.endpoints_reported=true
        printf("[doomrocket:HOSE] phase=endpoints id=%d dt=%.6f length=%.6f pack=%.6f,%.6f,%.6f weapon=%.6f,%.6f,%.6f",
            entry.id,dt,solver.length,a[1],a[2],a[3],b[1],b[2],b[3])
    end
    local visible,reason=solver:frame(dt,a[1],a[2],a[3],b[1],b[2],b[3])
    local frames_valid=visible and frames:update(solver,entry.pack,entry.weapon_frame,reason~="simulated" and reason~="paused")
    if not visible or not frames_valid then
        diagnose(entry,not visible and "solver_hidden" or "frame_rejected","solver_reason="..tostring(reason))
        Unit.set_unit_visibility(entry.visual,false)
        if entry.hide_reason~=reason then printf("[doomrocket:HOSE] phase=hide id=%d reason=%s",entry.id,tostring(reason)) end
        entry.hide_reason=reason
        return
    end
    entry.hide_reason=nil
    -- Keep the skinned mesh/root bound with the pack, not at the world origin.
    -- Controls remain world driven; preserve the compiled scale in BOTH matrices.
    local root=entry.root_bind:unbox()
    Matrix4x4.set_translation(root,Vector3(unpack(a)))
    local parent=Matrix4x4.multiply(entry.parent_to_root:unbox(),root)
    if not matrix_valid(parent) then
        diagnose(entry,"parent_pose_rejected",pose_summary(parent)); destroy_visual(entry); return
    end
    local inverse_parent=Matrix4x4.inverse(parent)
    Unit.set_local_pose(entry.visual,0,root)
    for i=1,#entry.nodes do
        local node=entry.nodes[i]
        local world_pose=Matrix4x4.multiply(node.bind:unbox(),native_pose(frames.poses[i]))
        local local_pose=Matrix4x4.multiply(world_pose,inverse_parent)
        if not matrix_valid(local_pose) then
            diagnose(entry,"control_pose_rejected","control="..i.." "..pose_summary(local_pose))
            destroy_visual(entry); return
        end
        Unit.set_local_pose(entry.visual,node.node,local_pose)
    end
    World.update_unit(entry.world,entry.visual)
    Unit.set_unit_visibility(entry.visual,true)
    entry.written_frames=(entry.written_frames or 0)+1
    entry.last_reason=nil
    if entry.written_frames==1 then
        printf("[doomrocket:HOSE] phase=pose_write id=%d controls=%d visibility_requested=true first_%s last_%s",
            entry.id,#entry.nodes,pose_summary(Unit.world_pose(entry.visual,entry.nodes[1].node)),
            pose_summary(Unit.world_pose(entry.visual,entry.nodes[#entry.nodes].node)))
    end
    entry.elapsed=(entry.elapsed or 0)+dt
    if not entry.sampled and entry.elapsed>=3 then
        entry.sampled=true
        printf("[doomrocket:HOSE] phase=sample id=%d simulated_steps=%d resets=%d length_error=%.6f",entry.id,solver.steps,solver.resets,solver:length_error(solver.rx,solver.ry,solver.rz))
    end
end

mod._start_warlock_hose=function(owner,outfit,inventory)
    if DEDICATED_SERVER or not owner or state.blocked[owner] or not inventory then return false end
    local world=active_world()
    if not world or state.unknown_worlds[world] or state.releasing_worlds[world]
        or not live_in(owner,world) or not live_in(outfit,world)
        or Unit.get_data(outfit,"unit_name")~=OUTFIT or inventory.unit~=owner or inventory.world~=world then return false end
    local weapon
    for _,candidate in pairs(inventory.inventory_item_units or {}) do
        if live_in(candidate,world) and Unit.get_data(candidate,"unit_name")==WEAPON then weapon=candidate; break end
    end
    if not weapon or not Unit.has_node(outfit,PROFILE.endpoints.pack.node)
        or not Unit.has_node(weapon,PROFILE.endpoints.weapon.node) then return false end
    local existing=state.entries[owner]
    if existing and existing.outfit==outfit and existing.weapon==weapon and existing.inventory==inventory then return true end
    if existing then stop(owner,"configuration_replaced") end
    if state.outfits[outfit] then return false end
    state.sequence=state.sequence+1
    local entry={owner=owner,outfit=outfit,weapon=weapon,inventory=inventory,world=world,id=state.sequence,
        pack_node=Unit.node(outfit,PROFILE.endpoints.pack.node),weapon_node=Unit.node(weapon,PROFILE.endpoints.weapon.node),
        pack_local=Matrix4x4Box(native_pose(PROFILE.endpoints.pack)),weapon_local=Matrix4x4Box(native_pose(PROFILE.endpoints.weapon)),
        pack=new_frame(),weapon_frame=new_frame()}
    state.entries[owner]=entry; state.outfits[outfit]=owner
    return true
end
mod._stop_warlock_hose=function(owner,reason) return stop(owner,reason or "unspecified") end
mod._stop_warlock_hose_item=function(owner,item,reason)
    local entry=state.entries[owner]
    if entry and (entry.weapon==item or entry.outfit==item) then return stop(owner,reason) end
end
mod._reset_warlock_hose=function(reason)
    state.epoch=state.epoch+1; state.pending=false
    local owners={}
    for owner in pairs(state.entries) do owners[#owners+1]=owner end
    for i=1,#owners do stop(owners[i],reason or "reset") end
end
mod._release_warlock_hose=function(world)
    state.epoch=state.epoch+1; state.pending=false
    state.releasing_worlds[world]=true
    state.unknown_worlds[world]=nil
    for owner,entry in pairs(state.entries) do
        if entry.world==world then
            state.entries[owner]=nil; state.outfits[entry.outfit]=nil
            entry.visual=nil -- Application.release_world owns destruction; no stale native handle calls.
        end
    end
end
mod._finish_release_warlock_hose=function(world)
    -- The pre-release guard prevents reentrant starts. Once native destruction
    -- returns, do not blacklist a pointer the engine may reuse for a new world.
    state.releasing_worlds[world]=nil
end
mod._queue_warlock_hose=function(world,dt)
    if DEDICATED_SERVER or world~=active_world() or state.releasing_worlds[world]
        or state.unknown_worlds[world] or state.pending or not next(state.entries)
        or type(dt)~="number" or dt~=dt or dt<0 or dt==math.huge then return end
    local entity=Managers.state.entity
    local animation=entity and entity:system("animation_system")
    if not animation then return end
    local epoch=state.epoch
    state.pending=true
    animation:add_safe_animation_callback(function()
        if state.epoch~=epoch then return end
        state.pending=false
        if world~=active_world() then return end
        local candidates,removed={},{}
        local player=Managers.player and Managers.player:local_player()
        local player_unit=player and player.player_unit
        local origin=live_in(player_unit,world) and Unit.world_position(player_unit,0)
        for owner,entry in pairs(state.entries) do
            if not valid_entry(entry) then removed[#removed+1]=owner
            else
                entry.distance=origin and Vector3.distance(origin,Unit.world_position(entry.outfit,entry.pack_node)) or 0
                candidates[#candidates+1]=entry
            end
        end
        for i=1,#removed do stop(removed[i],"context_removed") end
        table.sort(candidates,function(a,b) return a.distance==b.distance and a.id<b.id or a.distance<b.distance end)
        for i=1,#candidates do
            local entry=candidates[i]
            entry.callbacks=(entry.callbacks or 0)+1
            if state.entries[entry.owner]~=entry then -- A reentrant lifecycle callback already removed it.
            elseif not valid_entry(entry) then stop(entry.owner,"context_removed")
            elseif i<=MAX_ACTIVE and entry.distance<=MAX_DISTANCE then update_entry(entry,dt)
            else
                diagnose(entry,"visibility_budget",string.format("rank=%d distance=%.3f",i,entry.distance))
                destroy_visual(entry)
            end
        end
    end)
end
return
