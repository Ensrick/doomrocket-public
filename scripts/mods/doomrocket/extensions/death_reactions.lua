local mod = get_mod("doomrocket")

--=======================================
-- Have to copy a bunch of local functions from scripts\unit_extensions\generic\death_reactions.lua
--=======================================
local DeathReactions = DeathReactions
local BLACKBOARDS = BLACKBOARDS
local SCREENSPACE_DEATH_EFFECTS = {
	blunt = "fx/screenspace_blood_drops",
	heavy = "fx/screenspace_blood_drops_heavy",
}
local function is_hot_join_sync(killing_blow)
	local damage_type = killing_blow[DamageDataIndex.DAMAGE_TYPE]

	return damage_type == "sync_health"
end

local function play_screen_space_blood(world, unit, attacker_unit, killing_blow, damage_type)
	if Development.parameter("screen_space_player_camera_reactions") == false then
		return
	end

	local pos = POSITION_LOOKUP[unit] + Vector3(0, 0, 1)
	local player_manager = Managers.player
	local camera_manager = Managers.state.camera

	for _, player in pairs(player_manager:human_players()) do
		if not player.remote and (not script_data.disable_remote_blood_splatter or Unit.alive(attacker_unit) and player == player_manager:owner(attacker_unit)) then
			local vp_name = player.viewport_name
			local cam_pos = camera_manager:camera_position(vp_name)

			if Vector3.distance_squared(cam_pos, pos) < 9 and (not script_data.disable_behind_blood_splatter or camera_manager:is_in_view(vp_name, pos)) then
				local particle_name = SCREENSPACE_DEATH_EFFECTS[damage_type] or "fx/screenspace_blood_drops"

				Managers.state.blood:play_screen_space_blood(particle_name, Vector3.zero())
			end
		end
	end
end

local function handle_boss_difficulty_kill_achievement_tracking(breed, statistics_db)
	local difficulty_kill_achievements = breed.difficulty_kill_achievements

	if difficulty_kill_achievements then
		for i = 1, #difficulty_kill_achievements do
			local kill_achivement = difficulty_kill_achievements[i]
			local current_rank = Managers.state.difficulty:get_difficulty_rank()
			local player_manager = Managers.player
			local local_player_id = 1

			while player_manager:local_player(local_player_id) ~= nil do
				if local_player_id > 4 then
					ferror("Sanity check, how did we get above 4 here?")

					break
				end

				local player = player_manager:local_player(local_player_id)

				if not player.bot_player then
					local saved_rank = statistics_db:get_persistent_stat(player:stats_id(), kill_achivement)

					if saved_rank < current_rank then
						statistics_db:set_stat(player:stats_id(), kill_achivement, current_rank)
					end
				end

				local_player_id = local_player_id + 1
			end
		end
	end
end

local function handle_military_event_achievement(damage_type, breed_name, statistics_db)
	if damage_type == "military_finish" and breed_name == "chaos_warrior" then
		local stat_names = {
			"military_statue_kill_chaos_warriors",
			"military_statue_kill_chaos_warriors_cata",
		}

		for i = 1, #stat_names do
			local allowed_difficulties = QuestSettings.allowed_difficulties[stat_names[i]]
			local difficulty = Managers.state.difficulty:get_difficulty()

			if allowed_difficulties[difficulty] then
				local local_player = Managers.player:local_player()

				if local_player then
					local stats_id = local_player:stats_id()

					statistics_db:increment_stat(stats_id, "military_statue_kill_chaos_warriors_session")

					local num_chaos_warriors_killed = statistics_db:get_stat(stats_id, "military_statue_kill_chaos_warriors_session")

					if num_chaos_warriors_killed >= 3 then
						statistics_db:increment_stat(stats_id, stat_names[i])
						Managers.state.network.network_transmit:send_rpc_clients("rpc_increment_stat", NetworkLookup.statistics[stat_names[i]])
					end
				end
			end
		end
	end
end

