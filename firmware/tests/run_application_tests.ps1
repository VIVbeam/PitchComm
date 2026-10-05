# Execute the real main.cpp paths with host models, not Zephyr hardware.
param([string]$Compiler = '')
$ErrorActionPreference='Stop'
if (-not $Compiler) { $Compiler=(Get-Command g++ -ErrorAction Stop).Source }
# Put the selected compiler's runtime DLLs ahead of other installed toolchains.
$Compiler = (Get-Command $Compiler -CommandType Application -ErrorAction Stop).Source
$originalPath = $env:Path
try {
    $env:Path = (Split-Path -Parent $Compiler) + ';' + $originalPath
    $out=Join-Path $env:TEMP 'pitchcomm-test-application.exe'
    $flags=@('-std=c++17','-Wall','-Wextra','-Werror','-pthread','-ffunction-sections','-fdata-sections',
      '-Wl,--gc-sections','-DCONFIG_PITCHCOMM_CONSOLE=1',
      '-I',(Join-Path $PSScriptRoot 'support'),'-I',(Join-Path $PSScriptRoot '../include'))
    & $Compiler @flags '-DCONFIG_PITCHCOMM_DISPLAY=1' '-DCONFIG_PITCHCOMM_CATCHER_MENU=1' '-DPC_UNIT=PC_UNIT_catcher' (Join-Path $PSScriptRoot 'test_application.cpp') -o $out
    if ($LASTEXITCODE -ne 0) { throw 'Application model build failed' }
    & $out
    if ($LASTEXITCODE -ne 0) { throw 'Application model checks failed' }
    $coachOut=Join-Path $env:TEMP 'pitchcomm-test-application-coach.exe'
    & $Compiler @flags '-DPITCHCOMM_HOST_COACH=1' (Join-Path $PSScriptRoot 'test_application.cpp') -o $coachOut
    if ($LASTEXITCODE -ne 0) { throw 'Coach application model build failed' }
    & $coachOut
    if ($LASTEXITCODE -ne 0) { throw 'Coach application model checks failed' }
} finally {
    $env:Path = $originalPath
}
