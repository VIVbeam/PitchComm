<#
.SYNOPSIS
Builds one or more PitchComm firmware roles with west.

.DESCRIPTION
Runs from the repository root and builds each role into firmware/build/<role>:

  west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware -d firmware/build/<role> -- `
    -DEXTRA_CONF_FILE="<role fragments>"

Requires an NCS v3.4.0 toolchain with west on PATH, or pass -NcsVersion to
launch west through the nRF Util SDK manager toolchain.

.EXAMPLE
tools\build_firmware.ps1
Builds the five production roles (coach, catcher, pitcher, shortstop, centerfield).

.EXAMPLE
tools\build_firmware.ps1 -Roles pitcher -Pristine
Builds only the pitcher image, discarding the existing build directory first.

.EXAMPLE
tools\build_firmware.ps1 -Roles coach,pitcher -NcsVersion v3.4.0
Launches the v3.4.0 toolchain through nrfutil instead of using a shell's west.
#>
param(
    [ValidateSet('coach', 'catcher', 'pitcher', 'shortstop', 'centerfield', 'proof')]
    [string[]]$Roles = @('coach', 'catcher', 'pitcher', 'shortstop', 'centerfield'),
    [switch]$Pristine,
    [string]$NcsVersion = '',
    [string[]]$WestArgs = @()
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$board = 'xiao_nrf54l15/nrf54l15/cpuapp'
$fragments = @{
    coach       = 'roles/coach.conf'
    catcher     = 'roles/catcher.conf;roles/field-common.conf;roles/audio-unit.conf'
    pitcher     = 'roles/pitcher.conf;roles/field-common.conf;roles/audio-unit.conf'
    shortstop   = 'roles/shortstop.conf;roles/field-common.conf'
    centerfield = 'roles/centerfield.conf;roles/field-common.conf'
    proof       = 'roles/audio-proof.conf;roles/audio-unit.conf'
}

$nrfutil = $null
$westPath = $null
if ($NcsVersion) {
    $nrfutil = (Get-Command nrfutil -ErrorAction SilentlyContinue).Source
    if (-not $nrfutil) {
        throw "nrfutil was not found on PATH; it is required to launch NCS $NcsVersion. Install nRF Util, or run this script from an NCS toolchain shell without -NcsVersion."
    }
} else {
    $westPath = (Get-Command west -ErrorAction SilentlyContinue).Source
    if (-not $westPath) {
        throw "west was not found on PATH. Open an NCS v3.4.0 toolchain shell first (nrfutil sdk-manager toolchain launch --ncs-version v3.4.0 --terminal), or pass -NcsVersion v3.4.0."
    }
}

Push-Location $root
try {
    foreach ($role in $Roles) {
        $arguments = @('build', '-b', $board, 'firmware', '-d', "firmware/build/$role")
        if ($Pristine) { $arguments += '--pristine' }
        if ($WestArgs.Count) { $arguments += $WestArgs }
        $arguments += @('--', "-DEXTRA_CONF_FILE=$($fragments[$role])")
        if ($NcsVersion) {
            Write-Host "==> $role (NCS $NcsVersion): west $($arguments -join ' ')"
            & $nrfutil sdk-manager toolchain launch --ncs-version $NcsVersion -- west @arguments
        } else {
            Write-Host "==> ${role}: west $($arguments -join ' ')"
            & $westPath @arguments
        }
        if ($LASTEXITCODE -ne 0) { throw "Build failed for role '$role' (exit $LASTEXITCODE)" }
    }
} finally {
    Pop-Location
}
Write-Host "Built: $($Roles -join ', ')"
