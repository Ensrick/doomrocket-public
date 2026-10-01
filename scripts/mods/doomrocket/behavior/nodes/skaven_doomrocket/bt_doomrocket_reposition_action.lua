require("scripts/entity_system/systems/behaviour/nodes/bt_node")

BTDoomrocketRepositionAction = class(BTDoomrocketRepositionAction, BTNode)
BTDoomrocketRepositionAction.name = "BTDoomrocketRepositionAction"

local REAR_ANGLES = { 0, math.pi / 4, -math.pi / 4, math.pi / 3, -math.pi / 3 }

-- A completed shove requests one escape attempt. Retain the request while an
-- empty weapon finishes reloading, but never carry it over to another target.
BTConditions.doomrocket_should_reposition = function (blackboard, condition_args, action)
	if blackboard.doomrocket_reposition_active then
		return true
	end

	local requested_target = blackboard.doomrocket_reposition_request_target
	local target_unit = blackboard.target_unit
	local distance = blackboard.target_dist

	if not requested_target then
		return false
	end

	if requested_target ~= target_unit or not Unit.alive(target_unit)
		or type(distance) ~= "number" or not action or distance >= action.clear_distance then
		blackboard.doomrocket_reposition_request_target = nil

		return false
	end

	return blackboard.reloaded_rocket ~= false
end

BTDoomrocketRepositionAction.init = function (self, ...)
	BTDoomrocketRepositionAction.super.init(self, ...)
end

local function valid_navigation(unit, blackboard)
	local navigation = blackboard.navigation_extension

	-- release_bot also clears traverse_logic. A living frozen unit can have no
	-- navbot; stop/set_max_speed do not themselves guard that engine handle.
	return Unit.alive(unit) and HEALTH_ALIVE[unit] and POSITION_LOOKUP[unit]
		and navigation and blackboard.nav_world and navigation:traverse_logic()
end

local function flat_distance(first, second)
	return Vector3.length(Vector3.flat(first - second))
end

