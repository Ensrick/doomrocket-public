#!/usr/bin/env python3
"""Issues #34/#35: loading Warlock must not reset other mods' vanilla changes.

The mod used to re-run vanilla scripts/settings/breeds.lua and
scripts/settings/equipment/pickups.lua at load. Each vanilla breed file writes
its definition back into the existing table with table.create_copy, so the
re-run replaced every function another mod had hooked on a vanilla breed. Dutch
Spice spawns its Into the Nest arena waves from a VMF hook on
Breeds.skaven_storm_vermin_warlord.run_on_update; after the re-run the vanilla
function was back and the wave never spawned.

These tests execute the production registration files in Lua 5.1 with engine
tables stubbed. When the local game-source checkout is present, the category
mask is computed by vanilla's own BreedUtils. Neither lane is an in-game test.
"""

from pathlib import Path
import re
import unittest

from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/mods/doomrocket"
BREED = SCRIPTS / "breeds/skaven_doomrocket.lua"
PICKUP = SCRIPTS / "interactions/doom_rocket_pickup.lua"
BOOTSTRAP = SCRIPTS / "doomrocket.lua"
NATIVE_BREED_UTILS = ROOT.parent / "Vermintide-2-Source-Code/scripts/helpers/breed_utils.lua"

HARNESS = """
    function table.clone(t)
        local copy = {}
        for key, value in pairs(t) do
            copy[key] = type(value) == 'table' and table.clone(value) or value
        end
        return copy
    end
    -- Vanilla foundation/scripts/util/table.lua: write original into the
    -- existing table, keeping its identity and dropping keys it lacks.
    function table.create_copy(copy, original)
        if not copy then
            return table.clone(original)
        end
        for key, value in pairs(original) do
            if type(value) ~= 'table' then
                copy[key] = value
            else
                copy[key] = table.create_copy(copy[key], value)
            end
        end
        for key in pairs(copy) do
            if original[key] == nil then
                copy[key] = nil
            end
        end
        return copy
    end
    function math.degrees_to_radians(d) return d * math.pi / 180 end
    mod = { loaded_files = {} }
    function mod:dofile(path)
        self.loaded_files[#self.loaded_files + 1] = path
        assert(not string.find(path, '^scripts/settings/'),
            'vanilla settings re-run: ' .. path)
    end
    function get_mod(name)
        assert(name == 'doomrocket')
        return mod
    end

    function vanilla_warlord_update() return 'vanilla' end
    function other_mod_warlord_update() return 'other mod' end
    local warlord_definition = {
        race = 'skaven', boss = true, armor_category = 2,
        run_on_update = vanilla_warlord_update,
    }
    function rerun_vanilla_warlord_file()
        Breeds.skaven_storm_vermin_warlord = table.create_copy(
            Breeds.skaven_storm_vermin_warlord, warlord_definition)
    end

    Breeds = {
        skaven_ratling_gunner = {
            name = 'skaven_ratling_gunner', is_ai = true, race = 'skaven',
            special = true, armor_category = 2, run_speed = 4,
            aoe_height = 1.5, smart_object_template = 'fallback',
            hit_zones_lookup = { head = { prio = 1 } }, allowed_layers = { planks = 1.5 },
            max_health = { 12, 12, 18, 26.5, 39.5, 54, 72, 90, 12 },
        },
        skaven_storm_vermin = {
            name = 'skaven_storm_vermin', is_ai = true, race = 'skaven',
            elite = true, armor_category = 2,
            max_health = { 16, 16, 24, 35.25, 52.75, 86.5, 102.5, 118.5, 24 },
        },
    }
    Breeds.skaven_storm_vermin_warlord = table.clone(warlord_definition)
    Breeds.skaven_storm_vermin_warlord.name = 'skaven_storm_vermin_warlord'
    -- Dutch Spice, loaded before Warlock, installs its VMF hook in the field.
    Breeds.skaven_storm_vermin_warlord.run_on_update = other_mod_warlord_update
    other_mod_max_health = Breeds.skaven_storm_vermin.max_health
    other_mod_max_health.custom_marker = true

    BreedActions = {
        skaven_ratling_gunner = {
            shoot_ratling_gun = { name = 'shoot_ratling_gun', light_weight_projectile_template_name = 'ratling_gunner' },
            wind_up_ratling_gun = { name = 'wind_up_ratling_gun' },
            move_to_players = { name = 'move_to_players' },
        },
        skaven_storm_vermin = { push_attack = { name = 'push_attack', attack_anim = 'attack_push' } },
    }
    BreedHitZonesLookup = {}
    CHAOS, SKAVEN, BEASTMEN, UNDEAD, CRITTER, ELITES = {}, {}, {}, {}, {}, {}
    SKAVEN.skaven_ratling_gunner, SKAVEN.skaven_storm_vermin = true, true
    ELITES.skaven_storm_vermin = true
    Dismemberments = { skaven_ratling_gunner = { head = 'chr_skaven_head' } }
    LightWeightProjectiles, LightWeightProjectileEffects = {}, {}

    category_calls = {}
    BreedUtils = { inject_breed_category_mask = function(breed)
        category_calls[#category_calls + 1] = { breed = breed, armor = breed.armor_category }
        breed.category_mask = 'stub'
    end }
"""

