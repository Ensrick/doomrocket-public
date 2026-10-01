local mod = get_mod("doomrocket")

local new_packages = {
    "resource_packages/breeds/skaven_doomrocket",
}
local pacakge_tisch = {}

for k,v in ipairs(new_packages) do
    pacakge_tisch[v] = v
end

mod:hook(PackageManager, "load",
         function(func, self, package_name, reference_name, callback,
                  asynchronous, prioritize)
    if package_name ~= pacakge_tisch[package_name]then
        func(self, package_name, reference_name, callback, asynchronous,
             prioritize)
    end

end)

mod:hook(PackageManager, "unload",
         function(func, self, package_name, reference_name)
    if package_name ~= pacakge_tisch[package_name] then
        func(self, package_name, reference_name)
    end

end)

mod:hook(PackageManager, "has_loaded",
         function(func, self, package, reference_name)
    if package == pacakge_tisch[package] then
        return true
    end

    return func(self, package, reference_name)
end)



-- mod:hook(MatchmakingManager, "update", function(func, self, dt, ...)

--     for k,v in pairs(BLACKBOARDS) do
--         if v.breed.name == "skaven_doomrocket" then

--             for i,j in pairs(v) do
--                 if v.action then
--                     mod:echo(v.action.name)
--                 end
--             end
--         end
--     end

--     func(self, dt, ...)
-- end)

-- mod:hook(UnitSpawner,"spawn_network_unit", function (func, self, unit_name, unit_template_name, extension_init_data, position, rotation, material)
--     mod:echo(unit_template_name)
--     -- for k,v in pairs(extension_init_data) do
--     --     print(tostring(k).." = {")
--     --     for i,j in pairs(v) do
--     --         print("     "..i..   " = "..tostring(j)..",")
--     --     end
--     --     print("}")
--     -- end
--     return func(self, unit_name, unit_template_name, extension_init_data, position, rotation, material)
-- end)

-- local player = Managers.player:local_player()
-- local player_unit = player.player_unit
-- local position = Unit.local_position(player_unit, 0) + Vector3(0,0,1)
-- -- local unit_name = "units/weapons/enemy/wpn_skaven_ratlinggun/wpn_skaven_ratlinggun"
-- local unit_name = "units/weapons/enemy/wpn_skaven_set/wpn_skaven_halberd_41"
-- local unit = Managers.state.unit_spawner:spawn_local_unit(unit_name, position)

-- local data = Unit.has_node(unit, "weapon")
-- mod:echo(data)
-- mod:hook(WwiseWorld, "trigger_event", function(func, self, event_name, ...)
--     mod:echo(event_name)
--     return func(self, event_name)
-- end)


--this stuff probably needs to be in it's own mod or reworked to be more dynamic

local new_breeds = {
    "skaven_doomrocket",
}
local breeds_to_force_spawn = {}
for k,v in ipairs(new_breeds) do
    breeds_to_force_spawn[v] = v
end

-- Vanilla 6.11.3 gates the spawn queue on EnemyPackageLoader:is_breed_loaded_on_all_peers.
-- The old breed_loaded_on_all_peers table and update_breeds_loading_status() are both gone,
-- so the previous full-body replacement of ConflictDirector.update_spawn_queue nil-called
-- every spawn tick. Declaring our breeds loaded is all that replacement actually achieved.
mod:hook("EnemyPackageLoader", "is_breed_loaded_on_all_peers", function(func, self, breed_name)
	if breeds_to_force_spawn[breed_name] then
		return true
	end

	return func(self, breed_name)
end)


local breed_to_breed_stats = {}
for i,breed in ipairs(new_breeds) do
    breed_to_breed_stats[breed] = "skaven_ratling_gunner"
end
--some reason have to hook whole stats function
-- These two only ever existed to remap our custom breed onto the ratling gunner's
-- stat path (there is no statistics entry for skaven_doomrocket). Vanilla 6.11.3
-- rewrote both to go through self:_get_or_create_stat, so the old hand-rolled table
-- walk nil-derefs on any not-yet-created path and its fallback corrupted the root
-- stats node. Remap the arguments and let vanilla do the work.
local function _remap_breed_args(...)
	local n = select("#", ...)
	local args = { ... }

	for i = 1, n do
		local mapped = breed_to_breed_stats[args[i]]

		if mapped then
			args[i] = mapped
		end
	end

	return unpack(args, 1, n)
end

mod:hook(StatisticsDatabase, "modify_stat_by_amount", function (func, self, id, ...)
	return func(self, id, _remap_breed_args(...))
end)

mod:hook(StatisticsDatabase, "increment_stat", function (func, self, id, ...)
	return func(self, id, _remap_breed_args(...))
end)



local new_animations = {
	doomrocket_reload_start = {
		timing = 0.5,
		emitted_event = "anim_cb_attack_windup_start_finished"
	},
}

mod:hook(UnitSpawner, "create_unit_extensions", function(func, self, world, unit, unit_template_name, extension_init_data)

	if extension_init_data then
		if extension_init_data.locomotion_system then
			if extension_init_data.locomotion_system.breed then
				if extension_init_data.locomotion_system.breed.name == "skaven_doomrocket" then
					if Unit.alive(unit) then
						-- NO state-machine swap. The native ratling carrier keeps its
						-- own machine; the custom outfit keeps clips compiled against
						-- its own skeleton. Binding either unit to the other's machine
						-- is the uncatchable AnimationBlender crash class proven in
						-- v0.1.24/34.
						for animaiton_event, details in pairs(new_animations) do
							Unit.set_data(unit, animaiton_event, "timing", details.timing)
							Unit.set_data(unit, animaiton_event, "emitted_event", details.emitted_event)
						end

						mod.anim_emitters[unit] = AnimEmitter:new(unit, blackboard)

						-- Fixed-index hides are unsafe because an out-of-range mesh
						-- index is an engine assert. The complete native carrier hide
						-- runs after Warlock attachment below.
					end
				end
			end
		end
	end

	return func(self, world, unit, unit_template_name, extension_init_data)
end)


local alt_events = {
	-- doomrocket_reload = "units/bombadier/bombadier"
	wind_up_start = {
		machine = "units/bombadier/bombadier",
		event = "doomrocket_reload_start",
	},
	wind_up_loop = {
		machine = "units/bombadier/bombadier",
		event = "doomrocket_reload_loop",
	},
}
-- mod:hook(Unit, "animation_event", function(func, unit, event, ...)

--     if not Unit.has_animation_event(unit, event) then
-- 		local unit_name = Unit.get_data(unit, "breed")
-- 		mod:echo(unit_name)
-- 		if unit_name == "units/beings/enemies/skaven_ratlinggunner/chr_skaven_ratlinggunner" then
-- 			if alt_events[event] then
-- 				Unit.set_animation_state_machine(unit, alt_events[event])
-- 			else
-- 				Unit.set_animation_state_machine(unit, "units/beings/enemies/skaven_ratlinggunner/chr_skaven_ratlinggunner")
-- 			end
-- 		end
-- 	end



--     return func(unit, event, ...)
-- end)

