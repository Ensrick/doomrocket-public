local mod = get_mod("doomrocket")
-- Your mod code goes here.
-- https://vmf-docs.verminti.de

local MOD_VERSION = "0.1.60-alpha"
mod._doomrocket_version = MOD_VERSION
printf("[doomrocket:LOAD] v%s", MOD_VERSION)

-- mod:dofile("scripts/mods/doomrocket/utils/LobbyManager")
-- Managers.lobby = ModLobbyManager:new()


Managers.package:load("resource_packages/breeds/skaven_ratling_gunner", "global")
Managers.package:load("resource_packages/breeds/skaven_storm_vermin", "global")
-- Managers.package:load("resource_packages/breeds/skaven_warpfire_thrower", "global")
-- The visible Warlock uses a Ratling-family armor shader plus the exact
-- Stormvermin skin/fur/whisker children selected in Crunch's source scene.
-- Load both installed game packages before the runtime child-material swap.
Managers.package:load("units/beings/player/dark_pact_skins/skaven_ratlinggunner/skin_1001/third_person/chr_third_person_mesh", "global")

mod:dofile("scripts/mods/doomrocket/breeds/skaven_doomrocket")
mod:dofile("scripts/mods/doomrocket/interactions/doom_rocket_interaction")
mod:dofile("scripts/mods/doomrocket/interactions/doom_rocket_pickup")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_audio")
mod._doomrocket_chimney_anchor = mod:dofile("scripts/mods/doomrocket/utils/doomrocket_chimney_anchor")
mod._warlock_effect_package = mod:dofile("scripts/mods/doomrocket/utils/doomrocket_effect_package")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_backpack_smoke")
mod._doomrocket_crystal_anchor = mod:dofile("scripts/mods/doomrocket/utils/doomrocket_crystal_anchor")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_crystal_flame")
mod._doomrocket_hose_profile = mod:dofile("scripts/mods/doomrocket/utils/doomrocket_hose_profile")
mod._doomrocket_hose_solver = mod:dofile("scripts/mods/doomrocket/utils/doomrocket_hose_solver")
mod._doomrocket_hose_frames = mod:dofile("scripts/mods/doomrocket/utils/doomrocket_hose_frames")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_hose")
mod._warlock_animation_clock = mod:dofile("scripts/mods/doomrocket/utils/doomrocket_animation_clock")
mod._warlock_animation_manifest = mod:dofile("scripts/mods/doomrocket/utils/doomrocket_animation_manifest")
-- A separate trusted profile is inert until the explicit new-spawn rehearsal
-- command selects it. Never replace a registered artist profile.
local rehearsal_manifest = mod:dofile("scripts/mods/doomrocket/utils/doomrocket_native_rehearsal_manifest")
for id, profile in pairs(rehearsal_manifest.profiles) do
	if mod._warlock_animation_manifest.profiles[id] == nil then
		mod._warlock_animation_manifest.profiles[id] = profile
	end
end
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_animation_rehearsal")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_animation_ownership")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_outfit_correction")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_locomotion_animation")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_grip_alignment")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_traversal_pose")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_animation_blend")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_animation_probe")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_weapon_pose_probe")
mod:dofile("scripts/mods/doomrocket/utils/doomrocket_action_lookup")
mod:dofile("scripts/mods/doomrocket/extensions/projectile_rocket")
mod:dofile("scripts/mods/doomrocket/extensions/anim_emitter")
-- Vanilla snapshots its threat_values table at boot, before this mod registers its breed,
-- so an aggroed doomrocket used to hit `nil * amount` inside calculate_threat_value.
--
-- Register through vanilla's own setter rather than replacing calculate_threat_value with
-- a private snapshot. That replacement closed over its own table, so every mutator that
-- calls ConflictDirector.set_threat_value (elite_run, wave_of_plague_monks,
-- chaos_warriors_trickle, wave_of_berzerkers) silently no-op'd, and any breed registered
-- after this mod loaded still crashed.
for breed_name, data in pairs(Breeds) do
	ConflictDirector.set_threat_value(nil, breed_name, data.threat_value or 0)
