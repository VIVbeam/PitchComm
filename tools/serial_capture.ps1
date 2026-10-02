<#
.SYNOPSIS
Captures a PitchComm unit console on a COM port at 115200, optionally sends
commands, and summarizes SELFTEST lines.

.DESCRIPTION
Opens the port with System.IO.Ports.SerialPort, sends each comma-separated
-Command, and writes a timestamped log under firmware/build/logs/ (override
with -LogDir). SELFTEST lines are classified PASS/FAIL/SKIP, and any FAIL
makes the script exit 1.

Without -Port the script uses the only available COM port; with no port, or
more than one, it lists them and asks for -Port. Without -Seconds it captures
until Enter is pressed (Ctrl+C also stops); with -Seconds N it stops after N
seconds. -ParseFile reads an existing log and prints the summary without
opening a port.

Exit codes: 0 no SELFTEST FAIL, 1 at least one SELFTEST FAIL, 2 no usable COM
port or a bad argument.

.EXAMPLE
tools\serial_capture.ps1 -Command "eui,selftest,status" -Seconds 20
Uses the only COM port, sends three console commands, and summarizes selftest.

.EXAMPLE
tools\serial_capture.ps1 -Port COM5 -Command selftest
Captures COM5 until Enter is pressed.

.EXAMPLE
tools\serial_capture.ps1 -ParseFile firmware\build\logs\capture-20261002-120000-COM5.log
Re-summarizes an earlier capture.
#>
param(
    [string]$Port = '',
    [int]$Baud = 115200,
    [string]$Command = '',
    [int]$Seconds = 0,
    [string]$LogDir = '',
    [string]$ParseFile = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $LogDir) { $LogDir = Join-Path $root 'firmware/build/logs' }

function Get-SelftestResult {
    param([string[]]$Lines)
    $entries = New-Object 'System.Collections.Generic.List[object]'
    foreach ($line in $Lines) {
        $raw = ([string]$line).Trim()
        if ($raw -match '>>>') { continue }
        if ($raw -notmatch '(?i)SELFTEST\b') { continue }
        $status = 'INFO'
        if ($raw -match '(?i)\bFAIL\b') { $status = 'FAIL' }
        elseif ($raw -match '(?i)\bSKIP\b') { $status = 'SKIP' }
        elseif ($raw -match '(?i)\bPASS\b') { $status = 'PASS' }
        elseif ($raw -match '(?i)=READY\b') { $status = 'PASS' }
        elseif ($raw -match '(?i)\bOFFLINE\b') { $status = 'FAIL' }
        $entries.Add([pscustomobject]@{ status = $status; line = $raw })
    }
    return ,$entries
}

function Show-SelftestSummary {
    param($Entries)
    $pass = @($Entries | Where-Object { $_.status -eq 'PASS' })
    $fail = @($Entries | Where-Object { $_.status -eq 'FAIL' })
    $skip = @($Entries | Where-Object { $_.status -eq 'SKIP' })
    $info = @($Entries | Where-Object { $_.status -eq 'INFO' })
    Write-Host ''
    if (-not $Entries.Count) {
        Write-Host 'SELFTEST summary: no SELFTEST lines found.' -ForegroundColor Yellow
        Write-Host 'The selftest command only runs on a flashed board. Send it with -Command selftest and check the port, cable and baud rate.' -ForegroundColor DarkGray
        return 0
    }
    Write-Host ('SELFTEST summary: {0} PASS, {1} FAIL, {2} SKIP, {3} info' -f
        $pass.Count, $fail.Count, $skip.Count, $info.Count)
    $colors = @{ PASS = 'Green'; FAIL = 'Red'; SKIP = 'Yellow'; INFO = 'DarkGray' }
    foreach ($entry in $Entries) {
        Write-Host ('  [{0,-4}] {1}' -f $entry.status, $entry.line) -ForegroundColor $colors[$entry.status]
    }
    return $fail.Count
}

# --- offline summary mode ---------------------------------------------------
if ($ParseFile) {
    if (-not (Test-Path -LiteralPath $ParseFile -PathType Leaf)) {
        Write-Host ("Log file not found: {0}" -f $ParseFile) -ForegroundColor Red
        exit 2
    }
    $lines = @(Get-Content -LiteralPath $ParseFile -Encoding UTF8)
    $failCount = Show-SelftestSummary (Get-SelftestResult $lines)
    Write-Host ("Log: {0}" -f (Resolve-Path -LiteralPath $ParseFile).Path)
    if ($failCount -gt 0) { exit 1 }
    exit 0
}

