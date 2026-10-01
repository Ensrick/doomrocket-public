local mod = get_mod("doomrocket")

require("scripts/entity_system/systems/behaviour/nodes/bt_node")

BTDoomrocketShoveAction = class(BTDoomrocketShoveAction, BTNode)
BTDoomrocketShoveAction.name = "BTDoomrocketShoveAction"

-- React before the player reaches the point-blank launch boundary. The shorter
-- cooldown is deliberate TEST tuning; native push force/damage stay unchanged.
-- Evaluate directly: the Ratling tree has no Stormvermin BTUtilityNode.
local SHOVE_MAX_DISTANCE = 2.2
local SHOVE_MAX_TARGET_SPEED_AWAY = 1.5
local SHOVE_COOLDOWN_SECONDS = 2.0

-- A loaded weapon has nothing to reload while the target remains point-blank.
-- Hold a native idle action between shoves instead of restarting the complete
-- ranged sequence and rejecting its launch every AI tick. Empty weapons may
-- finish a real reload; the higher-priority shove can still interrupt it.
BTConditions.doomrocket_should_wait_at_close_range = function (blackboard)
	local target_unit = blackboard.target_unit
	local target_dist = blackboard.target_dist

	return blackboard.reloaded_rocket ~= false
		and target_unit ~= nil and Unit.alive(target_unit)
		and type(target_dist) == "number" and target_dist < SHOVE_MAX_DISTANCE
end

BTDoomrocketShoveAction.init = function (self, ...)
	BTDoomrocketShoveAction.super.init(self, ...)
end

-- Once entered, keep the condition sticky: enter consumes the cooldown
-- immediately, so evaluating eligibility again would abort the next frame.
BTConditions.doomrocket_should_shove = function (blackboard, condition_args, action)
	if blackboard.doomrocket_shove_active then
		return true
	end

	local target_unit = blackboard.target_unit

	if not action or not target_unit or not Unit.alive(target_unit) then
		return false
	end

	local target_dist = blackboard.target_dist
	local target_speed_away = blackboard.target_speed_away

	if type(target_dist) ~= "number" or type(target_speed_away) ~= "number" then
		return false
	end

	local action_name = action.name or "push_attack"
	local utility_actions = blackboard.utility_actions
	local utility_data = utility_actions and utility_actions[action_name]

	if not utility_data or type(utility_data.time_since_last) ~= "number"
		or utility_data.time_since_last < SHOVE_COOLDOWN_SECONDS then
		return false
	end

	if target_dist >= SHOVE_MAX_DISTANCE or target_speed_away >= SHOVE_MAX_TARGET_SPEED_AWAY
		or blackboard.target_is_not_downed == false then
		return false
	end

	if not BTConditions.ask_target_before_attacking(blackboard, condition_args, action) then
		return false
	end

	printf("[doomrocket:COMBAT] phase=shove_selected distance=%.3f speed_away=%.3f cooldown_s=%.3f",
		target_dist, target_speed_away, utility_data.time_since_last)

	return true
end

BTDoomrocketShoveAction.enter = function (self, unit, blackboard, t)
	local action = self._tree_node.action_data
	local action_name = action.name or "push_attack"
	local target_unit = blackboard.target_unit
	local data = {
		action_name = action_name,
		target_unit = target_unit,
		impact_t = t + action.impact_time,
		end_t = t + action.duration,
		impact_applied = false,
		navigation_disabled = false,
	}

	blackboard.doomrocket_shove_data = data
	blackboard.doomrocket_shove_active = true
	blackboard.action = action
	blackboard.active_node = BTDoomrocketShoveAction
	blackboard.attack_finished = false
	blackboard.attack_aborted = false
	blackboard.attack_token = true
	blackboard.attacking_target = target_unit
	blackboard.move_state = "attacking"
	blackboard.anim_cb_attack_shoot_start_finished = nil
	blackboard.anim_cb_attack_shoot_random_shot = nil

	local utility_data = blackboard.utility_actions and blackboard.utility_actions[action_name]

	if utility_data then
		utility_data.last_time = t
	end

	if not Unit.alive(target_unit) or not Unit.has_animation_event(unit, action.attack_anim) then
		data.invalid = true
		printf("[doomrocket:COMBAT] phase=shove_rejected target_alive=%s animation_available=%s",
			tostring(Unit.alive(target_unit)), tostring(Unit.has_animation_event(unit, action.attack_anim)))

		return
	end

	local navigation_extension = blackboard.navigation_extension

	navigation_extension:set_enabled(false)
	blackboard.locomotion_extension:set_wanted_velocity(Vector3.zero())
	blackboard.locomotion_extension:set_wanted_rotation(LocomotionUtils.rotation_towards_unit_flat(unit, target_unit))
	data.navigation_disabled = true

	Managers.state.network:anim_event(unit, action.attack_anim)
	AiUtils.add_attack_intensity(target_unit, action, blackboard)
	printf("[doomrocket:COMBAT] phase=shove_begin impact_s=%.2f duration_s=%.2f", action.impact_time, action.duration)
