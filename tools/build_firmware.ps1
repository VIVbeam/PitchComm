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
list is derived from each unit's audio/display/controls/relay flags, and a unit
whose generated PC_UNIT_ macro in firmware/include/pc/catalog.h is 0 (not
enrolled) is rejected. -Roles is kept as an alias for -Units and maps
centerfield to center. -RosterPath selects a different roster file (default
config/roster.json) for staged or test rosters. proof is not a roster key and
keeps its fixed proof fragments.

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

-DryRun validates the requested units exactly like a real run (roster keys,
enrollment, the NCS pin, BuildSuffix, and the NoBootloader/MinSize fragments)
but does not require west or nrfutil, writes no build directory, and prints for
each unit the key, the PC_UNIT define, the full -DEXTRA_CONF_FILE list and the
generated capability conf body.

.EXAMPLE
tools\build_firmware.ps1 -Units pitcher,catcher -DryRun
Validates both units and prints their fragments and generated confs without building.

.EXAMPLE
tools\build_firmware.ps1
Builds the default enrolled team: coach, pitcher, catcher, shortstop, center.

.EXAMPLE
tools\build_firmware.ps1 -RosterPath C:\temp\relay-roster.json -Units center -DryRun
Plans center from a staged roster that marks it as a Thread relay.

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
    [string]$RosterPath = 'config/roster.json',
    [switch]$Pristine,
    [switch]$MinSize,
    [switch]$StrictSize,
    [switch]$NoBootloader,
    [switch]$DryRun,
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
# -RosterPath defaults to config/roster.json and may be relative to the repo
# root or absolute; a test can stage a modified roster in the temp directory.
$rosterPath = $RosterPath
if (-not [System.IO.Path]::IsPathRooted($rosterPath)) {
    $rosterPath = Join-Path $root $rosterPath
}
if (-not (Test-Path -LiteralPath $rosterPath)) {
    throw "$RosterPath is missing; it is the enrollment and capability source of truth."
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
# -DryRun prints the fragment and conf it would write without creating them.
$generatedDir = Join-Path $root 'firmware/build/unit-confs'
if (-not $DryRun) {
    New-Item -ItemType Directory -Path $generatedDir -Force | Out-Null
}

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
    # The catcher's five-button menu owns its own pins, so the single recall
    # button is generated only for units without controls. The old per-role
    # Kconfig gave the catcher no field button.
    $lines.Add('CONFIG_PITCHCOMM_FIELD_BUTTON=' + $(if ($Info.controls) { 'n' } else { 'y' }))
    $lines.Add('CONFIG_PITCHCOMM_BATTERY=y')
    if ($Info.display) {
        $lines.Add('CONFIG_DISPLAY=y')
        $lines.Add('CONFIG_SSD1306=y')
    }
    # Thread device type. A relay is a Full Thread Device: routers stay
    # receive-on to forward Thread traffic, so it omits the sleepy-only symbols
    # and uses a larger stack. Everything else is a sleepy end device.
    $lines.Add('')
    if ($Info.relay) {
        $lines.Add('CONFIG_OPENTHREAD_FTD=y')
        $lines.Add('CONFIG_OPENTHREAD_MTD=n')
        $lines.Add('CONFIG_OPENTHREAD_THREAD_STACK_SIZE=8192')
    } else {
        $lines.Add('CONFIG_OPENTHREAD_FTD=n')
        $lines.Add('CONFIG_OPENTHREAD_MTD=y')
        $lines.Add('CONFIG_OPENTHREAD_MTD_SED=y')
        $lines.Add('CONFIG_OPENTHREAD_POLL_PERIOD=200')
        $lines.Add('CONFIG_OPENTHREAD_THREAD_STACK_SIZE=4096')
    }
    return $lines
}

function Get-BuildPlan {
    # Shared by the real build loop and -DryRun so both validate and print the
    # exact same fragments, defines and generated capability conf.
    param([string]$Key)

    $pcDefine = $null
    $capabilityLines = $null
    $capabilityPath = $null
    if ($Key -eq 'proof') {
        $fragmentList = 'roles/audio-proof.conf;roles/audio-unit.conf'
    } elseif ($Key -eq 'coach') {
        $fragmentList = 'roles/coach.conf'
    } else {
        $info = $rosterUnits[$Key]
        $capabilityLines = Get-CapabilityConf -Key $Key -Info $info
        $capabilityPath = Join-Path $generatedDir "$Key.conf"
        $fragmentList = @($capabilityPath, 'roles/field-common.conf')
        if ($info.audio) { $fragmentList += 'roles/audio-unit.conf' }
        $fragmentList = $fragmentList -join ';'
        $pcDefine = "PC_UNIT=PC_UNIT_$Key"
    }
    if ($NoBootloader) { $fragmentList += ';boards/no_bootloader.conf' }
    if ($MinSize) { $fragmentList += ';roles/min-size.conf' }

    $buildName = if ($BuildSuffix) { "$Key-$BuildSuffix" } else { $Key }
    [pscustomobject]@{
        Key = $Key
        BuildName = $buildName
        PcDefine = $pcDefine
        FragmentList = $fragmentList
        CapabilityLines = $capabilityLines
        CapabilityPath = $capabilityPath
    }
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

# -DryRun stops here: units, enrollment, the NCS pin and the fragment rules
# above are validated exactly like a real run, but west and nrfutil are not
# looked up and no build directory is written.
if ($DryRun) {
    Write-Host 'Dry run: no build directory is written; west and nrfutil are not required.'
    Write-Host "Pinned NCS version: $pinnedVersion (format checked; no toolchain lookup)"
    foreach ($unit in $requested) {
        $plan = Get-BuildPlan -Key $unit
        Write-Host ''
        Write-Host "==> dry-run: $($plan.Key)"
        Write-Host "  build directory: firmware/build/$($plan.BuildName) (not created)"
        Write-Host "  PC_UNIT define:  $(if ($plan.PcDefine) { $plan.PcDefine } else { '(none)' })"
        Write-Host "  -DEXTRA_CONF_FILE=$($plan.FragmentList)"
        if ($plan.CapabilityLines) {
            Write-Host "  generated capability conf ($($plan.CapabilityPath)):"
            foreach ($line in $plan.CapabilityLines) {
                Write-Host $line
            }
        } else {
            Write-Host '  generated capability conf: (none; static fragments)'
        }
    }
    exit 0
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
        $plan = Get-BuildPlan -Key $unit
        if ($plan.CapabilityLines) {
            Set-Content -LiteralPath $plan.CapabilityPath -Value ($plan.CapabilityLines -join "`n") -Encoding ascii
        }
        $buildName = $plan.BuildName
        $arguments = @('build', '-b', $board, 'firmware', '-d', "firmware/build/$buildName")
        if ($Pristine) { $arguments += '--pristine' }
        if ($WestArgs.Count) { $arguments += $WestArgs }
        $cmakeArgs = @("-DEXTRA_CONF_FILE=$($plan.FragmentList)")
        if ($plan.PcDefine) { $cmakeArgs += "-DEXTRA_CPPFLAGS=-D$($plan.PcDefine)" }
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
