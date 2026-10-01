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

local function release_package_if_safe()
	for world in pairs(state.releasing_worlds) do
		if not known_world(world) then
			state.releasing_worlds[world] = nil
		end
	end

	if next(state.entries) or next(state.releasing_worlds) or next(state.unknown_worlds) then
		return
	end

	local manager = state.package_manager

	if state.owns_package and manager == Managers.package then
		-- Never decrement another consumer's reference (e.g. native breed loading).
		if manager:has_loaded(PACKAGE, PACKAGE_REFERENCE) then
			manager:unload(PACKAGE, PACKAGE_REFERENCE)
		end
	end

	state.owns_package = nil
	state.package_manager = nil
end

local function stop(owner, reason)
	-- Claim before native calls: repeated/reentrant cleanup cannot use the ID twice.
	local entry = forget(owner)

	if not entry then
		return false
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
	local manager = Managers.package

	if not manager or not Application.can_get("package", PACKAGE) then
		return false
	end

	if not manager:has_loaded(PACKAGE, PACKAGE_REFERENCE) then
		-- Omitted async argument means load + flush in native PackageManager.
		manager:load(PACKAGE, PACKAGE_REFERENCE)
	end

	state.package_manager = manager
	state.owns_package = true
	return manager:has_loaded(PACKAGE, PACKAGE_REFERENCE)
		and Application.can_get("particles", EFFECT)
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
	if state.outfits[outfit] then
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

	if not pose or not ensure_resource() then
		return false
	end

	local node = Unit.node(outfit, anchor.node)
	local id = ScriptWorld.create_particles_linked(world, EFFECT, outfit, node, "destroy", pose)

	if type(id) ~= "number" then
		return false
	end

	state.entries[owner] = { outfit = outfit, world = world, id = id }
	state.outfits[outfit] = owner
	printf("[doomrocket:SMOKE] phase=start effect=%s node=%s", EFFECT, anchor.node)
	return true
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
end

mod._reset_warlock_backpack_smoke = function(reason)
	local owners = {}
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
	for owner, entry in pairs(state.entries) do
		if entry.world == world then
			owners[#owners + 1] = owner
		end
	end

	for i = 1, #owners do
		forget(owners[i])
	end

	if #owners > 0 or state.unknown_worlds[world] then
		state.releasing_worlds[world] = true
	end
	state.unknown_worlds[world] = nil
end

return
