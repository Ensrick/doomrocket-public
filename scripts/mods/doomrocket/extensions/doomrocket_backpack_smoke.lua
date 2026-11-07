local mod = get_mod("doomrocket")

local EFFECT = "fx/chr_warp_fire_backpack_smoke_01"
local PACKAGE = "resource_packages/breeds/skaven_warpfire_thrower"
local PACKAGE_REFERENCE = "doomrocket_backpack_smoke"
local OUTFIT = "units/warlock_bombardier/warlock_bombardier_3p"

-- Dispose through the OLD owner before replacing its functions on a Lua reload.
-- Strong records intentionally survive until cleanup, unlike weak outfit maps.
if mod._reset_warlock_backpack_smoke then
	mod._reset_warlock_backpack_smoke("module_reload")
end

local state = mod._doomrocket_backpack_smoke_state or {
	entries = {},
	outfits = {},
	releasing_worlds = {},
	unknown_worlds = {},
}
state.packages = state.packages or {}
state.creating_worlds = state.creating_worlds or {}
state.pending_owners = state.pending_owners or {}
state.pending_outfits = state.pending_outfits or {}
if state.owns_package and state.package_manager then
	state.packages[PACKAGE] = state.package_manager
end
state.owns_package, state.package_manager = nil, nil
mod._doomrocket_backpack_smoke_state = state

local function active_world()
	local manager = Managers.world

	if manager and manager:has_world("level_world") then
		return manager:world("level_world")
	end
end

local function known_world(world)
	local manager = Managers.world

	-- WorldManager.has_world deliberately excludes paused/disabled worlds.
	-- Their particles still exist: do not forget them or duplicate them on resume.
	return world and manager and (active_world() == world
		or manager._disabled_worlds and manager._disabled_worlds.level_world == world)
end

local function forget(owner)
	local entry = state.entries[owner]
	state.entries[owner] = nil

	if entry and state.outfits[entry.outfit] == owner then
		state.outfits[entry.outfit] = nil
	end

	return entry
end

local function forget_pending(entry)
	if state.pending_owners[entry.owner] == entry then state.pending_owners[entry.owner] = nil end
	if state.pending_outfits[entry.outfit] == entry then state.pending_outfits[entry.outfit] = nil end
end

local function cancel_pending(entry)
	entry.cancelled = true
	if not entry.operating then forget_pending(entry) end
end

local function release_package_if_safe()
	for world in pairs(state.releasing_worlds) do
		if not known_world(world) then
			state.releasing_worlds[world] = nil
		end
	end

	if state.prewarm_world and not known_world(state.prewarm_world) then state.prewarm_world = nil end
	if state.prewarm_world or next(state.entries) or next(state.pending_owners)
		or next(state.creating_worlds) or next(state.releasing_worlds) or next(state.unknown_worlds) then
		return
	end
	mod._warlock_effect_package.release(state.packages, PACKAGE_REFERENCE)
end

local function stop(owner, reason)
	local pending = state.pending_owners[owner]
	local cancelled = pending and not pending.cancelled
	if pending then cancel_pending(pending) end
	-- Claim before native calls: repeated/reentrant cleanup cannot use the ID twice.
	local entry = forget(owner)

	if not entry then
		if cancelled then release_package_if_safe() end
		return cancelled or false
	end

	if not state.releasing_worlds[entry.world] then
		if known_world(entry.world) then
			if Unit.alive(entry.outfit) then
				if Unit.world(entry.outfit) == entry.world then
					if World.are_particles_playing(entry.world, entry.id) then
						World.destroy_particles(entry.world, entry.id)
					end
				else
					state.unknown_worlds[entry.world] = true
				end
			end
			-- A deleted linked outfit already destroyed its emitter. Do NOT query the
			-- old ID: another effect may now own that integer in the same world.
		else
			-- Without a pre-release notification we cannot prove the old world's
			-- resources are gone. Forget the handle, retaining our package reference.
			state.unknown_worlds[entry.world] = true
		end
	end

	printf("[doomrocket:SMOKE] phase=stop reason=%s", tostring(reason))
	return true
end

local function valid_vector(values)
	if type(values) ~= "table" or #values ~= 3 then
		return false
	end

	for i = 1, 3 do
		local value = values[i]
		if type(value) ~= "number" or value ~= value or math.abs(value) == math.huge then
			return false
		end
	end

	return true
end

local function anchor_pose(anchor)
	if type(anchor) ~= "table" or anchor.node ~= "j_backpack"
		or not valid_vector(anchor.x_axis) or not valid_vector(anchor.y_axis)
		or not valid_vector(anchor.z_axis) or not valid_vector(anchor.position) then
		return nil
	end

	local pose = Matrix4x4.identity()
	Matrix4x4.set_x(pose, Vector3(unpack(anchor.x_axis)))
	Matrix4x4.set_y(pose, Vector3(unpack(anchor.y_axis)))
	Matrix4x4.set_z(pose, Vector3(unpack(anchor.z_axis)))
	Matrix4x4.set_translation(pose, Vector3(unpack(anchor.position)))
	return pose