local set_animation_state_machine = Unit.set_animation_state_machine
local has_animation_event = Unit.has_animation_event
local unit_get_data = Unit.get_data

-- Doomrocket owner unit -> warlock outfit unit riding it (weak: entries die
-- with the units). The owner is the native ratling carrier; its render meshes
-- stay hidden while its authored skeleton/PhysX scene drives the custom skin.
mod._warlock_outfits = mod._warlock_outfits or setmetatable({}, { __mode = "kv" })
mod._warlock_carriers = mod._warlock_carriers or setmetatable({}, { __mode = "k" })
mod._warlock_pending_death_drivers = mod._warlock_pending_death_drivers or setmetatable({}, { __mode = "k" })
mod._warlock_active_death_drivers = mod._warlock_active_death_drivers or {}
mod._warlock_death_sequence = mod._warlock_death_sequence or 0

local raw_set_mesh_visibility = Unit.set_mesh_visibility

local function warlock_game_time()
	local game_time = Managers.time and Managers.time:time("game")
	return game_time or Application.time_since_launch()
end

local function hide_warlock_carrier_meshes(unit)
	local num_meshes = 0
	local counted = pcall(function()
		num_meshes = Unit.num_meshes(unit)
	end)

	if not counted or not num_meshes or num_meshes <= 0 then
		num_meshes = 24
	end

	local hidden = 0
	for mesh_index = 0, num_meshes - 1 do
		if pcall(raw_set_mesh_visibility, unit, mesh_index, false, "default") then
			hidden = hidden + 1
		end
	end

	return hidden, num_meshes, counted
end

-- A native-carrier reveal was the v0.1.49 diagnostic shortcut that made a
-- ratling gunner corpse appear instead of the Warlock. Keep a runtime counter
-- as well as the static regression rule so an external visibility write is
-- visible in a tester log and attributable to one corpse.
mod:hook(Unit, "set_mesh_visibility", function(func, unit, mesh_index, visible, ...)
	local tracker = mod._warlock_carriers[unit]

	if tracker and visible then
		tracker.reveal_count = (tracker.reveal_count or 0) + 1
		if tracker.id then
			local elapsed_ms = (warlock_game_time() - tracker.created_game_at) * 1000
			printf("[doomrocket:RAGDOLL] phase=carrier_reveal id=%s source=%s elapsed_ms=%.1f mesh=%s carrier_reveals=%d",
				tracker.id, tracker.source, elapsed_ms, tostring(mesh_index),
				tracker.reveal_count)
		else
			printf("[doomrocket:CARRIER] unexpected living mesh reveal mesh=%s count=%d",
				tostring(mesh_index), tracker.reveal_count)
		end
	end

	-- An attempted reveal remains a test failure, but never let it replace the
	-- custom corpse with the native ratling while collecting that evidence.
	if tracker and visible then
		visible = false
	end

	return func(unit, mesh_index, visible, ...)
end)

mod:hook(Unit, "set_unit_visibility", function(func, unit, visible, ...)
	local result = func(unit, visible, ...)
	local tracker = mod._warlock_carriers[unit]

	if tracker and visible then
		tracker.reveal_count = (tracker.reveal_count or 0) + 1
		if tracker.id then
			local elapsed_ms = (warlock_game_time() - tracker.created_game_at) * 1000
			printf("[doomrocket:RAGDOLL] phase=carrier_reveal id=%s source=%s elapsed_ms=%.1f mesh=whole_unit carrier_reveals=%d",
				tracker.id, tracker.source, elapsed_ms, tracker.reveal_count)
		else
			printf("[doomrocket:CARRIER] unexpected living whole-unit reveal count=%d",
				tracker.reveal_count)
		end
		hide_warlock_carrier_meshes(unit)
	end

	return result
end)

mod:hook(Unit, "animation_event", function(func, unit, event, ...)
	-- The doomrocket owner is the native ratling carrier. Never bind the custom
	-- outfit to that foreign machine: cross-skeleton state-machine binding is a
	-- raw native crash (v0.1.24/34). The outfit mirrors only compatible events
	-- by name while alive and is removed from this registry in death pre_start.
	-- Unknown events are swallowed instead; the custom visual stays on the last
	-- compatible clip until an equivalent clip exists on its own machine.
	local breed = unit_get_data(unit, "breed")

	if breed and breed.name == "skaven_doomrocket" and not has_animation_event(unit, event) then
		return
	end

	-- Mirror registry (self-ASM driving mode only; empty in bridge mode).
	local outfit = mod._warlock_outfits[unit]

	if outfit then
		if Unit.alive(outfit) then
			if has_animation_event(outfit, event) then
				func(outfit, event, ...)
			end
		else
			mod._warlock_outfits[unit] = nil
		end
	end

	return func(unit, event, ...)
end)

-- NO raw-index animation mirroring. v0.1.25 crash: the rat's aim system
-- called animation_set_constraint_target(rat, 0, aim_target); forwarding that
-- raw index to the outfit - whose old state machine had no constraints - is
-- an engine assert that pcall CANNOT catch (same uncatchable class as the
-- v0.1.24 AnimationBlender crash). Variable and constraint indices are only
-- meaningful within one compiled state machine. Locomotion and visible aim
-- now resolve their own named variable/constraint on the outfit, guarded by
-- the matching animation_has_* query. Never forward carrier indices. Events
-- are mirrored above by name and gated on Unit.has_animation_event.


