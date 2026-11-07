local mod = get_mod("doomrocket")
mod:dofile("scripts/mods/doomrocket/breeds/skaven_doomrocket_inventory")

local function INVENTORY_UNIT(owner_unit)
	local breed = Unit.get_data(owner_unit, "breed")
	local inventory_template = breed.default_inventory_template
	local inventory_extension = ScriptUnit.extension(owner_unit, "ai_inventory_system")
	local inventory_unit = inventory_extension:get_unit(inventory_template)

	return inventory_unit
end

local function INVENTORY_UNIT_VS(owner_unit)
	local inventory_extension = ScriptUnit.extension(owner_unit, "inventory_system")
	local inventory_unit = inventory_extension:get_weapon_unit()

	return inventory_unit
end

local function IS_HUSK_UNIT(owner_unit)
	local is_network_unit = NetworkUnit.is_network_unit(owner_unit)
	local is_husk = is_network_unit and NetworkUnit.is_husk_unit(owner_unit)

	return is_husk
end

local function IS_UNIT_1P(owner_unit)
	return not IS_HUSK_UNIT(owner_unit)
end

local function IS_UNIT_3P(owner_unit)
	return IS_HUSK_UNIT(owner_unit)
end


Breeds.skaven_doomrocket = table.clone(Breeds.skaven_ratling_gunner)
-- #33: Ratling Gunner health and armor, so the Engineer has the Ratling's
-- breakpoints (a glass cannon) instead of the earlier Stormvermin health.
-- table.clone deep-copies max_health, so mutators that edit breed health
-- tables in place cannot leak between the two breeds.
Breeds.skaven_doomrocket.aim_template = "doomrocket"
Breeds.skaven_doomrocket.behavior = "skaven_doomrocket"
Breeds.skaven_doomrocket.threat_value = 7
Breeds.skaven_doomrocket.rocket_capacity = 3
Breeds.skaven_doomrocket.default_inventory_template = "doomrocket_inventory"
-- v0.1.36: donor is the RATLING GUNNER again (pure clone, no base_unit
-- override). The v0.1.28 "ratling proportions" stretch theory was wrong: the
-- stretch was the six unlinked j_*_scale bones (see the bridge in
-- skaven_doomrocket_inventory.lua). One skaven rest skeleton serves every rat
-- breed precisely BECAUSE proportions live in animated scale bones - so the
-- ratling donor gives Crunch's model the gun rat's full animation set, native
-- behavior, and a valid aim_target constraint, with no state-machine swaps
-- anywhere (cross-skeleton SM binding is fatal both ways, v0.1.24/34).
-- Deliberately NOT overriding unit_template. The clone keeps "ai_unit_ratling_gunner",
-- whose go_type the ENGINE's compiled network config actually knows about.
--
-- Pointing this at "ai_unit_doomrocket" made UnitSpawner call
-- GameSession.create_game_object with a go_type the engine has never heard of
-- ("Unknown game object ai_unit_doomrocket"), so no game object was created, the unit
-- got no id in unit_storage, and the first anim_event on it hard-asserted. A mod cannot
-- add engine game object types without installing its own network config, which this mod
-- does not do (the Network.config_hash hook is commented out).
--
-- Nothing is lost: vanilla's ai_unit_ratling_gunner template carries exactly the same
-- extension set this mod's ai_unit_doomrocket entry did (AIInventoryExtension,
-- GenericUnitAimExtension, PingTargetExtension over base ai_unit_base). The bombardier's
-- identity comes from the breed's behavior tree, inventory and aim template, not from the
-- extension list.
Breeds.skaven_doomrocket.death_reaction = "doomrocket"
-- The cloned Ratling death event would overlap the custom Warlock takes below. Death
-- playback is selected per corpse in the custom unit/husk reaction instead.
Breeds.skaven_doomrocket.death_sound_event = nil

-- The bombardier unit carries its own state machine, which lacks the hit_reaction_*
-- events; fall back to the ratling gunner machine so the reaction can play. Vanilla
-- calls this from DamageUtils.add_hit_reaction, so no melee-path hook is needed.
Breeds.skaven_doomrocket.hit_reaction_function = function (hit_unit, breed, hit_unit_dir, attack_direction, angle_difference)
	local hit_anim = (angle_difference < -math.pi * 0.75 or angle_difference > math.pi * 0.75) and "hit_reaction_backward"
		or angle_difference < -math.pi * 0.25 and "hit_reaction_left"
		or angle_difference < math.pi * 0.25 and "hit_reaction_forward"
		or "hit_reaction_right"

	if not Unit.has_animation_event(hit_unit, hit_anim) then
		Unit.set_animation_state_machine(hit_unit, "units/beings/enemies/skaven_ratlinggunner/chr_skaven_ratlinggunner")
	end

	return hit_anim
end

BreedActions.skaven_doomrocket = table.clone(BreedActions.skaven_ratling_gunner)
BreedActions.skaven_doomrocket.fire_rocket = table.clone(BreedActions.skaven_doomrocket.shoot_ratling_gun)
BreedActions.skaven_doomrocket.fire_rocket.name = "fire_rocket"
BreedActions.skaven_doomrocket.shoot_ratling_gun = nil
BreedActions.skaven_doomrocket.fire_rocket.light_weight_projectile_template_name = "doomrocket"
-- #16/#33: hold the visible aim for at least two seconds before the native
-- firing animation starts (was one second), so players have time to hear
-- the cue and react. Reload and shot cues are unchanged.
BreedActions.skaven_doomrocket.fire_rocket.minimum_aim_time = 2.0

