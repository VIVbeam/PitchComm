# Build and run the portable-core host tests.
param(
    [string]$Compiler = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Compiler) {
    $Compiler = (Get-Command g++ -ErrorAction SilentlyContinue).Source
    if (-not $Compiler) { $Compiler = (Get-Command clang++ -ErrorAction Stop).Source }
}
$out = Join-Path $env:TEMP 'pitchcomm-test-core.exe'
$sources = @(
    (Join-Path $PSScriptRoot 'test_core.cpp')
)
& $Compiler -std=c++17 -Wall -Wextra -Werror -I (Join-Path $PSScriptRoot '../include') @sources -o $out
if ($LASTEXITCODE -ne 0) { throw 'Test build failed' }
& $out
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