end

mod:dofile("scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/generated/bt_selector_skaven_doomrocket")
mod:dofile("scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/bt_doomrocket_shove_action")
mod:dofile("scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/bt_doomrocket_reposition_action")
mod:dofile("scripts/mods/doomrocket/utils/doomrocket_ballistics")
mod:dofile("scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/bt_doomrocket_launch_action")
mod:dofile("scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/bt_doomrocket_reload_action")
mod:dofile("scripts/mods/doomrocket/behavior/nodes/skaven_doomrocket/trees/skaven/skaven_doomrocket_behavior")
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_aim_template")
mod:dofile("scripts/mods/doomrocket/extensions/death_reactions")
mod:dofile("scripts/mods/doomrocket/utils/hooks")
mod:dofile("scripts/mods/doomrocket/utils/GameNetworkManager_utils")
mod:dofile("scripts/mods/doomrocket/rpc")
-- -- mod:dofile("scripts/managers/conflict_director/conflict_director")


--adds doomrocket killfeed icon
UISettings.breed_textures['skaven_doomrocket'] = 'unit_frame_portrait_enemy_doomrocket'
mod:dofile("scripts/mods/doomrocket/extensions/doomrocket_portrait_frame")

-- #33: throw players into the air with the native flail, without the camera grab.
-- Vanilla StatusUtils.set_catapulted_network routes a catapult to the victim's own
-- peer, whose GenericStatusExtension.set_catapulted enters the flailing catapulted
-- state and also force-turns the camera along the throw (force_look_rotation, a
-- 0.3 s lerp that ignores look input). The catapulted state itself keeps look
-- input. Route the same call through a mod RPC so the owning peer skips only that
-- forced turn. Vanilla's own explosion push cannot carry the knockback either:
-- math.auto_lerp(max_damage_radius, radius, push, 1, d) clamps to [push, 1], an
-- empty range for any push above 1, so inside the blast it returns 1 m/s.
local KNOCKBACK_NEAR_SPEED = 10 -- m/s horizontal within max_damage_radius
local KNOCKBACK_FAR_SPEED = 3 -- m/s horizontal at the blast edge
local KNOCKBACK_NEAR_LIFT = 5 -- m/s upward within max_damage_radius
local KNOCKBACK_FAR_LIFT = 2.5 -- m/s upward at the blast edge

local suppress_catapult_look = false

mod:hook("PlayerUnitFirstPerson", "force_look_rotation", function (func, self, ...)
	if suppress_catapult_look then
		return
	end

	return func(self, ...)
end)

-- Runs on the peer that owns the player unit (or the host for its own player/bots).
mod._doomrocket_catapult_local = function (unit, velocity)
	local status_extension = unit and Unit.alive(unit) and ScriptUnit.has_extension(unit, "status_system")

	if not status_extension or status_extension.is_husk or status_extension:is_disabled() then
		return false
	end

	suppress_catapult_look = true

	local ok = mod:pcall(status_extension.set_catapulted, status_extension, true, velocity)

	suppress_catapult_look = false

	return ok
end

mod:network_register("rpc_doomrocket_catapult", function (sender, go_id, x, y, z)
	local unit_storage = Managers.state.unit_storage
	local unit = unit_storage and type(go_id) == "number" and unit_storage:unit(go_id)

	if not unit or type(x) ~= "number" or type(y) ~= "number" or type(z) ~= "number" then
		return
	end

	mod._doomrocket_catapult_local(unit, Vector3(x, y, z))
end)