PICKUP_HARNESS = """
    mod = { loaded_files = {} }
    function mod:dofile(path)
        self.loaded_files[#self.loaded_files + 1] = path
        assert(not string.find(path, '^scripts/settings/'),
            'vanilla settings re-run: ' .. path)
    end
    function get_mod() return mod end
    first_aid_kit = { spawn_weighting = 0.5, pickup_name = 'first_aid_kit', other_mod_marker = true }
    Pickups = { level_events = { explosive_barrel = { spawn_weighting = 0.25 } },
        healing = { first_aid_kit = first_aid_kit } }
    AllPickups = { first_aid_kit = first_aid_kit, explosive_barrel = Pickups.level_events.explosive_barrel }
    LootRatPickups = { default = { other_mod_pickup = 1 } }
    NetworkLookup = { pickup_names = { 'first_aid_kit', 'explosive_barrel' }, item_names = { 'first_aid_kit' } }
    NetworkLookup.pickup_names.first_aid_kit, NetworkLookup.pickup_names.explosive_barrel = 1, 2
    NetworkLookup.item_names.first_aid_kit = 1
    CanWieldAllItemTemplates = {}
"""


def runtime(harness, *sources):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(harness)
    for source in sources:
        lua.execute(source.read_text(encoding="utf-8-sig"))
    return lua


def native_breed_utils():
    source = NATIVE_BREED_UTILS.read_text(encoding="utf-8-sig")
    return """
        bit = { bor = function(a, b)
            local result, place = 0, 1
            while a > 0 or b > 0 do
                if a % 2 == 1 or b % 2 == 1 then result = result + place end
                a, b, place = math.floor(a / 2), math.floor(b / 2), place * 2
            end
            return result
        end }
        BreedCategory = { Infantry = 1, Armored = 2, Berserker = 4,
            SuperArmor = 8, Special = 16, Boss = 32, Shielded = 64 }
    """ + source


