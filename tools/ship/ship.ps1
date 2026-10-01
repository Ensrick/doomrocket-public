# Standalone Warlock adapter for the copied Tweaker two-phase ship transaction.
# Shared helpers own claims, source/output receipts, the machine lease, the
# hidden launcher process, immutable publication snapshots and Workshop evidence.
[CmdletBinding()]
param(
    [ValidateSet('doomrocket')][string]$Mod = 'doomrocket',
    [switch]$BuildOnly,
    [switch]$AllowPublic,
    [switch]$PublicationOnly,
    [Parameter(Mandatory=$true)][string]$LauncherPath,
    [Parameter(Mandatory=$true)][string]$ConfigPath
)
$ErrorActionPreference = 'Stop'
if (-not $env:VT2_SHIP_SESSION_ID -and -not $env:CLAUDE_SESSION_ID -and -not $env:CODEX_THREAD_ID) {
    throw 'Standalone layout: set VT2_SHIP_SESSION_ID (or run under a Claude/Codex session id) before claim.ps1, BuildOnly and the ship. VMBLauncher derives the claim owner from the VMB project root, not from this repository path, so path-derived identities never match.'
}
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $PSScriptRoot 'repository-profile.ps1')
. (Join-Path $PSScriptRoot 'transaction-lease.ps1')
. (Join-Path $PSScriptRoot '../vmb-launcher-path.ps1')
. (Join-Path $PSScriptRoot 'publication-authorization.ps1')
. (Join-Path $PSScriptRoot 'publication-snapshot.ps1')
. (Join-Path $PSScriptRoot 'release-identity.ps1')
. (Join-Path $PSScriptRoot 'workshop-upload-evidence.ps1')
. (Join-Path $PSScriptRoot '../publish-release/release-mutation-lock.ps1')

