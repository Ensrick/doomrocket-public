local mod = get_mod("doomrocket")

AttachmentNodeLinking.ai_doomrocket = {
    wielded = {
        {
            target = 0,
            source = "j_leftweaponattach"
        },
        {
            target = "a_barrel",
            source = "j_leftweaponcomponent1"
        },
        {
            target = "handle",
            source = "j_lefthand"
        },
    },
    unwielded = {
        {
            target = 0,
            source = "a_spear"
        }
    }
}

AttachmentNodeLinking.doomrocket_pack = {
    {
        target = 0,
        source = "a_spear"
    },
}

-- Bones the Warlock Bombardier mesh is weighted to that the original torso/limb bridge
-- never named. Without these the parts sit at bind pose and visibly float: the backpack
-- (j_backpack), the loot sack, the first two tail segments, and the face detail bones.
-- mod._prune_armor_bridge drops any of these the base skeleton turns out to lack.
local DOOMROCKET_EXTRA_ARMOR_NODES = {
    "j_backpack",
    "j_loot_sack",
    "j_loot_sack_component6",
    "j_loot_sack_component7",
    "j_skull_parent",
    "j_skull_dynamic",
    "j_tail1",
    "j_tail2",
    "j_jaw",
    "j_nose",
    "j_leftear",
    "j_rightear",
    "j_lip_left",
    "j_lip_right",
}

