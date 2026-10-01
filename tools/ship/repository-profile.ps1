# Standalone layout adaptation of the copied Tweaker workflow.
function Get-WarlockModPrefix {
    param([string]$Mod)
    if ($Mod -cne 'doomrocket') { throw "This standalone ship only accepts doomrocket: $Mod" }
    return ''
}
function Get-WarlockModRoot {
    param([string]$RepoRoot, [string]$Mod)
    $null = Get-WarlockModPrefix $Mod
    return [IO.Path]::GetFullPath($RepoRoot)
}
function Get-WarlockModPathspec {
    param([string]$Mod)
    $null = Get-WarlockModPrefix $Mod
    return '.'
}
function Get-WarlockRepositoryProfile {
    param([string]$RepoRoot)
    $cfg = [IO.File]::ReadAllText((Join-Path $RepoRoot 'itemV2.cfg'))
    if ($cfg -match '(?m)^published_id\s*=\s*3794172730L;') {
        return [pscustomobject]@{Repository='Ensrick/doomrocket-private';Branch='private-copy';Id='3794172730';Suffix='-dev';Channel='development'}
    }
    if ($cfg -match '(?m)^published_id\s*=\s*3771657344L;') {
        return [pscustomobject]@{Repository='Ensrick/doomrocket-public';Branch='main';Id='3771657344';Suffix='-alpha';Channel='public'}
    }
    throw 'Unknown Warlock Workshop identity.'
}
