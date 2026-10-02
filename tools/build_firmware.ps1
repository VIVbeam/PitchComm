<#
.SYNOPSIS
Builds one or more PitchComm unit images with west and checks the image size.

.DESCRIPTION
Runs from the repository root and builds each requested roster key into
firmware/build/<key>:

  west build -b xiao_nrf54l15/nrf54l15/cpuapp firmware -d firmware/build/<key> -- `
    -DEXTRA_CONF_FILE="<generated capability conf>[;roles/field-common.conf][;roles/audio-unit.conf]" `
    -DEXTRA_CPPFLAGS=-DPC_UNIT=PC_UNIT_<key>

config/roster.json is the enrollment and capability source of truth: the file
list is derived from each unit's audio/display/controls flags, and a unit whose
generated PC_UNIT_ macro in firmware/include/pc/catalog.h is 0 (not enrolled) is
rejected. -Roles is kept as an alias for -Units and maps centerfield to center.
proof is not a roster key and keeps its fixed proof fragments.

The NCS version pin in firmware/ncs_version.txt is authoritative. Without
-NcsVersion, west is used directly and the pinned version is printed for
information only. With -NcsVersion, west is launched through the nRF Util SDK
manager toolchain and the value must match the pin; a deliberate override needs
-AllowVersionMismatch.

After each successful build, the text+data size of
firmware/build/<key>/zephyr/zephyr.elf is reported against the 712 KB
(729088 byte) MCUboot application slot. An overflow warns by default and fails
with -StrictSize. -MinSize appends roles/min-size.conf to every fragment list.

-NoBootloader removes MCUboot and uses the 776 KB (794624 byte) fallback layout:
it appends boards/no_bootloader.conf to EXTRA_CONF_FILE, passes
-DSB_CONFIG_BOOTLOADER_MCUBOOT=n and
-DEXTRA_DTC_OVERLAY_FILE=boards/no_bootloader.overlay, and measures against
794624 bytes. It does not change the build directory by itself; -BuildSuffix
selects one (builds land in firmware/build/<key>-<suffix>). The documented
fallback layout is -NoBootloader -BuildSuffix nb.

.EXAMPLE
tools\build_firmware.ps1
Builds the default enrolled team: coach, pitcher, catcher, shortstop, center.

.EXAMPLE
tools\build_firmware.ps1 -Units pitcher -MinSize -StrictSize -Pristine
Fits the pitcher image with the minimum-size fragment and fails if it does not.

.EXAMPLE
tools\build_firmware.ps1 -Roles centerfield
The -Roles alias maps centerfield to the center roster key.

.EXAMPLE
tools\build_firmware.ps1 -Units pitcher -NoBootloader -BuildSuffix nb -StrictSize
Builds firmware/build/pitcher-nb with MCUboot removed and fails if it is over
the 794624-byte fallback limit.

.EXAMPLE
tools\build_firmware.ps1 -Units coach -NcsVersion v3.4.0
Launches the pinned v3.4.0 toolchain through nrfutil instead of using a shell's west.
#>
param(
    [string[]]$Units = @('coach', 'pitcher', 'catcher', 'shortstop', 'center'),
    [string[]]$Roles = @(),
    [switch]$Pristine,
    [switch]$MinSize,
    [switch]$StrictSize,
    [switch]$NoBootloader,
    [string]$BuildSuffix = '',
    [string]$NcsVersion = '',
    [switch]$AllowVersionMismatch,
    [string[]]$WestArgs = @()
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$board = 'xiao_nrf54l15/nrf54l15/cpuapp'
$imageLimit = 729088  # 712 KB MCUboot application slot on the nRF54L15
$limitLabel = '712 KB MCuboot application slot'
$BuildSuffix = $BuildSuffix.Trim().TrimStart('-')
if ($NoBootloader) {
    $imageLimit = 794624  # 776 KB application area with MCUboot removed
    $limitLabel = '776 KB no-bootloader application slot'
    if (-not $BuildSuffix) {
        Write-Warning 'No -BuildSuffix given with -NoBootloader; firmware/build/<key> is reconfigured for a no-bootloader image. Pass -BuildSuffix nb for the documented firmware/build/<key>-nb layout.'
    }
}

# -Units is the roster-facing name; -Roles is the compatibility alias. Both
# accept comma-joined values from a powershell -File invocation.
if ($PSBoundParameters.ContainsKey('Roles') -and $PSBoundParameters.ContainsKey('Units')) {
    throw 'Use -Units or -Roles, not both.'
}
$requested = if ($PSBoundParameters.ContainsKey('Roles')) { $Roles } else { $Units }
$requested = @($requested | ForEach-Object { $_ -split ',' } |
    ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ })
$requested = @($requested | ForEach-Object { if ($_ -eq 'centerfield') { 'center' } else { $_ } } |
    Select-Object -Unique)
if (-not $requested.Count) { throw 'No units requested. Pass -Units with roster keys plus proof.' }

# --- roster and generated catalog -------------------------------------------
$rosterPath = Join-Path $root 'config/roster.json'
if (-not (Test-Path -LiteralPath $rosterPath)) {
    throw 'config/roster.json is missing; it is the enrollment and capability source of truth.'
}
$catalogPath = Join-Path $root 'firmware/include/pc/catalog.h'
if (-not (Test-Path -LiteralPath $catalogPath)) {
    throw 'firmware/include/pc/catalog.h is missing; run python tools\generate_catalog.py first.'
}
$roster = Get-Content -LiteralPath $rosterPath -Raw | ConvertFrom-Json
$rosterUnits = @{}
foreach ($unit in $roster.units) {
    $rosterUnits[$unit.key] = $unit
}
$catalogText = Get-Content -LiteralPath $catalogPath -Raw
$pcUnit = @{}
foreach ($match in [regex]::Matches($catalogText, '#define\s+PC_UNIT_([A-Za-z_][A-Za-z0-9_]*)\s+(\d+)')) {
    $pcUnit[$match.Groups[1].Value] = [int]$match.Groups[2].Value
}

foreach ($unit in $requested) {
    if ($unit -eq 'coach' -or $unit -eq 'proof') { continue }
    if (-not $rosterUnits.ContainsKey($unit)) {
        throw "Unknown unit '$unit'. Roster keys: $((@($rosterUnits.Keys) | Sort-Object) -join ', '); plus coach and proof."
    }
    if (-not $pcUnit.ContainsKey($unit)) {
        throw "firmware/include/pc/catalog.h has no PC_UNIT_$unit macro; run python tools\generate_catalog.py."
    }
    if ($pcUnit[$unit] -eq 0 -or -not $rosterUnits[$unit].enrolled) {
        throw "Unit '$unit' is not enrolled in config/roster.json (PC_UNIT_$unit is $($pcUnit[$unit])); enroll it and regenerate the catalog."
    }
}

# A field capability fragment is generated per build from the roster, so a new
# enrollment needs no new checked-in conf. audio also pulls the LE Audio stack.
$generatedDir = Join-Path $root 'firmware/build/unit-confs'
New-Item -ItemType Directory -Path $generatedDir -Force | Out-Null

function Get-CapabilityConf {
    param([string]$Key, [object]$Info)

    if ($Info.controls -and -not $Info.display) {
        throw "Unit '$Key' has controls without display; the catcher menu needs the OLED (CONFIG_PITCHCOMM_DISPLAY)."
    }
    $lines = New-Object 'System.Collections.Generic.List[string]'
    $lines.Add('# Generated by tools/build_firmware.ps1 from config/roster.json; do not edit.')
    $lines.Add('CONFIG_PITCHCOMM_CONSOLE=y')
    $lines.Add('CONFIG_PITCHCOMM_AUDIO=' + $(if ($Info.audio) { 'y' } else { 'n' }))
    $lines.Add('CONFIG_PITCHCOMM_DISPLAY=' + $(if ($Info.display) { 'y' } else { 'n' }))
    $lines.Add('CONFIG_PITCHCOMM_CATCHER_MENU=' + $(if ($Info.controls) { 'y' } else { 'n' }))
    $lines.Add('CONFIG_PITCHCOMM_FIELD_BUTTON=y')
    $lines.Add('CONFIG_PITCHCOMM_BATTERY=y')
    if ($Info.display) {
        $lines.Add('CONFIG_DISPLAY=y')
        $lines.Add('CONFIG_SSD1306=y')
    }
    $path = Join-Path $generatedDir "$Key.conf"
    Set-Content -LiteralPath $path -Value ($lines -join "`n") -Encoding ascii
    return $path
}

function Find-SizeTool {
    # First size tool on PATH, in the order the toolchains usually install them.
    foreach ($candidate in @('arm-zephyr-eabi-size', 'arm-none-eabi-size', 'size')) {
        $tool = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue
        if ($tool) { return $tool.Source }
    }
    return $null
}

