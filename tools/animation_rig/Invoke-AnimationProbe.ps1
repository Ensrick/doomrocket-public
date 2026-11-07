[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$AnimationFbx,
    [Parameter(Mandatory = $true)][string]$BodyFbx,
    [string]$ExportManifest,
    [string]$SkinProfile,
    [string]$AdaptedClips,
    [switch]$OriginalLegacyClips,
    [string]$IntegrationOverlay,
    [string]$RuntimePoses,
    [switch]$MidpointMotion,
    [string]$ProbeRoot = '.build\animation_sdk_probe',
    [string]$SdkRoot = 'C:\Program Files (x86)\Steam\steamapps\common\Vermintide 2 SDK',
    [string]$PythonExecutable = 'py'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
function Resolve-RepoPath([string]$Path) {
    if ([IO.Path]::IsPathRooted($Path)) { return [IO.Path]::GetFullPath($Path) }
    return [IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}
$probe = Resolve-RepoPath $ProbeRoot
$animation = Resolve-RepoPath $AnimationFbx
$body = Resolve-RepoPath $BodyFbx
if (-not $ExportManifest) { $ExportManifest = [IO.Path]::ChangeExtension($animation, '.export.json') }
$manifest = Resolve-RepoPath $ExportManifest
$pythonPrefix = @()
if ([IO.Path]::GetFileNameWithoutExtension($PythonExecutable) -eq 'py') { $pythonPrefix = @('-3') }
$guard = Join-Path $repoRoot 'tools\hose_lab\compile_paths.py'
$verifier = Join-Path $PSScriptRoot 'verify_compiled_animation.py'
$compiler = Join-Path $SdkRoot 'bin\stingray_win64_dev_x64.exe'
function Assert-ProbePaths {
    & $PythonExecutable @pythonPrefix $guard --repo-root $repoRoot --probe-root $probe
    if ($LASTEXITCODE -ne 0) { throw 'Probe paths rejected; no writer may start.' }
}
function Assert-CompilerAvailable {
    if (Get-Process -Name 'stingray_win64_dev_x64' -ErrorAction SilentlyContinue) {
        throw 'SDK compiler is already running. Coordinate with its owner before another compile.'
    }
}
Assert-ProbePaths
Assert-CompilerAvailable
foreach ($required in @($animation, $body, $manifest, $compiler)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing input: $required" }
}
$stageArgs = @('--stage', '--probe-root', $probe, '--animation-fbx', $animation, '--body-fbx', $body, '--manifest', $manifest, '--sdk-executable', $compiler)
if ($SkinProfile) { $stageArgs += @('--skin-profile', (Resolve-RepoPath $SkinProfile)) }
if ($AdaptedClips) { $stageArgs += @('--adapted-clips', (Resolve-RepoPath $AdaptedClips)) }
if ($OriginalLegacyClips) { $stageArgs += '--original-legacy-clips' }
if ($IntegrationOverlay) { $stageArgs += @('--integration-overlay', (Resolve-RepoPath $IntegrationOverlay)) }
& $PythonExecutable @pythonPrefix $verifier @stageArgs
if ($LASTEXITCODE -ne 0) { throw 'Animator input staging failed.' }
$packageClosure = Join-Path $PSScriptRoot 'package_closure.py'
$checkPackageClosure = $false
if ($IntegrationOverlay) {
    $registration = Get-Content -LiteralPath (Join-Path $probe 'integration_receipt.json') -Raw | ConvertFrom-Json
    $runtimeManifest = Get-Content -LiteralPath (Join-Path $probe 'integration_manifest.json') -Raw | ConvertFrom-Json
    $profile = $runtimeManifest.profiles.($registration.profile_id)
    if ($registration.cross_owner_transition_policy -cne $profile.cross_owner_transition_policy) {
        throw 'Integration receipt presentation policy differs from trusted manifest.'
    }
    if ($profile.cross_owner_transition_policy -cnotin @('cut', 'snapshot-blend-v1')) {
        throw 'Unsupported integration presentation policy.'
    }
    $checkPackageClosure = $profile.cross_owner_transition_policy -ceq 'snapshot-blend-v1'
    if ($checkPackageClosure) {
        Assert-ProbePaths
        & $PythonExecutable @pythonPrefix $packageClosure --stage --probe-root $probe --integration-overlay (Resolve-RepoPath $IntegrationOverlay)
        if ($LASTEXITCODE -ne 0) { throw 'Presentation package closure staging failed.' }
    }
}
foreach ($lane in @('candidate', 'reference')) {
    Assert-ProbePaths
    Assert-CompilerAvailable
    $laneRoot = Join-Path $probe $lane
    $source = Join-Path $laneRoot 'source'
    $data = Join-Path $laneRoot 'data'
    $bundles = Join-Path $laneRoot 'bundle'
    $stdout = Join-Path $laneRoot 'compiler.stdout.log'
    $stderr = Join-Path $laneRoot 'compiler.stderr.log'
    $compilerArgs = @('--compile', '--compile-for', 'win32', '--source-dir', ('"' + $source + '"'),
        '--data-dir', ('"' + $data + '"'), '--bundle-dir', ('"' + $bundles + '"'),
        '--map-source-dir', 'core', ('"' + $SdkRoot + '"'))
    $process = Start-Process -FilePath $compiler -ArgumentList $compilerArgs -WorkingDirectory $laneRoot `
        -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Get-Content -LiteralPath $stdout -Tail 8
    Get-Content -LiteralPath $stderr
    if ($process.ExitCode -ne 0 -or (Get-Content -LiteralPath $stdout -Raw) -notmatch 'Compile resulted in success!') {
        throw "Isolated $lane SDK compile failed; inspect $stdout and $stderr."
    }
}
Assert-ProbePaths
$auditArgs = @('--probe-root', $probe)
if ($RuntimePoses) { $auditArgs += @('--runtime-poses', (Resolve-RepoPath $RuntimePoses)) }
if ($MidpointMotion) { $auditArgs += '--midpoint-motion' }
& $PythonExecutable @pythonPrefix $verifier @auditArgs
if ($LASTEXITCODE -ne 0) { throw 'Decoded SDK animator contract failed.' }
if ($checkPackageClosure) {
    Assert-ProbePaths
    & $PythonExecutable @pythonPrefix $packageClosure --seal-sdk-resources --probe-root $probe
    if ($LASTEXITCODE -ne 0) { throw 'Compiled presentation resources changed before SDK receipt sealing.' }
    & $PythonExecutable @pythonPrefix $packageClosure --probe-root $probe
    if ($LASTEXITCODE -ne 0) { throw 'Compiled presentation sampler is absent from the mod package load closure.' }
}
Write-Output "Animator FBX/SDK checks passed. Report: $probe\compiled_animation_contract.json. No deployment, upload or in-game test occurred."
