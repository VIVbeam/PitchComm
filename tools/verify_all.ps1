<#
.SYNOPSIS
Runs the PitchComm host verification steps in one pass for bench days and CI.

.DESCRIPTION
Runs the checks a bench day or CI needs, in order, from the repository root
resolved from this script's own path:

  1. python tools/preflight.py --audio
  2. firmware/tests/run_host_tests.ps1
  3. firmware/tests/run_audio_tests.ps1
  4. gui/test/run_tests.ps1
  5. python tools/test_tools.py
  6. dev/host_compile/run.ps1 -Provisioned -MinSize -RawI2c -RosterVariant
  7. tools/check_build_plan.ps1
  8. python tools/audit_repo.py

Each step runs in its own child process, captures all output to a per-run
temporary log, and prints one PASS or FAIL line. A failing step also prints
the tail of its log. Every step still runs after a failure so the summary
shows the whole picture, and the script exits 1 when any required step failed.

By default tools/check_toolchain.ps1 runs last. Its result is informational:
west and nrfutil may be absent by design on a host-only machine, so it never
fails the run.

-Quick skips the host compile (step 6) and the toolchain check for a fast
host-only pass. -SkipToolchain skips only the toolchain check.

The runner does not modify the existing suites and writes nothing into the
repository: the suites already use the system temporary directory, and the
logs go to a fresh temporary directory printed at the end. Re-running is safe.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File tools\verify_all.ps1
Runs every step and prints the summary table.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File tools\verify_all.ps1 -Quick
Skips the host compile and the toolchain check.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File tools\verify_all.ps1 -SkipToolchain
Runs the host suite but not the informational toolchain check.

.NOTES
Windows PowerShell 5.1 compatible. Built-in cmdlets only, no network.
#>
[CmdletBinding()]
param(
    [switch]$SkipToolchain,
    [switch]$Quick
)

$ErrorActionPreference = 'Stop'

# Resolve the repository root from this script's own path so the runner works
# from any working directory.
$scriptPath = $PSCommandPath
if (-not $scriptPath) { $scriptPath = $MyInvocation.MyCommand.Path }
$root = Split-Path -Parent (Split-Path -Parent $scriptPath)
if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw ('Could not resolve the repository root from {0}' -f $scriptPath)
}

# Child PowerShell steps run in a fresh process so their exit codes are
# reliable and an exit inside a suite cannot stop this runner. Prefer Windows
# PowerShell 5.1; fall back to the current host when it is not available.
$powershellExe = (Get-Command powershell.exe -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1)
if ($powershellExe) { $powershellExe = $powershellExe.Source }
else { $powershellExe = (Get-Process -Id $PID).Path }

$pythonExe = (Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1)
if ($pythonExe) { $pythonExe = $pythonExe.Source }
else { $pythonExe = 'python' }

$logDir = Join-Path ([System.IO.Path]::GetTempPath()) ('pitchcomm-verify-all-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Format-Elapsed {
    param([double]$Seconds)
    if ($Seconds -ge 60) {
        $minutes = [int][Math]::Floor($Seconds / 60)
        return ('{0}m {1:0.0}s' -f $minutes, ($Seconds - ($minutes * 60)))
    }
    return ('{0:0.0}s' -f $Seconds)
}

$steps = New-Object 'System.Collections.Generic.List[object]'
function Add-Step {
    param(
        [string]$Name,
        [ValidateSet('python', 'powershell')][string]$Kind,
        [string]$Script,
        [string[]]$Arguments = @(),
        [string]$LogName,
        [switch]$Informational,
        [string]$SkipReason = ''
    )
    $steps.Add([pscustomobject]@{
        Name = $Name
        Kind = $Kind
        Script = $Script
        Arguments = $Arguments
        LogPath = Join-Path $logDir $LogName
        Informational = [bool]$Informational
        SkipReason = $SkipReason
    }) | Out-Null
}

# The eight required host steps, in fixed order.
Add-Step -Name 'preflight --audio' -Kind python `
    -Script (Join-Path $root 'tools\preflight.py') -Arguments @('--audio') `
    -LogName '01-preflight-audio.log'
Add-Step -Name 'host tests' -Kind powershell `
    -Script (Join-Path $root 'firmware\tests\run_host_tests.ps1') `
    -LogName '02-host-tests.log'
Add-Step -Name 'audio tests' -Kind powershell `
    -Script (Join-Path $root 'firmware\tests\run_audio_tests.ps1') `
    -LogName '03-audio-tests.log'
Add-Step -Name 'GUI tests' -Kind powershell `
    -Script (Join-Path $root 'gui\test\run_tests.ps1') `
    -LogName '04-gui-tests.log'
Add-Step -Name 'tool tests' -Kind python `
    -Script (Join-Path $root 'tools\test_tools.py') `
    -LogName '05-tool-tests.log'

