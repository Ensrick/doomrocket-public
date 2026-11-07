local mod = get_mod("doomrocket")

-- TEST-only, read-only grip telemetry. The launcher follows the hidden Ratling,
-- while the visible outfit has its own animation machine. Sample all three
-- units after the same world's animation pass; never retain native vectors.
local OUTFIT = "units/warlock_bombardier/warlock_bombardier_3p"
local WEAPON = "units/rocket/pRocketLauncher"
local INTERVAL = 0.2
local MAX_SECONDS = 60
local MAX_SAMPLES_PER_UNIT = 300
local MAX_SAMPLES_TOTAL = 600
local MAX_ACTIVE = 2
local OWNER_NODES = { "j_lefthand", "j_righthand", "j_leftweaponattach", "j_leftweaponcomponent1" }
local VISUAL_NODES = { "j_lefthand", "j_righthand" }
local WEAPON_NODES = { "handle", "a_barrel" }

if mod._reset_warlock_weapon_pose_probe then
	mod._reset_warlock_weapon_pose_probe()
end

local state = { entries = {}, pending = {}, epoch = 0, sequence = 0, total = 0 }

local function finite(value)
	return type(value) == "number" and value == value and math.abs(value) < math.huge
end

local function live(unit, world)
	return unit and Unit.alive(unit) and Unit.world(unit) == world
end

local function nodes(unit, names)
	local result = {}
	for i = 1, #names do
		local name = names[i]
		if not Unit.has_node(unit, name) then
			return nil
		end
		result[name] = Unit.node(unit, name)
	end
	return result
end

local function position(unit, node)
	local value = Unit.world_position(unit, node)
	local x, y, z = value.x, value.y, value.z
	if finite(x) and finite(y) and finite(z) then
		return { x = x, y = y, z = z }
	end
end

local function relative_cm(left, right, inverse_root)
	local value = Quaternion.rotate(inverse_root, Vector3(
		(left.x - right.x) * 100,
		(left.y - right.y) * 100,
		(left.z - right.z) * 100))
	return value.x, value.y, value.z
end

local function valid(entry)
	return live(entry.owner, entry.world) and live(entry.outfit, entry.world)
		and live(entry.weapon, entry.world)
		and HEALTH_ALIVE and HEALTH_ALIVE[entry.owner]
		and mod._warlock_outfits and mod._warlock_outfits[entry.owner] == entry.outfit
		and entry.inventory and entry.inventory.unit == entry.owner
end

local function stop(owner)
	state.entries[owner] = nil
end

