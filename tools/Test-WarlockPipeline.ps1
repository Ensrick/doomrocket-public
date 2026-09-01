# Static validation for the Warlock Bombardier pipeline. Run after
# splice_warlock_materials.ps1, before deploy/upload. Exits non-zero on any
# violation of the invariants in docs/WARLOCK_MODEL_PIPELINE.md.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$failures = New-Object System.Collections.Generic.List[string]

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { $failures.Add($Message) }
}

# --- Release-channel invariants --------------------------------------------

$itemConfig = Get-Content (Join-Path $repoRoot "itemV2.cfg") -Raw
Assert-True ($itemConfig -match '(?m)^published_id\s*=\s*3771657344L;\s*$') `
    "public-alpha config must target Workshop item 3771657344"
Assert-True ($itemConfig -match '(?m)^visibility\s*=\s*"public";\s*$') `
    "public-alpha Workshop item must remain public"
Assert-True ($itemConfig -match '(?m)^title\s*=\s*"Warprocket Bombardier v0\.1\.55-alpha";\s*$') `
    "public title must be exactly Warprocket Bombardier v0.1.55-alpha"
Assert-True ($itemConfig -notmatch '(?im)^title\s*=.*(?:TEST|Currently Unstable|\-dev)') `
    "public title must not contain TEST, Currently Unstable, or -dev"

# --- Source layout invariants ----------------------------------------------

$unitDir = Join-Path $repoRoot "units\warlock_bombardier"
foreach ($required in @(
        "warlock_bombardier_3p.fbx", "warlock_bombardier_3p.unit",
        "warlock_bombardier_3p.bones", "warlock_bombardier_3p.dcc_asset",
        "warlock_bombardier_3p.state_machine")) {
    Assert-True (Test-Path (Join-Path $unitDir $required)) "missing unit source: $required"
}
# Clip coverage is checked dynamically below: every animation the state
# machine references must exist as .fbx + .animation.

$unitText = Get-Content (Join-Path $unitDir "warlock_bombardier_3p.unit") -Raw
Assert-True ($unitText -match 'animation_state_machine\s*=\s*"units/warlock_bombardier/warlock_bombardier_3p"') `
    ".unit must reference its OWN state machine (v0.1.24: vanilla SMs on a mod skeleton are an uncatchable AnimationBlender crash)"

$smText = Get-Content (Join-Path $unitDir "warlock_bombardier_3p.state_machine") -Raw
Assert-True ($smText -match 'bones\s*=\s*"units/warlock_bombardier/warlock_bombardier_3p"') `
    ".state_machine bones key must be the unit's own path"

# Texture/channel regressions are Python/Pillow based because byte-exact PNG
# comparisons are not practical in PowerShell. Keep this in the mandatory
# pre-deploy pipeline: it also rejects source rocket slots that would enter the
# engine before Lua with no material-manager mapping.
$textureRegression = Join-Path $PSScriptRoot 'tests\test_warlock_texture_pipeline.py'
& py -3 $textureRegression
if ($LASTEXITCODE -ne 0) {
    [void]$failures.Add("texture/material regression suite failed (exit $LASTEXITCODE)")
}
$weaponRegression = Join-Path $PSScriptRoot 'tests\test_warlock_weapon_pipeline.py'
& py -3 $weaponRegression
if ($LASTEXITCODE -ne 0) {
    [void]$failures.Add("weapon source/runtime regression suite failed (exit $LASTEXITCODE)")
}