# --- resolve the port -------------------------------------------------------
$available = @([System.IO.Ports.SerialPort]::GetPortNames())
if (-not $Port) {
    if ($available.Count -eq 1) {
        $Port = $available[0]
        Write-Host ("Using the only COM port: {0}" -f $Port)
    } elseif ($available.Count -eq 0) {
        Write-Host 'No COM port found.' -ForegroundColor Red
        Write-Host 'Connect the XIAO debugger USB cable, confirm the board enumerates under Device Manager > Ports, then retry. Or pass -Port COMx explicitly.' -ForegroundColor DarkGray
        exit 2
    } else {
        Write-Host ("Several COM ports found: {0}" -f ($available -join ', ')) -ForegroundColor Red
        Write-Host 'Pass -Port COMx. Device Manager > Ports shows which one is the XIAO debugger.' -ForegroundColor DarkGray
        exit 2
    }
}

if ($Seconds -le 0 -and [Console]::IsInputRedirected) {
    $Seconds = 15
    Write-Host 'stdin is redirected and no -Seconds was given; bounding the capture at 15 seconds.' -ForegroundColor Yellow
}

if (-not (Test-Path -LiteralPath $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path $LogDir ("capture-{0}-{1}.log" -f $stamp, $Port)

$commands = @()
if ($Command) {
    $commands = @($Command -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

$serial = $null
$log = $null
$failCount = 0
$selftestLines = New-Object 'System.Collections.Generic.List[string]'
try {
    $serial = New-Object System.IO.Ports.SerialPort($Port, $Baud, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
    $serial.ReadTimeout = 1000
    $serial.WriteTimeout = 1000
    try {
        $serial.Open()
    } catch {
        Write-Host ("Could not open {0}: {1}" -f $Port, $_.Exception.Message) -ForegroundColor Red
        Write-Host 'Close other terminals (PuTTY, another capture) and check the port name; retry with -Port COMx from Device Manager > Ports.' -ForegroundColor DarkGray
        exit 2
    }

    $log = New-Object System.IO.StreamWriter($logPath, $false, (New-Object System.Text.UTF8Encoding($false)))
    $log.WriteLine('# PitchComm serial capture')
    $log.WriteLine(('# started {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')))
    $log.WriteLine(('# port {0}, baud {1}, duration {2}' -f $Port, $Baud, $(if ($Seconds -gt 0) { "$Seconds seconds" } else { 'until Enter' })))
    if ($commands.Count) { $log.WriteLine(('# commands: {0}' -f ($commands -join ', '))) }

    function Write-Log {
        param([string]$Text)
        $line = ('[{0}] {1}' -f (Get-Date -Format 'HH:mm:ss.fff'), $Text)
        $script:log.WriteLine($line)
        Write-Host $line
    }

    Write-Host ("Capturing {0} at {1} to {2}" -f $Port, $Baud, $logPath)
    Start-Sleep -Milliseconds 400
    if ($commands.Count) {
        try { $serial.Write("`r`n") } catch { }
        Start-Sleep -Milliseconds 200
        foreach ($item in $commands) {
            Write-Log ('>>> ' + $item)
            $serial.WriteLine($item)
            Start-Sleep -Milliseconds 500
        }
    }

    $pending = ''
    $deadline = if ($Seconds -gt 0) { (Get-Date).AddSeconds($Seconds) } else { $null }
    $stop = $false
    while (-not $stop) {
        if ($deadline -and (Get-Date) -ge $deadline) { break }
        if (-not $serial.IsOpen) { break }
        $chunk = ''
        try { $chunk = $serial.ReadExisting() } catch { $chunk = '' }
        if ($chunk) {
            $pending += $chunk
            while ($true) {
                $index = $pending.IndexOf("`n")
                if ($index -lt 0) { break }
                $line = $pending.Substring(0, $index).TrimEnd("`r")
                $pending = $pending.Substring($index + 1)
                if ($line -match '(?i)SELFTEST\b') { $selftestLines.Add($line) }
                Write-Log $line
            }
        } else {
            Start-Sleep -Milliseconds 50
        }
        if (-not $deadline -and -not [Console]::IsInputRedirected) {
            try {
                if ([Console]::KeyAvailable) {
                    $key = [Console]::ReadKey($true)
                    if ($key.Key -eq 'Enter') { $stop = $true }
                }
            } catch { }
        }
    }
    if ($pending) {
        $line = $pending.TrimEnd("`r")
        if ($line) {
            if ($line -match '(?i)SELFTEST\b') { $selftestLines.Add($line) }
            Write-Log $line
        }
    }
    Write-Host ("Capture complete ({0} bytes of console output)." -f (Get-Item -LiteralPath $logPath).Length)
} finally {
    if ($serial) {
        if ($serial.IsOpen) { $serial.Close() }
        $serial.Dispose()
    }
    if ($log) { $log.Dispose() }
}

$failCount = Show-SelftestSummary (Get-SelftestResult $selftestLines)
Write-Host ("Log: {0}" -f $logPath)
if ($failCount -gt 0) { exit 1 }
exit 0
