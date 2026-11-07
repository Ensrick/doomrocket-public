-- Native animation layers are zero-based. The installed VT2 SDK Unit API
-- exposes no layer-count getter: animation_get_state returns one value per
-- layer, including nil for a layer without a playing state. This internal
-- reader accepts only the outfit/sampler already bound and checked by its
-- caller; never pass the donor unit. A bare World.spawn_unit sampler has no
-- guaranteed unit_name data, so identity must come from that caller binding.
-- A pcall cannot contain the engine's out-of-range layer assertion.
-- Deliberate diagnostic/compositor support limit, not a native infinity test.
-- An empty native layer can report a finite ~1e37 sentinel; reject it. Artist
-- clips longer than one hour require an explicit reviewed contract change.
local MAX_LENGTH = 3600

local function finite(value)
	return type(value) == "number" and value == value and math.abs(value) < math.huge
end

local function pack(...)
	return { n = select("#", ...), ... }
end

local function ready(unit, world)
	if not unit or not Unit.alive(unit) then return false, "dead_unit" end
	if not world or Unit.world(unit) ~= world then return false, "wrong_world" end
	if not Unit.has_animation_state_machine(unit) then return false, "missing_state_machine" end
	return true
end

local function read(unit, world)
	for _, name in ipairs({ "alive", "world", "has_animation_state_machine",
		"animation_get_state", "animation_layer_info" }) do
		if type(Unit[name]) ~= "function" then return nil, nil, "missing_clock_api" end
	end
	local ok, reason = ready(unit, world)
	if not ok then return nil, nil, reason end
	local states = pack(Unit.animation_get_state(unit))
	if states.n ~= 1 then return nil, nil, "unsupported_layer_count" end
	if not finite(states[1]) or states[1] ~= math.floor(states[1]) then
		return nil, nil, "unready_animation_state"
	end
	-- Do not retain readiness across callbacks, frames or controller changes.
	-- This read and its native layer query are synchronous and never yield.
	ok, reason = ready(unit, world)
	if not ok then return nil, nil, reason end
	local time, length = Unit.animation_layer_info(unit, 0)
	if not finite(time) or not finite(length) or length <= 0 or length > MAX_LENGTH
		or time < 0 or time > length + 0.002 then return nil, nil, "invalid_clock" end
	return time, length
end

return function(unit, world)
	if type(Unit) ~= "table" then return nil, nil, "missing_clock_api" end
	-- Contains missing/unsupported Lua API errors, not native assertions. Their
	-- layer preconditions are checked above before calling animation_layer_info.
	local ok, time, length, reason = pcall(read, unit, world)
	if not ok then return nil, nil, "clock_api_error" end
	return time, length, reason
end
