local mod = get_mod("doomrocket")

local function finite(value)
	return type(value) == "number" and value == value and math.abs(value) < math.huge
end

local function valid_vector(value)
	return value and Vector3.is_valid(value) and finite(value.x) and finite(value.y) and finite(value.z)
end

local function forward_target(unit, position)
	if not valid_vector(position) then return nil end
	local direction = Quaternion.forward(Unit.local_rotation(unit, 0))
	if not valid_vector(direction) then return nil end
	local target = position + direction * 5
	return valid_vector(target) and target or nil
end

-- The visible outfit owns a separately compiled aim constraint. Resolve its
-- name on that exact unit; the carrier's numeric constraint index is invalid
-- on another skeleton. Death removes this outfit from the living registry.
local function aim_visible_outfit(unit, data, target)
	local outfit = mod._warlock_outfits and mod._warlock_outfits[unit]
	local ownership = mod._warlock_animation_ownership and mod._warlock_animation_ownership(unit, outfit)
	if not outfit or not Unit.alive(outfit) or not HEALTH_ALIVE or not HEALTH_ALIVE[unit]
		or not valid_vector(target) or (ownership and not ownership.visible_aim) then
		data.visible_aim_outfit = nil
		data.visible_aim_constraint = nil
		return
	end

	if data.visible_aim_outfit ~= outfit then
		data.visible_aim_outfit = outfit
		data.visible_aim_constraint = nil
		if Unit.animation_has_constraint_target(outfit, "aim_target") then
			data.visible_aim_constraint = Unit.animation_find_constraint_target(outfit, "aim_target")
		end
	end

	if data.visible_aim_constraint then
		Unit.animation_set_constraint_target(outfit, data.visible_aim_constraint, target)
	end
end

-- Both lanes apply the same already-resolved world-space target. In particular,
-- an absent/nonfinite replicated field must never reach the native carrier
-- constraint while only the visible outfit rejects it.
local function apply_aim(unit, data, target)
	if not valid_vector(target) then
		data.visible_aim_outfit, data.visible_aim_constraint = nil, nil
		return "invalid_target"
	end
	if data.constraint_target == nil then return "missing_constraint" end
	if Unit.has_animation_event(unit, "doomrocket_reload_start") then return "reload_suppressed" end
	Unit.animation_set_constraint_target(unit, data.constraint_target, target)
	aim_visible_outfit(unit, data, target)
	return "applied"
end

local function find_constraint(unit)
	if Unit.animation_has_constraint_target(unit, "aim_target") then
		return Unit.animation_find_constraint_target(unit, "aim_target")
	end
end

-- Read-only #55 evidence, collected in ordinary play. These are the transforms
-- at aim-update time, not post-animation samples or proof of network agreement.
-- Per-unit and module-wide caps bound ordinary sessions and diagnostic errors.
local diagnostic_total = 0
local function vector_text(value)
	if not valid_vector(value) then return "unavailable" end
	return string.format("%.3f,%.3f,%.3f", value.x, value.y, value.z)
end

local function token(value)
	return tostring(value or "n/a"):gsub("%s+", "_"):sub(1, 96)
end

local function facing_sample(unit, data, target, role, source, result, t, game, go_id)
	local outfit = mod._warlock_outfits and mod._warlock_outfits[unit]
	if outfit and not Unit.alive(outfit) then outfit = nil end
	local ownership = mod._warlock_animation_ownership and mod._warlock_animation_ownership(unit, outfit)
	local blackboard = data.blackboard
	local pattern = blackboard and blackboard.attack_pattern_data
	local action = blackboard and blackboard.action and blackboard.action.name
	if not action and game and go_id and NetworkLookup and NetworkLookup.bt_action_names then
		local id = GameSession.game_object_field(game, go_id, "bt_action_name")
		action = id and rawget(NetworkLookup.bt_action_names, id)
	end
	-- #65: optional facing telemetry must never index a native animation layer.
	-- The carrier is a foreign multi-layer ASM; the outfit has one zero-based
	-- layer. A native assertion here bypasses pcall and crashes ordinary spawning.
	-- Clock observations belong to the explicitly enabled, checked own-rig probe.
	local outfit_forward = outfit and Quaternion.forward(Unit.world_rotation(outfit, 0))
	printf("[doomrocket:FACING] v=%s role=%s go_id=%s t=%.2f stage=aim_update source=%s result=%s " ..
		"action=%s pattern=%s state=%s pose_owner=%s visible_aim=%s aim=%s root_pos=%s root_forward=%s " ..
		"outfit_pos=%s outfit_forward=%s owner_clock=%s/%s outfit_clock=%s/%s",
		token(mod._doomrocket_version), role, token(go_id), t, source, result,
		token(action), token(pattern and pattern.state), token(ownership and ownership.state),
		token(ownership and ownership.upper_body), tostring(not ownership or ownership.visible_aim == true),
		vector_text(target), vector_text(Unit.world_position(unit, 0)),
		vector_text(Quaternion.forward(Unit.world_rotation(unit, 0))),
		vector_text(outfit and Unit.world_position(outfit, 0)), vector_text(outfit_forward),
		"not_sampled", "not_sampled", "not_sampled", "not_sampled")