end

local function ensure_resource()
	local ready, reason = mod._warlock_effect_package.ensure(state.packages, PACKAGE, PACKAGE_REFERENCE)
	if not ready then return false, reason end
	return Application.can_get("particles", EFFECT), "effect_unavailable"
end

local function report_skip(reason)
	printf("[doomrocket:SMOKE] phase=skip reason=%s", reason)
end

local function create_emitter(entry, pose)
	pose = pose or anchor_pose(mod._doomrocket_chimney_anchor)
	if not pose then return nil end
	state.creating_worlds[entry.world] = (state.creating_worlds[entry.world] or 0) + 1
	local function finish_creation()
		local remaining = state.creating_worlds[entry.world] - 1
		state.creating_worlds[entry.world] = remaining > 0 and remaining or nil
		forget_pending(entry)
	end
	local function context_owned()
		return not state.releasing_worlds[entry.world] and not state.unknown_worlds[entry.world]
			and known_world(entry.world) and Unit.alive(entry.outfit)
			and Unit.world(entry.outfit) == entry.world
	end
	local function defer_cleanup()
		if not state.releasing_worlds[entry.world] then
			state.unknown_worlds[entry.world] = true
		end
		report_skip("creation_cleanup_deferred")
	end
	local function retire_created(id)
		-- Cancellation does not remove ownership; world/unit teardown can.
		local checked, playing
		if context_owned() then
			checked, playing = pcall(World.are_particles_playing, entry.world, id)
		end
		if checked and not playing then return true end
		if checked and playing and context_owned() then
			return pcall(World.destroy_particles, entry.world, id)
		end
		return false
	end
	local created, id = pcall(World.create_particles, entry.world, EFFECT, Vector3(0, 0, 0))
	if not created or type(id) ~= "number" or id ~= id or id < 0 or id == math.huge or id % 1 ~= 0 then
		finish_creation()
		-- A wrapper can allocate then error/return an invalid handle. Without a
		-- usable owned ID, only world teardown can prove the emitter is gone.
		defer_cleanup()
		report_skip("creation_failed")
		return nil
	end
	if not context_owned() then
		finish_creation()
		defer_cleanup()
		return nil
	end
	if entry.cancelled then
		local cleaned = retire_created(id)
		finish_creation()
		if not cleaned then defer_cleanup() end
		report_skip("creation_cancelled")
		return nil
	end
	local linked = pcall(World.link_particles, entry.world, id, entry.outfit, entry.node, pose, "destroy")
	if not linked then
		-- A failing wrapper could already have linked then deleted the launcher
		-- or released the world. Its integer ID could then name another emitter.
		local cleaned = retire_created(id)
		finish_creation()
		if not cleaned then
			-- The engine owns any uncertain emitter until this world is released.
			-- Keep the package reference and prohibit further spawns in that world.
			defer_cleanup()
		end
		report_skip("link_failed")
		return nil
	end
	if not context_owned() then
		finish_creation()
		defer_cleanup()
		return nil
	end
	if entry.cancelled then
		local cleaned = retire_created(id)
		finish_creation()
		if not cleaned then defer_cleanup() end
		report_skip("creation_cancelled")
		return nil
	end
	finish_creation()
	return id
end

local function attempt_start(entry, pose)
	if entry.operating then return false end
	entry.operating = true
	local checked, resident, reason = pcall(ensure_resource)
	entry.operating = false
	if entry.cancelled then
		forget_pending(entry)
		release_package_if_safe()
		return false
	elseif not checked or not resident then
		if not checked or reason == "resource_error" or reason == "package_not_loaded" then
			forget_pending(entry)
			release_package_if_safe()
		end
		return false
	end
	if DEDICATED_SERVER or not Unit.alive(entry.owner) or not Unit.alive(entry.outfit)
		or not known_world(entry.world) or Unit.world(entry.owner) ~= entry.world
		or Unit.world(entry.outfit) ~= entry.world
		or state.releasing_worlds[entry.world] or state.unknown_worlds[entry.world] then
		cancel_pending(entry)
		release_package_if_safe()
		return false
	elseif active_world() ~= entry.world then
		return false
	end
	pose = pose or anchor_pose(mod._doomrocket_chimney_anchor)
	if not pose then cancel_pending(entry); release_package_if_safe(); return false end
	entry.operating = true
	local id = create_emitter(entry, pose)
	entry.operating = false
	forget_pending(entry)
	if type(id) ~= "number" then release_package_if_safe(); return false end
	state.entries[entry.owner] = { outfit = entry.outfit, world = entry.world, id = id }
	state.outfits[entry.outfit] = entry.owner
	printf("[doomrocket:SMOKE] phase=start effect=%s node=%s", EFFECT, mod._doomrocket_chimney_anchor.node)
	return true