mod._doomrocket_knockback_player = function (hit_unit, damage_source, attacker_unit, impact_position, explosion_data)
	if not DamageUtils.is_player_unit(hit_unit) then
		return
	end

	local owner = Managers.player:unit_owner(hit_unit)
	local status_extension = ScriptUnit.has_extension(hit_unit, "status_system")
	local hit_position = POSITION_LOOKUP[hit_unit]

	if not owner or not status_extension or status_extension:is_disabled() or not hit_position then
		return
	end

	local direction, distance = Vector3.direction_length(Vector3.flat(hit_position - impact_position))

	if distance < 0.01 then
		local attacker_position = POSITION_LOOKUP[attacker_unit]

		direction = attacker_position and Vector3.normalize(Vector3.flat(hit_position - attacker_position)) or Vector3.zero()
	end

	local inner_radius = explosion_data.max_damage_radius
	local falloff = math.clamp((distance - inner_radius) / (explosion_data.radius - inner_radius), 0, 1)
	local speed = KNOCKBACK_NEAR_SPEED + (KNOCKBACK_FAR_SPEED - KNOCKBACK_NEAR_SPEED) * falloff
	local lift = KNOCKBACK_NEAR_LIFT + (KNOCKBACK_FAR_LIFT - KNOCKBACK_NEAR_LIFT) * falloff
	local velocity = direction * speed + Vector3(0, 0, lift)

	if not owner.remote then
		mod._doomrocket_catapult_local(hit_unit, velocity)

		return
	end

	local go_id = Managers.state.network:unit_game_object_id(hit_unit)

	if go_id then
		mod:network_send("rpc_doomrocket_catapult", owner:network_id(), go_id, velocity.x, velocity.y, velocity.z)
	end
end

--setup rocket explosion template
ExplosionTemplates["doomrocket_explosion"] = {
	explosion = {
		radius =  6,
		alert_enemies = true,
		max_damage_radius = 1.5,
		always_hurt_players = true,
		alert_enemies_radius = 15,
		-- Resolve the custom event only when Wwise actually registered it. The v0.1.59
		-- bank resource loaded without registering its events; leaving that unavailable
		-- event here helped turn an unrelated world-ownership mistake into a native crash.
		-- The vanilla Warpfire explosion is a safe audible fallback on every peer.
		sound_event_name = mod._doomrocket_select_impact_event(),
		damage_profile = "warpfire_thrower_explosion",
		effect_name = "fx/chr_warp_fire_explosion_01",
		damage_type = "grenade",
		-- #33: no template catapult or native push; server_hit_func throws each player
		-- with a distance-scaled catapult that leaves their camera alone.
		server_hit_func = mod._doomrocket_knockback_player,
		dont_rotate_fx = true,
		allow_friendly_fire_override = true,
		ai_friendly_fire = true,
		difficulty_power_level = {
			easy = {
				power_level_glance = 400,
				power_level = 800
			},
			normal = {
				power_level_glance = 400,
				power_level = 800
			},
			hard = {
				power_level_glance = 400,
				power_level = 800
			},
			harder = {
				power_level_glance = 400,
				power_level = 800
			},
			hardest = {
				power_level_glance = 400,
				power_level = 800
			},
			cataclysm = {
				power_level_glance = 400,
				power_level = 800
			},
			cataclysm_2 = {
				power_level_glance = 400,
				power_level = 800
			},
			cataclysm_3 = {
				power_level_glance = 400,
				power_level = 800
			}
		},
	}
}

-- ExplosionTemplates["doomrocket_explosion"].explosion["damage_type"] = "kinetic"
ExplosionTemplates["doomrocket_explosion"].name = "doomrocket_explosion"

-- #33: the rocket deals 40% less damage to other enemies, so more of them survive
-- the blast for players to kill (temporary health). Vanilla only scales friendly
-- fire for player attackers, so scale this explosion's final damage against AI.
local DOOMROCKET_DAMAGE_SOURCE = "skaven_doomrocket"
local DOOMROCKET_AI_DAMAGE_MULTIPLIER = 0.6