local function handle_castle_boss_achievement(killing_blow, unit)
	local conflict_manager = Managers.state.conflict

	if conflict_manager:count_units_by_breed_during_event("chaos_exalted_sorcerer_drachenfels") > 0 then
		local player_manager = Managers.player
		local victim_health_extension = ScriptUnit.has_extension(unit, "health_system")
		local victim_damage_data = victim_health_extension.last_damage_data
		local victim_player = player_manager:owner(unit)
		local attacker_unique_id = victim_damage_data.attacker_unique_id
		local attacker_player = player_manager:player_from_unique_id(attacker_unique_id)

		if attacker_player and attacker_player ~= victim_player then
			local boss_units = conflict_manager:alive_bosses()
			local boss_unit = boss_units[1]

			if boss_unit ~= unit then
				local blackboard = BLACKBOARDS[boss_unit]

				blackboard.no_kill_achievement = false
			end
		end
	end
end

local function ai_default_unit_pre_start(unit, context, t, killing_blow)
	local statistics_db = context.statistics_db
	local blackboard = BLACKBOARDS[unit]
	local breed = blackboard.breed
	local damage_type = killing_blow[DamageDataIndex.DAMAGE_TYPE]

	StatisticsUtil.register_kill(unit, killing_blow, statistics_db, true)
	handle_boss_difficulty_kill_achievement_tracking(breed, statistics_db)
	handle_military_event_achievement(damage_type, breed.name, statistics_db)
	handle_castle_boss_achievement(killing_blow, unit)
	QuestSettings.handle_bastard_block_on_death(breed, unit, killing_blow, statistics_db)

	local killer_unit = killing_blow[DamageDataIndex.ATTACKER]
	local owner_unit = AiUtils.get_actual_attacker_unit(killer_unit)
	local player = Managers.player:owner(owner_unit)

	if player then
		local weapon_name = killing_blow[DamageDataIndex.DAMAGE_SOURCE_NAME]
		local death_hit_zone = killing_blow[DamageDataIndex.HIT_ZONE]
		local breed_name = breed.name

		DeathReactions._add_ai_killed_by_player_telemetry(unit, breed_name, owner_unit, player, damage_type, weapon_name, death_hit_zone)
	end
end

