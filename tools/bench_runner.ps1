<#
.SYNOPSIS
Runs the PitchComm bench day in order: toolchain check, optional catalog and
audio rebuild, firmware builds, then the per-board flash and test walk.

.DESCRIPTION
One command for bench day. It calls the existing tools and does not duplicate
their logic:

  1. tools\check_toolchain.ps1          required tools and repo state
  2. python tools\generate_catalog.py   with -Rebuild
     python tools\build_audio_fs.py     with -Rebuild (self-verifying)
  3. tools\build_firmware.ps1           one build per requested unit
  4. the flash walk                     flash command and per-unit steps

The walk prints the flash order and the per-unit steps for each board. It does
not flash by itself: connect one board at a time, run the printed command, then
press Enter for the next board. -Yes skips the pauses and prints the complete
runbook in one pass. -DryRun prints the plan and the exact commands without
running anything.

The standard flash order is coach, pitcher, catcher, shortstop, center. The
roster keys and their capabilities come from config/roster.json; -Roles is an
alias for -Units that maps centerfield to center. Pass -Units to run a subset
(for example -Units coach,pitcher for the bench minimum). The audio step runs
only for units with the audio capability after an erase. Provisioning happens
after every EUI is recorded, so the runbook ends with the provision, rebuild,
and reflash loop.

.EXAMPLE
tools\bench_runner.ps1 -DryRun
Prints the full plan and commands; changes nothing.

.EXAMPLE
tools\bench_runner.ps1 -Rebuild
Checks the toolchain, regenerates the catalog and audio image, builds every
enrolled unit, then walks the boards with a pause between them.

.EXAMPLE
tools\bench_runner.ps1 -Units coach,pitcher -Yes
Prints the bench-minimum runbook without pauses.
#>
param(
    [string[]]$Units = @('coach', 'pitcher', 'catcher', 'shortstop', 'center'),
    [string[]]$Roles = @(),
    [switch]$Rebuild,
    [switch]$Yes,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tools = $PSScriptRoot
$powershell = (Get-Command powershell -ErrorAction Stop).Source

# -Units is the roster-facing name; -Roles is the compatibility alias. Both
# accept the direct form (-Units pitcher,catcher) and the powershell -File form,
# which arrives as one comma-joined string.
if ($PSBoundParameters.ContainsKey('Roles') -and $PSBoundParameters.ContainsKey('Units')) {
    throw 'Use -Units or -Roles, not both.'
}
$requested = if ($PSBoundParameters.ContainsKey('Roles')) { $Roles } else { $Units }
$requested = @($requested | ForEach-Object { $_ -split ',' } |
    ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ })
$requested = @($requested | ForEach-Object { if ($_ -eq 'centerfield') { 'center' } else { $_ } } |
    Select-Object -Unique)
if (-not $requested.Count) { throw 'No units requested. Pass -Units with roster keys plus proof.' }

$rosterPath = Join-Path $root 'config/roster.json'
if (-not (Test-Path -LiteralPath $rosterPath)) {
    throw 'config/roster.json is missing; it lists the enrollable units and capabilities.'
}
$roster = Get-Content -LiteralPath $rosterPath -Raw | ConvertFrom-Json
$rosterUnits = @{}
foreach ($unit in $roster.units) {
    $rosterUnits[$unit.key] = $unit
}
foreach ($unit in $requested) {
    if ($unit -eq 'coach' -or $unit -eq 'proof') { continue }
    if (-not $rosterUnits.ContainsKey($unit)) {
        throw ('Unknown unit(s): {0}. Roster keys: {1}; plus coach and proof.' -f
            $unit, ((@($rosterUnits.Keys) | Sort-Object) -join ', '))
    }
}

function Format-Command {
    param([string]$File, [string[]]$Arguments)
    $parts = New-Object 'System.Collections.Generic.List[string]'
    $parts.Add($(if ($File -match '\s') { '"' + $File + '"' } else { $File }))
    foreach ($argument in $Arguments) {
        $parts.Add($(if ($argument -match '\s') { '"' + $argument + '"' } else { $argument }))
    }
    return ($parts -join ' ')
}

function Invoke-Tool {
    param([string]$Label, [string]$File, [string[]]$Arguments)
    if ($DryRun) {
        Write-Host ('[dry-run] {0}' -f (Format-Command $File $Arguments))
        return
    }
    Write-Host ''
    Write-Host ('==> {0}' -f $Label)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw ("{0} failed (exit {1}). Fix the output above and rerun tools\bench_runner.ps1." -f $Label, $LASTEXITCODE)
    }
}

function Get-UnitLabel {
    param([string]$Key)
    if ($Key -eq 'coach') { return 'Coach console (Thread leader)' }
    if ($Key -eq 'proof') { return 'LE Audio proof (no call link)' }
    $info = $rosterUnits[$Key]
    $capabilities = New-Object 'System.Collections.Generic.List[string]'
    if ($info.audio) { $capabilities.Add('LE Audio') }
    if ($info.display) { $capabilities.Add('OLED') }
    if ($info.controls) { $capabilities.Add('menu') }
    if ($info.pitches) { $capabilities.Add('pitch calls') }
    $suffix = if ($capabilities.Count) { $capabilities -join ', ' } else { 'receiver' }
    return ('{0} ({1})' -f $info.label, $suffix)
}