end

local function apply_shove(unit, blackboard, data)
	local target_unit = data.target_unit
	local action = blackboard.action

	if not Unit.alive(target_unit) or not DamageUtils.check_distance(action, blackboard, unit, target_unit) or not DamageUtils.check_infront(unit, target_unit) then
		printf("[doomrocket:COMBAT] phase=shove_impact applied=false")

		return
	end

	AiUtils.damage_target(target_unit, unit, action, action.damage)

	local status_extension = ScriptUnit.has_extension(target_unit, "status_system")
	local locomotion_extension = ScriptUnit.has_extension(target_unit, "locomotion_system")

	if not status_extension or status_extension:is_disabled() or not locomotion_extension then
		printf("[doomrocket:COMBAT] phase=shove_impact applied=false")

		return
	end

	StatusUtils.set_pushed_network(target_unit, true)

	local velocity = Quaternion.forward(Unit.local_rotation(unit, 0)) * action.impact_push_speed

	locomotion_extension:add_external_velocity(velocity, action.max_impact_push_speed)
	printf("[doomrocket:COMBAT] phase=shove_impact applied=true push_speed=%.1f max_push_speed=%.1f",
		action.impact_push_speed, action.max_impact_push_speed)
end

BTDoomrocketShoveAction.run = function (self, unit, blackboard, t, dt)
	local data = blackboard.doomrocket_shove_data

	if not data or data.invalid then
		return "failed"
	end

	local target_unit = data.target_unit

	if blackboard.attack_aborted or not Unit.alive(target_unit) then
		return "done"
	end

	blackboard.locomotion_extension:set_wanted_rotation(LocomotionUtils.rotation_towards_unit_flat(unit, target_unit))

	if not data.impact_applied and t >= data.impact_t then
		data.impact_applied = true
		apply_shove(unit, blackboard, data)
	end

	if t >= data.end_t then
		return "done"
	end

	return "running"
end

BTDoomrocketShoveAction.leave = function (self, unit, blackboard, t, reason, destroy)
	local data = blackboard.doomrocket_shove_data

	if data and data.navigation_disabled and Unit.alive(unit) then
		blackboard.navigation_extension:set_enabled(true)
	end

	-- A generic BTSelector does not forward its destroy argument.  Restrict the
	-- idle transition to a normal completion so stagger/death/vortex actions can
	-- own their animation without an idle event racing them.
	if reason == "done" and Unit.alive(unit) and HEALTH_ALIVE[unit] and Unit.has_animation_event(unit, "idle") then
		Managers.state.network:anim_event(unit, "idle")
	end

	local action_name = data and data.action_name or "push_attack"
	local utility_data = blackboard.utility_actions and blackboard.utility_actions[action_name]

	if reason == "done" and utility_data then
		utility_data.last_done_time = t
	end

	-- One escape attempt follows a completed kick, including when the push has
	-- already moved its target outside 1.8 m. An interrupted kick requests none.
	if reason == "done" and data and not data.invalid and t >= data.end_t
		and Unit.alive(unit) and HEALTH_ALIVE[unit] and Unit.alive(data.target_unit) then
		blackboard.doomrocket_reposition_request_target = data.target_unit
	end

	blackboard.doomrocket_shove_data = nil
	blackboard.doomrocket_shove_active = nil
	blackboard.active_node = nil
	blackboard.attack_aborted = nil
	blackboard.attacking_target = nil
	blackboard.attack_finished = nil
	blackboard.attack_token = nil
	blackboard.anim_cb_attack_shoot_start_finished = nil
	blackboard.anim_cb_attack_shoot_random_shot = nil
end

return
