# Check the standalone repository before an SDK build; no boards are needed.
param([string]$Compiler = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$node = (Get-Command node -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
# Compiler tests use PowerShell 7 when available, including from Windows PowerShell.
$testShell = (Get-Command pwsh -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $testShell) { $testShell = (Get-Command powershell -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source }
$shellFlags = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File')

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Repository check failed: $Program (exit $LASTEXITCODE)." }
}

Push-Location $root
try {
    Invoke-Checked $python @('-B', 'tools/check_setup.py')
    $compilerArgs = @()
    if ($Compiler) { $compilerArgs = @('-Compiler', $Compiler) }
    foreach ($suite in @('run_host_tests.ps1', 'run_audio_tests.ps1', 'run_application_tests.ps1')) {
        Invoke-Checked $testShell ($shellFlags + @("firmware/tests/$suite") + $compilerArgs)
    }
    # Expand explicitly: Node versions differ in positional glob handling.
    $tests = @(Get-ChildItem -LiteralPath 'gui/test' -Filter '*.test.mjs' | Sort-Object Name | ForEach-Object { $_.FullName })
    if (-not $tests.Count) { throw 'GUI tests are missing from the repository.' }
    Invoke-Checked $node (@('--test', '--test-reporter=dot') + $tests)
    Invoke-Checked $testShell ($shellFlags + @('tools/build_firmware.ps1', '-DryRun', '-Units', 'coach,pitcher,catcher,shortstop,center'))
    Invoke-Checked $testShell ($shellFlags + @('tools/build_firmware.ps1', '-DryRun', '-Units', 'coach,pitcher,catcher,shortstop,center', '-MinSize', '-NoBootloader', '-BuildSuffix', 'nb'))
    Write-Host 'Repository checks passed. Nordic SDK compilation, image size and hardware operation still require validation.'
} finally {
    Pop-Location
}