AttachmentNodeLinking.doomrocket_armor = {
    {
        target = 0,
        source = "root_point",
    },
    {
        target = "j_hips",
        source = "j_hips",
    },
    {
        target = "j_leftupleg",
        source = "j_leftupleg",
    },
    {
        target = "j_rightupleg",
        source = "j_rightupleg",
    },
    {
        target = "j_spine",
        source = "j_spine",
    },
    -- THE SIX SCALE BONES (v0.1.36). Stingray has no scale compensation:
    -- vanilla sizes each skaven breed's proportions by ANIMATING dedicated
    -- j_*_scale segments at the top of every limb/spine chain, and its own
    -- skaven outfit table (ai_outfit_body_scale_w_tail,
    -- attachment_node_linking.lua) links exactly these six. Dalo commented
    -- three out and never listed the other three; unlinked scale bones hold
    -- their spawn pose while the donor drives their parents, so every vertex
    -- below diverges - the compounding limb stretch of v0.1.28/35.
    {
        target = "j_leftupleg_scale",
        source = "j_leftupleg_scale",
    },
    {
        target = "j_rightupleg_scale",
        source = "j_rightupleg_scale",
    },
    {
        target = "j_spine_scale",
        source = "j_spine_scale",
    },
    {
        target = "j_leftarm_scale",
        source = "j_leftarm_scale",
    },
    {
        target = "j_rightarm_scale",
        source = "j_rightarm_scale",
    },
    {
        target = "j_tail1_scale",
        source = "j_tail1_scale",
    },
    {
        target = "j_leftleg",
        source = "j_leftleg",
    },
    {
        target = "j_rightleg",
        source = "j_rightleg",
    },
    {
        target = "j_spine1",
        source = "j_spine1",
    },
    {
        target = "j_leftfoot",
        source = "j_leftfoot",
    },
    {
        target = "j_leftshoulder",
        source = "j_leftshoulder",
    },
    {
        target = "j_neck",
        source = "j_neck",
    },
    {
        target = "j_rightfoot",
        source = "j_rightfoot",
    },
    {
        target = "j_rightshoulder",
        source = "j_rightshoulder",
    },
    {
        target = "j_leftarm",
        source = "j_leftarm",
    },
    {
        target = "j_lefttoebase",
        source = "j_lefttoebase",
    },
    {
        target = "j_neck_1",
        source = "j_neck_1",
    },
    {
        target = "j_rightarm",
        source = "j_rightarm",
    },
    {
        target = "j_righttoebase",
        source = "j_righttoebase",
    },
    {
        target = "j_head",
        source = "j_head",
    },
    {
        target = "j_leftforearm",
        source = "j_leftforearm",
    },
    {
        target = "j_rightforearm",
        source = "j_rightforearm",
    },
    {
        target = "j_leftforearmroll",
        source = "j_leftforearmroll",
    },
    {
        target = "j_lefthand",
        source = "j_lefthand",
    },
    {
        target = "j_rightforearmroll",
        source = "j_rightforearmroll",
    },
    {
        target = "j_righthand",
        source = "j_righthand",
    },
    {
        target = "j_leftweaponattach",
        source = "j_leftweaponattach",
    },
    {
        target = "j_rightweaponattach",
        source = "j_rightweaponattach",
    },
    {
        target = "j_leftweaponcomponent1",
        source = "j_leftweaponcomponent1",
    },
    {
        target = "j_leftweaponcomponent10",
        source = "j_leftweaponcomponent10",
    },
    {
        target = "j_leftweaponcomponent2",
        source = "j_leftweaponcomponent2",
    },
    {
        target = "j_leftweaponcomponent3",
        source = "j_leftweaponcomponent3",
    },
    {
        target = "j_leftweaponcomponent4",
        source = "j_leftweaponcomponent4",
    },
    {
        target = "j_leftweaponcomponent5",
        source = "j_leftweaponcomponent5",
    },
    {
        target = "j_leftweaponcomponent6",
        source = "j_leftweaponcomponent6",
    },
    {
        target = "j_leftweaponcomponent7",
        source = "j_leftweaponcomponent7",
    },
    {
        target = "j_leftweaponcomponent8",
        source = "j_leftweaponcomponent8",
    },
    {
        target = "j_leftweaponcomponent9",
        source = "j_leftweaponcomponent9",
    },
    {
        target = "j_rightweaponcomponent1",
        source = "j_rightweaponcomponent1",
    },
    {
        target = "j_rightweaponcomponent10",
        source = "j_rightweaponcomponent10",
    },
    {
        target = "j_rightweaponcomponent2",
        source = "j_rightweaponcomponent2",
    },
    {
        target = "j_rightweaponcomponent3",
        source = "j_rightweaponcomponent3",
    },
    {
        target = "j_rightweaponcomponent4",
        source = "j_rightweaponcomponent4",
    },
    {
        target = "j_rightweaponcomponent5",
        source = "j_rightweaponcomponent5",
    },
    {
        target = "j_rightweaponcomponent6",
        source = "j_rightweaponcomponent6",
    },
    {
        target = "j_rightweaponcomponent7",
        source = "j_rightweaponcomponent7",
    },
    {
        target = "j_rightweaponcomponent8",
        source = "j_rightweaponcomponent8",
    },
    {
        target = "j_rightweaponcomponent9",
        source = "j_rightweaponcomponent9",
    },
    -- {
    --     target = "j_jaw",
    --     source = "j_jaw",
    -- },
    -- {
    --     target = "j_leftear",
    --     source = "j_leftear",
    -- },
    -- {
    --     target = "j_rightear",
    --     source = "j_rightear",
    -- },
    {
        target = "j_lefthandindex1",
        source = "j_lefthandindex1",
    },
    {
        target = "j_lefthandmiddle1",
        source = "j_lefthandmiddle1",
    },
    {
        target = "j_lefthandpinky1",
        source = "j_lefthandpinky1",
    },
    {
        target = "j_lefthandring1",
        source = "j_lefthandring1",
    },
    {
        target = "j_leftinhandthumb",
        source = "j_leftinhandthumb",
    },
    {
        target = "j_righthandindex1",
        source = "j_righthandindex1",
    },
    {
        target = "j_righthandmiddle1",
        source = "j_righthandmiddle1",
    },
    {
        target = "j_righthandpinky1",
        source = "j_righthandpinky1",
    },
    {
        target = "j_righthandring1",
        source = "j_righthandring1",
    },
    {
        target = "j_rightinhandthumb",
        source = "j_rightinhandthumb",
    },
    {
        target = "j_lefthandindex2",
        source = "j_lefthandindex2",
    },
    {
        target = "j_lefthandmiddle2",
        source = "j_lefthandmiddle2",
    },
    {
        target = "j_lefthandpinky2",
        source = "j_lefthandpinky2",
    },
    {
        target = "j_lefthandring2",
        source = "j_lefthandring2",
    },
    {
        target = "j_lefthandthumb1",
        source = "j_lefthandthumb1",
    },
    {
        target = "j_righthandindex2",
        source = "j_righthandindex2",
    },
    {
        target = "j_righthandmiddle2",
        source = "j_righthandmiddle2",
    },
    {
        target = "j_righthandpinky2",
        source = "j_righthandpinky2",
    },
    {
        target = "j_righthandring2",
        source = "j_righthandring2",
    },
    {
        target = "j_righthandthumb1",
        source = "j_righthandthumb1",
    },
    {
        target = "j_lefthandindex3",
        source = "j_lefthandindex3",
    },
    {
        target = "j_lefthandmiddle3",
        source = "j_lefthandmiddle3",
    },
    {
        target = "j_lefthandpinky3",
        source = "j_lefthandpinky3",
    },
    {
        target = "j_lefthandring3",
        source = "j_lefthandring3",
    },
    {
        target = "j_lefthandthumb2",
        source = "j_lefthandthumb2",
    },
    {
        target = "j_righthandindex3",
        source = "j_righthandindex3",
    },
    {
        target = "j_righthandmiddle3",
        source = "j_righthandmiddle3",
    },
    {
        target = "j_righthandpinky3",
        source = "j_righthandpinky3",
    },
    {
        target = "j_righthandring3",
        source = "j_righthandring3",
    },
    {
        target = "j_righthandthumb2",
        source = "j_righthandthumb2",
    },
}