local function ai_default_unit_start(unit, context, t, killing_blow, is_server)
	local killer_unit = killing_blow[DamageDataIndex.SOURCE_ATTACKER_UNIT] or killing_blow[DamageDataIndex.ATTACKER]
	local death_hit_zone = killing_blow[DamageDataIndex.HIT_ZONE]
	local damage_type = killing_blow[DamageDataIndex.DAMAGE_TYPE]
	local damaged_by_other = unit ~= killer_unit
	local blackboard = BLACKBOARDS[unit]
	local ai_extension = ScriptUnit.extension(unit, "ai_system")
	local breed = blackboard.breed

	if not breed.disable_alert_friends_on_death and damaged_by_other then
		AiUtils.alert_nearby_friends_of_enemy(unit, blackboard.group_blackboard.broadphase, killer_unit)
	end

	if is_server and breed.custom_death_enter_function then
		local damage_source = killing_blow[DamageDataIndex.DAMAGE_SOURCE_NAME]

		breed.custom_death_enter_function(unit, killer_unit, damage_type, death_hit_zone, t, damage_source)
	end

	ai_extension:die(killer_unit, killing_blow)

	local locomotion = ScriptUnit.has_extension(unit, "locomotion_system")

	if locomotion then
		local death_velocity = locomotion.death_velocity_boxed and locomotion.death_velocity_boxed:unbox() or Vector3.zero()

		locomotion:set_affected_by_gravity(false)
		locomotion:set_movement_type("script_driven")
		locomotion:set_wanted_velocity(death_velocity)
		Managers.state.entity:system("ai_navigation_system"):add_navbot_to_release(unit)
		locomotion:set_collision_disabled("death_reaction", true)
		locomotion:set_movement_type("disabled")
	end

	if not breed.keep_weapon_on_death and ScriptUnit.has_extension(unit, "ai_inventory_system") then
		local inventory_extension = Managers.state.entity:system("ai_inventory_system")

		inventory_extension:drop_item(unit)
	end

	local owner_unit = AiUtils.get_actual_attacker_unit(killer_unit)

	if not breed.no_blood then
		play_screen_space_blood(context.world, unit, owner_unit, killing_blow, damage_type)
	end

	if breed.death_sound_event then
		local wwise_source, wwise_world = WwiseUtils.make_unit_auto_source(context.world, unit, Unit.node(unit, "c_head"))
		local dialogue_extension = ScriptUnit.extension(unit, "dialogue_system")
		local switch_group = dialogue_extension.wwise_voice_switch_group

		if switch_group then
			local switch_value = dialogue_extension.wwise_voice_switch_value

			WwiseWorld.set_switch(wwise_world, switch_group, switch_value, wwise_source)
		end

		local playing_id = WwiseWorld.trigger_event(wwise_world, breed.death_sound_event, wwise_source)
		local hit_reaction_extension = ScriptUnit.has_extension(unit, "hit_reaction_system")

		if hit_reaction_extension then
			hit_reaction_extension:set_death_sound_event_id(playing_id)
		end
	end

	local death_extension = ScriptUnit.extension(unit, "death_system")
	local data = {
		breed = breed,
		finish_time = t + (breed.time_to_unspawn_after_death or 3),
		wall_nail_data = death_extension.wall_nail_data,
	}
	local force_despawn = breed.force_despawn

	if Managers.state.game_mode:has_activated_mutator("metal") and damage_type == "metal_mutator" then
		force_despawn = true
	end

	if force_despawn then
		Managers.state.unit_spawner:mark_for_deletion(unit)
	elseif not breed.ignore_death_watch_timer then
		data.push_to_death_watch_timer = 0
	end

	Managers.state.game_mode:ai_killed(unit, owner_unit, data, killing_blow)

	return data, DeathReactions.IS_NOT_DONE
end

local function trigger_unit_dialogue_death_event(killed_unit, killer_unit, hit_zone, damage_type)
	if not Unit.alive(killed_unit) or not Unit.alive(killer_unit) then
		return
	end

	if Unit.has_animation_state_machine(killed_unit) then
		if Unit.has_data(killed_unit, "enemy_dialogue_face_anim") then
			Unit.animation_event(killed_unit, "talk_end")
		end

		if Unit.has_data(killed_unit, "enemy_dialogue_body_anim") then
			Unit.animation_event(killed_unit, "talk_body_end")
		end
	end

	local killer_dialogue_extension = ScriptUnit.has_extension(killer_unit, "dialogue_system")
	local player = Managers.player:owner(killer_unit)

	if killer_dialogue_extension and player ~= nil then
		local killed_unit_name = "UNKNOWN"
		local breed_data = Unit.get_data(killed_unit, "breed")

		if breed_data then
			killed_unit_name = breed_data.name
		elseif ScriptUnit.has_extension(killed_unit, "dialogue_system") then
			killed_unit_name = ScriptUnit.extension(killed_unit, "dialogue_system").context.player_profile
		end

		if killed_unit_name == "skaven_rat_ogre" then
			local user_memory = killer_dialogue_extension.user_memory

			user_memory.times_killed_rat_ogre = (user_memory.times_killed_rat_ogre or 0) + 1
		end

		local inventory_extension = ScriptUnit.extension(killer_unit, "inventory_system")
		local weapon_slot = inventory_extension:get_wielded_slot_name()

		if weapon_slot == "slot_melee" or weapon_slot == "slot_ranged" then
			local dot_type = false
			local event_data = FrameTable.alloc_table()

			event_data.killed_type = killed_unit_name
			event_data.hit_zone = hit_zone
			event_data.weapon_slot = weapon_slot

			local weapon_data = inventory_extension:get_slot_data(weapon_slot)

			if weapon_data then
				event_data.weapon_type = weapon_data.item_data.item_type

				local attack_template = AttackTemplates[damage_type]

				if attack_template and attack_template.dot_type then
					dot_type = attack_template.dot_type
				end
			end

			local killer_name = killer_dialogue_extension.context.player_profile
			local blackboard = BLACKBOARDS[killed_unit]
			local optional_spawn_data = blackboard and blackboard.optional_spawn_data

			if optional_spawn_data and not optional_spawn_data.prevent_killed_enemy_dialogue then
				SurroundingAwareSystem.add_event(killer_unit, "killed_enemy", DialogueSettings.default_view_distance, "killer_name", killer_name, "hit_zone", hit_zone, "enemy_tag", killed_unit_name, "weapon_slot", weapon_slot, "dot_type", dot_type)
			end

			local event_name = "enemy_kill"
			local dialogue_input = ScriptUnit.extension_input(killer_unit, "dialogue_system")

			dialogue_input:trigger_dialogue_event(event_name, event_data)
		end
	end