local function scale_doomrocket_ai_damage(damage, ...)
	return damage * DOOMROCKET_AI_DAMAGE_MULTIPLIER, ...
end

mod:hook(DamageUtils, "calculate_damage", function (func, damage_output, target_unit, attacker_unit, hit_zone_name, original_power_level, boost_curve, boost_damage_multiplier, is_critical_strike, damage_profile, target_index, backstab_multiplier, damage_source, ...)
	if damage_source ~= DOOMROCKET_DAMAGE_SOURCE or not target_unit then
		return func(damage_output, target_unit, attacker_unit, hit_zone_name, original_power_level, boost_curve, boost_damage_multiplier, is_critical_strike, damage_profile, target_index, backstab_multiplier, damage_source, ...)
	end

	local target_breed = Unit.alive(target_unit) and Unit.get_data(target_unit, "breed")

	if not target_breed or target_breed.is_player then
		return func(damage_output, target_unit, attacker_unit, hit_zone_name, original_power_level, boost_curve, boost_damage_multiplier, is_critical_strike, damage_profile, target_index, backstab_multiplier, damage_source, ...)
	end

	return scale_doomrocket_ai_damage(func(damage_output, target_unit, attacker_unit, hit_zone_name, original_power_level, boost_curve, boost_damage_multiplier, is_critical_strike, damage_profile, target_index, backstab_multiplier, damage_source, ...))
end)

local num_explosions = #NetworkLookup.explosion_templates
NetworkLookup.explosion_templates[num_explosions + 1] = "doomrocket_explosion"
NetworkLookup.explosion_templates["doomrocket_explosion"] = num_explosions + 1




-- local function create_lookups(lookup, hashtable)
-- 	local i = #lookup

-- 	for key, _ in pairs(hashtable) do
-- 		i = i + 1
-- 		lookup[i] = key
-- 	end

-- 	return lookup
-- end
-- NetworkLookup.breeds = create_lookups({}, Breeds)

local num_breeeds = #NetworkLookup.breeds
NetworkLookup.breeds[num_breeeds + 1] = "skaven_doomrocket"
NetworkLookup.breeds["skaven_doomrocket"] = num_breeeds + 1

-- for k,v in pairs(NetworkLookup.breeds) do
-- 	mod:echo(k.."	"..tostring(v))
-- end

local num_dam = #NetworkLookup.damage_sources + 1
NetworkLookup.damage_sources["skaven_doomrocket"] = num_dam
NetworkLookup.damage_sources[num_dam] = "skaven_doomrocket"


local spawn_mod = get_mod("CreatureSpawner")

-- local add_spawn_catagory = {
--     beastmen_nu_gor = {
--         "misc",
--     },
--     beastmen_slaangor_standard = {
--         "misc",
--     },
-- }
-- table.merge(spawn_mod.unit_categories, table)
new_breed_names = {
    'skaven_doomrocket',
}

if spawn_mod then
	for i,breed_name in ipairs(new_breed_names) do
		table.insert(spawn_mod["all_units"], breed_name)
	end
end

-- Vanilla bt_minion.lua already pointed its own trees at their precompiled
-- selectors at boot. Only this mod's tree needs it; renaming every tree would
-- also point other mods' plain-BTSelector trees at selector classes that do not
-- exist.
BreedBehaviors.skaven_doomrocket[1] = "BTSelector_skaven_doomrocket"
BreedBehaviors.skaven_doomrocket.name = "skaven_doomrocket_GENERATED"

local husk_num = #NetworkLookup.husks
NetworkLookup.husks[husk_num + 1] = "units/rocket/SM_Rocket"
NetworkLookup.husks["units/rocket/SM_Rocket"] = husk_num + 1

local num_anims = #NetworkLookup.anims
NetworkLookup.anims[num_anims + 1] = "doomrocket_reload"
NetworkLookup.anims["doomrocket_reload"] = num_anims + 1


