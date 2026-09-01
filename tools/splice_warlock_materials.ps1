# Splice game-compiled child materials over the compiled
# child_materials/warlock_bombardier/wb_*_child resources in the built
# doomrocket bundle. MUST run after every `VMBLauncher build` and before
# deploy/upload.
#
# Why: the mod SDK cannot compile the character-skinning shader permutation -
# SDK-authored character materials always render the skin rigid and dark
# (vt2-pusfume issue #6, NATIVE_CHARACTER_MILESTONE.md). The proven fix is
# replacing each compiled child-material payload with the game's own compiled
# child (a slim binding table: parent shader hash + texture ids + variables),
# patched to reference this mod's texture resources.
#
# CRITICAL LAYOUT RULE (v0.1.16 boot-crash lesson): spliced children must NOT
# live in the boot-flushed main package. They ride in
# resource_packages/doomrocket/warlock_child.package, which is absent from
# doomrocket.mod's packages list and is loaded at runtime via
# mod:load_package AFTER the exact native donor packages are resident. The five
# materials/warlock_bombardier/wb_* boot materials stay SDK-compiled; the
# runtime swaps each slot to the child via Unit.set_material (hooks.lua).
#
# Donors (source-lineage verified against Crunch's Blender file):
#   armor/backpack <- dark-pact Ratling mtr_outfit 0488..., 768 B
#   skin            <- Stormvermin mtr_skin_climate_darken 2CC5..., 496 B
#   fur             <- Stormvermin mtr_fur_1bit_climate_burn EB66..., 416 B
#   whiskers        <- Stormvermin mtr_wiskers 3EB0..., 128 B
#
# Donor payloads derive from Fatshark game data: they are built under .build\
# and must never be committed.

param(
    [string]$GameBundleDir = "C:\Program Files (x86)\Steam\steamapps\common\Warhammer Vermintide 2\bundle",
    [string]$UnpackerExe = "C:\Tools\vt2_bundle_unpacker\target\release\unpacker.exe",
    [string]$UnpackerDict = "C:\Users\danjo\source\repos\vt2_bundle_unpacker\dictionary.csv",
    [switch]$UseVerifiedCache,
    [switch]$PayloadOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$bundleRoot = Join-Path $repoRoot "bundleV2"
$buildDir = Join-Path $repoRoot ".build\splice"
$makeTool = Join-Path $PSScriptRoot "make_spliced_child.py"
$spliceTool = Join-Path $PSScriptRoot "splice_bundle_resource.py"

New-Item -ItemType Directory -Force $buildDir | Out-Null

function Invoke-Py {
    param([string[]]$Arguments)
    & py -3 @Arguments 2>&1 | ForEach-Object { "  $_" }
    if ($LASTEXITCODE -ne 0) { throw "python tool failed: $($Arguments -join ' ')" }
}

function Assert-Sha256 {
    param([string]$Path, [string]$Expected)
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($actual -ne $Expected) {
        throw "donor hash mismatch: $Path -> $actual (expected $Expected)"
    }
}

# --- 1. Extract donor payloads from the installed game ---------------------

$donors = @(
    @{
        Key = "ratling"
        Bundle = "64f9019d56c8ce61"
        Includes = @("*0488D08E3CE5CBC3*")
        Files = @(
            @{ Name = "0488D08E3CE5CBC3.material"; Sha256 = "0D1DA98E59642E000E954A3438A28EDAC63982F1526937DE6A3893C6F0F144EC" }
        )
    },
    @{
        Key = "stormvermin"
        Bundle = "c43c291e4cc55d96"
        Includes = @("*2CC5FCB51388A255*", "*EB663E2D6E5EB732*", "*3EB079055472D4C3*")
        Files = @(
            @{ Name = "2CC5FCB51388A255.material"; Sha256 = "15BDECC1897BD62E2EBA055B38388840A95FCA3395CFE9E25A442817ECF16295" },
            @{ Name = "EB663E2D6E5EB732.material"; Sha256 = "64E8E88C1D17A54C2A774B3F1FF090B994CAF6620BD8E5C0E857C6D84C3270D2" },
            @{ Name = "3EB079055472D4C3.material"; Sha256 = "680284D028524BB224667DD4FF14013CF3C52C66CA62CE83E6C392C6CE47571A" }
        )
    }
)
foreach ($donor in $donors) {
    $dir = Join-Path $buildDir $donor.Key
    New-Item -ItemType Directory -Force $dir | Out-Null

    if (-not $UseVerifiedCache) {
        $bundlePath = Join-Path $GameBundleDir $donor.Bundle
        if (-not (Test-Path -LiteralPath $bundlePath)) {
            throw "native donor bundle is unavailable: $bundlePath. Restore the game data or rerun with -UseVerifiedCache only when the previously extracted donor files remain hash-valid."
        }

        $extractArgs = @("--dict", $UnpackerDict, "extract", $bundlePath, $dir, "--flatten")
        foreach ($include in $donor.Includes) {
            $extractArgs += @("--include", $include)
        }
        & $UnpackerExe @extractArgs 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "donor extraction command failed: $($donor.Key)"
        }
    }

    foreach ($file in $donor.Files) {
        $path = Join-Path $dir $file.Name
        if (-not (Test-Path -LiteralPath $path)) {
            throw "donor extraction failed: $($donor.Key) -> $($file.Name)"
        }
        Assert-Sha256 $path $file.Sha256
    }
    $source = if ($UseVerifiedCache) { "cache" } else { "installed game" }
    Write-Host "[splice] hash-verified donor $($donor.Key) from $source"
}
$ratlingPayload = Join-Path $buildDir "ratling\0488D08E3CE5CBC3.material"
$skinPayload = Join-Path $buildDir "stormvermin\2CC5FCB51388A255.material"
$furPayload = Join-Path $buildDir "stormvermin\EB663E2D6E5EB732.material"
$whiskersPayload = Join-Path $buildDir "stormvermin\3EB079055472D4C3.material"