local rocket_glaive_1 = {
	unit_extension_template = "ai_weapon_unit",
    unit_name = "units/rocket/pRocketLauncher",
	attachment_node_linking = AttachmentNodeLinking.ai_doomrocket,
    extension_init_data = {
        weapon_system = {
            weapon_template = "ratling_gun"
        }
    },
    drop_reasons = {
        death = true,
    },
}

local bombadier_pack_1 = {
	unit_extension_template = "ai_outfit_unit",
    unit_name = "units/bombadier/Backpack",
	attachment_node_linking = AttachmentNodeLinking.doomrocket_pack,
    drop_reasons = {
        death = false,
    },
}

-- Root-only fallback used for the v0.1.21/22 A-B test (own-ASM idle drive).
-- Kept for rollback: if the bridge ever misbehaves, swapping the item back to
-- this table gives a statically-posed but correctly-volumed model.
AttachmentNodeLinking.doomrocket_warlock_root = {
    {
        target = 0,
        source = "root_point",
    },
}

-- Crunch's Warlock Bombardier body (body, fur, armor, backpack on one rig).
-- The shipped .bones contains 138 entries; Dalo's source has the same set plus
-- camera_attach. The scale-100 armature wrapper is a real compiled hierarchy
-- difference, not evidence that the Bitsquid Blender exporter invented bones.
-- Living use is root-only/self-ASM; the filtered bridge below is calibration
-- metadata for the visual-only death retarget.
local bombadier_curiass = {
	unit_extension_template = "ai_outfit_unit",
    unit_name = "units/warlock_bombardier/warlock_bombardier_3p",
	attachment_node_linking = AttachmentNodeLinking.doomrocket_warlock_root,
    drop_reasons = {
        death = false,
    },
}

local rocket_glaives = {
    rocket_glaive_1,
    count = 1,
    name = 'doomrocket_inventory',
}

local bombadier_pack = {
    bombadier_pack_1,
    count = 1,
    name = 'doomrocket_inventory',
}

local bombadier_armor = {
    bombadier_curiass,
    count = 1,
    name = 'doomrocket_inventory',
}

