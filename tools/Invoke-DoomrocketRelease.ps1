[CmdletBinding()]
param(
    [switch]$PreflightOnly,
    [switch]$Deploy,
    [switch]$Upload,
    [string]$VmbExe = 'C:\Users\danjo\source\repos\vmb-launcher-baseline-056-20260726\bin\Release\net9.0-windows\win-x64\publish\VMBLauncher.exe',
    [string]$ConfigPath = 'C:\Users\danjo\source\repos\_doomrocket_public_vmb\vmblauncher.settings.json'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path $PSScriptRoot -Parent
$expectedBranch = 'public-alpha'
$expectedWorkshopId = '3771657344'
$expectedTitlePrefix = 'Warprocket Bombardier v'

function Assert-ExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

Push-Location $repoRoot
try {
    $branch = (& git branch --show-current).Trim()
    Assert-ExitCode 'Read git branch'
    if ($branch -ne $expectedBranch) {
        throw "Wrong release branch '$branch'; expected '$expectedBranch'."
    }

    $dirty = @(& git status --porcelain --untracked-files=all)
    Assert-ExitCode 'Read git status'
    if ($dirty.Count -gt 0) {
        throw "Release source must be committed and clean:`n$($dirty -join [Environment]::NewLine)"
    }

    & py -3 tools\check_repository.py --channel public
    Assert-ExitCode 'Public repository preflight'

    $itemConfig = Get-Content itemV2.cfg -Raw
    $titleMatch = [regex]::Match($itemConfig, '(?m)^title\s*=\s*"([^"]+)";\s*$')
    if (-not $titleMatch.Success -or -not $titleMatch.Groups[1].Value.StartsWith($expectedTitlePrefix) -or
        $titleMatch.Groups[1].Value -match 'TEST|Currently Unstable|-dev') {
        throw 'Public-alpha Workshop title guard failed.'
    }
    $expectedTitle = $titleMatch.Groups[1].Value

    if ($PreflightOnly) {
        Write-Output "[release] preflight OK - $expectedTitle -> Workshop $expectedWorkshopId"
        return
    }

    foreach ($path in ($VmbExe, $ConfigPath)) {
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Required release dependency is missing: $path"
        }
    }

    & $VmbExe build doomrocket --clean --config $ConfigPath
    Assert-ExitCode 'Clean VMB build'

    & powershell -NoProfile -ExecutionPolicy Bypass -File tools\splice_warlock_materials.ps1 -UseVerifiedCache
    Assert-ExitCode 'Verified material splice'

    & powershell -NoProfile -ExecutionPolicy Bypass -File tools\Test-WarlockPipeline.ps1
    Assert-ExitCode 'Full Warlock pipeline'

    if ($Deploy) {
        & $VmbExe deploy doomrocket --no-remote --config $ConfigPath
        Assert-ExitCode 'Local deploy'
    }

    if (-not $Upload) {
        Write-Output '[release] package validated; no upload requested. Re-run with -Upload to publish the public alpha.'
        return
    }

    & $VmbExe upload doomrocket --allow-public --config $ConfigPath
    Assert-ExitCode 'Public-alpha Workshop upload'

    $response = Invoke-RestMethod -Method Post `
        -Uri 'https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/' `
        -Body @{ itemcount = '1'; 'publishedfileids[0]' = $expectedWorkshopId }
    $detail = $response.response.publishedfiledetails[0]
    $localBytes = [int64]((Get-ChildItem bundleV2 -File | Measure-Object -Property Length -Sum).Sum)
    if ($detail.title -ne $expectedTitle -or $detail.visibility -ne 0 -or
        [int64]$detail.file_size -ne $localBytes) {
        throw "Steam verification failed: title='$($detail.title)', visibility=$($detail.visibility), remoteBytes=$($detail.file_size), localBytes=$localBytes"
    }
    if ($detail.description -notmatch '1369573612' -or
        $detail.description -notmatch 'Modded Realm' -or
        $detail.description -notmatch 'issues/new/choose') {
        throw 'Steam verification failed: VMF, Modded Realm, or issue-chooser guidance is missing.'
    }

    Write-Output "[release] VERIFIED - Workshop $expectedWorkshopId, content handle $($detail.hcontent_file), $localBytes bytes"
}
finally {
    Pop-Location
}