mod.anim_emitters = {}
mod.projectiles = {}

function mod.update(dt)
	-- Retain one asynchronous cosmetic-package lease per active world. Starting
	-- before ordinary emitter updates keeps first spawn out of sync-read/flush.
	mod._prewarm_warlock_child_materials()
	mod._prewarm_warlock_backpack_smoke()
	mod._prewarm_warlock_crystal_flame()

    for unit_string,projectile in pairs(mod.projectiles) do
		if unit_string then
			projectile:update(dt)
		end
	end

	for unit,anim_emitter in pairs(mod.anim_emitters) do
		anim_emitter:update(unit, dt)
	end

	mod._update_warlock_backpack_sounds()
	mod._update_warlock_backpack_smoke()
	mod._update_warlock_crystal_flame()
end

local function reset_warlock_runtime_state(reason, unload_bank)
	mod._reset_warlock_animation_probe(reason or "runtime_reset")
	mod._reset_warlock_animation_rehearsal()
	mod._reset_warlock_locomotion_animation()
	mod._reset_warlock_grip_alignment()
	mod._reset_warlock_traversal_pose()
	mod._reset_warlock_animation_ownership()
	mod._reset_warlock_outfit_correction()
	mod._reset_warlock_hose(reason or "runtime_reset")
	mod._reset_warlock_weapon_pose_probe()
	mod._reset_warlock_backpack_smoke(reason or "runtime_reset")
	mod._reset_warlock_crystal_flame(reason or "runtime_reset")
	mod._shutdown_doomrocket_audio(reason or "runtime_reset", unload_bank == true)

	if mod._reset_warlock_death_drivers then
		mod._reset_warlock_death_drivers()
	end
end

function mod.on_game_state_changed(status, state)
	if status == "exit" and state == "StateIngame" then
		reset_warlock_runtime_state("state_ingame_exit", false)
	end
end

function mod.on_disabled()
	reset_warlock_runtime_state("mod_disabled", true)
end

function mod.on_unload()
	reset_warlock_runtime_state("mod_unload", true)
end

-- utils/action_sweep_rewrite.lua (archived to _archive/) globally replaced
-- ActionSweep._play_character_impact for every player and every melee weapon, purely to
-- swap the bombardier's animation state machine on hit. Vanilla 6.11.3 extracted that
-- path into DamageUtils.add_hit_reaction and added the breed.hit_reaction_function
-- extension point, so that now lives on the breed itself. See breeds/skaven_doomrocket.lua.