InventoryConfigurations['doomrocket_inventory'] = {
    enemy_hit_sound = "bullet",
	anim_state_event = "idle",
	items = {
        -- bombadier_armor is the real body now, so the separate placeholder pack is
        -- retired: the new mesh carries its own backpack as a second material slot.
        bombadier_armor,
        rocket_glaives,
	},
    items_n = 2
}

InventoryConfigurations['warlock_engineer'] = {
    enemy_hit_sound = "spear",
	anim_state_event = "idle",
	multiple_configurations = { 
        "doomrocket_inventory",
        -- "ratlinggun",
        -- "halberd",
    },
    items_n = 1
}


-- local configs = InventoryConfigurations["ratlinggun"]
-- local items = configs.items
-- local items_n = configs.items_n
-- local index = 0
-- for i = 1, items_n, 1 do
--     index = index + 1
--     local item_category = items[i]
--     local item_category_n = item_category.count
--     local item_category_name = item_category.name
--     local item_index = math.random(1, item_category_n)
--     local item = item_category[item_index]
--     local item_unit_name = item.unit_name
--     local item_unit_template_name = item.unit_extension_template or "ai_inventory_item"
--     local item_flow_event = item.flow_event

--     mod:echo(item_category)
--     mod:echo(item_category_n)
--     mod:echo(item_category_name)
--     mod:echo(item_index)
--     mod:echo(item)
--     mod:echo(item_unit_name)
--     mod:echo(item_unit_template_name)
--     mod:echo(item_flow_event)
-- end

local new_configs = {
    doomrocket_inventory = InventoryConfigurations['doomrocket_inventory'],
    warlock_engineer =InventoryConfigurations['warlock_engineer']
}


for config_name, config in pairs(new_configs) do
	config.items_n = config.items and #config.items

	-- assert(AIInventoryTemplates[config_name] == nil, "Can't override configuration based templates")

	AIInventoryTemplates[config_name] = function ()
		return config_name
	end

	local multiple_configurations = config.multiple_configurations

	if multiple_configurations then
		config.config_lookup = {}

		for i = 1, #multiple_configurations do
			local config_name = multiple_configurations[i]
			config.config_lookup[config_name] = i
		end
	end
end


local num_invents = #NetworkLookup.ai_inventory
NetworkLookup.ai_inventory["doomrocket_inventory"] = num_invents + 1
NetworkLookup.ai_inventory[num_invents + 1] = "doomrocket_inventory"
-- Append the extra weighted bones to the armor bridge (target == source: the node has
-- the same name on the item and on the owner).
for i = 1, #DOOMROCKET_EXTRA_ARMOR_NODES do
    local node = DOOMROCKET_EXTRA_ARMOR_NODES[i]
    AttachmentNodeLinking.doomrocket_armor[#AttachmentNodeLinking.doomrocket_armor + 1] = {
        target = node,
        source = node,
    }
end