end

local function diagnose_facing(unit, data, target, role, source, result, t, game, go_id)
	if not finite(t) or diagnostic_total >= 240 or (data.facing_samples or 0) >= 30 then return end
	if data.facing_last_t and (t < data.facing_last_t or t < data.facing_last_t + 2) then return end
	data.facing_last_t = t
	data.facing_samples = (data.facing_samples or 0) + 1
	diagnostic_total = diagnostic_total + 1
	-- Telemetry must not interrupt aiming when a diagnostic API is unavailable.
	pcall(facing_sample, unit, data, target, role, source, result, t, game, go_id)
end

AimTemplates.doomrocket = {
	owner = {
		init = function (unit, data)
			local blackboard = BLACKBOARDS[unit]
			data.blackboard = blackboard
			-- Ratling donor (v0.1.36): its machine HAS the aim_target constraint,
			-- so the visual aim-bend is back. NEVER call
			-- animation_find_constraint_target on a machine without the
			-- constraint - engine assert (v0.1.32, stormvermin donor era).
			data.constraint_target = find_constraint(unit)
		end,
		update = function (unit, t, dt, data)
			local unit_position = POSITION_LOOKUP[unit]
			local aim_target = nil
			local source = "forward"
			local attack_pattern_data = data.blackboard.attack_pattern_data
			local ballistic_direction_box = attack_pattern_data and attack_pattern_data.ballistic_aim_direction_box
			if ballistic_direction_box then source = "ballistic" end

			if not ballistic_direction_box and data.blackboard.doomrocket_ballistic_aim_hold_direction_box then
				if t <= (data.blackboard.doomrocket_ballistic_aim_hold_until or -math.huge) then
					ballistic_direction_box = data.blackboard.doomrocket_ballistic_aim_hold_direction_box
					source = "ballistic_hold"
				else
					data.blackboard.doomrocket_ballistic_aim_hold_direction_box = nil
					data.blackboard.doomrocket_ballistic_aim_hold_until = nil
				end
			end

			if ballistic_direction_box or (attack_pattern_data and attack_pattern_data.shoot_direction_box) then
				local direction_box = ballistic_direction_box or attack_pattern_data.shoot_direction_box
				if not ballistic_direction_box then source = "line_of_sight" end
				local shoot_direction = direction_box:unbox()
				local length_squared = valid_vector(shoot_direction) and Vector3.length_squared(shoot_direction)

				if valid_vector(unit_position) and finite(length_squared) and length_squared > 0.000001 then
					aim_target = unit_position + Vector3.normalize(shoot_direction) * 5
				else
					aim_target, source = forward_target(unit, unit_position), "forward_invalid_direction"
				end
			else
				aim_target = forward_target(unit, unit_position)
			end

			local result = apply_aim(unit, data, aim_target)

			local game = Managers.state.network:game()
			local go_id = Managers.state.unit_storage:go_id(unit)

			if game and go_id and valid_vector(aim_target) then
				GameSession.set_game_object_field(game, go_id, "aim_target", aim_target)
			end
			diagnose_facing(unit, data, aim_target, "owner", source, result, t, game, go_id)
		end,
		leave = function (unit, data)
			return
		end
	},
	husk = {
		init = function (unit, data)
			-- See owner.init: ratling machine carries the aim constraint.
			data.constraint_target = find_constraint(unit)
		end,
		update = function (unit, t, dt, data)
			local game = Managers.state.network:game()
			local go_id = Managers.state.unit_storage:go_id(unit)
			local aim_target, source

			if game and go_id then
				aim_target = GameSession.game_object_field(game, go_id, "aim_target")
				source = "replicated"
			else
				aim_target, source = forward_target(unit, POSITION_LOOKUP[unit]), "forward_no_game_object"
			end
			local result = apply_aim(unit, data, aim_target)
			diagnose_facing(unit, data, aim_target, "husk", source, result, t, game, go_id)
		end,
		leave = function (unit, data)
			return
		end
	}
}
