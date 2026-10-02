<#
.SYNOPSIS
Flashes one built PitchComm role image with west.

.DESCRIPTION
Runs from the repository root:

  west flash -d firmware/build/<role> [--erase]

The XIAO nRF54L15 uses the same board target for every role; the role is
encoded in the image built by tools/build_firmware.ps1. Use -Erase on the
first flash of a board (or after changing the partition layout).

.EXAMPLE
tools\flash_firmware.ps1 -Role catcher -Erase
Erases the board and flashes the catcher image.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('coach', 'catcher', 'pitcher', 'shortstop', 'centerfield', 'proof')]
    [string]$Role,
    [switch]$Erase
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$westPath = (Get-Command west -ErrorAction SilentlyContinue).Source
if (-not $westPath) {
    throw 'west was not found on PATH. Open an NCS v3.4.0 toolchain shell and retry.'
}
$build = "firmware/build/$Role"
if (-not (Test-Path -LiteralPath (Join-Path $root $build))) {
    throw "No build found at $build. Run tools\build_firmware.ps1 -Roles $Role first."
}
Push-Location $root
try {
    $arguments = @('flash', '-d', $build)
    if ($Erase) { $arguments += '--erase' }
    Write-Host "==> west $($arguments -join ' ')"
    & $westPath @arguments
    if ($LASTEXITCODE -ne 0) { throw "Flashing failed for role '$Role' (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}
Write-Host "Flashed $Role."
