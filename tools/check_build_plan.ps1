<#
.SYNOPSIS
Checks the generated field build plan with tools/build_firmware.ps1 -DryRun.

.DESCRIPTION
Plans every default unit plus the proof without a toolchain and pins the
capability rules that a host-only machine cannot compile:

  - every default unit and the proof plan cleanly
  - the pitcher fragment enables audio and the recall button
  - the catcher fragment enables the menu and the display driver and leaves the
    recall button off, because the five-button menu owns those pins
  - a display unit enables the OLED and keeps audio off
  - the proof uses the proof fragments
  - an unenrolled unit is rejected by name

No build directory is written and west is not required. Exits 1 and lists the
failed checks when any rule breaks.

.NOTES
Windows PowerShell 5.1 compatible. Built-in cmdlets only, no network.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$scriptPath = $PSCommandPath
if (-not $scriptPath) { $scriptPath = $MyInvocation.MyCommand.Path }
$root = Split-Path -Parent (Split-Path -Parent $scriptPath)
$buildScript = Join-Path $root 'tools\build_firmware.ps1'
if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw ('Could not find tools\build_firmware.ps1 under {0}' -f $root)
}

$powershellExe = (Get-Command powershell.exe -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1)
if ($powershellExe) { $powershellExe = $powershellExe.Source }
else { $powershellExe = (Get-Process -Id $PID).Path }

$failures = New-Object 'System.Collections.Generic.List[string]'

function Invoke-DryRun {
    param([string]$Units)
    $argv = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $buildScript, '-DryRun', '-Units', $Units)
    # Native stderr with -DryRun on the rejection path must not become a
    # terminating error while the preference is Stop.
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $powershellExe @argv 2>&1 | Out-String
        return [pscustomobject]@{ Output = $output; ExitCode = $LASTEXITCODE }
    } finally {
        $ErrorActionPreference = $previousEap
    }
}

function Get-DryRunSection {
    param([string]$Output, [string]$Unit)
    $match = [regex]::Match($Output, '(?s)==> dry-run: ' + [regex]::Escape($Unit) + '(.*?)(?==> dry-run: |\z)')
    if ($match.Success) { return $match.Groups[1].Value }
    return ''
}

function Assert-Check {
    param([string]$Name, [bool]$Condition)
    if ($Condition) {
        Write-Host ('PASS {0}' -f $Name)
    } else {
        Write-Host ('FAIL {0}' -f $Name) -ForegroundColor Red
        $failures.Add($Name) | Out-Null
    }
}

$all = Invoke-DryRun 'coach,pitcher,catcher,shortstop,center,proof'
Assert-Check -Name 'all default units and the proof plan (exit 0)' -Condition ($all.ExitCode -eq 0)

$coach = Get-DryRunSection $all.Output 'coach'
$pitcher = Get-DryRunSection $all.Output 'pitcher'
$catcher = Get-DryRunSection $all.Output 'catcher'
$center = Get-DryRunSection $all.Output 'center'
$proof = Get-DryRunSection $all.Output 'proof'

Assert-Check -Name 'coach uses the coach fragment and no unit define' `
    -Condition (($coach -match 'roles/coach\.conf') -and ($coach -notmatch 'PC_UNIT='))
Assert-Check -Name 'pitcher enables audio' -Condition ($pitcher -match 'CONFIG_PITCHCOMM_AUDIO=y')
Assert-Check -Name 'pitcher enables the recall button' -Condition ($pitcher -match 'CONFIG_PITCHCOMM_FIELD_BUTTON=y')
Assert-Check -Name 'pitcher carries the unit define' -Condition ($pitcher -match 'PC_UNIT=PC_UNIT_pitcher')
Assert-Check -Name 'catcher enables the menu' -Condition ($catcher -match 'CONFIG_PITCHCOMM_CATCHER_MENU=y')
Assert-Check -Name 'catcher enables the display driver' -Condition ($catcher -match 'CONFIG_SSD1306=y')
Assert-Check -Name 'catcher leaves the recall button to the menu' -Condition ($catcher -match 'CONFIG_PITCHCOMM_FIELD_BUTTON=n')
Assert-Check -Name 'center enables the display and not audio' `
    -Condition (($center -match 'CONFIG_PITCHCOMM_DISPLAY=y') -and ($center -match 'CONFIG_PITCHCOMM_AUDIO=n'))
Assert-Check -Name 'proof uses the proof fragments' -Condition ($proof -match 'roles/audio-proof\.conf;roles/audio-unit\.conf')

$rejected = Invoke-DryRun 'first'
Assert-Check -Name 'unenrolled unit is rejected' -Condition ($rejected.ExitCode -ne 0)
Assert-Check -Name 'rejection names the key' -Condition ($rejected.Output -match "Unit 'first' is not enrolled")

if ($failures.Count -gt 0) {
    Write-Host ('build plan check failed: {0} check(s)' -f $failures.Count) -ForegroundColor Red
    exit 1
}
Write-Host 'Build plan check passed.'
exit 0