# --- 2. Build patched payloads ---------------------------------------------
# Texture ids = murmur64 of extensionless resource paths.
# Verified Ratling 0488 channels:
#   texture_map_02af90f8 = base color
#   texture_map_8bf37d8e = tangent normal + roughness in alpha
#   texture_map_27b67fd2 = packed metallic/AO/feature/emission mask
# Variable C985395A is the emissive color multiplied by packed-map alpha.
#
# Crunch's source graph uses BC directly, NR.rgb directly with NR.a as
# roughness, and MASE_Fix.rgb as its final mask response. The adapter builder
# restores original MASE.a because that channel is the localized emission mask
# from which the separate E image was authored. Never bind the E RGB image into
# texture_map_27b67fd2: v0.1.50 did that and turned the entire backpack into an
# overbright mask while discarding metallic/AO data.

$armorAndBackpack = @(
    @{ Name = "wb_armor";    Df = "300FD46C61FB7091"; Nm = "DD7D6050A52FBF6D"; Ma = "D6D9CA1DA53AB7F3"; EmVar = "0,0,0" },
    @{ Name = "wb_backpack"; Df = "C4D517C71806AE3B"; Nm = "38DFFF0C6905532F"; Ma = "D5CECA5B225DE243"; EmVar = "0.61224258,1.32689383,0.24368675" }
)
foreach ($mat in $armorAndBackpack) {
    Write-Host "[splice] payload $($mat.Name)_child (Ratling 0488 packed-mask adapter)"
    Invoke-Py @($makeTool,
        "--extracted", $ratlingPayload,
        "--resource", "child_materials/warlock_bombardier/$($mat.Name)_child",
        "--expect-size", "768", "--expect-parent", "3D25339231384C80",
        "--map", "C554581405CC782C=$($mat.Df)",
        "--map", "6F873A2AA7CA611C=$($mat.Nm)",
        "--map", "8ABCC048427DAE38=$($mat.Ma)",
        "--set-variable", "C985395A=$($mat.EmVar)",
        "--expect-texture-count", "7",
        "--expect-texture", "6A35771D=0B35F2C32178BB63",
        "--expect-texture", "1E706DD3=19ADB9C889F644A0",
        "--expect-texture", "E25C59E9=2E82F037A3245005",
        "--expect-texture", "EEE29B95=2E82F037A3245005",
        "--expect-texture", "texture_map_02af90f8=$($mat.Df)",
        "--expect-texture", "texture_map_27b67fd2=$($mat.Ma)",
        "--expect-texture", "texture_map_8bf37d8e=$($mat.Nm)",
        "--out", (Join-Path $buildDir "$($mat.Name)_child.payload"))
}