-- Runtime material swap for the warlock body (Pusfume native contract).
-- The five boot-package wb_* materials are SDK compiles, which the engine can
-- only render RIGID and dark: the mod SDK never emits the character-skinning
-- shader permutation (vt2-pusfume issue #6). The real bindings are game child
-- payloads spliced over child_materials/warlock_bombardier/wb_*_child, which
-- ride in a separate NON-boot package (boot-flushing a spliced child crashes
-- the engine at PatchedResourcePackage::flush - v0.1.16). Swap every slot once
-- both packages are resident; the hook runs per spawn, so a miss self-heals
-- on the next bombardier.
local WARLOCK_ARMOR_DONOR_PACKAGE = "units/beings/player/dark_pact_skins/skaven_ratlinggunner/skin_1001/third_person/chr_third_person_mesh"
local WARLOCK_NATIVE_BODY_PACKAGE = "resource_packages/breeds/skaven_storm_vermin"
local WARLOCK_CHILD_PACKAGE = "resource_packages/doomrocket/warlock_child"
local WARLOCK_SLOT_MATERIALS = {
	{ "DoomRocket_Armor", "child_materials/warlock_bombardier/wb_armor_child" },
	{ "DoomRocket_Backpack", "child_materials/warlock_bombardier/wb_backpack_child" },
	{ "wb_skin", "child_materials/warlock_bombardier/wb_skin_child" },
	{ "wb_fur", "child_materials/warlock_bombardier/wb_fur_child" },
	{ "wb_whiskers", "child_materials/warlock_bombardier/wb_whiskers_child" },
}
local WARLOCK_CUSTOM_TEXTURES = {
	"textures/warlock_bombardier/wb_armor_df",
	"textures/warlock_bombardier/wb_armor_nm",
	"textures/warlock_bombardier/wb_armor_ma",
	"textures/warlock_bombardier/wb_backpack_df",
	"textures/warlock_bombardier/wb_backpack_nm",
	"textures/warlock_bombardier/wb_backpack_ma",
}
local warlock_child_package_requested = false

-- Death visuals use a two-unit contract: the hidden native ratling owns all
-- actors/PhysX, while this physics-free custom unit owns the pixels. Previous
-- builds failed in three independent ways: custom actors destabilized PhysX;
-- per-bone links destroyed this unit's hierarchy; and raw native local poses
-- were copied into a custom hierarchy whose compiled armature wrapper is 100x.
--
-- The calibrated transfer below is deliberately captured in death pre_start,
-- before GenericHitReactionExtension can emit its delayed death event. It then
-- runs from AnimationSystem's safe callback, after World.update_animations and
-- before World.update_scene. The outfit ASM stays enabled for its proven render
-- lifecycle, but bone mode "ignore" makes this callback the sole bone writer.
local WARLOCK_RAGDOLL_SAMPLE_TIMES_MS = { 0, 100, 250, 500, 1000, 2000, 5000 }
local WARLOCK_RAGDOLL_MONITOR_TIME_MS = 5000
local WARLOCK_RAGDOLL_EXPECTED_NODES = 90
local WARLOCK_MATRIX_AXIS_EPSILON = 0.000001
local WARLOCK_MATRIX_VOLUME_EPSILON = 0.00001
local WARLOCK_RAGDOLL_PROBE_NAMES = {
	"root_point", "j_hips", "j_head", "j_righthand", "j_lefthand",
	"j_rightfoot", "j_leftfoot",
}

local function warlock_rigid_world_pose(unit, node)
	return Matrix4x4.from_quaternion_position(
		Unit.world_rotation(unit, node), Unit.world_position(unit, node))
end

local function warlock_matrix_is_invertible(matrix)
	if not Matrix4x4.is_valid(matrix) then
		return false
	end

	local x = Matrix4x4.axis(matrix, 1)
	local y = Matrix4x4.axis(matrix, 2)
	local z = Matrix4x4.axis(matrix, 3)
	local x_length = Vector3.length(x)
	local y_length = Vector3.length(y)
	local z_length = Vector3.length(z)
	if x_length < WARLOCK_MATRIX_AXIS_EPSILON or
		y_length < WARLOCK_MATRIX_AXIS_EPSILON or
		z_length < WARLOCK_MATRIX_AXIS_EPSILON then
		return false
	end

	-- Axis lengths alone do not detect collinear/sheared singular matrices.
	-- Normalize the scalar triple product so the test is scale-independent.
	local normalized_volume = math.abs(Vector3.dot(x, Vector3.cross(y, z))) /
		(x_length * y_length * z_length)

	return normalized_volume > WARLOCK_MATRIX_VOLUME_EPSILON
end

local function warlock_node_depth(unit, node)
	local depth = 0
	local current = node

	while current and current ~= 0 and depth < 256 do
		local parent = Unit.scene_graph_parent(unit, current)
		if not parent or parent == current then
			break
		end

		current = parent
		depth = depth + 1
	end

	return depth
end

local function warlock_unit_actor_count(unit)
	local count = -1
	pcall(function()
		count = Unit.num_actors(unit)
	end)

	return count
end

local function warlock_bounds_radius(unit)
	local radius = 0
	pcall(function()
		local _, extents = Unit.box(unit)
		radius = Vector3.length(extents)
	end)

	return radius
end


local function warlock_max_bone_radius(driver)
	local outfit_unit = driver.outfit
	local center = Unit.world_position(outfit_unit, driver.outfit_hips)
	local radius = 0

	for i = 1, #driver.node_pairs do
		local distance = Vector3.length(
			Unit.world_position(outfit_unit, driver.node_pairs[i].target) - center)
		radius = math.max(radius, distance)
	end

	return radius
end

local function stop_warlock_death_driver(driver, reason)
	if driver.stopped then
		return
	end

	driver.stopped = true
	mod._warlock_active_death_drivers[driver] = nil
	if not driver.monitor_complete then
		local now = warlock_game_time()
		local owner_alive = driver.owner and Unit.alive(driver.owner) or false
		local outfit_alive = driver.outfit and Unit.alive(driver.outfit) or false
		printf("[doomrocket:RAGDOLL] phase=stop id=%s source=%s elapsed_ms=%.1f owner_alive=%s outfit_alive=%s reason=%s callbacks=%d pose_writes=%d sleep_skips=%d",
			driver.id, driver.source, (now - driver.created_game_at) * 1000,
			tostring(owner_alive), tostring(outfit_alive), tostring(reason),
			driver.callback_count or 0, driver.pose_write_callbacks or 0,
			driver.sleep_skip_callbacks or 0)
	end
end

local function complete_warlock_death_monitor(driver, now)
	if driver.monitor_complete then
		return
	end

	driver.monitor_complete = true
	printf("[doomrocket:RAGDOLL] phase=stop id=%s source=%s elapsed_ms=%.1f owner_alive=true outfit_alive=true reason=monitor_complete callbacks=%d pose_writes=%d sleep_skips=%d",
		driver.id, driver.source, (now - driver.created_game_at) * 1000,
		driver.callback_count or 0, driver.pose_write_callbacks or 0,
		driver.sleep_skip_callbacks or 0)
end

local function warlock_carrier_ragdoll_sleeping(driver)
	local actors = driver.ragdoll_actors
	if not actors then
		actors = {}
		-- Actor names are not guaranteed to match deform-bone names. Enumerate
		-- the carrier's actual physics scene instead of assuming j_* actors exist.
		for actor_index = 0, Unit.num_actors(driver.owner) - 1 do
			local actor = Unit.actor(driver.owner, actor_index)
			if actor and Actor.is_dynamic(actor) then
				actors[#actors + 1] = actor
			end
		end

		-- Before the death event activates the native ragdoll there may be no
		-- dynamic bodies yet. Retry on the next callback rather than mistaking
		-- that transition frame for a sleeping corpse.
		if #actors == 0 then
			return false
		end
		driver.ragdoll_actors = actors
	end

	for i = 1, #actors do
		if not Actor.is_sleeping(actors[i]) then
			return false
		end
	end

	return true
end

local function sample_warlock_death_driver(driver, now, checkpoint_ms, wall_gap_ms)
	local owner_unit = driver.owner
	local outfit_unit = driver.outfit
	local owner_root = Unit.world_position(owner_unit, 0)
	local outfit_anchor = Unit.world_position(outfit_unit, 0)
	local owner_hips = Unit.world_position(owner_unit, driver.owner_hips)
	local outfit_hips = Unit.world_position(outfit_unit, driver.outfit_hips)
	local hips_offset = outfit_hips - owner_hips
	local root_delta = Vector3.length(outfit_anchor - owner_root)
	local hips_delta = Vector3.length(hips_offset)
	local hips_drift = Vector3.length(hips_offset - driver.initial_hips_offset:unbox())
	local parent_mismatch = 0
	local scale_mutations = 0
	local nonhips_translation_mutations = 0

	for i = 1, #driver.node_pairs do
		local pair = driver.node_pairs[i]
		if Unit.scene_graph_parent(outfit_unit, pair.target) ~= pair.parent then
			parent_mismatch = parent_mismatch + 1
		end
		if Vector3.length(Unit.local_scale(outfit_unit, pair.target) -
				pair.initial_local_scale:unbox()) > 0.0001 then
			scale_mutations = scale_mutations + 1
		end
		if not pair.is_hips and Vector3.length(Unit.local_position(outfit_unit, pair.target) -
				pair.initial_local_position:unbox()) > 0.0001 then
			nonhips_translation_mutations = nonhips_translation_mutations + 1
		end
	end

	local anchor_max_drift = 0
	local named_root_drift = 0
	for i = 1, #driver.probes do
		local probe = driver.probes[i]
		local offset = Unit.world_position(outfit_unit, probe.target) -
			Unit.world_position(owner_unit, probe.source)
		local drift = Vector3.length(offset - probe.initial_offset:unbox())
		anchor_max_drift = math.max(anchor_max_drift, drift)
		if probe.name == "root_point" then
			named_root_drift = drift
		end
	end

	local bounds_radius = warlock_bounds_radius(outfit_unit)
	local max_bone_radius = warlock_max_bone_radius(driver)
	local bounds_ratio = driver.initial_bounds_radius > 0 and
		bounds_radius / driver.initial_bounds_radius or 1
	local max_bone_radius_ratio = driver.initial_max_bone_radius > 0 and
		max_bone_radius / driver.initial_max_bone_radius or 1
	local tracker = driver.carrier_tracker

	printf("[doomrocket:RAGDOLL] phase=sample id=%s source=%s checkpoint_ms=%d elapsed_ms=%.1f wall_gap_ms=%.1f owner_alive=true outfit_alive=true nodes=%d custom_actors=%d carrier_reveals=%d parent_mismatch=%d root_delta=%.3f named_root_drift=%.3f hips_delta=%.3f hips_drift=%.3f anchor_max_drift=%.3f scale_mutations=%d nonhips_translation_mutations=%d bounds_ratio=%.3f max_bone_radius_ratio=%.3f pose_writes=%d sleep_skips=%d",
		driver.id, driver.source, checkpoint_ms, (now - driver.created_game_at) * 1000,
		wall_gap_ms, #driver.node_pairs, warlock_unit_actor_count(outfit_unit),
		tracker and tracker.reveal_count or 0, parent_mismatch, root_delta,
		named_root_drift, hips_delta, hips_drift, anchor_max_drift,
		scale_mutations, nonhips_translation_mutations, bounds_ratio,
		max_bone_radius_ratio, driver.pose_write_callbacks or 0,
		driver.sleep_skip_callbacks or 0)
end

local queue_warlock_death_pose

local function apply_warlock_death_pose(driver)
	local owner_unit = driver.owner
	local outfit_unit = driver.outfit

	if not owner_unit or not Unit.alive(owner_unit) or
			not outfit_unit or not Unit.alive(outfit_unit) then
		stop_warlock_death_driver(driver, "unit_not_alive")
		return false
	end

	local wall_now = Application.time_since_launch()
	local now = warlock_game_time()
	local wall_gap_ms = (wall_now - driver.last_callback_wall_at) * 1000
	driver.last_callback_wall_at = wall_now
	driver.callback_count = driver.callback_count + 1
	driver.max_wall_gap_ms = math.max(driver.max_wall_gap_ms or 0, wall_gap_ms)
	-- The first five seconds are the proven, fully driven validation window.
	-- Do not inspect/cache carrier actors until the native death ragdoll has had
	-- time to activate: pre-ragdoll actors can report sleeping and would freeze
	-- the visual skeleton while the newly activated carrier keeps moving.
	local carrier_sleeping = driver.monitor_complete and
		warlock_carrier_ragdoll_sleeping(driver)
	if carrier_sleeping then
		driver.sleep_skip_callbacks = driver.sleep_skip_callbacks + 1
	end

	-- Freeze all source samples before touching the target. Source transforms are
	-- rebuilt rigid (unit scale) so native animated scale/shear can never enter
	-- the custom skin. With Stingray's row-matrix convention:
	--   D = inverse(S0) * St; desiredWorld = T0 * D
	-- and desiredLocal = desiredWorld * inverse(desiredParentWorld).
	-- The final inverse-parent step is what normalizes the 100x wrapper.
	local desired_worlds = {}
	if not carrier_sleeping then
		for i = 1, #driver.node_pairs do
			local pair = driver.node_pairs[i]
			local source_world = warlock_rigid_world_pose(owner_unit, pair.source)
			if not Matrix4x4.is_valid(source_world) then
				stop_warlock_death_driver(driver, "invalid_source_matrix")
				return false
			end

			local source_delta = Matrix4x4.multiply(
				pair.source_world_inverse_at_handoff:unbox(), source_world)
			desired_worlds[i] = Matrix4x4.multiply(
				pair.target_world_at_handoff:unbox(), source_delta)

			if not Matrix4x4.is_valid(source_delta) or
				not Matrix4x4.is_valid(desired_worlds[i]) then
				stop_warlock_death_driver(driver, "invalid_source_or_world_matrix")
				return false
			end
		end
	end

	local resolved_worlds = {}
	local function resolve_target_world(node)
		local pair_index = driver.pair_by_target[node]
		if pair_index then
			return desired_worlds[pair_index]
		end
		if node == 0 then
			return Unit.world_pose(outfit_unit, 0)
		end

		local cached = resolved_worlds[node]
		if cached then
			return cached
		end

		local graph_node = driver.target_graph[node]
		if not graph_node then
			return Unit.world_pose(outfit_unit, node)
		end

		local parent_world = resolve_target_world(graph_node.parent)
		local world_pose = Matrix4x4.multiply(
			graph_node.local_pose_at_handoff:unbox(), parent_world)
		resolved_worlds[node] = world_pose

		return world_pose
	end

	-- Resolve and validate the entire candidate pose before the first engine
	-- write. A NaN/Inf matrix must never reach Unit.set_local_*.
	local desired_locals = {}
	for i = 1, carrier_sleeping and 0 or #driver.node_pairs do
		local pair = driver.node_pairs[i]
		local parent_world = resolve_target_world(pair.parent)
		if not warlock_matrix_is_invertible(parent_world) then
			stop_warlock_death_driver(driver, "singular_parent_matrix")
			return false
		end

		local parent_inverse = Matrix4x4.inverse(parent_world)
		if not Matrix4x4.is_valid(parent_inverse) then
			stop_warlock_death_driver(driver, "invalid_parent_inverse")
			return false
		end

		local desired_local = Matrix4x4.multiply(
			desired_worlds[i], parent_inverse)

		if not warlock_matrix_is_invertible(desired_local) then
			stop_warlock_death_driver(driver, "invalid_parent_or_local_matrix")
			return false
		end

		desired_locals[i] = desired_local
	end

	-- The bridge table is not parent-first, so node_pairs was explicitly sorted
	-- by target scene-graph depth during calibration.
	for i = 1, carrier_sleeping and 0 or #driver.node_pairs do
		local pair = driver.node_pairs[i]
		local desired_local = desired_locals[i]
		Unit.set_local_rotation(outfit_unit, pair.target,
			Matrix4x4.rotation(desired_local))
		if pair.is_hips then
			Unit.set_local_position(outfit_unit, pair.target,
				Matrix4x4.translation(desired_local))
		end
	end

	if not carrier_sleeping then
		World.update_unit(Unit.world(outfit_unit), outfit_unit)
		driver.pose_write_callbacks = driver.pose_write_callbacks + 1
	end

	local elapsed_ms = (now - driver.created_game_at) * 1000
	local checkpoint = WARLOCK_RAGDOLL_SAMPLE_TIMES_MS[driver.next_sample]
	if checkpoint and elapsed_ms >= checkpoint then
		repeat
			driver.next_sample = driver.next_sample + 1
			checkpoint = WARLOCK_RAGDOLL_SAMPLE_TIMES_MS[driver.next_sample]
		until not checkpoint or elapsed_ms < checkpoint

		-- Report the worst callback gap since the previous checkpoint, not just
		-- the final frame before this sample. Otherwise a one-frame stall between
		-- checkpoints can disappear from the log.
		local max_wall_gap_ms = driver.max_wall_gap_ms
		driver.max_wall_gap_ms = 0
		sample_warlock_death_driver(driver, now,
			WARLOCK_RAGDOLL_SAMPLE_TIMES_MS[driver.next_sample - 1], max_wall_gap_ms)
	end

	if elapsed_ms >= WARLOCK_RAGDOLL_MONITOR_TIME_MS then
		complete_warlock_death_monitor(driver, now)
	end

	return true
end

queue_warlock_death_pose = function(driver)
	if not driver or driver.stopped or driver.callback_pending then
		return
	end

	local entity_manager = Managers.state.entity
	local animation_system = entity_manager and entity_manager:system("animation_system")
	if not animation_system then
		stop_warlock_death_driver(driver, "animation_system_missing")
		return
	end

	driver.callback_pending = true
	animation_system:add_safe_animation_callback(function()
		driver.callback_pending = false
		if not driver.stopped then
			apply_warlock_death_pose(driver)
		end
	end)
end

-- AnimationSystem's callback queue is global and ScriptWorld drains it once
-- for every active world. Enqueuing from inside a callback can therefore run
-- the 90-bone transfer several times in one rendered frame. Instead, enqueue
-- once only after the specific world that owns this carrier has finished its
-- animation pass; ScriptWorld drains it immediately before that same world's
-- scene update.
local function queue_warlock_death_drivers_for_world(world)
	for driver, _ in pairs(mod._warlock_active_death_drivers) do
		if driver.stopped then
			mod._warlock_active_death_drivers[driver] = nil
		elseif not driver.owner or not Unit.alive(driver.owner) or
				not driver.outfit or not Unit.alive(driver.outfit) then
			stop_warlock_death_driver(driver, "unit_not_alive")
		elseif Unit.world(driver.owner) == world and
			(not driver.monitor_complete or not warlock_carrier_ragdoll_sleeping(driver)) then
			queue_warlock_death_pose(driver)
		end
	end
end

-- VMF accepts only one hook per mod/method, even across hook and hook_safe.
-- Keep pre-animation gait updates and post-animation corpse/hose queueing in
-- the same hook; registering a second hook silently leaves death bones frozen.
-- This vararg tail preserves every native return value, including nil slots.
local function finish_warlock_animation_update(world, dt, ...)
	mod:pcall(queue_warlock_death_drivers_for_world, world)
	mod:pcall(mod._queue_warlock_hose, world, dt)
	return ...
end

-- The owner has already moved; this world's dt also covers interpolated husks.
mod:hook(World, "update_animations", function(func, world, dt, ...)
	mod._update_warlock_locomotion_animation(world, dt)
	return finish_warlock_animation_update(world, dt, func(world, dt, ...))
end)

mod:hook(World, "update_animations_with_callback", function(func, world, dt, ...)
	mod._update_warlock_locomotion_animation(world, dt)
	return finish_warlock_animation_update(world, dt, func(world, dt, ...))
end)

mod._reset_warlock_death_drivers = function()
	for driver, _ in pairs(mod._warlock_active_death_drivers) do
		driver.stopped = true
		driver.callback_pending = false
	end
	mod._warlock_active_death_drivers = {}
	mod._warlock_pending_death_drivers = setmetatable({}, { __mode = "k" })
	mod._warlock_outfits = setmetatable({}, { __mode = "kv" })
	mod._warlock_carriers = setmetatable({}, { __mode = "k" })
end

mod._prepare_warlock_death = function(owner_unit, source)
	mod._stop_warlock_locomotion_animation(owner_unit)
	mod._stop_warlock_hose(owner_unit, "death_" .. tostring(source))
	-- Cosmetic emitter ownership ends before the outfit enters its corpse handoff.
	mod._stop_warlock_backpack_smoke(owner_unit, "death_" .. tostring(source))
	-- Stop while the visible outfit and its backpack source are still alive. Later death
	-- callbacks hand animation ownership to the corpse and may delete either unit.
	mod._stop_warlock_backpack_sound(owner_unit, "death_" .. tostring(source))

	mod._warlock_death_sequence = mod._warlock_death_sequence + 1
	local id = string.format("%s-%04d", source, mod._warlock_death_sequence)
	local created_game_at = warlock_game_time()
	local created_wall_at = Application.time_since_launch()
	local outfit_unit = mod._warlock_outfits[owner_unit]
	local function reject_calibration(reason)
		printf("[doomrocket:RAGDOLL] phase=stop id=%s source=%s elapsed_ms=0 owner_alive=%s outfit_alive=%s reason=%s callbacks=0 pose_writes=0 sleep_skips=0",
			id, source, tostring(owner_unit and Unit.alive(owner_unit) or false),
			tostring(outfit_unit and Unit.alive(outfit_unit) or false), reason)
		return nil
	end

	if not outfit_unit or not Unit.alive(outfit_unit) then
		return reject_calibration("no_live_outfit")
	end

	local bridge = AttachmentNodeLinking.doomrocket_warlock_bridge
	local node_pairs = {}
	local target_seen = {}
	local hips_count = 0
	local skipped = 0
	for i = 1, #bridge do
		local entry = bridge[i]
		local target_node = entry.target
		local source_node = entry.source
		local target_name = type(target_node) == "string" and target_node or nil
		local source_name = type(source_node) == "string" and source_node or nil
		local excluded =
			(target_name and (target_name:sub(-6) == "_scale" or target_name == "aim_target")) or
			(source_name and (source_name:sub(-6) == "_scale" or source_name == "aim_target"))

		-- Target 0 is already root-linked by the inventory attachment. Keep that
		-- single link and drive only the intact child hierarchy.
		if target_node ~= 0 and not excluded then
			if target_name and not Unit.has_node(outfit_unit, target_name) then
				return reject_calibration("missing_target_node")
		end
			if source_name and not Unit.has_node(owner_unit, source_name) then
				return reject_calibration("missing_source_node")
		end

			local target_index = target_name and Unit.node(outfit_unit, target_name) or target_node
			local source_index = source_name and Unit.node(owner_unit, source_name) or source_node
			if target_seen[target_index] then
				return reject_calibration("duplicate_target_node")
		end
			target_seen[target_index] = true

			local parent = Unit.scene_graph_parent(outfit_unit, target_index)
			local source_world_at_handoff = warlock_rigid_world_pose(owner_unit, source_index)
			local target_world_at_handoff = Unit.world_pose(outfit_unit, target_index)
			local initial_local_position = Unit.local_position(outfit_unit, target_index)
			local initial_local_scale = Unit.local_scale(outfit_unit, target_index)
			if not warlock_matrix_is_invertible(source_world_at_handoff) or
					not warlock_matrix_is_invertible(target_world_at_handoff) or
				not Vector3.is_valid(initial_local_position) or
				not Vector3.is_valid(initial_local_scale) then
				return reject_calibration("invalid_handoff_matrix")
		end
			local source_world_inverse_at_handoff = Matrix4x4.inverse(source_world_at_handoff)
			if not Matrix4x4.is_valid(source_world_inverse_at_handoff) then
				return reject_calibration("invalid_source_inverse")
		end

			local is_hips = (source_name == "j_hips") or (target_name == "j_hips")
			if is_hips then
				hips_count = hips_count + 1
			end

			node_pairs[#node_pairs + 1] = {
				target = target_index,
				source = source_index,
				source_name = source_name,
				name = target_name or source_name or tostring(target_index),
				parent = parent,
				depth = warlock_node_depth(outfit_unit, target_index),
				is_hips = is_hips,
				source_world_at_handoff = Matrix4x4Box(source_world_at_handoff),
				source_world_inverse_at_handoff = Matrix4x4Box(source_world_inverse_at_handoff),
				target_world_at_handoff = Matrix4x4Box(target_world_at_handoff),
				initial_local_position = Vector3Box(initial_local_position),
				initial_local_scale = Vector3Box(initial_local_scale),
			}
		elseif target_node ~= 0 then
			skipped = skipped + 1
		end
	end
	if #node_pairs ~= WARLOCK_RAGDOLL_EXPECTED_NODES then
		return reject_calibration("unexpected_node_count")
	end
	if hips_count ~= 1 or not Unit.has_node(owner_unit, "j_hips") or
		not Unit.has_node(outfit_unit, "j_hips") then
		return reject_calibration("missing_or_duplicate_hips")
	end

	table.sort(node_pairs, function(a, b)
		return a.depth == b.depth and a.target < b.target or a.depth < b.depth
	end)

	local pair_by_target = {}
	local target_graph = {}
	for i = 1, #node_pairs do
		pair_by_target[node_pairs[i].target] = i
		local current = node_pairs[i].parent
		local guard = 0
		while current and current ~= 0 and not target_graph[current] and guard < 256 do
			local parent = Unit.scene_graph_parent(outfit_unit, current)
			local local_pose_at_handoff = Unit.local_pose(outfit_unit, current)
			if not warlock_matrix_is_invertible(local_pose_at_handoff) then
				return reject_calibration("invalid_target_graph_pose")
			end
			target_graph[current] = {
				parent = parent,
				local_pose_at_handoff = Matrix4x4Box(local_pose_at_handoff),
			}
			current = parent
			guard = guard + 1
		end
	end

	local probes = {}
	for i = 1, #WARLOCK_RAGDOLL_PROBE_NAMES do
		local name = WARLOCK_RAGDOLL_PROBE_NAMES[i]
		if Unit.has_node(owner_unit, name) and Unit.has_node(outfit_unit, name) then
			local source_node = Unit.node(owner_unit, name)
			local target_node = Unit.node(outfit_unit, name)
			probes[#probes + 1] = {
				name = name,
				source = source_node,
				target = target_node,
				initial_offset = Vector3Box(Unit.world_position(outfit_unit, target_node) -
					Unit.world_position(owner_unit, source_node)),
			}
		end
	end

	local owner_hips = Unit.node(owner_unit, "j_hips")
	local outfit_hips = Unit.node(outfit_unit, "j_hips")
	local tracker = mod._warlock_carriers[owner_unit] or { reveal_count = 0 }
	tracker.id = id
	tracker.source = source
	tracker.created_game_at = created_game_at
	mod._warlock_carriers[owner_unit] = tracker

	local driver = {
		id = id,
		source = source,
		created_game_at = created_game_at,
		created_wall_at = created_wall_at,
		last_callback_wall_at = created_wall_at,
		owner = owner_unit,
		outfit = outfit_unit,
		node_pairs = node_pairs,
		pair_by_target = pair_by_target,
		target_graph = target_graph,
		probes = probes,
		owner_hips = owner_hips,
		outfit_hips = outfit_hips,
		initial_hips_offset = Vector3Box(
			Unit.world_position(outfit_unit, outfit_hips) -
			Unit.world_position(owner_unit, owner_hips)),
		next_sample = 1,
		callback_count = 0,
		pose_write_callbacks = 0,
		sleep_skip_callbacks = 0,
		callback_pending = false,
		max_wall_gap_ms = 0,
		monitor_complete = false,
		carrier_tracker = tracker,
	}
	driver.initial_bounds_radius = warlock_bounds_radius(outfit_unit)
	driver.initial_max_bone_radius = warlock_max_bone_radius(driver)

	-- Calibration above must see the last proven living pose. Only after it is
	-- boxed do we detach event mirroring and switch animation ownership.
	mod._warlock_outfits[owner_unit] = nil
	Unit.set_animation_bone_mode(outfit_unit, "ignore")
	Unit.set_bones_lod(outfit_unit, 0)
	Unit.set_unit_visibility(outfit_unit, true)
	mod._warlock_pending_death_drivers[owner_unit] = driver
	mod._warlock_active_death_drivers[driver] = true

	printf("[doomrocket:RAGDOLL] phase=begin id=%s source=%s elapsed_ms=0 owner_alive=true outfit_alive=true nodes=%d scale_aim_excluded=%d custom_actors=%d carrier_reveals=%d bone_mode=ignore callback=post_animation",
		id, source, #node_pairs, skipped, warlock_unit_actor_count(outfit_unit),
		tracker.reveal_count or 0)

	return driver
end

mod._take_warlock_death_driver = function(owner_unit)
	local driver = mod._warlock_pending_death_drivers[owner_unit]
	mod._warlock_pending_death_drivers[owner_unit] = nil

	return driver
end

mod._update_warlock_death_pose = function(data)
	local driver = data.warlock_pose_driver

	if not driver then
		return
	end
	if driver.stopped then
		data.warlock_pose_driver = nil
		return
	end

	-- The owner-world animation hooks retain this driver until either unit is
	-- deleted, including after vanilla's short unit/husk reaction completes.
	-- Five seconds ends telemetry only; sleeping native actors suspend the
	-- expensive pose transfer and a later physics wake resumes it.
end

mod._apply_warlock_child_materials = function(outfit_unit)
	if not Managers.package:has_loaded(WARLOCK_ARMOR_DONOR_PACKAGE, "global") or
			not Managers.package:has_loaded(WARLOCK_NATIVE_BODY_PACKAGE, "global") then
		printf("[doomrocket] warlock materials skipped: Ratling/Stormvermin donor packages not resident yet")
		return
	end

	if not mod.load_package or not mod.package_status then
		printf("[doomrocket] warlock materials skipped: VMF package API unavailable")
		return
	end

	if not warlock_child_package_requested then
		warlock_child_package_requested = true
		mod:load_package(WARLOCK_CHILD_PACKAGE, nil, true)
	end

	if mod:package_status(WARLOCK_CHILD_PACKAGE) ~= "loaded" then
		printf("[doomrocket] warlock materials skipped: child package status %s",
			tostring(mod:package_status(WARLOCK_CHILD_PACKAGE)))
		return
	end

	local missing_textures = 0
	for _, texture_path in ipairs(WARLOCK_CUSTOM_TEXTURES) do
		if not Application.can_get("texture", texture_path) then
			missing_textures = missing_textures + 1
			printf("[doomrocket:MATERIAL] texture NOT resident: %s", texture_path)
		end
	end

	local applied = 0
	for _, binding in ipairs(WARLOCK_SLOT_MATERIALS) do
		local slot_name, material_path = binding[1], binding[2]
		if Application.can_get("material", material_path) then
			Unit.set_material(outfit_unit, slot_name, material_path)
			applied = applied + 1
			printf("[doomrocket:MATERIAL] slot %s <- %s", slot_name, material_path)
		else
			printf("[doomrocket:MATERIAL] material NOT resident for slot %s: %s",
				slot_name, material_path)
		end
	end

	printf("[doomrocket:MATERIAL] assignment summary: slots=%d/%d custom_textures=%d/%d resident",
		applied, #WARLOCK_SLOT_MATERIALS,
		#WARLOCK_CUSTOM_TEXTURES - missing_textures, #WARLOCK_CUSTOM_TEXTURES)
end

mod:hook(AIInventoryExtension, "_setup_configuration", function (func, self, unit, start_n, inventory_configuration, item_extension_init_data)
	-- Prune the armor bridge to nodes the OWNER actually has, BEFORE vanilla links.
	--
	-- vanilla link_unit does Unit.node(source, source_node), and a missing node is an
	-- engine-level fatal that pcall cannot catch, so the bridge may only name nodes that
	-- exist on this breed's base skeleton. Unit.has_node is the safe existence test.
	-- Pruning here (rather than shipping a hand-verified list) means we can name every
	-- bone the mesh is weighted to and let the ones the base lacks drop out quietly.
	mod._prune_armor_bridge(unit)

	local result = func(self, unit, start_n, inventory_configuration, item_extension_init_data)

	local outfit_units = self.inventory_item_outfit_units

	local wearing_warlock_body = false

	for i, outfit_unit in ipairs(outfit_units) do
		if Unit.alive(outfit_unit) then
			local outfit_unit_name = Unit.get_data(outfit_unit, "unit_name")
			if outfit_unit_name == "units/beings/enemies/skaven_plague_monk/chr_skaven_plague_monk" then
				Unit.disable_animation_state_machine(outfit_unit)
			elseif outfit_unit_name == "units/warlock_bombardier/warlock_bombardier_3p" then
				-- Living configuration proven since v0.1.37: root-only attachment
				-- plus this custom unit's own enabled ASM. Its clips were imported
				-- from compiled ratling animation and recompiled against THIS rig.
				-- Per-bone World links deform the Blender hierarchy, while binding
				-- a foreign state machine is an uncatchable engine crash.
				Unit.set_animation_bone_mode(outfit_unit, "transform")
				Unit.set_bones_lod(outfit_unit, 0)
				Unit.enable_animation_state_machine(outfit_unit)
				if Unit.has_animation_event(outfit_unit, "idle") then
					Unit.animation_event(outfit_unit, "idle")
				end
				mod._warlock_outfits[unit] = outfit_unit
				mod._start_warlock_locomotion_animation(unit, outfit_unit)
				wearing_warlock_body = true
				mod._apply_warlock_child_materials(outfit_unit)
				-- This runs on the authoritative unit and every husk, including hot-joins, so
				-- each peer owns exactly one spatial loop on the visible backpack outfit.
				mod._start_warlock_backpack_sound(unit, outfit_unit)
				mod._start_warlock_backpack_smoke(unit, outfit_unit)
				mod._start_warlock_hose(unit, outfit_unit, self)
			end
		end
	end

	-- Crunch's unit now ships all five meshes (body, fur, vanilla armor, warlock armor,
	-- backpack), so the donor must not also draw. (An earlier `if false` here - staged
	-- when the set was believed body-less, then never reverted - shipped in v0.1.13 and
	-- resurrected the donor rat.)
	if wearing_warlock_body and Unit.alive(unit) then
		-- Hide the donor body's renderables only. Do NOT use Unit.set_unit_visibility on
		-- the owner: the outfit is linked to the owner's scene-graph nodes and driven by
		-- the owner's animation, so the base unit must keep animating even though nothing
		-- of it should draw.
		-- v0.1.10-dev hid 0: the loop was gated on Unit.has_mesh(unit, index), but that
		-- API does not take a mesh index, so it returned false and broke immediately.
		-- Ask the unit how many meshes it has; if that API is unavailable, use the
		-- 24-mesh count measured from the current compiled native ratling carrier.
		local hidden, num_meshes, counted = hide_warlock_carrier_meshes(unit)

		-- Register only after the initial hide. Any later true mesh write is a
		-- regression and is correlated with the eventual corpse ID at death.
		mod._warlock_carriers[unit] = { reveal_count = 0 }

		printf("[doomrocket] donor reports %s mesh(es)%s",
			tostring(num_meshes), counted and "" or " (Unit.num_meshes unavailable; used fallback)")

		printf("[doomrocket] warlock body attached; hid %d base mesh(es) on the donor unit", hidden)
	end

	return result
end)

-- Stop before native inventory teardown unlinks/deletes the parent outfit.
mod:hook(AIInventoryExtension, "destroy", function(func, self, ...)
	mod._stop_warlock_locomotion_animation(self.unit)
	mod._stop_warlock_hose(self.unit, "inventory_destroy")
	mod._stop_warlock_backpack_smoke(self.unit, "inventory_destroy")
	return func(self, ...)
end)

mod:hook(AIInventoryExtension, "freeze", function(func, self, ...)
	mod._stop_warlock_locomotion_animation(self.unit)
	mod._stop_warlock_hose(self.unit, "inventory_freeze")
	mod._stop_warlock_backpack_smoke(self.unit, "inventory_freeze")
	return func(self, ...)
end)

-- Stop only when vanilla's drop eligibility allows this exact carried item.
-- The cosmetic hose must disappear before any dropped actor is created.
mod:hook(AIInventoryExtension, "drop_single_item", function(func, self, index, reason, ...)
	local item_unit = self.inventory_item_units and self.inventory_item_units[index]
	local item = self.inventory_item_definitions and self.inventory_item_definitions[index]
	local dropped = self.dropped_items and self.dropped_items[index]
	local extension = item_unit and Unit.alive(item_unit) and ScriptUnit.has_extension(item_unit, "ai_inventory_item_system")
	local template = item and (item.unit_extension_template or "ai_inventory_item")
	if dropped == nil and extension and not extension.dropped and item and item.drop_reasons and item.drop_reasons[reason]
		and template ~= "ai_helmet_unit" and template ~= "ai_outfit_unit" and template ~= "ai_skin_unit" then
		mod._stop_warlock_hose_item(self.unit, item_unit, "inventory_drop")
	end
	return func(self, index, reason, ...)
end)

mod:hook(AIInventoryExtension, "disable_inventory_item", function(func, self, item, item_unit, ...)
	mod._stop_warlock_hose_item(self.unit, item_unit, "inventory_disable_item")
	return func(self, item, item_unit, ...)
end)

-- Forget IDs before the engine releases the world. The engine owns destruction
-- here; a later reset must never operate on a recycled particle/world handle.
mod:hook(Application, "release_world", function(func, world, ...)
	mod._release_warlock_locomotion_world(world)
	mod._release_warlock_hose(world)
	mod._release_warlock_smoke_world(world)
	local function finish_release(...)
		mod._finish_release_warlock_hose(world)
		return ...
	end
	return finish_release(func(world, ...))
end)

-- these functions are needed so the client can properly spawn in the custom breed with right breed data set
local unit_go_sync_functions = require("scripts/mods/doomrocket/utils/game_object_initializers_extractors")
mod:hook(UnitSpawner, 'set_gameobject_initializer_data', function(func, self, initializer_function_table, extraction_function_table, gameobject_context)
	initializer_function_table = unit_go_sync_functions.initializers
	extraction_function_table = unit_go_sync_functions.extractors
	return func(self, initializer_function_table, extraction_function_table, gameobject_context)
end)

mod:hook(UnitSpawner, 'set_gameobject_to_unit_creator_function', function(func, self, function_table)
	function_table = unit_go_sync_functions.unit_from_gameobject_creator_func
	return func(self, function_table)
end)


--stops a crash but needs to be revisted as it borks other things
-- mod:hook(Unit, 'animation_set_constraint_target', function(func, self, index, value)

-- 	-- print(index)
-- 	-- print(value)

-- 	local result = func(self, index, value)

-- 	-- return func(self, index, value)
-- 	return
-- end)

-- Merge our two templates into the REAL vanilla table rather than swapping the whole
-- file out for a stale copy. See utils/unit_extension_template_additions.lua.
local apply_unit_extension_template_additions = dofile("scripts/mods/doomrocket/utils/unit_extension_template_additions")

mod:hook(_G, 'require', function(func, file_name, ...)
	local result = func(file_name, ...)

	if file_name == "scripts/network/unit_extension_templates" and type(result) == "table" then
		apply_unit_extension_template_additions(result)
	end

	return result
end)

-- unit_spawner.lua and breed_freezer.lua capture this table at file scope during boot,
-- before any mod loads, so the hook above would never reach those references. Merging
-- once directly covers them whenever require returns a cached table. Idempotent.
apply_unit_extension_template_additions(require("scripts/network/unit_extension_templates"))

-- print(Network.config_hash('global'))



-- local function get_network_options()
-- 	local network_options = {
-- 		config_file_name = "scripts/mods/doomrocket/utils/doomrocket", -- MODIFIED
-- 		ip_address = Network.default_network_address(),
-- 		lobby_port = GameSettingsDevelopment.network_port,
-- 		map = "None",
-- 		max_members = 4,
-- 		project_hash = "bulldozer",
-- 		query_port = script_data.query_port or script_data.settings.query_port,
-- 		server_port = script_data.server_port or script_data.settings.server_port or 27015,
-- 		steam_port = script_data.steam_port or script_data.settings.steam_port,
-- 	}
-- 	return network_options
-- end

-- mod:hook_origin(LobbyManager, "setup_network_options", function(self, increment_lobby_port)
-- 	local network_options = get_network_options()
-- 	local lobby_port = script_data.server_port or script_data.settings.server_port or network_options.lobby_port
-- 	lobby_port = lobby_port + self._lobby_port_increment
-- 	if increment_lobby_port then
-- 		self._lobby_port_increment = self._lobby_port_increment + 1
-- 	end
-- 	network_options.lobby_port = lobby_port
-- 	self._network_options = network_options
-- end)

mod:hook(PickupUnitExtension, 'init', function(func, self, extension_init_context, unit, extension_init_data)

	local interaction_type = Unit.get_data(unit, "interaction_data", "interaction_type")
	local result = func(self, extension_init_context, unit, extension_init_data)
	if interaction_type == "doom_rocket" then
		Unit.set_data(unit, "interaction_data", "interaction_type", "doom_rocket")
	end
	return result
end)


--for running projectile_rocket cleanup code only when rocket is marked for deletion
mod:hook(GrowQueue, 'pop_first', function(func, self)

	local unit = func(self)
	if unit then
		local prj_rckt = mod.projectiles[unit]
		if prj_rckt then
			prj_rckt:destroy()
		end
	end

	return unit
end)

-- Fatshark added a
-- assert(self.is_server, "[HealthTriggerSystem] Clients should not hold health trigger extensions")
-- line for some reason, no idea why. This just origin hooks it so it don't do that
mod:hook(HealthTriggerSystem,'extensions_ready', function (func, self, world, unit, extension_name)

	local extension = self.unit_extensions[unit]

	extension.health_extension = ScriptUnit.extension(unit, "health_system")

	assert(extension.health_extension)

	extension.last_health_percent = extension.health_extension:current_health_percent()
	extension.last_health_tick_percent = extension.health_extension:current_health_percent()
	extension.dialogue_input = ScriptUnit.extension_input(unit, "dialogue_system")
	extension.tick_time = 0
end)