end

local function trigger_player_killing_blow_ai_buffs(ai_unit, killing_blow)
	local attacker_unit = killing_blow[DamageDataIndex.SOURCE_ATTACKER_UNIT] or killing_blow[DamageDataIndex.ATTACKER]

	if not Unit.alive(attacker_unit) or not Unit.alive(ai_unit) then
		return
	end

	local breed_attacker = Unit.get_data(attacker_unit, "breed")
	local breed_killed = Unit.get_data(ai_unit, "breed")

	Managers.state.event:trigger("on_killed", killing_blow, breed_killed, breed_attacker, attacker_unit, ai_unit)

	if not breed_attacker or not breed_attacker.is_player or not breed_killed then
		return
	end

	local side_manager = Managers.state.side

	if not side_manager:is_enemy(attacker_unit, ai_unit) then
		return
	end

	Managers.state.event:trigger("on_player_killed_enemy", killing_blow, breed_killed, ai_unit)

	local buff_extension = ScriptUnit.has_extension(attacker_unit, "buff_system")

	if buff_extension then
		buff_extension:trigger_procs("on_kill", killing_blow, breed_killed, ai_unit)
	end

	if (breed_killed.special or breed_killed.elite) and buff_extension then
		buff_extension:trigger_procs("on_kill_elite_special", killing_blow, breed_killed, ai_unit)
	end

	local side = side_manager.side_by_unit[ai_unit]

	if breed_killed.elite then
		local player_and_bot_units = side.ENEMY_PLAYER_AND_BOT_UNITS

		for i = 1, #player_and_bot_units do
			local unit = player_and_bot_units[i]
			local buff_extension = ScriptUnit.has_extension(unit, "buff_system")

			if buff_extension then
				buff_extension:trigger_procs("on_elite_killed", killing_blow, breed_killed, ai_unit)
			end
		end
	end

	if breed_killed.boss then
		local player_and_bot_units = side.ENEMY_PLAYER_AND_BOT_UNITS

		for i = 1, #player_and_bot_units do
			local unit = player_and_bot_units[i]
			local buff_extension = ScriptUnit.has_extension(unit, "buff_system")

			if buff_extension then
				buff_extension:trigger_procs("on_boss_killed", killing_blow, breed_killed)
			end
		end
	end

	if breed_killed.special then
		local player_and_bot_units = side.ENEMY_PLAYER_AND_BOT_UNITS

		for i = 1, #player_and_bot_units do
			local unit = player_and_bot_units[i]
			local buff_extension = ScriptUnit.has_extension(unit, "buff_system")

			if buff_extension then
				buff_extension:trigger_procs("on_special_killed", killing_blow, breed_killed, ai_unit)
			end
		end
	end

	local ping_extension = ScriptUnit.has_extension(ai_unit, "ping_system")

	if ping_extension then
		local player_and_bot_units = side.ENEMY_PLAYER_AND_BOT_UNITS

		for i = 1, #player_and_bot_units do
			local unit = player_and_bot_units[i]
			local buff_extension = ScriptUnit.has_extension(unit, "buff_system")

			if buff_extension then
				buff_extension:trigger_procs("on_pingable_target_killed", killing_blow, breed_killed)
			end
		end
	end
