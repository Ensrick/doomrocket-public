[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string[]]$AnimationFbx,
    [Parameter(Mandatory = $true)][string]$BodyFbx,
    [string[]]$ExportManifest,
    [string]$AdaptedClips,
    [switch]$CompatibilityOnly,
    [string]$ProbeRoot = '.build\animation_native_pose_oracle',
    [string]$SdkRoot = 'C:\Program Files (x86)\Steam\steamapps\common\Vermintide 2 SDK',
    [string]$PythonExecutable = 'py',
    [ValidateRange(10, 600)][int]$TimeoutSeconds = 120,
    [switch]$IncludeReference,
    [switch]$CompileOnly
)
# This isolated SDK runner does not deploy, upload, start Steam, or load the game.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$compiler = [IO.Path]::GetFullPath((Join-Path $SdkRoot 'bin\stingray_win64_dev_x64.exe'))
$guard = Join-Path $repoRoot 'tools\hose_lab\compile_paths.py'
$helper = Join-Path $PSScriptRoot 'runtime_pose_probe.py'
$pythonPrefix = @()
if ([IO.Path]::GetFileNameWithoutExtension($PythonExecutable) -eq 'py') { $pythonPrefix = @('-3') }
function Resolve-RepoPath([string]$Path) {
    if ([IO.Path]::IsPathRooted($Path)) { return [IO.Path]::GetFullPath($Path) }
    return [IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}
function Assert-ProbePaths([string]$Probe) {
    & $PythonExecutable @pythonPrefix $guard --repo-root $repoRoot --probe-root $Probe
    if ($LASTEXITCODE -ne 0) { throw 'Probe paths rejected; no writer may start.' }
}
function Assert-SdkAvailable {
    if (Get-Process -Name 'stingray_win64_dev_x64' -ErrorAction SilentlyContinue) {
        throw 'Another SDK process is running. Coordinate with its owner before continuing.'
    }
}
function Run-Helper([string[]]$Arguments) {
    & $PythonExecutable @pythonPrefix $helper @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Native oracle input/receipt validation failed.' }
}
function Quote-ProcessArgument([string]$Argument) {
    if ($Argument.Contains('"') -or $Argument.Contains("`r") -or $Argument.Contains("`n")) {
        throw 'Quotes and newlines are not allowed in native SDK arguments.'
    }
    # All path arguments below name files/directories, with no trailing separator.
    return '"' + $Argument + '"'
}
function Stop-OwnedSdk($Process, $OwnedStart, [string]$LaneRoot) {
    $live = Get-Process -Id $Process.Id -ErrorAction SilentlyContinue
    if (-not $live) { return }
    if (-not $OwnedStart) { $OwnedStart = $Process.StartTime.ToUniversalTime() }
    $details = Get-CimInstance Win32_Process -Filter "ProcessId = $($Process.Id)"
    $matches = $live.StartTime.ToUniversalTime() -eq $OwnedStart -and
        [IO.Path]::GetFullPath($details.ExecutablePath) -eq $compiler -and
        $details.CommandLine.Contains($LaneRoot)
    if (-not $matches) { throw 'Process ownership could not be verified; no process was terminated.' }
    Stop-Process -Id $Process.Id -Force
    if (-not $Process.WaitForExit(10000)) { throw 'Owned SDK termination did not complete within 10 seconds.' }
}
function Run-OwnedSdk([string]$LaneRoot, [string[]]$Arguments, [string]$Phase, [string]$Probe) {
    Assert-ProbePaths $Probe
    Assert-SdkAvailable
    $stdout = Join-Path $LaneRoot ($Phase + '.stdout.log')
    $stderr = Join-Path $LaneRoot ($Phase + '.stderr.log')
    $process = Start-Process -FilePath $compiler -ArgumentList $Arguments -WorkingDirectory $LaneRoot `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $ownedStart = $null
    try {
        $ownedStart = $process.StartTime.ToUniversalTime()
        $record = @{ schema = 1; pid = $process.Id; executable = $compiler; executable_sha256 = (Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash.ToLowerInvariant(); start_utc = $ownedStart.ToString('o');
            probe = $Probe; phase = $Phase; arguments = $Arguments; timeout_seconds = $TimeoutSeconds }
        $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $LaneRoot ($Phase + '.process.json')) -Encoding UTF8
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            throw "Owned SDK $Phase exceeded $TimeoutSeconds seconds; inspect $stdout and $stderr."
        }
        $process.WaitForExit()
        Get-Content -LiteralPath $stdout -Tail 8
        if ((Get-Item -LiteralPath $stderr).Length) { Get-Content -LiteralPath $stderr -Tail 10 }
        if ($process.ExitCode -ne 0) { throw "Owned SDK $Phase failed with exit $($process.ExitCode)." }
        if ($Phase -eq 'compiler' -and (Get-Content -LiteralPath $stdout -Raw) -notmatch 'Compile resulted in success!') {
            throw 'SDK did not report a successful compilation.'
        }
    } finally {
        # Metadata I/O failures and timeouts both get the same bounded cleanup.
        # Never stop a pre-existing SDK, reused PID, or another project's process.
        $process.Refresh()
        if (-not $process.HasExited) { Stop-OwnedSdk $process $ownedStart $LaneRoot }
        $process.Dispose()
    }
}

$probe = Resolve-RepoPath $ProbeRoot
$body = Resolve-RepoPath $BodyFbx
Assert-ProbePaths $probe
Assert-SdkAvailable
foreach ($required in @($body, $compiler, $helper, $guard)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing input: $required" }
}
# This exact installed mod-tools build was observed entering the compiler even
# with --no-compile and a boot ini. Avoid repeating that known failed bootstrap.
$compilerHash = (Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not $CompileOnly -and $compilerHash -eq '721bc354a520510ea270147c57230c87cc7e07d93f78ca1a0763d5bdb74137de') {
    throw 'Native playback is unavailable through this installed VT2 SDK mod-tools executable: --no-compile entered compiler prerequisites instead of Lua boot. Use -CompileOnly for isolated source compilation; see tools/animation_rig/NATIVE_POSE_ORACLE.md. No native pose capture has been validated.'
}
if ($ExportManifest -and $ExportManifest.Count -ne $AnimationFbx.Count) { throw 'Supply one manifest per animation.' }
if ($CompatibilityOnly -and (-not $AdaptedClips -or $AnimationFbx.Count -ne 1)) {
    throw 'Compatibility mode requires AdaptedClips and one frozen diagnostic FBX/manifest for staging.'
}
$lanes = @('candidate')
if ($IncludeReference) { $lanes += 'reference' }
for ($index = 0; $index -lt $AnimationFbx.Count; $index++) {
    $animation = Resolve-RepoPath $AnimationFbx[$index]
    $manifest = [IO.Path]::ChangeExtension($animation, '.export.json')
    if ($ExportManifest) { $manifest = Resolve-RepoPath $ExportManifest[$index] }
    $clipProbe = Join-Path $probe ('clip_' + $index.ToString('D2'))
    Assert-ProbePaths $clipProbe
    $stageArguments = @('stage', '--probe-root', $clipProbe, '--animation-fbx', $animation, '--body-fbx', $body, '--manifest', $manifest, '--sdk-executable', $compiler)
    if ($AdaptedClips) { $stageArguments += @('--adapted-clips', (Resolve-RepoPath $AdaptedClips)) }
    if ($CompatibilityOnly) { $stageArguments += '--compatibility-only' }
    Run-Helper -Arguments $stageArguments
    foreach ($lane in $lanes) {
        $laneRoot = Join-Path $clipProbe $lane
        $source = Join-Path $laneRoot 'source'
        $data = Join-Path $laneRoot 'data'
        $bundles = Join-Path $laneRoot 'bundle'
        $compileArguments = @('--compile', '--suppress-messagebox', '--compile-for', 'win32', '--source-dir', (Quote-ProcessArgument $source),
            '--data-dir', (Quote-ProcessArgument $data), '--bundle-dir', (Quote-ProcessArgument $bundles),
            '--map-source-dir', 'core', (Quote-ProcessArgument $SdkRoot))
        Run-OwnedSdk $laneRoot $compileArguments 'compiler' $clipProbe
        Run-Helper -Arguments @('bind-compiled', '--probe-root', $clipProbe, '--lane', $lane, '--sdk-executable', $compiler)
        if ($CompileOnly) { continue }
        # The ini resource bootstrap matches the SDK's own LUT generator.
        $runtimeArguments = @('--no-rendering', '--disable-default-window', '--suppress-messagebox', '--no-compile',
            '--data-dir', (Quote-ProcessArgument $data), '--ini', 'native_pose_oracle',
            '--default-console-log-path', (Quote-ProcessArgument (Join-Path $laneRoot 'runtime.console.log')))
        Run-OwnedSdk $laneRoot $runtimeArguments 'runtime' $clipProbe
        Run-Helper -Arguments @('validate', '--probe-root', $clipProbe, '--lane', $lane, '--sdk-executable', $compiler)
    }
}
if ($CompileOnly) {
    Write-Output "Isolated harness source compiled below $probe. Native pose capture was not performed."
} else {
    Write-Output "Native SDK pose capture validated below $probe. The recorder does not infer animation fidelity."
}