local function sample(entry)
	local owner, outfit, weapon = entry.owner, entry.outfit, entry.weapon
	-- Read composed world transforms, not cached transforms from before this
	-- animation evaluation. The unit flush is also required with the driver off.
	World.update_unit(entry.world, owner)
	World.update_unit(entry.world, outfit)
	World.update_unit(entry.world, weapon)
	local native, visual, carried = entry.native, entry.visual, entry.carried
	local n_left = position(owner, native.j_lefthand)
	local n_right = position(owner, native.j_righthand)
	local n_attach = position(owner, native.j_leftweaponattach)
	local n_component = position(owner, native.j_leftweaponcomponent1)
	local v_left = position(outfit, visual.j_lefthand)
	local v_right = position(outfit, visual.j_righthand)
	local visible_attach_node = visual.j_leftweaponattach or visual.j_lefthand
	local v_attach = position(outfit, visible_attach_node)
	local n_root = position(owner, 0)
	local w_root = position(weapon, 0)
	local w_handle = position(weapon, carried.handle)
	local w_barrel = position(weapon, carried.a_barrel)
	if not (n_left and n_right and n_attach and n_component and v_left and v_right
		and n_root
		and v_attach and w_root and w_handle and w_barrel) then
		stop(owner)
		return
	end

	-- Rotate differences into the carrier's current root frame. This removes
	-- path motion/turning, but keeps any transposed sway or phase error visible.
	local inverse_root = Quaternion.inverse(Unit.world_rotation(owner, 0))
	local nlx, nly, nlz = relative_cm(n_left, n_root, inverse_root)
	local vlx, vly, vlz = relative_cm(v_left, n_root, inverse_root)
	local lhx, lhy, lhz = relative_cm(v_left, n_left, inverse_root)
	local ahx, ahy, ahz = relative_cm(v_attach, n_attach, inverse_root)
	local rhx, rhy, rhz = relative_cm(v_right, n_right, inverse_root)
	local nhx, nhy, nhz = relative_cm(w_handle, n_left, inverse_root)
	local vhx, vhy, vhz = relative_cm(w_handle, v_left, inverse_root)
	local wrx, wry, wrz = relative_cm(w_root, n_attach, inverse_root)
	local bcx, bcy, bcz = relative_cm(w_barrel, n_component, inverse_root)
	local left_deg = math.deg(Quaternion.angle(
		Unit.world_rotation(outfit, visual.j_lefthand),
		Unit.world_rotation(owner, native.j_lefthand)))
	local attach_deg = math.deg(Quaternion.angle(
		Unit.world_rotation(outfit, visible_attach_node),
		Unit.world_rotation(owner, native.j_leftweaponattach)))
	local right_deg = math.deg(Quaternion.angle(
		Unit.world_rotation(outfit, visual.j_righthand),
		Unit.world_rotation(owner, native.j_righthand)))
	local speed = 0
	if entry.last_root and entry.last_sample_t and entry.elapsed > entry.last_sample_t then
		local dx, dy = n_root.x - entry.last_root.x, n_root.y - entry.last_root.y
		speed = math.sqrt(dx * dx + dy * dy) / (entry.elapsed - entry.last_sample_t)
	end
	if not (finite(nlx) and finite(nly) and finite(nlz)
		and finite(vlx) and finite(vly) and finite(vlz)
		and finite(lhx) and finite(lhy) and finite(lhz)
		and finite(ahx) and finite(ahy) and finite(ahz)
		and finite(rhx) and finite(rhy) and finite(rhz)
		and finite(nhx) and finite(nhy) and finite(nhz)
		and finite(vhx) and finite(vhy) and finite(vhz)
		and finite(wrx) and finite(wry) and finite(wrz)
		and finite(bcx) and finite(bcy) and finite(bcz)
		and finite(left_deg) and finite(attach_deg) and finite(right_deg)
		and finite(speed)) then
		stop(owner)
		return
	end

	entry.samples = entry.samples + 1
	state.total = state.total + 1
	entry.last_root = n_root
	entry.last_sample_t = entry.elapsed
	printf("[doomrocket:GRIP] id=%d t=%.2f n=%d event=%s mirrored=%s speed_mps=%.2f frame=carrier_root stage=post_unit_update alignment=%s attach_source=%s " ..
		"left_native_root_cm=%.2f,%.2f,%.2f left_visual_root_cm=%.2f,%.2f,%.2f " ..
		"left_vn_cm=%.2f,%.2f,%.2f aux_attach_vn_cm=%.2f,%.2f,%.2f " ..
		"right_vn_cm=%.2f,%.2f,%.2f handle_n_cm=%.2f,%.2f,%.2f " ..
		"handle_v_cm=%.2f,%.2f,%.2f root_n_cm=%.2f,%.2f,%.2f " ..
		"barrel_n_cm=%.2f,%.2f,%.2f left_rot_deg=%.1f aux_attach_rot_deg=%.1f right_rot_deg=%.1f",
		entry.id, entry.elapsed, entry.samples, entry.event, tostring(entry.mirrored), speed,
		mod._warlock_grip_alignment_status and mod._warlock_grip_alignment_status(owner) or "off",
		visual.j_leftweaponattach and "attach" or "hand_fallback",
		nlx, nly, nlz, vlx, vly, vlz, lhx, lhy, lhz, ahx, ahy, ahz, rhx, rhy, rhz,
		nhx, nhy, nhz, vhx, vhy, vhz, wrx, wry, wrz,
		bcx, bcy, bcz, left_deg, attach_deg, right_deg)
end

