[CmdletBinding()]
param(
    [string]$FbxPath = '.build\hose_rig_probe\warlock_hose.fbx',
    [string]$ContractPath = 'tools\hose_lab\rig\runtime_contract.json',
    [string]$ProbeRoot = '.build\hose_lab_compiled_probe',
    [string]$SdkRoot = 'C:\Program Files (x86)\Steam\steamapps\common\Vermintide 2 SDK',
    [string]$PythonExecutable = 'py'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
function Resolve-RepoPath([string]$Path) {
    if ([IO.Path]::IsPathRooted($Path)) { return [IO.Path]::GetFullPath($Path) }
    return [IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
}
$resolvedProbe = Resolve-RepoPath $ProbeRoot
$pythonPrefix = @()
if ([IO.Path]::GetFileNameWithoutExtension($PythonExecutable) -eq 'py') { $pythonPrefix = @('-3') }
$pathGuard = Join-Path $PSScriptRoot '..\compile_paths.py'
function Assert-ProbePaths {
    & $PythonExecutable @pythonPrefix $pathGuard --repo-root $repoRoot --probe-root $resolvedProbe
    if ($LASTEXITCODE -ne 0) { throw 'Probe path preflight failed; no writer may be started.' }
}
function Assert-CompilerAvailable {
    if (Get-Process -Name 'stingray_win64_dev_x64' -ErrorAction SilentlyContinue) {
        throw 'SDK compiler is already running. Coordinate with its owner; do not launch concurrently.'
    }
}
Assert-ProbePaths
Assert-CompilerAvailable
$source = Join-Path $resolvedProbe 'source'
$data = Join-Path $resolvedProbe 'data'
$bundles = Join-Path $resolvedProbe 'bundle'
$fbx = Resolve-RepoPath $FbxPath
$contract = Resolve-RepoPath $ContractPath
$compiler = Join-Path $SdkRoot 'bin\stingray_win64_dev_x64.exe'
foreach ($required in @($fbx, $contract, $compiler)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing input: $required" }
}
# Dedicated generated inputs only. No deletion, deployment, game launch or upload.
[void](New-Item -ItemType Directory -Path (Join-Path $source 'units\hose') -Force)
[void](New-Item -ItemType Directory -Path (Join-Path $source 'materials') -Force)
$stagedFbx = Join-Path $source 'units\hose\warlock_hose.fbx'
Copy-Item -LiteralPath $fbx -Destination $stagedFbx
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'warlock_hose.unit.template') -Destination (Join-Path $source 'units\hose\warlock_hose.unit')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'hose_probe.material.template') -Destination (Join-Path $source 'materials\hose_probe.material')
$stdout = Join-Path $resolvedProbe 'compiler.stdout.log'
$stderr = Join-Path $resolvedProbe 'compiler.stderr.log'
$compilerArgs = @('--compile', '--compile-for', 'win32', '--source-dir', ('"' + $source + '"'),
    '--data-dir', ('"' + $data + '"'), '--bundle-dir', ('"' + $bundles + '"'),
    '--map-source-dir', 'core', ('"' + $SdkRoot + '"'))
Assert-ProbePaths
Assert-CompilerAvailable
$process = Start-Process -FilePath $compiler -ArgumentList $compilerArgs -WorkingDirectory $resolvedProbe `
    -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput $stdout -RedirectStandardError $stderr
Get-Content -LiteralPath $stdout -Tail 12
Get-Content -LiteralPath $stderr
if ($process.ExitCode -ne 0 -or (Get-Content -LiteralPath $stdout -Raw) -notmatch 'Compile resulted in success') {
    throw "Isolated SDK compilation failed; inspect $stdout and $stderr"
}
$unit = & $PythonExecutable @pythonPrefix $pathGuard --repo-root $repoRoot --probe-root $resolvedProbe `
    --data-root $data --resource 'units/hose/warlock_hose.unit'
if ($LASTEXITCODE -ne 0) { throw 'SDK resource index/path verification failed.' }
& $PythonExecutable @pythonPrefix (Join-Path $PSScriptRoot 'verify_asset.py') --unit $unit --fbx $stagedFbx --contract $contract `
    --report (Join-Path $resolvedProbe 'compiled_hose_contract.json')
if ($LASTEXITCODE -ne 0) { throw 'Compiled hose geometry/skin verification failed.' }
Write-Output '[hose-asset] PASS - isolated geometry/skin compiler probe only; not an in-game test.'