end

mod._prewarm_warlock_backpack_smoke = function ()
	if DEDICATED_SERVER then return false end
	local world = active_world()
	if not world or state.releasing_worlds[world] or state.unknown_worlds[world] then return false end
	state.prewarm_world = world
	return ensure_resource()
end

mod._start_warlock_backpack_smoke = function(owner, outfit)
	if DEDICATED_SERVER or not owner or not Unit.alive(owner)
		or not outfit or not Unit.alive(outfit)
		or Unit.get_data(outfit, "unit_name") ~= OUTFIT then
		return false
	end

	local existing = state.entries[owner]

	if existing and existing.outfit == outfit then
		return known_world(existing.world) and Unit.world(outfit) == existing.world
			and not state.releasing_worlds[existing.world] or false
	elseif existing then
		stop(owner, "outfit_replaced")
	end

	-- The same visible outfit cannot be claimed by a second carrier.
	local pending = state.pending_owners[owner]
	if pending and pending.outfit == outfit then
		return attempt_start(pending)
	elseif pending then
		cancel_pending(pending)
	end
	if state.outfits[outfit] or state.pending_outfits[outfit] then
		return false
	end

	local world = active_world()
	local anchor = mod._doomrocket_chimney_anchor

	if not world or state.releasing_worlds[world] or state.unknown_worlds[world]
		or Unit.world(outfit) ~= world or type(anchor) ~= "table"
		or anchor.node ~= "j_backpack" or not Unit.has_node(outfit, anchor.node) then
		return false
	end

	local pose = anchor_pose(anchor)

	if not pose then
		return false
	end

	local node = Unit.node(outfit, anchor.node)
	local entry = { owner = owner, outfit = outfit, world = world, node = node }
	state.pending_owners[owner], state.pending_outfits[outfit] = entry, entry
	return attempt_start(entry, pose)
end

mod._stop_warlock_backpack_smoke = function(owner, reason)
	return stop(owner, reason or "unspecified")
end

mod._update_warlock_backpack_smoke = function()
	local stopped = {}

	for owner, entry in pairs(state.entries) do
		if not Unit.alive(owner) or not Unit.alive(entry.outfit) or not known_world(entry.world) then
			stopped[#stopped + 1] = owner
		end
	end

	for i = 1, #stopped do
		stop(stopped[i], "context_removed")
	end
	local pending = {}
	for _, entry in pairs(state.pending_owners) do pending[#pending + 1] = entry end
	for i = 1, #pending do
		local entry = pending[i]
		if state.pending_owners[entry.owner] == entry and not entry.operating then
			if not Unit.alive(entry.owner) or not Unit.alive(entry.outfit)
				or not known_world(entry.world) or Unit.world(entry.owner) ~= entry.world
				or Unit.world(entry.outfit) ~= entry.world then
				cancel_pending(entry)
			elseif active_world() == entry.world then attempt_start(entry) end
		end
	end
	release_package_if_safe()
end

mod._reset_warlock_backpack_smoke = function(reason)
	local owners = {}
	state.prewarm_world = nil
	local pending = {}
	for _, entry in pairs(state.pending_owners) do pending[#pending + 1] = entry end
	for i = 1, #pending do cancel_pending(pending[i]) end
	for owner in pairs(state.entries) do
		owners[#owners + 1] = owner
	end

	for i = 1, #owners do
		stop(owners[i], reason or "reset")
	end

	release_package_if_safe()
end

mod._release_warlock_smoke_world = function(world)
	-- Called BEFORE Application.release_world. The engine is about to free all
	-- particles; no particle API or package unload is safe/necessary here.
	local owners = {}
	local pending = {}
	for _, entry in pairs(state.pending_owners) do pending[#pending + 1] = entry end
	local pending_in_world = false
	for i = 1, #pending do
		if pending[i].world == world then cancel_pending(pending[i]); pending_in_world = true end
	end
	local prewarmed = state.prewarm_world == world
	if prewarmed then state.prewarm_world = nil end
	for owner, entry in pairs(state.entries) do
		if entry.world == world then
			owners[#owners + 1] = owner
		end
	end

	for i = 1, #owners do
		forget(owners[i])
	end

	if #owners > 0 or state.unknown_worlds[world] or state.creating_worlds[world] or pending_in_world or prewarmed then
		state.releasing_worlds[world] = true
	end
	state.unknown_worlds[world] = nil
end

return