Write-Host "[splice] payload wb_skin_child (exact source Stormvermin skin)"
Invoke-Py @($makeTool,
    "--extracted", $skinPayload,
    "--resource", "child_materials/warlock_bombardier/wb_skin_child",
    "--expect-size", "496", "--expect-parent", "EE15D2DA0DB8191E",
    "--map", "ED67ABE0A2542484=ED67ABE0A2542484",
    "--expect-texture-count", "6",
    "--expect-texture", "6A35771D=0B35F2C32178BB63",
    "--expect-texture", "BB4A8D2F=328E22775ECE4D7C",
    "--expect-texture", "1E706DD3=19ADB9C889F644A0",
    "--expect-texture", "040408FA=4B7F05AED3F40BDF",
    "--expect-texture", "62E7F461=A706B01BC822A417",
    "--expect-texture", "F17ED3B3=ED67ABE0A2542484",
    "--out", (Join-Path $buildDir "wb_skin_child.payload"))
Assert-Sha256 (Join-Path $buildDir "wb_skin_child.payload") "15BDECC1897BD62E2EBA055B38388840A95FCA3395CFE9E25A442817ECF16295"

Write-Host "[splice] payload wb_fur_child (exact source Stormvermin fur)"
Invoke-Py @($makeTool,
    "--extracted", $furPayload,
    "--resource", "child_materials/warlock_bombardier/wb_fur_child",
    "--expect-size", "416", "--expect-parent", "3BC475F93930640D",
    "--map", "1916CFCA6ED85BFD=1916CFCA6ED85BFD",
    "--expect-texture-count", "5",
    "--expect-texture", "5940AA57=328E22775ECE4D7C",
    "--expect-texture", "1E706DD3=19ADB9C889F644A0",
    "--expect-texture", "374548C2=4E1893E178945A92",
    "--expect-texture", "50736EB4=1916CFCA6ED85BFD",
    "--expect-texture", "0526F37D=E7AC0D635A39E926",
    "--out", (Join-Path $buildDir "wb_fur_child.payload"))
Assert-Sha256 (Join-Path $buildDir "wb_fur_child.payload") "64E8E88C1D17A54C2A774B3F1FF090B994CAF6620BD8E5C0E857C6D84C3270D2"

Write-Host "[splice] payload wb_whiskers_child (exact source Stormvermin whiskers)"
Invoke-Py @($makeTool,
    "--extracted", $whiskersPayload,
    "--resource", "child_materials/warlock_bombardier/wb_whiskers_child",
    "--expect-size", "128", "--expect-parent", "64058AD3567FB490",
    "--map", "3E851D59331DC868=3E851D59331DC868",
    "--expect-texture-count", "3",
    "--expect-texture", "68F2A5BA=A3854CB4540799DF",
    "--expect-texture", "CDAA7E64=3E851D59331DC868",
    "--expect-texture", "552EAA73=FE1EAB79ADD8215B",
    "--out", (Join-Path $buildDir "wb_whiskers_child.payload"))
Assert-Sha256 (Join-Path $buildDir "wb_whiskers_child.payload") "680284D028524BB224667DD4FF14013CF3C52C66CA62CE83E6C392C6CE47571A"

# --- 3. Splice each payload into exactly one built bundle ------------------

if ($PayloadOnly) {
    Write-Host "[splice] OK - 5 payloads verified; PayloadOnly left bundleV2 unchanged"
    return
}

$materials = @("wb_armor", "wb_backpack", "wb_skin", "wb_whiskers", "wb_fur")
foreach ($mat in $materials) {
    $payload = Join-Path $buildDir "${mat}_child.payload"
    $resource = "child_materials/warlock_bombardier/${mat}_child"
    $splicedInto = @()
    foreach ($bundleFile in (Get-ChildItem -LiteralPath $bundleRoot -Filter *.mod_bundle -File)) {
        # A miss is expected for every bundle except the package that owns this
        # resource. Windows PowerShell promotes a native program's stderr to an
        # ErrorRecord; with our global Stop preference that used to abort the
        # scan on the first ordinary miss. Probe under Continue, preserve the
        # native exit code, then restore fail-fast behavior for real work.
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & py -3 $spliceTool $bundleFile.FullName --type material --name $resource --payload $payload --dry-run *> $null
        $probeExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference

        if ($probeExitCode -eq 0) {
            Invoke-Py @($spliceTool, $bundleFile.FullName,
                "--type", "material", "--name", $resource, "--payload", $payload)
            $splicedInto += $bundleFile.Name
        }
    }
    if ($splicedInto.Count -ne 1) {
        throw "expected $resource in exactly 1 bundle, spliced into $($splicedInto.Count)"
    }
    Write-Host "[splice] $resource -> $($splicedInto[0])"
}

Write-Host "[splice] OK - 5 warlock child materials carry game bindings"
