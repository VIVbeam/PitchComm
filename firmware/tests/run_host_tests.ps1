# Build and run the portable-core host tests.
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
$out = Join-Path $env:TEMP 'pitchcomm-test-core.exe'
$sources = @(
    (Join-Path $PSScriptRoot 'test_core.cpp')
)
$flags = @('-std=c++17', '-Wall', '-Wextra', '-Werror', '-I', (Join-Path $PSScriptRoot '../include'))
if ($Sanitize) {
    # ASan/UBSan catches out-of-bounds reads in the decode fuzz. Some MSYS2
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

# pc/addr.h must stay valid C: the Zephyr radio link includes it from C, while
# the host suite is C++, so the C++ build alone cannot catch C-only breakage.
$probe = Join-Path $env:TEMP 'pitchcomm-addr-c-probe.c'
@'
#include "pc/addr.h"
static uint8_t eui[8];
static uint8_t out[16];
int main(void) {
    pc_link_local_from_eui(eui, out);
    return out[0] == 0xfe && out[1] == 0x80 ? 0 : 1;
}
'@ | Set-Content -Path $probe -Encoding ASCII
& $Compiler '-std=c11' '-Wall' '-Wextra' '-Werror' '-I' (Join-Path $PSScriptRoot '../include') '-x' 'c' '-fsyntax-only' $probe
if ($LASTEXITCODE -ne 0) { throw 'pc/addr.h is not valid C' }

& $out
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }

# The shared GUI command and state fixtures must parse with the firmware
# parsers and stay structurally valid.
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$fixtureCommands = Join-Path $repo 'dev/protocol/gui_commands.txt'
$fixtureStates = Join-Path $repo 'dev/protocol/state_frames.txt'
$outProtocol = Join-Path $env:TEMP 'pitchcomm-test-protocol.exe'
& $Compiler @flags (Join-Path $PSScriptRoot 'test_protocol_fixtures.cpp') -o $outProtocol
if ($LASTEXITCODE -ne 0) { throw 'Protocol fixture test build failed' }
& $outProtocol $fixtureCommands $fixtureStates
if ($LASTEXITCODE -ne 0) { throw 'Protocol fixture tests failed' }