-- The shipped Warlock state-machine skeleton has 138 bones. Bridge entries
-- whose TARGET bone is absent from that unit are engine fatals at lookup time,
-- so the death-retarget metadata uses this filtered copy. Generated from
-- warlock_bombardier_3p.bones - keep the two in sync (Test-WarlockPipeline).
local WARLOCK_UNIT_BONES = {
    ["root_point"] = true,
    ["j_hips"] = true,
    ["j_whip_parent"] = true,
    ["j_whip_dynamic"] = true,
    ["j_tail1"] = true,
    ["j_tail1_scale"] = true,
    ["j_tail2"] = true,
    ["j_tail3"] = true,
    ["j_tail4"] = true,
    ["j_tail5"] = true,
    ["j_tail6"] = true,
    ["j_spine"] = true,
    ["j_spine_scale"] = true,
    ["j_spine1"] = true,
    ["j_rightshoulder"] = true,
    ["j_rightarm"] = true,
    ["j_rightarm_scale"] = true,
    ["j_rightforearm"] = true,
    ["j_righthand"] = true,
    ["j_rightweaponattach"] = true,
    ["j_rightweaponcomponent9"] = true,
    ["j_rightweaponcomponent8"] = true,
    ["j_rightweaponcomponent7"] = true,
    ["j_rightweaponcomponent6"] = true,
    ["j_rightweaponcomponent5"] = true,
    ["j_rightweaponcomponent4"] = true,
    ["j_rightweaponcomponent3"] = true,
    ["j_rightweaponcomponent2"] = true,
    ["j_rightweaponcomponent10"] = true,
    ["j_rightweaponcomponent1"] = true,
    ["j_rightinhandthumb"] = true,
    ["j_righthandthumb1"] = true,
    ["j_righthandthumb2"] = true,
    ["j_righthandring1"] = true,
    ["j_righthandring2"] = true,
    ["j_righthandring3"] = true,
    ["j_righthandpinky1"] = true,
    ["j_righthandpinky2"] = true,
    ["j_righthandpinky3"] = true,
    ["j_righthandmiddle1"] = true,
    ["j_righthandmiddle2"] = true,
    ["j_righthandmiddle3"] = true,
    ["j_righthandindex1"] = true,
    ["j_righthandindex2"] = true,
    ["j_righthandindex3"] = true,
    ["j_rightforearmroll"] = true,
    ["j_neck"] = true,
    ["j_necklace_01_parent"] = true,
    ["j_necklace_01_dynamic"] = true,
    ["j_necklace_02_parent"] = true,
    ["j_necklace_02_dynamic"] = true,
    ["j_neck_1"] = true,
    ["j_head"] = true,
    ["j_righteyelidtop"] = true,
    ["j_righteyelidbottom"] = true,
    ["j_righteyebrow3"] = true,
    ["j_righteyebrow2"] = true,
    ["j_righteyebrow1"] = true,
    ["j_rightear"] = true,
    ["j_nose"] = true,
    ["j_lip_upright"] = true,
    ["j_lip_upleft"] = true,
    ["j_lip_right"] = true,
    ["j_lip_left"] = true,
    ["j_lefteyelidtop"] = true,
    ["j_lefteyelidbottom"] = true,
    ["j_lefteyebrow3"] = true,
    ["j_lefteyebrow2"] = true,
    ["j_lefteyebrow1"] = true,
    ["j_leftear"] = true,
    ["j_jaw"] = true,
    ["j_lip_downright"] = true,
    ["j_lip_downleft"] = true,
    ["j_face_cloth_right_01_parent"] = true,
    ["j_face_cloth_right_01_dynamic"] = true,
    ["j_face_cloth_right_02_parent"] = true,
    ["j_face_cloth_right_02_dynamic"] = true,
    ["j_face_cloth_left_01_parent"] = true,
    ["j_face_cloth_left_01_dynamic"] = true,
    ["j_face_cloth_left_02_parent"] = true,
    ["j_face_cloth_left_02_dynamic"] = true,
    ["j_loot_sack"] = true,
    ["j_loot_sack_component7"] = true,
    ["j_loot_sack_component6"] = true,
    ["j_loot_sack_component5"] = true,
    ["j_loot_sack_component4"] = true,
    ["j_loot_sack_component3"] = true,
    ["j_loot_sack_component2"] = true,
    ["j_loot_sack_component1"] = true,
    ["j_leftshoulder"] = true,
    ["j_leftarm"] = true,
    ["j_leftarm_scale"] = true,
    ["j_leftforearm"] = true,
    ["j_lefthand"] = true,
    ["j_leftweaponattach"] = true,
    ["j_leftweaponcomponent9"] = true,
    ["j_leftweaponcomponent8"] = true,
    ["j_leftweaponcomponent7"] = true,
    ["j_leftweaponcomponent6"] = true,
    ["j_leftweaponcomponent5"] = true,
    ["j_leftweaponcomponent4"] = true,
    ["j_leftweaponcomponent3"] = true,
    ["j_leftweaponcomponent2"] = true,
    ["j_leftweaponcomponent10"] = true,
    ["j_leftweaponcomponent1"] = true,
    ["j_leftinhandthumb"] = true,
    ["j_lefthandthumb1"] = true,
    ["j_lefthandthumb2"] = true,
    ["j_lefthandring1"] = true,
    ["j_lefthandring2"] = true,
    ["j_lefthandring3"] = true,
    ["j_lefthandpinky1"] = true,
    ["j_lefthandpinky2"] = true,
    ["j_lefthandpinky3"] = true,
    ["j_lefthandmiddle1"] = true,
    ["j_lefthandmiddle2"] = true,
    ["j_lefthandmiddle3"] = true,
    ["j_lefthandindex1"] = true,
    ["j_lefthandindex2"] = true,
    ["j_lefthandindex3"] = true,
    ["j_leftforearmroll"] = true,
    ["j_backpack_parent"] = true,
    ["j_backpack"] = true,
    ["j_skull_parent"] = true,
    ["j_skull_dynamic"] = true,
    ["j_rightupleg"] = true,
    ["j_rightupleg_scale"] = true,
    ["j_rightleg"] = true,
    ["j_rightfoot"] = true,
    ["j_righttoebase"] = true,
    ["j_rightinfootindex"] = true,
    ["j_leftupleg"] = true,
    ["j_leftupleg_scale"] = true,
    ["j_leftleg"] = true,
    ["j_leftfoot"] = true,
    ["j_lefttoebase"] = true,
    ["j_leftinfootindex"] = true,
    ["aim_target"] = true,
}