# The version pin is the source of truth for every build.
$versionPath = Join-Path $root 'firmware/ncs_version.txt'
if (-not (Test-Path -LiteralPath $versionPath)) {
    throw 'NCS version pin is missing: firmware/ncs_version.txt. Restore it (for example v3.4.0) before building.'
}
$pinnedVersion = [string](Get-Content -LiteralPath $versionPath -TotalCount 1)
$pinnedVersion = $pinnedVersion.Trim()
if ($pinnedVersion -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$') {
    throw "NCS version pin is invalid: firmware/ncs_version.txt must contain one line like v3.4.0 (found '$pinnedVersion')."
}
if ($NcsVersion -and $NcsVersion -ne $pinnedVersion) {
    if (-not $AllowVersionMismatch) {
        throw "NCS version mismatch: -NcsVersion $NcsVersion does not match the firmware/ncs_version.txt pin ($pinnedVersion). Pass -AllowVersionMismatch only for a deliberate override."
    }
    Write-Warning "-NcsVersion $NcsVersion overrides the firmware/ncs_version.txt pin ($pinnedVersion)."
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
        throw "west was not found on PATH. Open an NCS $pinnedVersion toolchain shell first (nrfutil sdk-manager toolchain launch --ncs-version $pinnedVersion --terminal), or pass -NcsVersion $pinnedVersion."
    }
    Write-Host "Pinned NCS version: $pinnedVersion (west on PATH; not comparing)"
}

Push-Location $root
$builtNames = New-Object 'System.Collections.Generic.List[string]'
try {
    foreach ($unit in $requested) {
        $pcDefine = $null
        if ($unit -eq 'proof') {
            $fragmentList = 'roles/audio-proof.conf;roles/audio-unit.conf'
        } elseif ($unit -eq 'coach') {
            $fragmentList = 'roles/coach.conf'
        } else {
            $info = $rosterUnits[$unit]
            $capabilityConf = Get-CapabilityConf -Key $unit -Info $info
            $fragmentList = @($capabilityConf, 'roles/field-common.conf')
            if ($info.audio) { $fragmentList += 'roles/audio-unit.conf' }
            $fragmentList = $fragmentList -join ';'
            $pcDefine = "PC_UNIT=PC_UNIT_$unit"
        }
        if ($NoBootloader) { $fragmentList += ';boards/no_bootloader.conf' }
        if ($MinSize) { $fragmentList += ';roles/min-size.conf' }
        $buildName = if ($BuildSuffix) { "$unit-$BuildSuffix" } else { $unit }
        $arguments = @('build', '-b', $board, 'firmware', '-d', "firmware/build/$buildName")
        if ($Pristine) { $arguments += '--pristine' }
        if ($WestArgs.Count) { $arguments += $WestArgs }
        $cmakeArgs = @("-DEXTRA_CONF_FILE=$fragmentList")
        if ($pcDefine) { $cmakeArgs += "-DEXTRA_CPPFLAGS=-D$pcDefine" }
        if ($NoBootloader) {
            $cmakeArgs += @('-DSB_CONFIG_BOOTLOADER_MCUBOOT=n',
                            '-DEXTRA_DTC_OVERLAY_FILE=boards/no_bootloader.overlay')
        }
        $arguments += @('--') + $cmakeArgs
        if ($NcsVersion) {
            Write-Host "==> $buildName (NCS $NcsVersion): west $($arguments -join ' ')"
            & $nrfutil sdk-manager toolchain launch --ncs-version $NcsVersion -- west @arguments
        } else {
            Write-Host "==> ${buildName}: west $($arguments -join ' ')"
            & $westPath @arguments
        }
        if ($LASTEXITCODE -ne 0) { throw "Build failed for unit '$buildName' (exit $LASTEXITCODE)" }
        $builtNames.Add($buildName)

        $elf = Join-Path $root "firmware/build/$buildName/zephyr/zephyr.elf"
        if (-not (Test-Path -LiteralPath $elf)) {
            Write-Warning "IMAGE ${buildName}: zephyr.elf not found at firmware/build/$buildName/zephyr/zephyr.elf"
            continue
        }
        $sizeTool = Find-SizeTool
        if (-not $sizeTool) {
            Write-Host "IMAGE ${buildName}: size tool not found (install the NCS toolchain or use west's rom_report)"
            continue
        }
        $bytes = $null
        foreach ($line in @(& $sizeTool $elf 2>$null)) {
            if ($line -match '^\s*(\d+)\s+(\d+)(\s|$)') {
                $bytes = [int64]$Matches[1] + [int64]$Matches[2]
                break
            }
        }
        if ($null -eq $bytes) {
            Write-Warning "IMAGE ${buildName}: could not parse size output from $sizeTool; use west's rom_report"
            continue
        }
        $percent = (100.0 * $bytes / $imageLimit).ToString('0.0', [System.Globalization.CultureInfo]::InvariantCulture)
        Write-Host "IMAGE ${buildName}: $bytes / $imageLimit bytes ($percent%)"
        if ($bytes -gt $imageLimit) {
            Write-Warning "IMAGE ${buildName} is over the $limitLabel."
            if ($StrictSize) { throw "Image '$buildName' does not fit the $limitLabel ($bytes bytes)." }
        }
    }
} finally {
    Pop-Location
}
Write-Host "Built: $($builtNames -join ', ')"