-- Reuse the Stormvermin's zero-damage shove and push force, but
-- not its animation callback node.  The living Doomrocket uses the Ratling
-- state machine and the visible outfit only shares attack_shoot_align; the
-- custom action applies the shove once from a timer instead of waiting for the
-- unavailable anim_cb_stormvermin_push event.
BreedActions.skaven_doomrocket.push_attack = table.clone(BreedActions.skaven_storm_vermin.push_attack)
BreedActions.skaven_doomrocket.push_attack.attack_anim = "attack_shoot_align"
BreedActions.skaven_doomrocket.push_attack.impact_time = 0.65
BreedActions.skaven_doomrocket.push_attack.duration = 1.2

-- Sustained escape after the kick: run for 8-12 seconds and seek 20 m
-- separation. Plan shorter safe segments so this does not require one long
-- unobstructed ray. Blocked movement still terminates instead of looping.
BreedActions.skaven_doomrocket.reposition = {
	name = "reposition",
	clear_distance = 20.0,
	goal_distance = 8.0,
	min_duration = 8.0,
	max_duration = 12.0,
	max_plans = 32,
	max_blocked_plans = 2,
	replan_interval = 0.75,
	handoff_lookahead = 0.5,
	arrival_distance = 0.3,
	minimum_progress = 0.15,
	nav_height = 0.5,
	move_speed = Breeds.skaven_doomrocket.run_speed,
	move_anim = "move_fwd_run",
}

BreedActions.skaven_doomrocket.switch_weapons = {
    switch_animation = "idle",
    switch_weapon_index = 2,
    cooldown = -1,
    switching_done_time = 0.2
}

-- Vanilla scripts/settings/breeds.lua finishes every breed after the breed
-- files run: name, category mask, race/elite sets and action names. Do the same
-- for this breed only. This mod used to re-run that whole vanilla file, which
-- re-executed every vanilla breed file and overwrote other mods' load-time
-- changes to vanilla breeds. Dutch Spice hooks
-- Breeds.skaven_storm_vermin_warlord.run_on_update to spawn its Into the Nest
-- arena waves; the re-run put the vanilla function back, so the wave never
-- came (#34, #35). Everything else is inherited from the finished donor clone.
local BREED_RACE_SETS = {
	chaos = CHAOS,
	skaven = SKAVEN,
	beastmen = BEASTMEN,
	undead = UNDEAD,
	critter = CRITTER,
}

local function finish_breed_registration(breed_name)
	local breed = Breeds[breed_name]
	local hit_zones_lookup = BreedHitZonesLookup[breed_name]

	if hit_zones_lookup then
		breed.hit_zones_lookup = hit_zones_lookup
	end

	BreedUtils.inject_breed_category_mask(breed)

	breed.name = breed_name
	breed.is_ai = true

	local race_set = BREED_RACE_SETS[breed.race]

	if race_set then
		race_set[breed_name] = true
	end

	if breed.elite then
		ELITES[breed_name] = true
	end

	for action_name, action_data in pairs(BreedActions[breed_name]) do
		action_data.name = action_name
	end
end

finish_breed_registration("skaven_doomrocket")


Dismemberments["skaven_doomrocket"] = table.clone(Dismemberments["skaven_ratling_gunner"])

LightWeightProjectiles["doomrocket"] = {
    projectile_speed = 80,
		light_weight_projectile_effect = "doomrocket",
		damage_profile = "ratling_gunner",
		projectile_max_range = 50,
		hit_effect = "ratling_gunner",
		impact_push_speed = 1.5,
		spread = math.degrees_to_radians(7),
		attack_power_level = {
			20,
			40,
			120,
			200,
			250,
			250,
			250,
			250
		}
}
LightWeightProjectileEffects["doomrocket"] = {
    ratling_gun_bullet = {
		vfx = {
			{
				particle_name = "fx/chr_warp_fire_flamethrower_01",
				kill_policy = "destroy"
			},
			{
				particle_name = "fx/warp_lightning_bolt_impact",
				kill_policy = "stop"
			},
			{
				particle_name = "fx/wpnfx_skaven_ratlinggun_muzzlefx",
				link = "p_fx",
				unit_function = INVENTORY_UNIT
			}
		},
		sfx = {
			{
				looping_sound_event_name = "Play_weapon_warpbullet_flyby_proximity",
				looping_sound_stop_event_name = "Stop_weapon_warpbullet_flyby_proximity"
			}
		}
	}
}

-- local world = Managers.world:world("level_world")
-- -- local wwise_world = Wwise.wwise_world(world)
-- local player = Managers.player:local_player()
-- local player_unit = player.player_unit
-- local position = Unit.local_position(player_unit, 0)
-- local rotation = Unit.local_rotation(player_unit, 0)
-- -- WwiseWorld.trigger_event(wwise_world, "Play_enemy_warpfire_thrower_shoot", position, rotation)
-- Managers.state.unit_spawner:spawn_local_unit("units/bombadier/Backpack", position, rotation)

-- local function is_available(type, name)
-- 	printf("%s.%s : available? => %s", name, type, Application.can_get(type, name))
-- end
-- is_available("unit", "units/bombadier/Backpack")
