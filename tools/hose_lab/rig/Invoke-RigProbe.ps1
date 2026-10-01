[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ArtistScene,
    [string]$BlenderExe = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe',
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
if (-not $OutputPath) { $OutputPath = Join-Path $repoRoot '.build\hose_rig_probe' }
if (-not [IO.Path]::IsPathRooted($OutputPath)) { $OutputPath = Join-Path $repoRoot $OutputPath }
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
& py -3 (Join-Path $PSScriptRoot '..\compile_paths.py') --repo-root $repoRoot --probe-root $OutputPath
if ($LASTEXITCODE -ne 0) { throw 'Rig path preflight failed; no writer may be started.' }
$ArtistScene = (Resolve-Path -LiteralPath $ArtistScene).Path
if ((Get-FileHash -LiteralPath $ArtistScene -Algorithm SHA256).Hash -ne 'AB6EBC9EF45CEA6E402BBD0415C2D40716824552C2AB514947902D1EAC06C1B2') {
    throw 'Artist scene differs from the reviewed input; remeasure instead of updating the hash.'
}
if (-not (Test-Path -LiteralPath $BlenderExe -PathType Leaf)) { throw 'Blender executable not found.' }

function Invoke-ProbeBlender([string]$Script, [bool]$OpenArtist = $false) {
    $probeArgs = @('--background', '--disable-autoexec', '--python-exit-code', '1')
    if ($OpenArtist) { $probeArgs += $ArtistScene }
    $probeArgs += @('--python', (Join-Path $PSScriptRoot $Script), '--', '--repo', $repoRoot, '--output', $OutputPath)
    & $BlenderExe @probeArgs
    if ($LASTEXITCODE -ne 0) { throw "Blender probe failed: $Script" }
}

function Invoke-ProbePython([string]$Script) {
    & py -3 (Join-Path $PSScriptRoot $Script) --repo $repoRoot --output $OutputPath
    if ($LASTEXITCODE -ne 0) { throw "Python probe failed: $Script" }
}

Invoke-ProbeBlender 'inspect_hose.py' $true
Invoke-ProbePython 'analyze_hose.py'
Invoke-ProbeBlender 'inspect_socket.py' $true
Invoke-ProbePython 'read_weapon_contract.py'
Invoke-ProbeBlender 'build_hose_rig.py' $true
Invoke-ProbePython 'verify_hose_fbx.py'
Invoke-ProbeBlender 'verify_roundtrip_blender.py'
Write-Output "Offline rig/export checks passed. Candidate files: $OutputPath. No SDK build, game deployment or Workshop upload occurred."