# -Quick skips the host compile and the toolchain check.
$quickReason = ''
if ($Quick) { $quickReason = 'quick mode' }
Add-Step -Name 'host compile (all modes)' -Kind powershell `
    -Script (Join-Path $root 'dev\host_compile\run.ps1') `
    -Arguments @('-Provisioned', '-MinSize', '-RawI2c', '-RosterVariant') `
    -LogName '06-host-compile.log' -SkipReason $quickReason

Add-Step -Name 'build plan (dry run)' -Kind powershell `
    -Script (Join-Path $root 'tools\check_build_plan.ps1') `
    -LogName '07-build-plan.log'

Add-Step -Name 'repo audit' -Kind python `
    -Script (Join-Path $root 'tools\audit_repo.py') `
    -LogName '08-repo-audit.log'

$toolchainReason = $quickReason
if (-not $Quick -and $SkipToolchain) { $toolchainReason = '-SkipToolchain' }
Add-Step -Name 'toolchain check' -Kind powershell `
    -Script (Join-Path $root 'tools\check_toolchain.ps1') `
    -LogName '09-toolchain.log' -Informational -SkipReason $toolchainReason

$results = New-Object 'System.Collections.Generic.List[object]'
$totalWatch = [System.Diagnostics.Stopwatch]::StartNew()

Write-Host 'PitchComm verification run'
Write-Host ('  root: {0}' -f $root)
Write-Host ('  mode: {0}' -f $(if ($Quick) { 'quick, host compile and toolchain skipped' } else { 'full' }))
Write-Host ('  logs: {0}' -f $logDir)
Write-Host ''

Push-Location -LiteralPath $root
try {
    foreach ($step in $steps) {
        if ($step.SkipReason) {
            Write-Host ('SKIP        {0} ({1})' -f $step.Name, $step.SkipReason) -ForegroundColor Yellow
            $results.Add([pscustomobject]@{
                Name = $step.Name
                Result = 'SKIP'
                Elapsed = '-'
            }) | Out-Null
            continue
        }

        $exe = $pythonExe
        $argv = @($step.Script) + $step.Arguments
        if ($step.Kind -eq 'powershell') {
            $exe = $powershellExe
            $argv = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $step.Script) + $step.Arguments
        }

        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        $exitCode = 1
        # Windows PowerShell 5.1 turns native stderr into terminating errors
        # while $ErrorActionPreference is Stop, so relax it for the child call.
        $previousEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & $exe @argv *> $step.LogPath
            $exitCode = $LASTEXITCODE
        } catch {
            Add-Content -LiteralPath $step.LogPath -Value ('runner: ' + $_.Exception.Message) `
                -ErrorAction SilentlyContinue
        } finally {
            $ErrorActionPreference = $previousEap
        }
        $watch.Stop()

        $passed = ($exitCode -eq 0)
        if ($passed) {
            $result = 'PASS'
            $color = 'Green'
        } elseif ($step.Informational) {
            $result = 'FAIL (info)'
            $color = 'Yellow'
        } else {
            $result = 'FAIL'
            $color = 'Red'
        }
        $elapsed = Format-Elapsed $watch.Elapsed.TotalSeconds
        Write-Host ('{0,-11} {1} ({2})' -f $result, $step.Name, $elapsed) -ForegroundColor $color

        if (-not $passed) {
            Write-Host ('            log: {0}' -f $step.LogPath) -ForegroundColor DarkGray
            $tail = @(Get-Content -LiteralPath $step.LogPath -Tail 25 -ErrorAction SilentlyContinue)
            foreach ($line in $tail) {
                Write-Host ('            | {0}' -f $line)
            }
        }

        $results.Add([pscustomobject]@{
            Name = $step.Name
            Result = $result
            Elapsed = $elapsed
        }) | Out-Null
    }
} finally {
    Pop-Location
}
$totalWatch.Stop()

# Summary table: step, result, elapsed.
$nameWidth = 4
foreach ($row in $results) {
    if ($row.Name.Length -gt $nameWidth) { $nameWidth = $row.Name.Length }
}

Write-Host ''
Write-Host '== summary =='
Write-Host ('{0}  {1}  {2}' -f 'Step'.PadRight($nameWidth), 'Result'.PadRight(11), 'Elapsed'.PadLeft(9))
Write-Host ('{0}  {1}  {2}' -f ('-' * $nameWidth), ('-' * 11), ('-' * 9))
foreach ($row in $results) {
    Write-Host ('{0}  {1}  {2}' -f $row.Name.PadRight($nameWidth), $row.Result.PadRight(11), $row.Elapsed.PadLeft(9))
}
Write-Host ''
Write-Host ('Total elapsed: {0}' -f (Format-Elapsed $totalWatch.Elapsed.TotalSeconds))
Write-Host ('Logs: {0}' -f $logDir)
if (@($results | Where-Object { $_.Result -eq 'FAIL (info)' }).Count -gt 0) {
    Write-Host 'FAIL (info) is informational only and does not affect the exit code.'
}

$failed = @($results | Where-Object { $_.Result -eq 'FAIL' })
if ($failed.Count -gt 0) {
    Write-Host ''
    Write-Host ('{0} required step(s) failed.' -f $failed.Count) -ForegroundColor Red
    exit 1
}
Write-Host ''
Write-Host 'All required steps passed.' -ForegroundColor Green
exit 0