function Get-BoardSteps {
    param([string]$Key)
    $capture = 'tools\serial_capture.ps1 -Port COMx -Command "eui,selftest,status" -Seconds 20'
    switch ($Key) {
        'coach' {
            return @(
                'Flash:  tools\flash_firmware.ps1 -Role coach -Erase   (-Erase on a first flash or layout change)',
                ('Console: ' + $capture),
                'Record the EUI; selftest must show only PASS or SKIP, never FAIL.',
                'Keep the coach powered from now on: it is the Thread leader and relay.'
            )
        }
        'catcher' {
            return @(
                'Flash:  tools\flash_firmware.ps1 -Role catcher -Erase',
                ('Console: ' + $capture),
                'Check selftest: OLED, CONTROLS and BATTERY PASS; STORAGE and AUDIO SKIP.',
                'Run the menu: pitch, height, location, send; Back and long-hold volume.'
            )
        }
        'pitcher' {
            return @(
                'Flash:  tools\flash_firmware.ps1 -Role pitcher -Erase',
                ('Console: ' + $capture),
                'Check selftest: CONTROLS and BATTERY PASS; OLED SKIP; AUDIO READY or SKIP.',
                'After an erase, load the calls: python tools\build_audio_fs.py then tools\flash_audio.ps1.'
            )
        }
        'shortstop' {
            return @(
                'Flash:  tools\flash_firmware.ps1 -Role shortstop -Erase',
                ('Console: ' + $capture),
                'Check selftest: OLED, CONTROLS and BATTERY PASS; AUDIO SKIP.',
                'Check the display strip and the recall button.'
            )
        }
        'center' {
            return @(
                'Flash:  tools\flash_firmware.ps1 -Role center -Erase',
                ('Console: ' + $capture),
                'Check selftest: OLED, CONTROLS and BATTERY PASS; AUDIO SKIP.',
                'Check the display strip and the recall button.'
            )
        }
        'proof' {
            return @(
                'Flash:  tools\flash_firmware.ps1 -Role proof -Erase',
                ('Console: ' + $capture),
                'Pair the JY300, then watch for the spoken FASTBALL / UP / INSIDE call.'
            )
        }
        default {
            return @('Flash the image, open the console, and run selftest.')
        }
    }
}

$enrolled = @($roster.units | Where-Object { $_.enrolled })
$unitArgs = New-Object 'System.Collections.Generic.List[string]'
foreach ($unit in $enrolled) {
    $unitArgs.Add(('--unit {0}=EUI' -f $unit.key))
}

Write-Host 'PitchComm bench runner'
Write-Host ('  root:   {0}' -f $root)
Write-Host ('  units:  {0}' -f ($requested -join ', '))
Write-Host ('  mode:   {0}' -f $(if ($DryRun) { 'dry run, nothing is executed' } else { 'live' }))
Write-Host ('  rebuild catalog and audio: {0}' -f $(if ($Rebuild) { 'yes' } else { 'no' }))

# --- 1. toolchain -----------------------------------------------------------
Invoke-Tool 'Toolchain check' $powershell @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $tools 'check_toolchain.ps1'))

# --- 2. optional rebuild ----------------------------------------------------
if ($Rebuild) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $python) {
        throw 'python was not found on PATH. Install Python 3.10+ and retry; tools\check_toolchain.ps1 reports the details.'
    }
    Invoke-Tool 'Regenerate the call catalog' $python @((Join-Path $tools 'generate_catalog.py'))
    Invoke-Tool 'Rebuild the audio filesystem (self-verifying)' $python @((Join-Path $tools 'build_audio_fs.py'))
}

# --- 3. builds (one call per unit so a failure names the unit) --------------
foreach ($unit in $requested) {
    Invoke-Tool ("Build {0}" -f $unit) $powershell @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $tools 'build_firmware.ps1'), '-Units', $unit)
}

# --- 4. flash walk ----------------------------------------------------------
Write-Host ''
Write-Host 'Flash walk (one board at a time)'
for ($index = 0; $index -lt $requested.Count; $index++) {
    $unit = $requested[$index]
    Write-Host ''
    Write-Host ('Board {0}/{1}: {2} - {3}' -f ($index + 1), $requested.Count, $unit, (Get-UnitLabel $unit))
    Write-Host ('  image: firmware/build/{0}' -f $unit)
    foreach ($step in (Get-BoardSteps $unit)) {
        Write-Host ('  - {0}' -f $step)
    }
    if (-not $Yes -and -not $DryRun) {
        Read-Host '  Run the steps above, then press Enter for the next board (Ctrl+C stops)' | Out-Null
    }
}

Write-Host ''
Write-Host 'After every EUI is recorded'
Write-Host '  - Provision the team:'
Write-Host ('      python tools\provision.py --coach EUI {0} --channel 15' -f ($unitArgs -join ' '))
Write-Host '  - Rebuild every unit (team_config.h changed): tools\build_firmware.ps1'
Write-Host '  - Reflash every board, then repeat the audio step on audio units.'
Write-Host '  - Captures are under firmware\build\logs\; the full checklist is dev\test-checklist.md.'
if ($DryRun) {
    Write-Host ''
    Write-Host 'Dry run complete: nothing was executed.'
}
exit 0