# Every animation referenced by the state machine must exist as clip + recipe
# and every .animation recipe must target the unit's own skeleton.
foreach ($match in [regex]::Matches($smText, '"units/warlock_bombardier/anims/([^"]+)"')) {
    $clip = $match.Groups[1].Value
    Assert-True (Test-Path (Join-Path $unitDir "anims\$clip.fbx")) "state machine references missing clip FBX: $clip"
    Assert-True (Test-Path (Join-Path $unitDir "anims\$clip.animation")) "state machine references missing .animation recipe: $clip"
}
foreach ($recipe in (Get-ChildItem (Join-Path $unitDir "anims") -Filter *.animation)) {
    $recipeText = Get-Content $recipe.FullName -Raw
    Assert-True ($recipeText -match 'bones\s*=\s*"units/warlock_bombardier/warlock_bombardier_3p"') `
        "$($recipe.Name): bones key must be the unit's own path"
}

# --- Ragdoll invariants (v0.1.44) -------------------------------------------
# v0.1.40-43 proved the custom PhysX scene can be activated internally by the
# outfit state machine before Lua can reassert kinematic mode. It must not be
# compiled at all. The visible outfit follows the hidden vanilla owner's
# authored death/ragdoll through the pre-event bone bridge.
$physxPath = Join-Path $unitDir "warlock_bombardier_3p.physx"
Assert-True (-not (Test-Path $physxPath)) `
    "custom .physx must stay absent (v0.1.40-43 world-physics explosion class)"
Assert-True ($smText -notmatch '(?m)^ragdolls\s*=') `
    ".state_machine must not declare a custom ragdolls block"
Assert-True ($smText -notmatch 'state_type\s*=\s*"ragdoll"') `
    ".state_machine must not contain a custom ragdoll state"

# --- Package layout invariants (v0.1.16 boot-crash class) -------------------

$modFile = Get-Content (Join-Path $repoRoot "doomrocket.mod") -Raw
Assert-True ($modFile -notmatch 'warlock_child') `
    "doomrocket.mod must NOT boot-load the child package (spliced children crash PatchedResourcePackage::flush)"

$mainPackage = Get-Content (Join-Path $repoRoot "resource_packages\doomrocket\doomrocket.package") -Raw
Assert-True ($mainPackage -notmatch 'child_materials') `
    "main package must NOT list child_materials (boot-crash class)"

$childPackage = Join-Path $repoRoot "resource_packages\doomrocket\warlock_child.package"
Assert-True (Test-Path $childPackage) "missing warlock_child.package"
$childMaterials = @("wb_armor_child", "wb_backpack_child", "wb_skin_child", "wb_fur_child", "wb_whiskers_child")
if (Test-Path $childPackage) {
    $childText = Get-Content $childPackage -Raw
    foreach ($name in $childMaterials) {
        Assert-True ($childText -match [regex]::Escape("child_materials/warlock_bombardier/$name")) `
            "warlock_child.package missing $name"
        Assert-True (Test-Path (Join-Path $repoRoot "child_materials\warlock_bombardier\$name.material")) `
            "missing child material source: $name.material"
    }
}

# --- Runtime wiring invariants ---------------------------------------------

$hooks = Get-Content (Join-Path $repoRoot "scripts\mods\doomrocket\utils\hooks.lua") -Raw
Assert-True ($hooks -notmatch '(?m)^\s*(?:local\s+swapped\s*=\s*)?(?:pcall\()?\s*(?:Unit\.)?set_animation_state_machine\(outfit_unit') `
    "hooks.lua must not point the outfit at a foreign state machine (v0.1.24 AnimationBlender crash)"
foreach ($call in @(
        'Unit\.set_animation_bone_mode\(outfit_unit,\s*"transform"\)',
        'Unit\.set_bones_lod\(outfit_unit,\s*0\)',
        'mod\._apply_warlock_child_materials\(outfit_unit\)')) {
    Assert-True ($hooks -match $call) "hooks.lua warlock branch missing required call: $call"
}
Assert-True ($hooks -match 'Application\.can_get\("material",\s*material_path\)') `
    "runtime material swap must verify each spliced child material is resident"
Assert-True ($hooks -match 'Application\.can_get\("texture",\s*texture_path\)') `
    "runtime material diagnostics must verify custom texture residency"

# Historical death-handoff implementations repeatedly passed brittle positive
# regexes while failing in Stingray. The mutation-tested policy suite owns all
# ragdoll mechanism and telemetry assertions; this pipeline retains material,
# package, animation, and built-asset checks around it.
$ragdollRegression = Join-Path $PSScriptRoot 'tests\Test-WarlockRagdollRegressions.ps1'
try {
    & $ragdollRegression -RepoRoot $repoRoot
} catch {
    [void]$failures.Add("ragdoll regression suite failed: $($_.Exception.Message)")
}

$deathReactions = Get-Content (Join-Path $repoRoot "scripts\mods\doomrocket\extensions\death_reactions.lua") -Raw
$breedSource = Get-Content (Join-Path $repoRoot "scripts\mods\doomrocket\breeds\skaven_doomrocket.lua") -Raw
Assert-True ($breedSource -match 'Breeds\.skaven_doomrocket\s*=\s*table\.clone\(Breeds\.skaven_ratling_gunner\)') `
    "doomrocket breed must retain the native Ratling carrier whose actors drive the visual handoff"
Assert-True ($breedSource -notmatch 'base_unit\s*=') `
    "doomrocket breed must not override the native Ratling carrier unit"
Assert-True ([regex]::Matches($deathReactions, 'mod\._prepare_warlock_death\(').Count -eq 2) `
    "doomrocket death reaction must prepare the vanilla carrier for both unit and husk"
foreach ($lane in @('unit', 'husk')) {
    Assert-True ($deathReactions -match
        "(?ms)pre_start = function \([^)]+\)\s*(?:--[^\r\n]*\r?\n\s*)*mod\._prepare_warlock_death\(unit, `"$lane`"\)\s*ai_default_${lane}_pre_start") `
        "$lane carrier handoff must be calibrated in pre_start before the delayed death event"
    Assert-True ($deathReactions -match
        "(?s)start = function \([^)]+\)\s*local warlock_pose_driver = mod\._take_warlock_death_driver\(unit\)\s*local data, result = ai_default_${lane}_start") `
        "$lane start must consume the driver calibrated in pre_start"
}
Assert-True ($deathReactions -notmatch 'mod\._(?:schedule|update)_warlock_ragdoll') `
    "delayed custom-ragdoll handoff must not return"
# Scope animation-state checks to the Warlock branch (the plague monk branch
# also disables its outfit ASM). The Warlock must retain its own working ASM.
$warlockBranchText = [regex]::Match($hooks, '(?s)elseif outfit_unit_name == "units/warlock_bombardier/warlock_bombardier_3p" then(.*?)(?:\r?\n\s*elseif|\r?\n\s*end\s*\r?\n\s*end)').Groups[1].Value
Assert-True ($warlockBranchText.Length -gt 0) "could not extract the warlock branch from hooks.lua"
$hasEnable = $warlockBranchText -match 'Unit\.enable_animation_state_machine\(outfit_unit\)'
Assert-True ($hasEnable -and $warlockBranchText -notmatch 'Unit\.disable_animation_state_machine\(outfit_unit\)') `
    "warlock branch must keep its own animation state machine enabled"

# Every bridge target must exist on the shipped skeleton (missing target = an
# uncatchable Unit.node fatal at vanilla link time). The WARLOCK_UNIT_BONES
# whitelist in the inventory lua must exactly match the current .bones list.
$bonesText = Get-Content (Join-Path $unitDir "warlock_bombardier_3p.bones") -Raw
$bonesList = [regex]::Matches($bonesText, '"([^"]+)"') | ForEach-Object { $_.Groups[1].Value }
$invText = Get-Content (Join-Path $repoRoot "scripts\mods\doomrocket\breeds\skaven_doomrocket_inventory.lua") -Raw
$whitelistBlock = [regex]::Match($invText, '(?s)local WARLOCK_UNIT_BONES = \{(.*?)\}').Groups[1].Value
$whitelist = [regex]::Matches($whitelistBlock, '\["([^"]+)"\]') | ForEach-Object { $_.Groups[1].Value }
Assert-True ($whitelist.Count -eq $bonesList.Count) `
    "WARLOCK_UNIT_BONES count $($whitelist.Count) != .bones count $($bonesList.Count)"
$diff = Compare-Object $whitelist $bonesList
Assert-True (-not $diff) "WARLOCK_UNIT_BONES diverges from .bones: $(($diff | ForEach-Object InputObject) -join ', ')"
# Per-bone scene links fight the enabled outfit ASM and corrupt its hierarchy.
Assert-True ($invText -match 'bombadier_curiass\.attachment_node_linking = AttachmentNodeLinking\.doomrocket_warlock_root') `
    "enabled Warlock outfit ASM requires root-only attachment linking"

# v0.1.25 crash class: variable/constraint indices are only meaningful within
# one compiled state machine; forwarding a raw index to a unit on a different
# SM is an engine assert pcall cannot catch. Only name-based event mirroring
# (gated on Unit.has_animation_event) is safe.
Assert-True ($hooks -notmatch 'mod:hook\(Unit,\s*"animation_set_variable"') `
    "hooks.lua must not mirror animation_set_variable by raw index (v0.1.25 crash class)"
Assert-True ($hooks -notmatch 'mod:hook\(Unit,\s*"animation_set_constraint_target"') `
    "hooks.lua must not mirror animation_set_constraint_target by raw index (v0.1.25 crash class)"

# v0.1.27 crash class check moved below the driving-mode extraction: bridge
# mode (warlock branch disables its ASM) must not register for mirroring.

$doomrocketLua = Get-Content (Join-Path $repoRoot "scripts\mods\doomrocket\doomrocket.lua") -Raw
Assert-True ($doomrocketLua -match 'skaven_ratlinggunner/skin_1001/third_person/chr_third_person_mesh') `
    "doomrocket.lua must force-load the Ratling armor donor package"
Assert-True ($doomrocketLua -match 'resource_packages/breeds/skaven_storm_vermin') `
    "doomrocket.lua must force-load the native Stormvermin skin/fur/whisker package"
foreach ($lifecyclePattern in @(
        'on_game_state_changed[\s\S]*?status\s*==\s*"exit"[\s\S]*?state\s*==\s*"StateIngame"[\s\S]*?reset_warlock_runtime_state\(\)',
        'function\s+mod\.on_disabled\(\)[\s\S]*?reset_warlock_runtime_state\(\)',
        'function\s+mod\.on_unload\(\)[\s\S]*?reset_warlock_runtime_state\(\)')) {
    Assert-True ($doomrocketLua -match $lifecyclePattern) `
        "doomrocket.lua must reset persistent Warlock death drivers on every lifecycle exit"
}

# Slot names in the runtime swap table must exactly match the .unit materials block.
$slotNames = [regex]::Matches($unitText, '(?m)^\s*(\w+)\s*=\s*"materials/warlock_bombardier/') | ForEach-Object { $_.Groups[1].Value }
foreach ($slot in $slotNames) {
    Assert-True ($hooks -match "`"$slot`"\s*,\s*`"child_materials/warlock_bombardier/") `
        "hooks.lua WARLOCK_SLOT_MATERIALS missing slot '$slot' from the .unit materials block"
}
Assert-True ($slotNames.Count -eq 5) "expected 5 material slots in .unit, found $($slotNames.Count)"

# --- Built bundle invariants (only when bundles exist) ----------------------

$bundleRoot = Join-Path $repoRoot "bundleV2"
$childBundle = Join-Path $bundleRoot "f5283f9585ea8355.mod_bundle"
if (Test-Path $childBundle) {
    # Spliced payload sizes: 2x768 (Ratling armor family), 496/416/128
    # (exact Stormvermin skin/fur/whiskers).
    # The SDK-compiled child materials are ~22 KB sources -> 185/321 KB payloads,
    # so tiny record sizes prove the splice actually ran on this bundle.
    $spliceTool = Join-Path $PSScriptRoot "splice_bundle_resource.py"
    $expected = @{ "wb_armor_child" = 768; "wb_backpack_child" = 768; "wb_skin_child" = 496;
                   "wb_fur_child" = 416; "wb_whiskers_child" = 128 }
    foreach ($name in $expected.Keys) {
        # Dry-run output: "<bundle>: splicing (material, <hash>) <current> -> <new> bytes"
        $probe = & py -3 $spliceTool $childBundle --type material `
            --name "child_materials/warlock_bombardier/$name" `
            --payload $spliceTool --dry-run 2>&1 | Out-String
        Assert-True ($probe -match '\)\s+(\d+)\s+->\s+\d+\s+bytes' -and [int]$Matches[1] -eq $expected[$name]) `
            "child bundle: $name is not spliced to $($expected[$name]) B (probe said: $($probe.Trim() -replace '\s+', ' '))"
    }
} else {
    Write-Host "[test] bundleV2 child bundle absent - skipping built-bundle checks (source-only run)"
}

# --- Verdict ----------------------------------------------------------------

if ($failures.Count -gt 0) {
    foreach ($failure in $failures) { Write-Host "[test] FAIL: $failure" -ForegroundColor Red }
    throw "Test-WarlockPipeline: $($failures.Count) failure(s)"
}
Write-Host "[test] OK - warlock pipeline invariants hold"
