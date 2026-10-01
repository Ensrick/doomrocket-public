local mod = get_mod("doomrocket")

-- The hidden native carrier and the visible outfit have different state machines.
-- Only write the variable resolved on this outfit; native variable indices are
-- never transferable. Position deltas also work for engine-driven host movement
-- and interpolated client husks without intercepting native animation writes.
local OUTFIT = "units/warlock_bombardier/warlock_bombardier_3p"
local SPEED_VARIABLE = "warlock_move_speed"
local MAX_SAMPLE_DT = 0.25
local MAX_SAMPLE_SPEED = 12

if mod._reset_warlock_locomotion_animation then
	mod._reset_warlock_locomotion_animation()
end

local entries = {}

local function finite(value)
	return type(value) == "number" and value == value and math.abs(value) < math.huge
end

local function position(owner)
	local value = Unit.world_position(owner, 0)

	if finite(value.x) and finite(value.y) and finite(value.z) then
		-- Native vector temporaries cannot be kept between animation frames.
		return value.x, value.y
	end
end

function mod._stop_warlock_locomotion_animation(owner)
	if owner then
		entries[owner] = nil
	end
end

function mod._reset_warlock_locomotion_animation()
	entries = {}
end

function mod._release_warlock_locomotion_world(world)
	-- Called before native world release: afterward even lifetime queries can
	-- touch stale handles. Dropping these records needs no engine API calls.
	for owner, entry in pairs(entries) do
		if entry.world == world then
			entries[owner] = nil
		end
	end
end

function mod._start_warlock_locomotion_animation(owner, outfit)
	mod._stop_warlock_locomotion_animation(owner)

	if not owner or not Unit.alive(owner) or not outfit or not Unit.alive(outfit)
		or not mod._warlock_outfits or mod._warlock_outfits[owner] ~= outfit
		or Unit.get_data(outfit, "unit_name") ~= OUTFIT
		or not Unit.animation_has_variable(outfit, SPEED_VARIABLE) then
		return false
	end

	local world = Unit.world(owner)

	if not world or Unit.world(outfit) ~= world then
		return false
	end

	local index = Unit.animation_find_variable(outfit, SPEED_VARIABLE)
	local x, y = position(owner)
	entries[owner] = { outfit = outfit, world = world, index = index, x = x, y = y }
	Unit.animation_set_variable(outfit, index, 0)
	return true
end

function mod._update_warlock_locomotion_animation(world, dt)
	for owner, entry in pairs(entries) do
		if not Unit.alive(owner) or not Unit.alive(entry.outfit)
			or not mod._warlock_outfits or mod._warlock_outfits[owner] ~= entry.outfit
			or not HEALTH_ALIVE or not HEALTH_ALIVE[owner] then
			entries[owner] = nil
		elseif entry.world == world then
			if Unit.world(owner) ~= world or Unit.world(entry.outfit) ~= world then
				entries[owner] = nil
			elseif not finite(dt) or dt <= 0 or dt > MAX_SAMPLE_DT then
				-- Pauses and long hitches have no trustworthy per-frame derivative.
				entry.x, entry.y = nil, nil
				Unit.animation_set_variable(entry.outfit, entry.index, 0)
			else
				local x, y = position(owner)
				local speed = 0

				if x and entry.x then
					local dx, dy = x - entry.x, y - entry.y
					local measured = math.sqrt(dx * dx + dy * dy) / dt

					-- Reject teleports instead of rapidly spinning the legs for a frame.
					if finite(measured) and measured <= MAX_SAMPLE_SPEED then
						speed = measured
					end
				end

				entry.x, entry.y = x, y
				Unit.animation_set_variable(entry.outfit, entry.index, speed)
			end
		end
	end
end
