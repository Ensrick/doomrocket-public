local ACTIONS = BreedActions.skaven_doomrocket

local DEFAULT_RANGED = {
	"BTSequence",
	{
		"BTSelector",
		{
			"BTMoveToPlayersAction",
			name = "move_to_players",
			condition = "ratling_gunner_skulked_for_too_long",
			action_data = ACTIONS.move_to_players
		},
		{
			"BTSequence",
			{
				"BTRatlingGunnerApproachAction",
				name = "lurk",
				action_data = ACTIONS.lurk
			},
			{
				"BTRatlingGunnerApproachAction",
				name = "engage",
				action_data = ACTIONS.engage
			},
			name = "skulk_movement"
		},
		name = "movement_method"
	},
	{
		"BTRatlingGunnerWindUpAction",
		name = "wind_up_ratling_gun",
		action_data = ACTIONS.wind_up_ratling_gun
	},
	{
		"BTRatlingGunnerShootAction",
		name = "shoot_ratling_gun",
		action_data = ACTIONS.shoot_ratling_gun
	},
	{
		"BTRatlingGunnerMoveToShootAction",
		name = "move_to_shoot_position",
		action_data = ACTIONS.move_to_shoot_position
	},
	name = "attack_pattern"
}

local RANGED_COMBAT = {
	"BTUtilityNode",
	{
		"BTSequence",
		{
			"BTSelector",
			{
				"BTMoveToPlayersAction",
				name = "move_to_players",
				condition = "ratling_gunner_skulked_for_too_long",
				action_data = ACTIONS.move_to_players
			},
			{
				"BTSequence",
				{
					"BTRatlingGunnerApproachAction",
					name = "lurk",
					action_data = ACTIONS.lurk
				},
				{
					"BTRatlingGunnerApproachAction",
					name = "engage",
					action_data = ACTIONS.engage
				},
				name = "skulk_movement"
			},
			name = "movement_method"
		},
		{
			"BTRatlingGunnerWindUpAction",
			name = "wind_up_ratling_gun",
			action_data = ACTIONS.wind_up_ratling_gun
		},
		{
            "BTDoomrocketLaunchAction",
            name = "fire_rocket",
            action_data = ACTIONS.fire_rocket
        },
		{
			"BTRatlingGunnerMoveToShootAction",
			name = "move_to_shoot_position",
			action_data = ACTIONS.move_to_shoot_position
		},
		name = "attack_pattern"
	},
	condition = "confirmed_player_sighting",
	name = "in_combat"
}
local MELEE_COMBAT = {
	"BTUtilityNode",
	{
		"BTClanRatFollowAction",
		name = "follow",
		action_data = ACTIONS.follow
	},
	{
		"BTAttackAction",
		name = "running_attack",
		condition = "ask_target_before_attacking",
		action_data = ACTIONS.running_attack
	},
	{
		"BTAttackAction",
		name = "normal_attack",
		condition = "ask_target_before_attacking",
		action_data = ACTIONS.normal_attack
	},
	{
		"BTCombatShoutAction",
		name = "combat_shout",
		action_data = ACTIONS.combat_shout
	},
	condition = "ungor_archer_enter_melee_combat",
	name = "in_combat"
}


BreedBehaviors.skaven_doomrocket = {
	"BTSelector",
	{
		"BTSpawningAction",
		condition = "spawn",
		name = "spawn"
	},
	{
		"BTInVortexAction",
		condition = "in_vortex",
		name = "in_vortex"
	},
	{
		"BTFallAction",
		condition = "is_falling",
		name = "falling"
	},
	{
		"BTStaggerAction",
		name = "stagger",
		condition = "stagger",
		action_data = ACTIONS.stagger
	},
	{
		"BTSelector",
		{
			"BTTeleportAction",
			condition = "at_teleport_smartobject",
			name = "teleport"
		},
		{
			"BTClimbAction",
			condition = "at_climb_smartobject",
			name = "climb"
		},
		{
			"BTJumpAcrossAction",
			condition = "at_jump_smartobject",
			name = "jump_across"
		},
		{
			"BTSmashDoorAction",
			name = "smash_door",
			condition = "at_door_smartobject",
			action_data = ACTIONS.smash_door
		},
		condition = "at_smartobject",
		name = "smartobject"
	},
	{
		"BTSelector",
		{
			"BTDoomrocketShoveAction",
			name = "push_attack",
			condition = "doomrocket_should_shove",
			action_data = ACTIONS.push_attack
		},
		{
			"BTDoomrocketRepositionAction",
			name = "reposition",
			condition = "doomrocket_should_reposition",
			action_data = ACTIONS.reposition
		},
		{
			"BTIdleAction",
			name = "wait_at_close_range",
			condition = "doomrocket_should_wait_at_close_range"
		},
		{
			"BTSequence",
			{
				"BTSelector",
				{
					"BTMoveToPlayersAction",
					name = "move_to_players",
					condition = "ratling_gunner_skulked_for_too_long",
					action_data = ACTIONS.move_to_players
				},
				{
					"BTSequence",
					{
						"BTRatlingGunnerApproachAction",
						name = "lurk",
						action_data = ACTIONS.lurk
					},
					{
						"BTRatlingGunnerApproachAction",
						name = "engage",
						action_data = ACTIONS.engage
					},
					name = "skulk_movement"
				},
				name = "movement_method"
			},
			{
				"BTDoomrocketReloadAction",
				name = "wind_up_ratling_gun",
				action_data = ACTIONS.wind_up_ratling_gun
			},
			{
				"BTDoomrocketLaunchAction",
				name = "fire_rocket",
				action_data = ACTIONS.fire_rocket
			},
			{
				"BTRatlingGunnerMoveToShootAction",
				name = "move_to_shoot_position",
				action_data = ACTIONS.move_to_shoot_position
			},
			name = "attack_pattern"
		},
		name = "close_combat_selector"
	},
	{
		"BTIdleAction",
		name = "idle"
	},
	name = "skaven_ratling_gunner"
}

return