end

local function update_wall_nail(unit, dt, t, data)
	for hit_ragdoll_actor, nail_data in pairs(data.wall_nail_data) do
		local actor = Unit.actor(unit, hit_ragdoll_actor)

		if actor and Actor.is_physical(actor) then
			local world = Unit.world(unit)
			local position = Actor.position(actor)

			fassert(Vector3.is_valid(position), "Position from actor is not valid.")

			nail_data.position = Vector3Box(position)

			local dir = nail_data.attack_direction:unbox()
			local fly_time = 0.3
			local ray_dist = nail_data.hit_speed * fly_time

			fassert(ray_dist > 0, "Ray distance is not greater than 0")

			local collision_filter = "filter_weapon_nailing"
			local hit, hit_position, hit_distance, _, _ = PhysicsWorld.immediate_raycast(World.get_data(world, "physics_world"), position, dir, data.nailed and math.min(ray_dist, 0.4) or ray_dist, "closest", "collision_filter", collision_filter)

			if hit then
				Unit.disable_animation_state_machine(unit)
				Actor.set_kinematic(actor, true)
				Actor.set_collision_enabled(actor, false)

				local thickness = Unit.get_data(unit, "breed").ragdoll_actor_thickness[hit_ragdoll_actor]
				local node = Actor.node(actor)

				Unit.scene_graph_link(unit, node, nil)

				nail_data.node = node

				fassert(Vector3.is_valid(hit_position), "Position from raycast is valid")

				nail_data.target_position = Vector3Box(hit_position - dir * thickness)
				nail_data.start_t = t
				nail_data.end_t = t + math.max(hit_distance / ray_dist * fly_time, 0.01)
				data.finish_time = math.max(data.finish_time, t + 30)
				data.nailed = true
			else
				data.wall_nail_data[hit_ragdoll_actor] = nil
			end
		elseif actor and data.nailed then
			local node = nail_data.node
			local lerp_t = math.min(math.auto_lerp(nail_data.start_t, nail_data.end_t, 0, 1, t), 1)

			Unit.set_local_position(unit, node, Vector3.lerp(nail_data.position:unbox(), nail_data.target_position:unbox(), lerp_t))
		end
	end
end

local function ai_default_unit_update(unit, dt, context, t, data, is_server)
	local removed_externally = data.remove

	if removed_externally then
		Managers.state.conflict:register_unit_destroyed(unit, BLACKBOARDS[unit], "death_done")

		return DeathReactions.IS_DONE
	end

	if data.finish_time then
		if t < data.finish_time then
			if next(data.wall_nail_data) then
				update_wall_nail(unit, dt, t, data)
			end
		else
			data.finish_time = nil
		end
	end

	if data.push_to_death_watch_timer and t > data.push_to_death_watch_timer then
		Managers.state.unit_spawner:push_unit_to_death_watch_list(unit, t, data)

		data.push_to_death_watch_timer = nil
	end

	return DeathReactions.IS_NOT_DONE
end

local function ai_default_husk_pre_start(unit, context, t, killing_blow)
	local statistics_db = context.statistics_db

	if not is_hot_join_sync(killing_blow) then
		StatisticsUtil.register_kill(unit, killing_blow, statistics_db)
	end

	local breed = Unit.get_data(unit, "breed")

	handle_boss_difficulty_kill_achievement_tracking(breed, statistics_db)

	local killer_unit = killing_blow[DamageDataIndex.ATTACKER]
	local owner_unit = AiUtils.get_actual_attacker_unit(killer_unit)
	local player = Managers.player:owner(owner_unit)

	if player then
		local breed_name = breed.name
		local damage_type = killing_blow[DamageDataIndex.DAMAGE_TYPE]
		local weapon_name = killing_blow[DamageDataIndex.DAMAGE_SOURCE_NAME]
		local death_hit_zone = killing_blow[DamageDataIndex.HIT_ZONE]

		DeathReactions._add_ai_killed_by_player_telemetry(unit, breed_name, owner_unit, player, damage_type, weapon_name, death_hit_zone)
	end