function mod._start_warlock_weapon_pose_probe(owner, outfit, inventory)
	stop(owner)
	if state.total >= MAX_SAMPLES_TOTAL or not owner or not Unit.alive(owner)
		or not outfit or not Unit.alive(outfit) or not inventory
		or not mod._warlock_outfits or mod._warlock_outfits[owner] ~= outfit
		or Unit.get_data(outfit, "unit_name") ~= OUTFIT then
		return false
	end
	local world = Unit.world(owner)
	if not world or Unit.world(outfit) ~= world or inventory.unit ~= owner then
		return false
	end
	local weapon
	for _, candidate in pairs(inventory.inventory_item_units or {}) do
		if live(candidate, world) and Unit.get_data(candidate, "unit_name") == WEAPON then
			weapon = candidate
			break
		end
	end
	if not weapon then
		return false
	end
	local native = nodes(owner, OWNER_NODES)
	local visual = nodes(outfit, VISUAL_NODES)
	if visual and Unit.has_node(outfit, "j_leftweaponattach") then
		visual.j_leftweaponattach = Unit.node(outfit, "j_leftweaponattach")
	end
	local carried = nodes(weapon, WEAPON_NODES)
	if not (native and visual and carried) then
		return false
	end
	state.sequence = state.sequence + 1
	state.entries[owner] = {
		id = state.sequence, owner = owner, outfit = outfit, weapon = weapon,
		inventory = inventory, world = world, native = native, visual = visual,
		carried = carried, elapsed = 0, next_sample = 0, samples = 0,
		event = "setup_idle", mirrored = true,
	}
	printf("[doomrocket:GRIP] phase=armed id=%d interval_s=%.1f max_s=%d", state.sequence, INTERVAL, MAX_SECONDS)
	return true
end

function mod._note_warlock_weapon_pose_event(owner, event, mirrored)
	local entry = state.entries[owner]
	if entry then
		entry.event = tostring(event):gsub("%s+", "_"):sub(1, 64)
		entry.mirrored = mirrored == true
	end
end

function mod._stop_warlock_weapon_pose_probe(owner)
	stop(owner)
end

function mod._stop_warlock_weapon_pose_probe_item(owner, item)
	local entry = state.entries[owner]
	if entry and (entry.weapon == item or entry.outfit == item) then
		stop(owner)
	end
end

function mod._reset_warlock_weapon_pose_probe()
	state.epoch = state.epoch + 1
	state.entries = {}
	state.pending = {}
	state.total = 0
end

function mod._release_warlock_weapon_pose_probe_world(world)
	state.epoch = state.epoch + 1
	state.pending[world] = nil
	for owner, entry in pairs(state.entries) do
		if entry.world == world then
			stop(owner)
		end
	end
end

function mod._queue_warlock_weapon_pose_probe(world, dt)
	if state.pending[world] or not next(state.entries) or not finite(dt)
		or dt <= 0 or dt > 0.25 or state.total >= MAX_SAMPLES_TOTAL then
		return
	end
	local entity = Managers.state.entity
	local animation = entity and entity:system("animation_system")
	if not animation then
		return
	end
	local epoch = state.epoch
	state.pending[world] = true
	animation:add_safe_animation_callback(function()
		if state.epoch ~= epoch then
			return
		end
		state.pending[world] = nil
		local candidates = {}
		for owner, entry in pairs(state.entries) do
			if entry.world == world then
				if valid(entry) then
					candidates[#candidates + 1] = entry
				else
					stop(owner)
				end
			end
		end
		table.sort(candidates, function(a, b) return a.id < b.id end)
		for i = 1, math.min(#candidates, MAX_ACTIVE) do
			local entry = candidates[i]
			if state.entries[entry.owner] == entry and valid(entry) then
				entry.elapsed = entry.elapsed + dt
				if entry.elapsed >= MAX_SECONDS or entry.samples >= MAX_SAMPLES_PER_UNIT then
					stop(entry.owner)
				elseif entry.elapsed >= entry.next_sample and state.total < MAX_SAMPLES_TOTAL then
					local ok = mod:pcall(sample, entry)
					if ok then
						entry.next_sample = entry.elapsed + INTERVAL
					else
						stop(entry.owner)
					end
				end
			end
		end
	end)
end