AttachmentNodeLinking.doomrocket_warlock_bridge = {}
for i = 1, #AttachmentNodeLinking.doomrocket_armor do
    local entry = AttachmentNodeLinking.doomrocket_armor[i]
    if entry.target == 0 or WARLOCK_UNIT_BONES[entry.target] then
        local bridge = AttachmentNodeLinking.doomrocket_warlock_bridge
        bridge[#bridge + 1] = entry
    end
end

-- v0.1.36: bridge driving with the six scale-bone links active - the vanilla
-- ai_outfit_body_scale_w_tail configuration. doomrocket_warlock_root above
-- remains the self-ASM fallback table.
bombadier_curiass.attachment_node_linking = AttachmentNodeLinking.doomrocket_warlock_root
-- Called from the AIInventoryExtension._setup_configuration hook before vanilla links.
-- Runs once: Unit.node on a node the owner lacks is an uncatchable engine fatal, so any
-- entry whose source is absent from the base skeleton is removed here instead.
local _armor_bridge_pruned = false

function mod._prune_armor_bridge(owner_unit)
    if _armor_bridge_pruned or not owner_unit or not Unit.alive(owner_unit) then
        return
    end

    -- AIInventoryExtension runs this hook for every enemy. Do not let whichever
    -- breed happens to equip an outfit first prune the shared Warlock bridge
    -- against its unrelated skeleton (the latest log caught a Bestigor doing
    -- exactly that). The bridge is authored only for the Doomrocket donor.
    local owner_breed = Unit.get_data(owner_unit, "breed")
    if not owner_breed or owner_breed.name ~= "skaven_doomrocket" then
        return
    end

    local bridge = AttachmentNodeLinking.doomrocket_warlock_bridge
    local kept, dropped = {}, {}

    for i = 1, #bridge do
        local entry = bridge[i]
        local source = entry.source

        if type(source) ~= "string" or Unit.has_node(owner_unit, source) then
            kept[#kept + 1] = entry
        else
            dropped[#dropped + 1] = source
        end
    end

    for i = #bridge, 1, -1 do
        bridge[i] = nil
    end
    for i = 1, #kept do
        bridge[i] = kept[i]
    end

    _armor_bridge_pruned = true
    printf("[doomrocket] armor bridge: %d node(s) linked, %d dropped (absent on base)%s",
        #kept, #dropped, #dropped > 0 and (": " .. table.concat(dropped, ", ")) or "")
end
