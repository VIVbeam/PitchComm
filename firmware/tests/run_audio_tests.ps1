# Build and run the portable streaming-resampler host tests.
param(
    [string]$Compiler = '',
    [switch]$Sanitize
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Compiler) {
    $Compiler = (Get-Command g++ -ErrorAction SilentlyContinue).Source
    if (-not $Compiler) { $Compiler = (Get-Command clang++ -ErrorAction Stop).Source }
}
$out = Join-Path $env:TEMP 'pitchcomm-test-audio.exe'
$sources = @(
    (Join-Path $PSScriptRoot 'test_audio.cpp')
)
$flags = @('-std=c++17', '-Wall', '-Wextra', '-Werror', '-I', (Join-Path $PSScriptRoot '../include'))
if ($Sanitize) {
    # UBSan catches any overflow in the interpolation/gain math. Some MSYS2
    # toolchains ship g++ without the sanitizer runtimes; fall back to -O1.
    & $Compiler @flags '-fsanitize=address,undefined' '-fno-omit-frame-pointer' '-g' @sources -o $out
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'sanitizer build failed (libasan/libubsan missing?); falling back to -O1 -g'
        & $Compiler @flags '-O1' '-g' @sources -o $out
    }
} else {
    & $Compiler @flags @sources -o $out
}
if ($LASTEXITCODE -ne 0) { throw 'Test build failed' }
& $out
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
