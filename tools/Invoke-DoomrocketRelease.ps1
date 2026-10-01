# Compatibility entry point: use the canonical standalone ship adapter.
[CmdletBinding()]
param([switch]$BuildOnly, [switch]$AllowPublic, [switch]$PublicationOnly,
      [Parameter(Mandatory=$true)][string]$LauncherPath,
      [Parameter(Mandatory=$true)][string]$ConfigPath)
& (Join-Path $PSScriptRoot 'ship/ship.ps1') @PSBoundParameters