end

local function ai_default_husk_update(unit, dt, context, t, data)
	if next(data.wall_nail_data) then
		update_wall_nail(unit, dt, t, data)

		return DeathReactions.IS_NOT_DONE
	elseif t < data.finish_time and not data.player_collided and not data.nailed then
		return DeathReactions.IS_NOT_DONE
	end

	local locomotion = ScriptUnit.has_extension(unit, "locomotion_system")

	if locomotion then
		locomotion:destroy()
	end

	return DeathReactions.IS_DONE
end

local function ai_default_husk_start(unit, context, t, killing_blow, is_server)
	local killer_unit = killing_blow[DamageDataIndex.ATTACKER]
	local damage_type = killing_blow[DamageDataIndex.DAMAGE_TYPE]
	local locomotion = ScriptUnit.has_extension(unit, "locomotion_system")

	if locomotion then
		locomotion:set_mover_disable_reason("husk_death_reaction", true)
		locomotion:set_collision_disabled("husk_death_reaction", true)
	end

	local owner_unit = AiUtils.get_actual_attacker_unit(killer_unit)
	local breed = Unit.get_data(unit, "breed")

	if not breed.no_blood then
		play_screen_space_blood(context.world, unit, owner_unit, killing_blow, damage_type)
	end

	if ScriptUnit.has_extension(unit, "ai_inventory_system") then
		local inventory_system = Managers.state.entity:system("ai_inventory_system")

		inventory_system:drop_item(unit)
	end

	if breed.death_sound_event and not is_hot_join_sync(killing_blow) then
		local wwise_source, wwise_world = WwiseUtils.make_unit_auto_source(context.world, unit, Unit.node(unit, "c_head"))
		local dialogue_extension = ScriptUnit.extension(unit, "dialogue_system")
		local switch_group = dialogue_extension.wwise_voice_switch_group

		if switch_group then
			local switch_value = dialogue_extension.wwise_voice_switch_value

			WwiseWorld.set_switch(wwise_world, switch_group, switch_value, wwise_source)
		end

		local playing_id = WwiseWorld.trigger_event(wwise_world, breed.death_sound_event, wwise_source)
		local hit_reaction_extension = ScriptUnit.has_extension(unit, "hit_reaction_system")

		if hit_reaction_extension then
			hit_reaction_extension:set_death_sound_event_id(playing_id)
		end
	end

	local death_extension = ScriptUnit.extension(unit, "death_system")
	local data = {
		breed = breed,
		finish_time = t + 3,
		wall_nail_data = death_extension.wall_nail_data,
	}

	Managers.state.game_mode:ai_killed(unit, owner_unit, data, killing_blow)

	return data, DeathReactions.IS_NOT_DONE
end

--================================
-- Custom death reaction templates
--================================
DeathReactions.templates.sm_rocket = {
	unit = {
		pre_start = function (unit, context, t, killing_blow)
			return
		end,
		start = function (unit, context, t, killing_blow, is_server)
			rocket_projectile = mod.projectiles[unit]
			if rocket_projectile then
				rocket_projectile:rocket_explode()
			end
		end,
		update = function (unit, dt, context, t, data)
			return
		end,
	},
	husk = {
		pre_start = function (unit, context, t, killing_blow)
			return
		end,
		start = function (unit, context, t, killing_blow, is_server)

		end,
		update = function (unit, dt, context, t, data)
			return
		end,
	},
}