class VanillaTableCompatTests(unittest.TestCase):
    def test_no_mod_script_reruns_a_vanilla_settings_file(self):
        rerun = re.compile(r"""^[^-\n]*\bdofile\(\s*["']scripts/settings/""", re.M)
        offenders = [str(path.relative_to(ROOT)) for path in SCRIPTS.rglob("*.lua")
                     if rerun.search(path.read_text(encoding="utf-8-sig"))]
        self.assertEqual(offenders, [])

    def test_other_mods_changes_to_vanilla_breeds_survive_registration(self):
        lua = runtime(HARNESS, BREED)
        lua.execute("""
            local warlord = Breeds.skaven_storm_vermin_warlord
            assert(warlord.run_on_update == other_mod_warlord_update,
                'Dutch Spice warlord hook was replaced')
            assert(Breeds.skaven_storm_vermin.max_health == other_mod_max_health)
            assert(other_mod_max_health.custom_marker)
            assert(Breeds.skaven_ratling_gunner.name == 'skaven_ratling_gunner')
            assert(BreedActions.skaven_ratling_gunner.shoot_ratling_gun.light_weight_projectile_template_name
                == 'ratling_gunner')
            assert(#mod.loaded_files == 1)
        """)

    def test_harness_detects_a_vanilla_breed_file_rerun(self):
        lua = runtime(HARNESS)
        lua.execute("""
            rerun_vanilla_warlord_file()
            assert(Breeds.skaven_storm_vermin_warlord.run_on_update == vanilla_warlord_update)
        """)

    def test_warlock_breed_is_finished_like_vanilla_breeds(self):
        lua = runtime(HARNESS, BREED)
        lua.execute("""
            local breed = Breeds.skaven_doomrocket
            assert(breed.name == 'skaven_doomrocket' and breed.is_ai)
            assert(SKAVEN.skaven_doomrocket and not ELITES.skaven_doomrocket)
            assert(not CHAOS.skaven_doomrocket and not BEASTMEN.skaven_doomrocket)
            assert(#category_calls == 1 and category_calls[1].breed == breed)
            -- #33: Ratling Gunner breakpoints, in a table of its own.
            local ratling = Breeds.skaven_ratling_gunner
            assert(category_calls[1].armor == ratling.armor_category)
            assert(breed.armor_category == ratling.armor_category)
            assert(breed.max_health ~= ratling.max_health)
            for rank, health in ipairs(ratling.max_health) do
                assert(breed.max_health[rank] == health, rank)
            end
            assert(breed.max_health[5] ~= Breeds.skaven_storm_vermin.max_health[5])
            for action_name, action in pairs(BreedActions.skaven_doomrocket) do
                assert(action.name == action_name, action_name)
            end
            local actions = BreedActions.skaven_doomrocket
            assert(actions.fire_rocket and not actions.shoot_ratling_gun)
            assert(actions.switch_weapons.name == 'switch_weapons')
            assert(actions.push_attack ~= BreedActions.skaven_storm_vermin.push_attack)
        """)

    @unittest.skipUnless(NATIVE_BREED_UTILS.exists(), "local game-source checkout not present")
    def test_native_category_mask_marks_the_armored_special(self):
        lua = runtime(HARNESS)
        lua.execute(native_breed_utils())
        lua.execute(BREED.read_text(encoding="utf-8-sig"))
        lua.execute("""
            local mask = Breeds.skaven_doomrocket.category_mask
            assert(mask == BreedCategory.Special + BreedCategory.Armored, tostring(mask))
            assert(Breeds.skaven_doomrocket.immediate_threat)
        """)

    def test_pickup_registration_keeps_other_mods_pickups(self):
        lua = runtime(PICKUP_HARNESS, PICKUP)
        lua.execute("""
            local rocket = Pickups.level_events.doom_rocket
            assert(AllPickups.doom_rocket == rocket and rocket.pickup_name == 'doom_rocket')
            assert(Pickups.healing.first_aid_kit == first_aid_kit and first_aid_kit.other_mod_marker)
            assert(first_aid_kit.spawn_weighting == 0.5)
            assert(AllPickups.first_aid_kit == first_aid_kit)
            assert(Pickups.level_events.explosive_barrel.spawn_weighting == 0.25)
            assert(LootRatPickups.default.other_mod_pickup == 1)
            local id = NetworkLookup.pickup_names.doom_rocket
            assert(id == 3 and NetworkLookup.pickup_names[id] == 'doom_rocket')
            assert(#mod.loaded_files == 0)
        """)

    def test_only_the_warlock_behavior_tree_is_renamed(self):
        bootstrap = BOOTSTRAP.read_text(encoding="utf-8-sig")
        self.assertNotRegex(bootstrap, r"pairs\(\s*BreedBehaviors\s*\)")
        lines = re.findall(r"(?m)^BreedBehaviors\.skaven_doomrocket.*$", bootstrap)
        self.assertEqual(len(lines), 2)
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute("""
            BreedBehaviors = {
                skaven_doomrocket = { 'BTSelector', name = 'skaven_doomrocket' },
                other_mod_breed = { 'BTSelector', name = 'other_mod_breed' },
                skaven_clan_rat = { 'BTSelector_skaven_clan_rat', name = 'skaven_clan_rat_GENERATED' },
            }
        """ + "\n".join(lines) + """
            assert(BreedBehaviors.skaven_doomrocket[1] == 'BTSelector_skaven_doomrocket')
            assert(BreedBehaviors.skaven_doomrocket.name == 'skaven_doomrocket_GENERATED')
            assert(BreedBehaviors.other_mod_breed[1] == 'BTSelector')
            assert(BreedBehaviors.other_mod_breed.name == 'other_mod_breed')
            assert(BreedBehaviors.skaven_clan_rat[1] == 'BTSelector_skaven_clan_rat')
        """)


if __name__ == "__main__":
    unittest.main(verbosity=2)
