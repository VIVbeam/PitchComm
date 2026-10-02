# Regression tests for the PitchComm Python tooling (stdlib-only unittest suite).
#
# Usage: powershell -File tools/run_tool_tests.ps1
# The tests read the repository but never write to it; fixtures live in the
# system temporary directory.
[CmdletBinding()]
param(
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    & $Python -m unittest -v tools.test_tools
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
