<#
.SYNOPSIS
Flashes one built PitchComm firmware image with west.

.DESCRIPTION
Runs from the repository root, either for one roster unit or for an explicit
build directory:

  west flash -d firmware/build/<unit> [--erase]       (-Unit)
  west flash -d <BuildDir> [--erase]                  (-BuildDir)

-Unit accepts the enrolled keys from config/roster.json plus coach (the
implicit unit 0), resolved at runtime. -Role is a compatibility
alias for -Unit that maps the legacy key centerfield to the center roster key.
-BuildDir designates any directory, which is how the no-bootloader builds are
flashed (for example tools\build_firmware.ps1 -NoBootloader -BuildSuffix nb
then tools\flash_firmware.ps1 -BuildDir firmware/build/pitcher-nb -Erase).
Pass exactly one of -Unit, -Role or -BuildDir.

The XIAO nRF54L15 uses the same board target for every unit; the unit is
encoded in the image built by tools/build_firmware.ps1. Use -Erase on the
first flash of a board or after changing the partition layout (it also wipes
the LittleFS audio image and saved bonds; rerun tools\flash_audio.ps1 for the
pitcher afterwards).

.EXAMPLE
tools\flash_firmware.ps1 -Unit catcher -Erase
Erases the board and flashes the catcher image.

.EXAMPLE
tools\flash_firmware.ps1 -Role centerfield -Erase
The -Role alias maps centerfield to the center roster key.

.EXAMPLE
tools\flash_firmware.ps1 -BuildDir firmware/build/pitcher-nb -Erase
Erases the board and flashes the no-bootloader pitcher image.
#>
param(
    [string]$Unit = '',
    [string]$Role = '',
    [string]$BuildDir = '',
    [switch]$Erase
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$usingRole = $PSBoundParameters.ContainsKey('Role')
if ($usingRole -and $PSBoundParameters.ContainsKey('Unit')) {
    throw 'Use -Unit or -Role, not both.'
}
$requested = if ($usingRole) { $Role } else { $Unit }
if ($requested) {
    $requested = $requested.Trim().ToLowerInvariant()
    # -Role is the compatibility alias, so only it maps the legacy centerfield
    # spelling on to the center roster key. -Unit takes current keys only.
    if ($usingRole -and $requested -eq 'centerfield') { $requested = 'center' }
}
if (-not $requested -and -not $BuildDir) {
    throw 'Specify a build with -Unit <unit> or -BuildDir <path> (for example -BuildDir firmware/build/pitcher-nb).'
}
if ($requested -and $BuildDir) {
    throw 'Use either -Unit or -BuildDir, not both.'
}
if ($requested) {
    $rosterPath = Join-Path $root 'config/roster.json'
    if (-not (Test-Path -LiteralPath $rosterPath)) {
        throw 'config/roster.json is missing; it is the enrollment source of truth for -Unit.'
    }
    try {
        $roster = Get-Content -LiteralPath $rosterPath -Raw | ConvertFrom-Json
    } catch {
        throw "config/roster.json is not readable JSON: $($_.Exception.Message)"
    }
    $enrolled = @($roster.units | Where-Object { $_.enrolled } | ForEach-Object { $_.key })
    $known = @($roster.units | ForEach-Object { $_.key })
    # The coach is the implicit unit 0.
    if ($requested -ne 'coach') {
        if ($enrolled -notcontains $requested) {
            if ($known -contains $requested) {
                throw "Unit '$requested' is not enrolled in config/roster.json. Enrolled keys: $($enrolled -join ', '); plus coach."
            }
            throw "Unknown unit '$requested'. Roster keys: $((@($known) | Sort-Object) -join ', '); plus coach."
        }
    }
}
if ($requested) {
    $buildArg = "firmware/build/$requested"
    $buildPath = Join-Path $root $buildArg
    $label = $requested
} else {
    $buildArg = $BuildDir.Replace('\', '/')
    $buildPath = if ([System.IO.Path]::IsPathRooted($BuildDir)) { $BuildDir } else { Join-Path $root $BuildDir }
    $label = $BuildDir
}
if (-not (Test-Path -LiteralPath $buildPath -PathType Container)) {
    if ($requested) {
        throw "No build found at $buildArg. Run tools\build_firmware.ps1 -Units $label first, or pass the right -BuildDir."
    }
    throw "No build found at $buildArg. Pass the right -BuildDir, or build it with tools\build_firmware.ps1."
}
$westPath = (Get-Command west -ErrorAction SilentlyContinue).Source
if (-not $westPath) {
    throw 'west was not found on PATH. Open an NCS v3.4.0 toolchain shell and retry.'
}
Push-Location $root
try {
    $arguments = @('flash', '-d', $buildArg)
    if ($Erase) { $arguments += '--erase' }
    Write-Host "==> west $($arguments -join ' ')"
    & $westPath @arguments
    if ($LASTEXITCODE -ne 0) { throw "Flashing failed for '$label' (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}
Write-Host "Flashed $label."