DeathReactions.templates.doomrocket = {
    unit = {
        pre_start = function (unit, context, t, killing_blow)
            -- Capture the final living Warlock pose and detach event mirroring
            -- synchronously in DeathSystem.kill_unit. GenericHitReaction emits
            -- its delayed death event later in the frame, before start().
            mod._prepare_warlock_death(unit, "unit")
            ai_default_unit_pre_start(unit, context, t, killing_blow)
			if not is_hot_join_sync(killing_blow) then
				mod._play_warlock_death_voice(unit)
			end
        end,
        start = function (unit, context, t, killing_blow, is_server)
            local warlock_pose_driver = mod._take_warlock_death_driver(unit)
            local data, result = ai_default_unit_start(unit, context, t, killing_blow, is_server)
            data.warlock_pose_driver = warlock_pose_driver

            trigger_unit_dialogue_death_event(unit, killing_blow[DamageDataIndex.ATTACKER], killing_blow[DamageDataIndex.HIT_ZONE], killing_blow[DamageDataIndex.DAMAGE_TYPE])
            trigger_player_killing_blow_ai_buffs(unit, killing_blow)
            Managers.state.entity:system("play_go_tutorial_system"):register_killing_blow(killing_blow[DamageDataIndex.DAMAGE_TYPE], killing_blow[DamageDataIndex.ATTACKER])

            if unit ~= killing_blow[DamageDataIndex.ATTACKER] and ScriptUnit.has_extension(unit, "ai_system") then
                ScriptUnit.extension(unit, "ai_system"):attacked(killing_blow[DamageDataIndex.ATTACKER], t, killing_blow)
            end

            local attacker_unit = killing_blow[DamageDataIndex.ATTACKER]

            Managers.state.game_mode:ai_hit_by_player(unit, attacker_unit, killing_blow)

            --triggers enemy to explode if killed from a back blow
            if killing_blow[DamageDataIndex.HIT_ZONE] == "aux" then
                local position = Unit.local_position(unit, 0)
                local rotation = Unit.local_rotation(unit, 0)
                local explosion_template_name = "doomrocket_explosion"
                local damage_source = "skaven_doomrocket"
                local power_level = 1000

                if is_server then
					mod._doomrocket_sound_impact_requested(position)
					local area_damage_system = Managers.state.entity:system("area_damage_system")
					area_damage_system:create_explosion(unit, position, rotation,
						explosion_template_name, 1, damage_source, power_level,
						false, unit)
                end
            end

            return data, result
        end,
        update = function (unit, dt, context, t, data)
            mod._update_warlock_death_pose(data)
            local result = ai_default_unit_update(unit, dt, context, t, data)

            return result
        end,
    },
    husk = {
        pre_start = function (unit, context, t, killing_blow)
            mod._prepare_warlock_death(unit, "husk")
            ai_default_husk_pre_start(unit, context, t, killing_blow)
			if not is_hot_join_sync(killing_blow) then
				mod._play_warlock_death_voice(unit)
			end
        end,
        start = function (unit, context, t, killing_blow, is_server)
            local warlock_pose_driver = mod._take_warlock_death_driver(unit)
            local data, result = ai_default_husk_start(unit, context, t, killing_blow, is_server)
            data.warlock_pose_driver = warlock_pose_driver

            if not is_hot_join_sync(killing_blow) then
                trigger_player_killing_blow_ai_buffs(unit, killing_blow)
            end

            Managers.state.unit_spawner:freeze_unit_extensions(unit, t, data)

            local attacker_unit = killing_blow[DamageDataIndex.ATTACKER]

            Managers.state.game_mode:ai_hit_by_player(unit, attacker_unit, killing_blow)

            return data, result
        end,
        update = function (unit, dt, context, t, data)
            mod._update_warlock_death_pose(data)
            local result = ai_default_husk_update(unit, dt, context, t, data)

            return result
        end,
    },
}

-- mod:hook(Managers.state.entity, "extension_extractor_function", function(func, unit, unit_template_name)
--     print('[[[[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]]]]]')
--     print(unit_template_name)
--     local result1, result2 = func(unit, unit_template_name)
--     for k,v in pairs(result1) do
--         print(v)
--     end
--     return result1, result2
-- end)
