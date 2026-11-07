local mod = get_mod("doomrocket")
Pickups = Pickups or {}

Pickups.level_events.doom_rocket = {
    additional_data_func = "doom_rocket",
	debug_pickup_category = "level_event",
	hud_description = "doom_rocket",
	individual_pickup = false,
	item_description = "doom_rocket",
	item_name = "doom_rocket",
	only_once = true,
	slot_name = "slot_level_event",
	spawn_weighting = 1,
	type = "doom_rocket",
	unit_name = "units/weapons/player/pup_explosive_barrel/pup_explosive_barrel_01",
	unit_template_name = "explosive_pickup_projectile_unit",
	wield_on_pickup = false,
}

-- Register only this pickup, the way vanilla pickups.lua registers its own.
-- Re-running that whole vanilla file (the old approach) recreated every vanilla
-- pickup table and LootRatPickups and re-normalized the DLC weights, discarding
-- other mods' load-time pickup changes (#35). Level-event pickups are spawned by
-- name, never by weighted draw, so this one needs no weight normalization.
local doom_rocket_pickup = Pickups.level_events.doom_rocket

doom_rocket_pickup.pickup_name = "doom_rocket"
AllPickups.doom_rocket = doom_rocket_pickup

function create_lookup(lookup, hashtable)
	local i = #lookup

	for key, _ in pairs(hashtable) do
		i = i + 1
		lookup[i] = key
	end

	return lookup
end

-- NetworkLookup.pickup_names = create_lookup({}, AllPickups)

local num_pickups = #NetworkLookup.pickup_names + 1
NetworkLookup.pickup_names[num_pickups] = "doom_rocket"
NetworkLookup.pickup_names["doom_rocket"] = num_pickups

ItemMasterList = ItemMasterList or {}
ItemMasterList.doom_rocket = {
	gamepad_hud_icon = "consumables_icon_defence",
	hud_icon = "consumables_icon_defence",
	inventory_icon = "icons_placeholder",
	is_local = true,
	item_type = "explosive_inventory_item",
	left_hand_unit = "units/weapons/player/wpn_explosive_barrel/wpn_explosive_barrel_01",
	rarity = "plentiful",
	slot_type = "healthkit",
	temporary_template = "explosive_barrel",
	can_wield = CanWieldAllItemTemplates,
}

local num_items = #NetworkLookup.item_names + 1
NetworkLookup.item_names[num_items] = "doom_rocket"
NetworkLookup.item_names["doom_rocket"] = num_items