function Assert-Native([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed: exit $LASTEXITCODE" }
}
function Invoke-Launcher([string[]]$Arguments) {
    $run = Invoke-VmbLauncherProcess -Lease $launcherLease -ArgumentList ($Arguments + @('--config', $privateConfig)) -WorkingDirectory $repoRoot -ReplayOutput
    if ($run.ExitCode -ne 0) { throw "VMBLauncher $($Arguments -join ' ') failed: exit $($run.ExitCode)" }
    return $run
}
function Assert-LiveAuthorization {
    $result = Get-LivePublicationAuthorization -Repo $profile.Repository -SourceCommit $sourceCommit
    if (-not $result.Ok) { throw $result.Message }
    return $result
}

$transaction = $null
$launcherLease = $null
$releaseMutex = $null
$privateConfig = $null
Push-Location $repoRoot
try {
    $profile = Get-WarlockRepositoryProfile -RepoRoot $repoRoot
    if ($profile.Channel -cne 'public') { throw 'This checkout publishes only the public-alpha repository and item.' }
    $displayName = 'Warlock Engineer'
    $lua = [IO.File]::ReadAllText((Join-Path $repoRoot 'scripts/mods/doomrocket/doomrocket.lua'))
    if ($lua -notmatch 'local\s+MOD_VERSION\s*=\s*"([^"]+)"') { throw 'Missing MOD_VERSION.' }
    $version = $matches[1]
    $expectedTitle = "$displayName v$version"
    if (-not $version.EndsWith($profile.Suffix)) { throw 'Version does not match the selected channel.' }
    $identity = Test-ReleaseIdentity -SourceVersion $version -ChangelogText ([IO.File]::ReadAllText((Join-Path $repoRoot 'CHANGELOG.md')))
    if (-not $identity.Ok) { throw $identity.Message }
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'claim.ps1') -Mod $Mod -RepoRoot $repoRoot -Verify -ExpectedVersion $version
    Assert-Native 'Claim verification'
    if (-not $BuildOnly -and (-not $AllowPublic -or -not $PublicationOnly)) {
        throw 'This publication-only run requires -AllowPublic -PublicationOnly; no local/remote deployment is attempted.'
    }
    $sourceCommit = (& git rev-parse HEAD).Trim()
    Assert-Native 'Read source commit'
    if (-not $BuildOnly) {
        if (@(& git status --porcelain --untracked-files=all).Count) { throw 'Final ship requires clean reviewed source.' }
        $authorization = Assert-LiveAuthorization
    }
    $settings = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $ConfigPath)) | ConvertFrom-Json
    $transaction = Enter-VmbMachineTransactionLease -Action $(if ($BuildOnly) {'build-only'} else {'ship'}) -Mod $Mod -ProjectRoot $settings.ProjectRoot -TimeoutMilliseconds 300000
    $launcherLease = Enter-VmbLauncherExecutableLease -LauncherPath $LauncherPath -RequireDirectPath
    $settings = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $ConfigPath)) | ConvertFrom-Json
    $selectedMod = Join-Path $settings.ProjectRoot $Mod
    & py -3 -c 'import pathlib,sys; assert pathlib.Path(sys.argv[1]).resolve() == pathlib.Path(sys.argv[2]).resolve()' $selectedMod $repoRoot
    Assert-Native 'Configured source identity'
    # Preserve existing VMB settings, but isolate every child behind one private file.
    $privateConfig = Join-Path ([IO.Path]::GetTempPath()) ("warlock-ship-$PID-" + [guid]::NewGuid().ToString('N') + '.json')
    [IO.File]::WriteAllText($privateConfig, ($settings | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
    $null = Assert-VmbLauncherPublicationCapability -LauncherExecutableLease $launcherLease -WorkingDirectory $repoRoot -RequireReceiptAuthority
    & py -3 tools/check_repository.py --channel $profile.Channel
    Assert-Native 'Repository preflight'
    & powershell -NoProfile -ExecutionPolicy Bypass -File tools/tests/Test-WarlockPublicationLayout.ps1
    Assert-Native 'Standalone publication layout and checkout-policy preflight'
    $inventoryEntry = Get-VtBuildReceiptInventoryEntry -RepoRoot $repoRoot -Mod $Mod
    $ignoreProblems = @(Get-VtBundleAuthorityIgnoreStateErrors -Mod $Mod -Authority ([string]$inventoryEntry.BundleAuthority) -GitIgnoreText ([IO.File]::ReadAllText((Join-Path $repoRoot '.gitignore'))))
    if ($ignoreProblems.Count) { throw "Bundle authority preflight failed: $($ignoreProblems -join '; ')" }
    $before = Get-VtBuildWorkingSourceMap -RepoRoot $repoRoot -Mod $Mod
    $repro = Test-VtBuildWorkingSourceReproducibility -SourceMap $before
    if (-not $repro.Ok) { throw ($repro.Problems -join '; ') }
    $build = Invoke-Launcher @('build', $Mod, '--clean')
    & powershell -NoProfile -ExecutionPolicy Bypass -File tools/splice_warlock_materials.ps1 -UseVerifiedCache
    Assert-Native 'Verified native material splice'
    & powershell -NoProfile -ExecutionPolicy Bypass -File tools/Test-WarlockPipeline.ps1
    Assert-Native 'Full Warlock pipeline'
    $normalization = Invoke-BuildOutputNormalization -RepoRoot $repoRoot -Mod $Mod
    $after = Get-VtBuildWorkingSourceMap -RepoRoot $repoRoot -Mod $Mod
    $comparison = Compare-VtBuildSourceMaps -Expected $before -Actual $after
    if (-not $comparison.Ok) { throw ($comparison.Problems -join '; ') }
    $output = Get-VtBuildWorkingOutputSet -RepoRoot $repoRoot -Mod $Mod -SourceMap $after
    $builderVersion = [string]$build.ExecutableProof.version
    if ($BuildOnly) {
        $receipt = New-VtBuildReceipt -Mod $Mod -SourceMap $after -OutputSet $output -BuilderVersion $builderVersion -NormalizationPolicy $normalization.Policy
        $path = Write-VtBuildReceipt -RepoRoot $repoRoot -Mod $Mod -Receipt $receipt
        Write-Host "BUILD-ONLY VERIFIED: $version; $path; no deployment or publication."
        return
    }

    # This independently proves the committed BuildOnly receipt against the
    # rebuilt, spliced payload, captures exact bytes, and rejects source drift.
    $snapshot = Get-VtPublicationSnapshot -RepoRoot $repoRoot -SourceCommit $sourceCommit -Mod $Mod -ExpectedBuilderVersion $builderVersion
    $authorization = Assert-LiveAuthorization
    $releaseMutex = Enter-VtGitHubReleaseMutationMutex
    $tag = "v$version"
    $artifactDir = Join-Path $repoRoot '.build/publication'
    [IO.Directory]::CreateDirectory($artifactDir) | Out-Null
    $zipPath = Join-Path $artifactDir "doomrocket-$version.zip"
    Add-Type -AssemblyName System.IO.Compression
    $zipStream = [IO.File]::Open($zipPath, [IO.FileMode]::Create)
    $zip = [IO.Compression.ZipArchive]::new($zipStream, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($file in $snapshot.BundleFiles) {
            $entry = $zip.CreateEntry([string]$file.Path)
            $entryStream = $entry.Open()
            try { $entryStream.Write([byte[]]$file.Bytes, 0, [int]$file.Length) } finally { $entryStream.Dispose() }
        }
    } finally { $zip.Dispose(); $zipStream.Dispose() }
    $notes = Join-Path $artifactDir 'release-notes.md'
    $releaseIdentity = "## v$version"
    $changelog = [IO.File]::ReadAllText((Join-Path $repoRoot 'CHANGELOG.md'))
    $releaseSection = [regex]::Match($changelog, '(?ms)^' + [regex]::Escape($releaseIdentity) + '[^\r\n]*\r?\n(.*?)(?=^## v|\z)')
    if (-not $releaseSection.Success) { throw 'Missing version-bound release notes.' }
    [IO.File]::WriteAllText($notes, "$displayName $tag. Built from $sourceCommit through the standalone adaptation of the Tweaker ship transaction. Native material splice, package checks and hosted QA passed. Workshop item: $($profile.Id). Publication only; no game installation or local deployment is claimed.`n`n$($releaseSection.Groups[1].Value.Trim())`n")
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $existingJson = & gh release view $tag --repo $profile.Repository --json tagName,isDraft,targetCommitish 2>$null
        $releaseViewExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($releaseViewExit -eq 0) {
        $remoteTag = & gh api "repos/$($profile.Repository)/git/ref/tags/$tag" --jq '.object.sha'
        Assert-Native 'Read existing release tag'
        if ($remoteTag.Trim() -cne $sourceCommit) { throw 'Existing release tag points at another commit; it will not be moved.' }
    } else {
        & gh release create $tag --repo $profile.Repository --target $sourceCommit --prerelease --draft --title "$displayName $tag" --notes-file $notes
        Assert-Native 'Create source-bound GitHub prerelease draft'
    }
    & gh release upload $tag $zipPath --repo $profile.Repository --clobber
    Assert-Native 'Upload exact package archive'
    $downloadDir = Join-Path $artifactDir ('download-' + [guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($downloadDir) | Out-Null
    & gh release download $tag --repo $profile.Repository --pattern ([IO.Path]::GetFileName($zipPath)) --dir $downloadDir
    Assert-Native 'Download hosted package archive for verification'
    $downloadedZip = Join-Path $downloadDir ([IO.Path]::GetFileName($zipPath))
    if ((Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash -cne (Get-FileHash -LiteralPath $downloadedZip -Algorithm SHA256).Hash) { throw 'Hosted package archive differs from the immutable publication snapshot.' }
    $authorization = Assert-LiveAuthorization
    $assetName = Get-WorkshopPublicationReceiptAssetName -Mod $Mod
    $receiptPath = Join-Path $artifactDir $assetName
    $receipt = New-WorkshopPublicationReceipt -RepoRoot $repoRoot -Repository $profile.Repository -ReleaseTag $tag -ReceiptAssetName $assetName -Mod $Mod -Version $version -Owner (Get-CanonicalShipOwnerId -RepoRoot $repoRoot) -SourceCommit $sourceCommit -PublicationSnapshot $snapshot -AuthorizationEvidence $authorization.Evidence
    [IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
    & gh release upload $tag $receiptPath --repo $profile.Repository --clobber
    Assert-Native 'Host exact publication receipt'
    & gh release edit $tag --repo $profile.Repository --draft=false --prerelease
    Assert-Native 'Publish source-bound GitHub prerelease'
    $null = Assert-LiveAuthorization
    $logPath = Join-Path $settings.SteamRoot 'logs/workshop_log.txt'
    $evidence = Invoke-VtWorkshopUploadEvidence -Path $logPath -PublishedId $profile.Id -UploadAction {
        $null = Invoke-Launcher @('upload', $Mod, '--allow-public', '--publication-receipt', $receiptPath)
    }
    $total = [long](($snapshot.BundleFiles | Measure-Object -Property Length -Sum).Sum)
    for ($attempt = 0; $attempt -lt 6; $attempt++) {
        $response = Invoke-RestMethod -Method Post -Uri 'https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/' -Body @{itemcount='1';'publishedfileids[0]'=$profile.Id}
        $detail = $response.response.publishedfiledetails[0]
        if ($detail.result -eq 1 -and $detail.title -ceq $expectedTitle -and $detail.visibility -eq 0 -and [long]$detail.file_size -eq $total -and ($evidence.Status -ne 'UPLOADED' -or [string]$detail.hcontent_file -ceq [string]$evidence.ManifestId)) { break }
        if ($attempt -lt 5) { Start-Sleep -Seconds 5 }
    }
    if ($detail.result -ne 1 -or $detail.title -cne $expectedTitle -or $detail.visibility -ne 0 -or [long]$detail.file_size -ne $total) { throw 'Steam metadata differs from the published public-alpha artifact.' }
    if ($evidence.Status -eq 'UPLOADED' -and [string]$detail.hcontent_file -cne [string]$evidence.ManifestId) { throw 'Steam content handle differs from the fresh upload transaction.' }
    $record = [ordered]@{Version=$version;SourceCommit=$sourceCommit;Workshop=$detail;UploadEvidence=$evidence;Deployment='SKIPPED: publication-only, game not installed';VerifiedUtc=[datetime]::UtcNow.ToString('o')}
    [IO.File]::WriteAllText((Join-Path $artifactDir 'verified-publication.json'), ($record | ConvertTo-Json -Depth 20))
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'claim.ps1') -Mod $Mod -RepoRoot $repoRoot -Release
    Assert-Native 'Release completed version claim'
    Write-Host "VERIFIED WORKSHOP: $tag; item $($profile.Id); handle $($detail.hcontent_file); $total bytes. No deployment."
} finally {
    if ($releaseMutex) { $releaseMutex.ReleaseMutex(); $releaseMutex.Dispose() }
    if ($privateConfig -and (Test-Path -LiteralPath $privateConfig)) { Remove-Item -LiteralPath $privateConfig -Force }
    if ($launcherLease) { Exit-VmbLauncherExecutableLease -Lease $launcherLease }
    if ($transaction) { Exit-VmbMachineTransactionLease -Lease $transaction }
    Pop-Location
}