-- Bombardiers are enabled unconditionally; the old /doom chat command that toggled them
-- is gone. The toggle-OFF path it provided was unsafe anyway: it nil'd entries out of the
-- breeds arrays while iterating them, and specials pacing picks with
-- breeds[Math.random(1, #breeds)], so a hole could hand it a nil breed.
mod.doom = true

for setting_name, settings in pairs(SpecialsSettings) do
	if settings.breeds then
		settings.breeds[#settings.breeds + 1] = "skaven_doomrocket"
	end

	if settings.difficulty_overrides then
		for diff, diff_settings in pairs(settings.difficulty_overrides) do
			if diff_settings.breeds then
				diff_settings.breeds[#diff_settings.breeds + 1] = "skaven_doomrocket"
			end
		end
	end
end

mod:hook(ConflictDirector, 'refresh_conflict_director_patches', function (func, self)
	local result = func(self)
	if mod.doom then
		if CurrentSpecialsSettings.breeds then
			local has_doomrockets = false
			for k,v in pairs(CurrentSpecialsSettings.breeds) do
				if k == 'skaven_doomrocket' or v == 'skaven_doomrocket' then
					has_doomrockets = true
				end
			end

			if not has_doomrockets then
				-- Was #CurrentSpecialsSettings (the settings table itself, hash-only, so
				-- always 0), which wrote to index 1 and overwrote the first special in the
				-- pool instead of appending to it.
				CurrentSpecialsSettings.breeds[#CurrentSpecialsSettings.breeds + 1] = 'skaven_doomrocket'
			end
		end
	end
	return result
end)

-- for setting_name, settings in pairs(SpecialsSettings) do
-- 	if settings.breeds then
-- 		for index, breed in ipairs(settings.breeds) do
-- 			mod:echo(tostring(index).." "..tostring(breed))
-- 		end
-- 	end
-- end

-- Managers.state.conflict.specials_pacing

-- for index, breed in ipairs(SpecialsSettings.skaven_light.breeds) do
-- 	mod:echo(tostring(index).." "..tostring(breed))
-- end

-- for setting_name, settings in pairs(SpecialsSettings) do
-- 	if settings.breeds then
-- 		settings.breeds[#settings.breeds + 1] = "skaven_doomrocket"
-- 	end
-- 	if settings.difficulty_overrides then
-- 		for diff, diff_settings in pairs(settings.difficulty_overrides) do
-- 			if diff_settings.breeds then
-- 				diff_settings.breeds[#diff_settings.breeds + 1] = "skaven_doomrocket"
-- 			end
-- 		end
-- 	end
-- end

-- for k,v in pairs(CurrentPacing) do
-- 	mod:echo(tostring(k).."	"..tostring(v))
-- end
-- mod:echo(CurrentPacing)
-- mod:echo(Managers.state.conflict.current_conflict_settings)
-- mod:echo(Managers.level_transition_handler:get_current_conflict_director())


-- for k,v in pairs(CurrentSpecialsSettings.breeds) do
-- 	mod:echo(tostring(k).."	"..tostring(v))
-- end

-- CurrentSpecialsSettings.breeds[#CurrentSpecialsSettings + 1] = 'skaven_doomrocket'

-- mod:hook(SpecialsPacing, 'update', function(func, self, t, alive_specials, specials_population, player_positions)
-- 	-- for k,v in pairs(self._specials_spawn_queue) do
-- 	-- 	mod:echo(tostring(k).."	"..tostring(v))
-- 	-- end
-- 	return func(self, t, alive_specials, specials_population, player_positions)
-- end)

-- local difficulty, difficulty_tweak = Managers.state.difficulty:get_difficulty()
-- local fallback_difficulty = Managers.state.difficulty.fallback_difficulty
-- local composition_difficulty = DifficultyTweak.converters.composition(difficulty, difficulty_tweak)
-- local director = ConflictDirectors[Managers.state.conflict.current_conflict_settings]
-- -- for k,v in pairs(director.specials) do
-- -- 	mod:echo(tostring(k).."	"..tostring(v))
-- -- end

-- -- local thinger = ConflictUtils.patch_settings_with_difficulty(table.clone(director.specials), composition_difficulty, fallback_difficulty)
-- local source_settings = table.clone(director.specials)
-- local overrides = source_settings.difficulty_overrides
-- local override_settings = overrides and (overrides[difficulty] or overrides[fallback_difficulty])

-- if override_settings then
-- 	for key, _ in pairs(source_settings) do
-- 		if key ~= "difficulty_overrides" then
-- 			source_settings[key] = override_settings[key] or source_settings[key]
-- 			mod:echo('not key')
-- 		end
-- 	end

-- 	source_settings.difficulty_overrides = nil

-- 	-- return source_settings
-- 	mod:echo('this branch')
-- else
-- 	-- return source_settings
-- 	mod:echo('that branch')
-- end

-- CurrentSpecialsSettings.breeds[#CurrentSpecialsSettings + 1] = 'skaven_doomrocket'
-- Managers.state.conflict:refresh_conflict_director_patches()

-- mod:hook(ConflictUtils, 'patch_settings_with_difficulty', function(func, source_settings, difficulty, fallback_difficulty)

-- 	return func(source_settings, difficulty, fallback_difficulty)
-- end)