BTDoomrocketRepositionAction._plan = function (self, unit, blackboard, data, t)
	local action = self._tree_node.action_data
	local position = POSITION_LOOKUP[unit]
	local target_position = POSITION_LOOKUP[data.target_unit]
	local away = Vector3.flat(position - target_position)

	if Vector3.length_squared(away) < 0.0001 then
		away = Vector3.flat(Quaternion.forward(Unit.local_rotation(unit, 0))) * -1
	end

	if Vector3.length_squared(away) < 0.0001 then
		return false
	end

	away = Vector3.normalize(away)
	data.plan_attempts = data.plan_attempts + 1
	local navigation = blackboard.navigation_extension
	local traverse_logic = navigation:traverse_logic()
	local angle_away = math.atan2(away.y, away.x)
	local angles = {}

	-- Keep some of the previous heading when the target moves or a diagonal
	-- escape opens out. The blended ray is validated just like every fallback;
	-- smoothing must never cut an unchecked corner or steer toward the player.
	if data.heading_box then
		local heading = data.heading_box:unbox() * 0.75 + away * 0.25

		if Vector3.length_squared(heading) > 0.0001 then
			angles[1] = math.atan2(heading.y, heading.x)
		end
	end

	for _, angle_offset in ipairs(REAR_ANGLES) do
		angles[#angles + 1] = angle_away + angle_offset
	end

	-- Try the longest useful segment first, with shorter safe options in tight
	-- spaces. Every goal is relative to the Engineer, so reaching one can lead
	-- to another instead of stopping at the old fixed radius around the player.
	for _, segment_scale in ipairs({1, 0.5, 0.25}) do
	for _, angle in ipairs(angles) do
		local candidate = Vector3(
			position.x + math.cos(angle) * action.goal_distance * segment_scale,
			position.y + math.sin(angle) * action.goal_distance * segment_scale,
			position.z)

		-- Every accepted segment initially moves away from the current target.
		-- Rear diagonals that would first cut toward it are rejected.
		if Vector3.dot(Vector3.flat(candidate - position), away) >= action.minimum_progress then
			local can_go, projected_start, projected_end = LocomotionUtils.ray_can_go_on_mesh(
				blackboard.nav_world, position, candidate, traverse_logic, action.nav_height, action.nav_height)

			if can_go and projected_end and math.abs(projected_end.z - position.z) <= action.nav_height
				and Vector3.dot(Vector3.flat(projected_end - position), away) >= action.minimum_progress
				and flat_distance(projected_end, target_position) > flat_distance(position, target_position) then
				data.destination_box = Vector3Box(projected_end)
				data.segment_start_box = Vector3Box(position)
				data.progress_position_box = Vector3Box(position)
				local segment = Vector3.flat(projected_end - position)
				data.heading_box = Vector3Box(Vector3.normalize(segment))
				data.handoff_distance = math.min(action.move_speed * action.handoff_lookahead,
					Vector3.length(segment) * 0.25)
				data.handoff_attempted = false
				data.next_replan_t = t + action.replan_interval
				navigation:move_to(projected_end)
				printf("[doomrocket:COMBAT] phase=reposition_plan attempt=%d target_distance=%.3f",
					data.plan_attempts, flat_distance(projected_end, target_position))

				return true
			end
		end
	end
	end

	return false
end

BTDoomrocketRepositionAction.enter = function (self, unit, blackboard, t)
	local action = self._tree_node.action_data
	local data = {
		target_unit = blackboard.doomrocket_reposition_request_target,
		start_t = t,
		clearance_t = t + action.min_duration,
		end_t = t + action.max_duration,
		plan_attempts = 0,
		blocked_plans = 0,
		navigation_owned = false,
	}

	blackboard.doomrocket_reposition_request_target = nil
	blackboard.doomrocket_reposition_active = true
	blackboard.doomrocket_reposition_data = data
	blackboard.action = action
	blackboard.active_node = BTDoomrocketRepositionAction

	if data.target_unit ~= blackboard.target_unit or not Unit.alive(data.target_unit)
		or not POSITION_LOOKUP[data.target_unit] or not valid_navigation(unit, blackboard) then
		data.outcome = "invalid_context"

		return
	end

	local navigation = blackboard.navigation_extension
	navigation:stop()
	navigation:set_enabled(true)
	navigation:set_max_speed(action.move_speed)
	blackboard.locomotion_extension:set_wanted_rotation(nil)
	data.navigation_owned = true

	if not self:_plan(unit, blackboard, data, t) then
		data.outcome = "no_safe_route"

		return
	end

	Managers.state.network:anim_event(unit, action.move_anim)
	blackboard.move_state = "moving"
	printf("[doomrocket:COMBAT] phase=reposition_begin clear_distance=%.2f minimum_s=%.2f timeout_s=%.2f speed=%.2f",
		action.clear_distance, action.min_duration, action.max_duration, action.move_speed)
end

BTDoomrocketRepositionAction.run = function (self, unit, blackboard, t, dt)
	local data = blackboard.doomrocket_reposition_data
	local action = self._tree_node.action_data

	if not data or data.outcome then
		return "done"
	end

	if data.target_unit ~= blackboard.target_unit or not Unit.alive(data.target_unit) then
		data.outcome = "target_changed"

		return "done"
	end

	if not valid_navigation(unit, blackboard) or not POSITION_LOOKUP[data.target_unit] then
		data.outcome = "invalid_context"

		return "done"
	end

	local position = POSITION_LOOKUP[unit]
	local target_position = POSITION_LOOKUP[data.target_unit]

	if t >= data.clearance_t and flat_distance(position, target_position) >= action.clear_distance then
		data.outcome = "clearance_reached"

		return "done"
	elseif blackboard.reloaded_rocket == false then
		data.outcome = "reload_needed"

		return "done"
	elseif t >= data.end_t then
		data.outcome = "timeout"

		return "done"
	end

	-- A moving player can cross behind the planned escape segment without
	-- changing target identity. Stop that route immediately rather than walk
	-- toward the player until the next planning interval.
	local remaining_segment = Vector3.flat(data.destination_box:unbox() - position)
	local away_from_target = Vector3.flat(position - target_position)
	local planned_segment = Vector3.flat(data.destination_box:unbox() - data.segment_start_box:unbox())
	local arrived = Vector3.length(remaining_segment) <= action.arrival_distance
		or Vector3.dot(remaining_segment, planned_segment) <= 0

	if not arrived and Vector3.dot(remaining_segment, away_from_target) < 0 then
		data.outcome = "target_crossed_route"

		return "done"
	end

	-- Replace a viable leg before the navbot reaches its endpoint and brakes.
	-- One speculative handoff per leg bounds queries; if no safe continuation
	-- exists yet, retain the current safe goal and retry only after arrival.
	-- This proximity check is independent of the slower stalled-path timer.
	if not arrived and not data.handoff_attempted
		and Vector3.length(remaining_segment) <= data.handoff_distance
		and data.plan_attempts < action.max_plans
		and blackboard.navigation_extension:number_failed_move_attempts() == 0 then
		data.handoff_attempted = true

		if self:_plan(unit, blackboard, data, t) then
			data.blocked_plans = 0

			return "running"
		end
	end

	if t >= data.next_replan_t then
		local stalled = flat_distance(position, data.progress_position_box:unbox()) < action.minimum_progress

		-- Unlike blackboard.no_path_found, this native counter is reset when a
		-- new destination is submitted, so an earlier failed path cannot win.
		local path_failed = blackboard.navigation_extension:number_failed_move_attempts() > 0

		if path_failed or arrived or stalled then
			-- Successful legs do not spend the blocked-route retry budget.
			data.blocked_plans = arrived and 0 or data.blocked_plans + 1
			if data.blocked_plans >= action.max_blocked_plans or data.plan_attempts >= action.max_plans
				or not self:_plan(unit, blackboard, data, t) then
				data.outcome = "blocked"

				return "done"
			end
		else
			data.progress_position_box:store(position)
			data.next_replan_t = t + action.replan_interval
		end
	end

	return "running"
end

BTDoomrocketRepositionAction.leave = function (self, unit, blackboard, t, reason, destroy)
	local data = blackboard.doomrocket_reposition_data

	if data and data.navigation_owned and valid_navigation(unit, blackboard) then
		local navigation = blackboard.navigation_extension
		navigation:stop()
		navigation:set_max_speed(AiUtils.get_default_breed_move_speed(unit, blackboard))
		blackboard.locomotion_extension:set_wanted_velocity(Vector3.zero())

		-- Only normal completion owns an idle transition. Stagger/death and other
		-- higher-priority actions supply their own animation after an interruption.
		if reason == "done" and Unit.has_animation_event(unit, "idle") then
			Managers.state.network:anim_event(unit, "idle")
			blackboard.move_state = "idle"
		end
	end

	printf("[doomrocket:COMBAT] phase=reposition_end reason=%s plans=%d elapsed_s=%.3f",
		data and data.outcome or tostring(reason), data and data.plan_attempts or 0,
		data and t - data.start_t or 0)
	blackboard.doomrocket_reposition_active = nil
	blackboard.doomrocket_reposition_data = nil
	blackboard.active_node = nil
end

return
