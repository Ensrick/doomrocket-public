[CmdletBinding()]
param(
    [string]$ProbeRoot,
    [string]$SdkRoot = 'C:\Program Files (x86)\Steam\steamapps\common\Vermintide 2 SDK',
    [string]$PythonExecutable = 'py'
)
# COMPILE ONLY. Negative fixtures contain unsafe runtime values; NEVER run them.
# Coordinate with other maintainers before using the shared SDK compiler.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$buildRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot '.build'))
if (-not $ProbeRoot) { $ProbeRoot = Join-Path $buildRoot 'hose_lab_native_chain_probe' }
if (-not [IO.Path]::IsPathRooted($ProbeRoot)) { $ProbeRoot = Join-Path $repoRoot $ProbeRoot }
$outputRoot = [IO.Path]::GetFullPath($ProbeRoot)
$pythonPrefix = @()
if ([IO.Path]::GetFileNameWithoutExtension($PythonExecutable) -eq 'py') { $pythonPrefix = @('-3') }
$pathGuard = Join-Path $PSScriptRoot '..\compile_paths.py'
function Assert-ProbePaths {
    & $PythonExecutable @pythonPrefix $pathGuard --repo-root $repoRoot --probe-root $outputRoot
    if ($LASTEXITCODE -ne 0) { throw 'Probe path preflight failed; no writer may be started.' }
}
function Assert-CompilerAvailable {
    if (Get-Process -Name 'stingray_win64_dev_x64' -ErrorAction SilentlyContinue) {
        throw 'SDK compiler is already running. Coordinate with its owner; do not launch concurrently.'
    }
}
Assert-ProbePaths
Assert-CompilerAvailable
$sourceDir = Join-Path $outputRoot 'source'
$dataDir = Join-Path $outputRoot 'data'
$bundleDir = Join-Path $outputRoot 'bundle'
$compiler = Join-Path $SdkRoot 'bin\stingray_win64_dev_x64.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) { throw "Missing SDK compiler: $compiler" }
& $PythonExecutable @pythonPrefix (Join-Path $PSScriptRoot 'generate_fixtures.py') --output-dir $sourceDir
if ($LASTEXITCODE -ne 0) { throw 'Fixture generation failed.' }
$stdout = Join-Path $outputRoot 'compiler.stdout.log'
$stderr = Join-Path $outputRoot 'compiler.stderr.log'
$compilerArgs = @('--compile', '--compile-for', 'win32', '--source-dir', ('"' + $sourceDir + '"'),
    '--data-dir', ('"' + $dataDir + '"'), '--bundle-dir', ('"' + $bundleDir + '"'),
    '--map-source-dir', 'core', ('"' + [IO.Path]::GetFullPath($SdkRoot) + '"'))
Write-Output "SDK SHA256: $((Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash)"
Assert-ProbePaths
Assert-CompilerAvailable
$process = Start-Process -FilePath $compiler -ArgumentList $compilerArgs -WorkingDirectory $outputRoot `
    -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
if ($process.ExitCode -ne 0 -or -not (Select-String -LiteralPath $stdout -SimpleMatch 'Compile resulted in success!' -Quiet)) {
    throw "Compiler did not confirm success. Inspect $stdout and $stderr; do not repeat an assertion-producing probe."
}
$resourceArgs = @()
foreach ($case in @('base', 'mass_zero', 'mass_numeric', 'mass_string', 'bone_swap',
                    'flags', 'unknown_pin', 'expressions', 'no_tip_bone')) {
    $resourceArgs += @('--resource', "chain_${case}.state_machine")
}
& $PythonExecutable @pythonPrefix $pathGuard --repo-root $repoRoot --probe-root $outputRoot `
    --data-root $dataDir @resourceArgs | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'SDK resource index/path verification failed.' }
& $PythonExecutable @pythonPrefix (Join-Path $PSScriptRoot 'verify_compiled.py') --data-root $dataDir
if ($LASTEXITCODE -ne 0) { throw 'Compiled descriptor verification failed.' }
Write-Output "Compiler-only proof passed. No game, deployment or upload was performed. Logs: $outputRoot"
