# PitchComm host syntax-check harness.
#
# Compiles the firmware sources with the host gcc/g++ (-fsyntax-only) so that
# syntax and preprocessor errors surface before an NCS toolchain is available.
# Zephyr/OpenThread/Bluetooth/lc3 headers come from dev/host_compile/stubs.
#
# The -D sets mirror firmware/Kconfig plus prj.conf, the role .conf fragments,
# roles/audio-unit.conf where the role includes it, the board conf, and the
# effects of boards/xiao_nrf54l15_nrf54l15_cpuapp.overlay (the overlay itself
# is devicetree only; the stubs pin the two things it selects: the SSD1306 at
# I2C 0x3C and ADC AIN7 in zephyr,user). Field roles also pass
# -DPC_UNIT=PC_UNIT_<key> from the generated catalog; the coach build omits it
# and falls back to kCoach, and the proof build never selects a unit. The
# `first` role probes a non-default key (PC_UNIT_first is 0 today).
#
# Optional modes, combinable in one run:
#   -Provisioned  generate a temporary app/team_config.h with
#                 PC_TEAM_CONFIGURED 1 and check main.cpp + thread_link.c
#                 against it (firmware/include is never written to)
#   -MinSize      recheck every role with roles/min-size.conf applied
#   -RawI2c       recheck display.cpp with CONFIG_SSD1306 undefined so the
#                 raw I2C fallback is parsed
#   -RosterVariant render a catalog for dev/host_compile/roster-variant.json
#                 with the generator API into a temporary include overlay and
#                 compile dev/host_compile/catalog_probe.cpp against it, so its
#                 static_asserts pin a six-unit roster (coach + default four +
#                 right + custom bench, center audio on) end to end
#   -Strict       add extra warning flags, do not treat warnings as errors,
#                 and print them as informational NOTE lines
#
# Usage (PowerShell 7+):
#   pwsh -File dev/host_compile/run.ps1
#   pwsh -File dev/host_compile/run.ps1 -Roles coach,pitcher
#   pwsh -File dev/host_compile/run.ps1 -Provisioned -MinSize -RawI2c -Strict
#   pwsh -File dev/host_compile/run.ps1 -RosterVariant
#   pwsh -File dev/host_compile/run.ps1 -SkipAudio
# Windows PowerShell 5.1:
#   powershell -NoProfile -ExecutionPolicy Bypass -File dev/host_compile/run.ps1
#
# Exit code 0 only when every attempted compile passes.

param(
    [string[]]$Roles = @('coach', 'catcher', 'pitcher', 'shortstop', 'center', 'first', 'proof'),
    [string]$CompilerC = '',
    [string]$CompilerCpp = '',
    [switch]$SkipAudio,
    [switch]$Provisioned,
    [switch]$MinSize,
    [switch]$RawI2c,
    [switch]$RosterVariant,
    [switch]$Strict
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$includeDir = Join-Path $repo 'firmware\include'
$srcDir = Join-Path $repo 'firmware\src'
$stubDir = Join-Path $PSScriptRoot 'stubs'
$toolsDir = Join-Path $repo 'tools'
$variantRosterPath = Join-Path $PSScriptRoot 'roster-variant.json'
$variantProbePath = Join-Path $PSScriptRoot 'catalog_probe.cpp'

if (-not $CompilerC) {
    $CompilerC = (Get-Command gcc -ErrorAction SilentlyContinue).Source
    if (-not $CompilerC) { throw 'gcc not found on PATH; pass -CompilerC' }
}
if (-not $CompilerCpp) {
    $CompilerCpp = (Get-Command g++ -ErrorAction SilentlyContinue).Source
    if (-not $CompilerCpp) { throw 'g++ not found on PATH; pass -CompilerCpp' }
}

# --- strict-mode warning flags ----------------------------------------------
# -Wstrict-prototypes and -Wmissing-prototypes are C/ObjC only; g++ rejects
# them with a "valid for C/ObjC but not for C++" diagnostic. -Wmissing-
# declarations is valid for both languages and does not fire on inline or
# constexpr header functions.
$strictFlagsC = @(
    '-Wundef',
    '-Wshadow',
    '-Wcast-qual',
    '-Wpointer-arith',
    '-Wstrict-prototypes',
    '-Wmissing-prototypes',
    '-Wmissing-declarations'
)
$strictFlagsCpp = @(
    '-Wundef',
    '-Wshadow',
    '-Wcast-qual',
    '-Wpointer-arith',
    '-Wmissing-declarations'
)

# --- role macro sets --------------------------------------------------------

# prj.conf + boards/xiao_nrf54l15_nrf54l15_cpuapp.conf.
$common = @(
    'CONFIG_CPP=1',
    'CONFIG_STD_CPP17=1',
    'CONFIG_SYS_CLOCK_TICKS_PER_SEC=1000',
    'CONFIG_LOG=1',
    'CONFIG_PRINTK=1',
    'CONFIG_SERIAL=1',
    'CONFIG_CONSOLE=1',
    'CONFIG_UART_CONSOLE=1',
    'CONFIG_CONSOLE_SUBSYS=1',
    'CONFIG_CONSOLE_GETLINE=1',
    'CONFIG_GPIO=1',
    'CONFIG_HWINFO=1',
    'CONFIG_MAIN_STACK_SIZE=4096',
    'CONFIG_HEAP_MEM_POOL_SIZE=32768',
    'CONFIG_ASSERT=1',
    'CONFIG_THREAD_NAME=1',
    'CONFIG_FPU=1',
    'CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE=4096',
    'CONFIG_I2C=1',
    'CONFIG_PITCHCOMM_CONSOLE=1'
)

# roles/coach.conf and roles/field-common.conf networking + settings blocks.
$network = @(
    'CONFIG_NETWORKING=1',
    'CONFIG_NET_IPV6=1',
    'CONFIG_NET_UDP=1',
    'CONFIG_NET_SOCKETS=1',
    'CONFIG_NET_L2_OPENTHREAD=1',
    'CONFIG_OPENTHREAD=1',
    'CONFIG_OPENTHREAD_MANUAL_START=1',
    'CONFIG_OPENTHREAD_THREAD_STACK_SIZE=4096',
    'CONFIG_SETTINGS=1',
    'CONFIG_ZMS=1',
    'CONFIG_FLASH_MAP=1',
    'CONFIG_SETTINGS_ZMS=1'
)

# roles/field-common.conf sleepy-end-device block (catcher/pitcher/fielders).
$field = @(
    'CONFIG_OPENTHREAD_MTD=1',
    'CONFIG_OPENTHREAD_MTD_SED=1',
    'CONFIG_OPENTHREAD_POLL_PERIOD=200',
    'CONFIG_OPENTHREAD_RADIO_WORKQUEUE_STACK_SIZE=1024',
    'CONFIG_OPENTHREAD_NUM_MESSAGE_BUFFERS=48',
    'CONFIG_ADC=1',
    'CONFIG_ADC_CONFIGURABLE_INPUTS=1'
)

# roles/audio-unit.conf. CONFIG_BT_ISO_TX_MTU and CONFIG_BT_CONN_TX_USER_DATA_SIZE
# are ints the source reads; the conf leaves them at their Kconfig defaults, so
# representative values are pinned here.
$audioUnit = @(
    'CONFIG_BT=1',
    'CONFIG_BT_SMP=1',
    'CONFIG_BT_CENTRAL=1',
    'CONFIG_BT_ISO_CENTRAL=1',
    'CONFIG_BT_GATT_CLIENT=1',
    'CONFIG_BT_GATT_AUTO_DISCOVER_CCC=1',
    'CONFIG_BT_GATT_AUTO_UPDATE_MTU=1',
    'CONFIG_UTF8=1',
    'CONFIG_BT_AUDIO=1',
    'CONFIG_BT_AUDIO_TX=1',
    'CONFIG_BT_BAP_UNICAST_CLIENT=1',
    'CONFIG_BT_ISO_TX_BUF_COUNT=4',
    'CONFIG_BT_ISO_TX_MTU=251',
    'CONFIG_BT_ISO_MAX_CHAN=1',
    'CONFIG_BT_BAP_UNICAST_CLIENT_GROUP_STREAM_COUNT=1',
    'CONFIG_BT_BAP_UNICAST_CLIENT_ASE_SNK_COUNT=1',
    'CONFIG_BT_BAP_UNICAST_CLIENT_ASE_SRC_COUNT=0',
    'CONFIG_BT_KEYS_OVERWRITE_OLDEST=1',
    'CONFIG_BT_EXT_ADV=1',
    'CONFIG_BT_SETTINGS=1',
    'CONFIG_SETTINGS=1',
    'CONFIG_ZMS=1',
    'CONFIG_FLASH_MAP=1',
    'CONFIG_SETTINGS_ZMS=1',
    'CONFIG_LIBLC3=1',
    'CONFIG_BT_BUF_EVT_RX_SIZE=255',
    'CONFIG_BT_BUF_ACL_RX_SIZE=255',
    'CONFIG_BT_BUF_ACL_TX_SIZE=251',
    'CONFIG_BT_BUF_CMD_TX_SIZE=255',
    'CONFIG_BT_RX_STACK_SIZE=4096',
    'CONFIG_FILE_SYSTEM=1',
    'CONFIG_FILE_SYSTEM_LITTLEFS=1',
    'CONFIG_FLASH=1',
    'CONFIG_BT_LL_SOFTDEVICE=1',
    'CONFIG_BT_CONN_TX_USER_DATA_SIZE=4'
)

$roleTable = [ordered]@{
    coach = @{
        Defines = $common + $network + @(
            'CONFIG_PITCHCOMM_ROLE_COACH=1',
            'CONFIG_OPENTHREAD_FTD=1',
            'CONFIG_OPENTHREAD_MAX_CHILDREN=4',
            'CONFIG_OPENTHREAD_NUM_MESSAGE_BUFFERS=64'
        )
        Sources = @('main.cpp', 'thread_link.c')
    }
    catcher = @{
        Defines = $common + $network + $field + @(
            'PC_UNIT=PC_UNIT_catcher',
            'CONFIG_PITCHCOMM_ROLE_CATCHER=1',
            'CONFIG_PITCHCOMM_DISPLAY=1',
            'CONFIG_PITCHCOMM_CATCHER_MENU=1',
            'CONFIG_PITCHCOMM_BATTERY=1',
            'CONFIG_DISPLAY=1',
            'CONFIG_SSD1306=1'
        )
        Sources = @('main.cpp', 'thread_link.c', 'display.cpp', 'buttons.cpp', 'battery.cpp')
    }
    pitcher = @{
        Defines = $common + $network + $field + $audioUnit + @(
            'PC_UNIT=PC_UNIT_pitcher',
            'CONFIG_PITCHCOMM_ROLE_PITCHER=1',
            'CONFIG_PITCHCOMM_AUDIO=1',
            'CONFIG_PITCHCOMM_FIELD_BUTTON=1',
            'CONFIG_PITCHCOMM_BATTERY=1'
        )
        Sources = @('main.cpp', 'thread_link.c', 'buttons.cpp', 'battery.cpp',
            'storage.c', 'audio_source.c')
    }
    shortstop = @{
        Defines = $common + $network + $field + @(
            'PC_UNIT=PC_UNIT_shortstop',
            'CONFIG_PITCHCOMM_ROLE_SHORTSTOP=1',
            'CONFIG_PITCHCOMM_DISPLAY=1',
            'CONFIG_PITCHCOMM_FIELD_BUTTON=1',
            'CONFIG_PITCHCOMM_BATTERY=1',
            'CONFIG_DISPLAY=1',
            'CONFIG_SSD1306=1'
        )
        Sources = @('main.cpp', 'thread_link.c', 'display.cpp', 'buttons.cpp', 'battery.cpp')
    }
    center = @{
        Defines = $common + $network + $field + @(
            'PC_UNIT=PC_UNIT_center',
            'CONFIG_PITCHCOMM_ROLE_CENTERFIELD=1',
            'CONFIG_PITCHCOMM_DISPLAY=1',
            'CONFIG_PITCHCOMM_FIELD_BUTTON=1',
            'CONFIG_PITCHCOMM_BATTERY=1',
            'CONFIG_DISPLAY=1',
            'CONFIG_SSD1306=1'
        )
        Sources = @('main.cpp', 'thread_link.c', 'display.cpp', 'buttons.cpp', 'battery.cpp')
    }
    # first is not enrolled (PC_UNIT_first is 0 in catalog.h), so it proves the
    # PC_UNIT macro path compiles for a non-default roster key. It carries no
    # field capability defines, so the main.cpp enrollment assert does not treat
    # it as a field image.
    first = @{
        Defines = $common + $network + $field + @(
            'PC_UNIT=PC_UNIT_first'
        )
        Sources = @('main.cpp', 'thread_link.c')
    }
    proof = @{
        Defines = $common + $audioUnit + @(
            'CONFIG_PITCHCOMM_ROLE_AUDIO_PROOF=1',
            'CONFIG_PITCHCOMM_AUDIO=1'
        )
        Sources = @('main.cpp', 'thread_link.c', 'storage.c', 'audio_source.c')
    }
}

# The audio sources are listed last in the pitcher and proof source sets:
# they carry the largest stub surface.
$failed = 0
$modeStats = [ordered]@{}

function Add-Stat {
    param(
        [string]$Mode,
        [int]$Pass = 0,
        [int]$Fail = 0,
        [int]$Skip = 0,
        [int]$Notes = 0
    )
    if (-not $script:modeStats.Contains($Mode)) {
        $script:modeStats[$Mode] = @{ Pass = 0; Fail = 0; Skip = 0; Notes = 0 }
    }
    $script:modeStats[$Mode].Pass += $Pass
    $script:modeStats[$Mode].Fail += $Fail
    $script:modeStats[$Mode].Skip += $Skip
    $script:modeStats[$Mode].Notes += $Notes
}

function Invoke-SyntaxCheck {
    param(
        [string]$Role,
        [string]$File,
        [string]$Compiler,
        [string]$Std,
        [string[]]$Defines,
        [string]$Mode = 'base',
        [string[]]$ExtraIncludes = @(),
        [switch]$StrictMode
    )

    $label = $Mode
    if ($StrictMode) { $label = "$Mode+strict" }

    $filePath = Join-Path $srcDir $File
    $compilerArgs = @('-fsyntax-only', '-Wall', '-Wextra')
    if (-not $StrictMode) { $compilerArgs += '-Werror' }
    $compilerArgs += "-std=$Std"
    foreach ($dir in $ExtraIncludes) { $compilerArgs += @('-I', $dir) }
    $compilerArgs += @('-I', $includeDir, '-I', $stubDir)
    if ($StrictMode) {
        if ($File -like '*.c') { $compilerArgs += $strictFlagsC }
        else { $compilerArgs += $strictFlagsCpp }
    }
    foreach ($define in $Defines) { $compilerArgs += "-D$define" }
    $compilerArgs += $filePath

    # Windows PowerShell 5.1 turns native stderr into terminating errors when
    # $ErrorActionPreference is Stop, so relax it for the compiler call only.
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $Compiler @compilerArgs 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousEap
    }
    $ok = ($exitCode -eq 0)
    $warningLines = @($output | Where-Object { "$_" -match 'warning:' })

    if ($ok) {
        Write-Host ("PASS {0,-22} {1,-11} [{2}]" -f $File, $Role, $label)
        if ($StrictMode) {
            foreach ($warning in $warningLines) { Write-Host "    NOTE $warning" -ForegroundColor Yellow }
        }
    } else {
        Write-Host ("FAIL {0,-22} {1,-11} [{2}]" -f $File, $Role, $label) -ForegroundColor Red
        $output | ForEach-Object { Write-Host "    $_" }
    }

    $statMode = $label
    if ($ok) {
        Add-Stat -Mode $statMode -Pass 1 -Notes $warningLines.Count
    } else {
        Add-Stat -Mode $statMode -Fail 1
        $script:failed = $script:failed + 1
    }
}

function Invoke-FileCheck {
    param(
        [string]$Role,
        [string]$File,
        [string[]]$Defines,
        [string]$Mode,
        [string[]]$ExtraIncludes = @(),
        [switch]$StrictMode
    )

    if ($File -like '*.c') {
        Invoke-SyntaxCheck -Role $Role -File $File -Compiler $CompilerC -Std 'gnu11' `
            -Defines $Defines -Mode $Mode -ExtraIncludes $ExtraIncludes -StrictMode:$StrictMode
    } else {
        Invoke-SyntaxCheck -Role $Role -File $File -Compiler $CompilerCpp -Std 'gnu++17' `
            -Defines $Defines -Mode $Mode -ExtraIncludes $ExtraIncludes -StrictMode:$StrictMode
    }
}

function Invoke-RoleRun {
    param(
        [string]$Role,
        [string[]]$Defines,
        [string]$Mode,
        [string[]]$Files = $null,
        [string[]]$ExtraIncludes = @(),
        [switch]$StrictMode
    )

    Write-Host ("== {0} [{1}] ==" -f $Role, $Mode)
    if ($null -eq $Files) { $Files = $roleTable[$Role].Sources }
    foreach ($file in $Files) {
        if ($SkipAudio -and ($file -eq 'storage.c' -or $file -eq 'audio_source.c')) {
            Write-Host ("SKIP {0,-22} {1,-11} [{2}]" -f $file, $Role, $Mode) -ForegroundColor Yellow
            Add-Stat -Mode $Mode -Skip 1
            continue
        }
        Invoke-FileCheck -Role $Role -File $file -Defines $Defines -Mode $Mode `
            -ExtraIncludes $ExtraIncludes -StrictMode:$StrictMode
    }
}

# roles/min-size.conf removes CONFIG_LOG and CONFIG_ASSERT, sets the
# OpenThread debug option to n (omitted, like autoconf.h), and shrinks the
# OpenThread buffers. A min-size image can be combined with any role.
function Get-MinSizeDefines {
    param([string[]]$Defines)

    $out = @()
    foreach ($define in $Defines) {
        if ($define -eq 'CONFIG_LOG=1') { continue }
        if ($define -eq 'CONFIG_ASSERT=1') { continue }
        if ($define -like 'CONFIG_OPENTHREAD_DEBUG=*') { continue }
        if ($define -like 'CONFIG_OPENTHREAD_NUM_MESSAGE_BUFFERS=*') { continue }
        if ($define -like 'CONFIG_OPENTHREAD_MAX_CHILDREN=*') { continue }
        $out += $define
    }
    $out += 'CONFIG_OPENTHREAD_NUM_MESSAGE_BUFFERS=32'
    $out += 'CONFIG_OPENTHREAD_MAX_CHILDREN=4'
    return $out
}

# Writes a provisioned team_config.h in a fresh temporary directory and
# returns that directory. firmware/include/app/team_config.h is never
# touched. Values are lab-only placeholders; every EUI is nonzero and unique.
function New-ProvisionedTeamConfig {
    $root = Join-Path ([System.IO.Path]::GetTempPath()) `
        ("pitchcomm-host-compile-" + [System.Guid]::NewGuid().ToString('N'))
    $appDir = Join-Path $root 'app'
    New-Item -ItemType Directory -Path $appDir -Force | Out-Null

    $lines = @(
        '/*',
        ' * HOST HARNESS GENERATED: provisioned app/team_config.h.',
        ' * Written to a temporary include directory by dev/host_compile/run.ps1',
        ' * with -Provisioned. Lab-only credentials; never committed and never',
        ' * written into firmware/include.',
        ' */',
        '#pragma once',
        '',
        '#include <stdint.h>',
        '',
        '#define PC_TEAM_CONFIGURED 1',
        '',
        '#define PC_TEAM_NETWORK_NAME "PitchCommHost"',
        '#define PC_TEAM_PANID 0x5a17',
        '#define PC_TEAM_CHANNEL 19',
        '#define PC_TEAM_UDP_PORT 45678',
        '',
        '#define PC_TEAM_XPANID {0x0a, 0x1b, 0x2c, 0x3d, 0x4e, 0x5f, 0x60, 0x71}',
        '#define PC_TEAM_NETWORK_KEY {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, \',
        '                             0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xf0, 0x01}',
        '#define PC_TEAM_MESH_LOCAL_PREFIX {0xfd, 0x12, 0x34, 0x56, 0x78, 0x9a, 0xbc, 0xde}',
        '',
        'static const uint8_t team_eui64[5][8] = {',
        '  {0x02, 0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x10},',
        '  {0x02, 0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x11},',
        '  {0x02, 0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x12},',
        '  {0x02, 0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x13},',
        '  {0x02, 0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x14},',
        '};'
    )
    Set-Content -LiteralPath (Join-Path $appDir 'team_config.h') -Value ($lines -join "`n") -Encoding ascii
    return $root
}

# -RosterVariant support: render the catalog for
# dev/host_compile/roster-variant.json with the generator API into a fresh
# temporary include overlay, then compile dev/host_compile/catalog_probe.cpp
# against it. The repo's config/, firmware/include/ and tools/ are only read,
# and build/validation.lock is never created because generate() is not called.
function Invoke-RosterVariantPass {
    param([switch]$StrictMode)

    $label = 'rostervariant'
    if ($StrictMode) { $label = "$label+strict" }

    if (-not (Test-Path -LiteralPath $variantRosterPath)) {
        throw "Missing variant roster: $variantRosterPath"
    }
    if (-not (Test-Path -LiteralPath $variantProbePath)) {
        throw "Missing probe translation unit: $variantProbePath"
    }

    $root = Join-Path ([System.IO.Path]::GetTempPath()) `
        ("pitchcomm-roster-variant-" + [System.Guid]::NewGuid().ToString('N'))
    try {
        $configDir = Join-Path $root 'config'
        New-Item -ItemType Directory -Path $configDir -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $repo 'config\calls.json') `
            -Destination (Join-Path $configDir 'calls.json') -Force
        Copy-Item -LiteralPath $variantRosterPath `
            -Destination (Join-Path $configDir 'roster.json') -Force

        # A quoted include such as units.h -> "catalog.h" resolves next to the
        # including header first, so the variant catalog only takes effect as
        # part of an overlay of the real include tree. The tree is copied into
        # the temporary root, never changed in place.
        $overlay = Join-Path $root 'include'
        New-Item -ItemType Directory -Path $overlay -Force | Out-Null
        Copy-Item -Path (Join-Path $includeDir '*') -Destination $overlay -Recurse -Force
        $catalogPath = Join-Path $overlay 'pc\catalog.h'

        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) {
            throw 'python not found on PATH; -RosterVariant needs it for tools/generate_catalog.py'
        }

        $generatorCode = @"
import sys
sys.path.insert(0, r'$toolsDir')
import generate_catalog as generator
data, version = generator.load(r'$root')
files = generator.render(data, version)
with open(r'$catalogPath', 'w', encoding='utf-8', newline='\n') as output:
    output.write(files['firmware/include/pc/catalog.h'])
index = generator.unit_index(data)
by_key = {play['key']: play for play in data['plays']}
audio_mask = generator.unit_mask(data, [unit['key'] for unit in data['units'] if unit['audio']])
pitch_mask = generator.unit_mask(data, [unit['key'] for unit in data['units'] if unit['pitches']])
all_play = generator.unit_mask(data, by_key[13]['audience'])
see_down = generator.unit_mask(data, by_key[18]['audience'])
listeners = [unit['key'] for unit in data['units']
             if unit['audio'] and generator.unit_mask(data, [unit['key']]) & see_down]
print('dictionary 0x{:08x}'.format(version))
print('kUnitCount {}  PC_UNIT_bench {}  kUnitMask(bench) {}  kUnitMask(right) {}'.format(
    len(data['units']) + 1, index['bench'],
    generator.unit_mask(data, ['bench']), generator.unit_mask(data, ['right'])))
print('pitch audience {}  audio mask {}'.format(pitch_mask, audio_mask))
print('play 13 audience {}  play 18 audience {}  audio in play 18: {}'.format(
    all_play, see_down, ', '.join(listeners)))
print('play 18 clip {}'.format('/audio/d18.wav' if see_down & audio_mask else 'absent'))
"@

        # -B keeps the generator import from writing tools/__pycache__.
        $previousEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $generated = @(& $python.Source -B -c $generatorCode 2>&1)
            $generatorExit = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousEap
        }
        if ($generatorExit -ne 0) {
            Write-Host ("FAIL {0,-22} {1,-11} [{2}]" -f 'catalog_probe.cpp', 'roster', $label) -ForegroundColor Red
            foreach ($line in $generated) { Write-Host "    $line" }
            Add-Stat -Mode $label -Fail 1
            $script:failed = $script:failed + 1
            return
        }
        Write-Host 'Variant catalog from tools/generate_catalog.py (read only; no lock taken):'
        foreach ($line in $generated) { Write-Host "  $line" }

        $compilerArgs = @('-fsyntax-only', '-Wall', '-Wextra')
        if (-not $StrictMode) { $compilerArgs += '-Werror' }
        $compilerArgs += '-std=gnu++17'
        if ($StrictMode) { $compilerArgs += $strictFlagsCpp }
        $compilerArgs += @('-I', $overlay, '-I', $includeDir, '-I', $stubDir, $variantProbePath)

        $previousEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $output = & $CompilerCpp @compilerArgs 2>&1
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousEap
        }
        $ok = ($exitCode -eq 0)
        $warningLines = @($output | Where-Object { "$_" -match 'warning:' })
        if ($ok) {
            Write-Host ("PASS {0,-22} {1,-11} [{2}]" -f 'catalog_probe.cpp', 'roster', $label)
            if ($StrictMode) {
                foreach ($warning in $warningLines) { Write-Host "    NOTE $warning" -ForegroundColor Yellow }
            }
            Add-Stat -Mode $label -Pass 1 -Notes $warningLines.Count
        } else {
            Write-Host ("FAIL {0,-22} {1,-11} [{2}]" -f 'catalog_probe.cpp', 'roster', $label) -ForegroundColor Red
            $output | ForEach-Object { Write-Host "    $_" }
            Add-Stat -Mode $label -Fail 1
            $script:failed = $script:failed + 1
        }
    } finally {
        if (Test-Path -LiteralPath $root) {
            Remove-Item -LiteralPath $root -Recurse -Force
        }
    }
}

$requested = @($Roles | ForEach-Object { $_.ToLowerInvariant() })
foreach ($role in $requested) {
    if (-not $roleTable.Contains($role)) {
        throw "Unknown role '$role'. Known roles: $($roleTable.Keys -join ', ')"
    }
}

$provisionRoot = $null
try {
    if ($Strict) {
        Write-Host 'Strict mode: extra warnings are informational; only real compile errors fail.'
    }
    if ($Provisioned) {
        $provisionRoot = New-ProvisionedTeamConfig
        Write-Host "Provisioned team_config: $provisionRoot (temporary; firmware/include is untouched)"
    }

    Write-Host ''
    Write-Host '### base ###'
    foreach ($role in $requested) {
        Invoke-RoleRun -Role $role -Defines $roleTable[$role].Defines -Mode 'base' -StrictMode:$Strict
    }

    if ($MinSize) {
        Write-Host ''
        Write-Host '### minsize ###'
        foreach ($role in $requested) {
            Invoke-RoleRun -Role $role -Defines (Get-MinSizeDefines -Defines $roleTable[$role].Defines) `
                -Mode 'minsize' -StrictMode:$Strict
        }
    }

    if ($RawI2c) {
        $rawRoles = @($requested | Where-Object { $roleTable[$_].Defines -contains 'CONFIG_SSD1306=1' })
        if ($rawRoles.Count -gt 0) {
            Write-Host ''
            Write-Host '### rawi2c ###'
            foreach ($role in $rawRoles) {
                Write-Host ("== {0} [rawi2c] ==" -f $role)
                $rawDefines = @($roleTable[$role].Defines | Where-Object { $_ -ne 'CONFIG_SSD1306=1' })
                Invoke-FileCheck -Role $role -File 'display.cpp' -Defines $rawDefines `
                    -Mode 'rawi2c' -StrictMode:$Strict
            }
        }
    }

    if ($Provisioned) {
        Write-Host ''
        Write-Host '### provisioned ###'
        foreach ($role in $requested) {
            Invoke-RoleRun -Role $role -Defines $roleTable[$role].Defines -Mode 'provisioned' `
                -Files @('main.cpp', 'thread_link.c') -ExtraIncludes @($provisionRoot) -StrictMode:$Strict
        }
    }

    if ($RosterVariant) {
        Write-Host ''
        Write-Host '### rostervariant ###'
        Write-Host ("== {0} [{1}] ==" -f 'roster', 'rostervariant')
        Invoke-RosterVariantPass -StrictMode:$Strict
    }
} finally {
    if ($provisionRoot -and (Test-Path -LiteralPath $provisionRoot)) {
        Remove-Item -LiteralPath $provisionRoot -Recurse -Force
    }
}

Write-Host ''
Write-Host '== summary =='
foreach ($mode in $modeStats.Keys) {
    $stat = $modeStats[$mode]
    Write-Host ("  {0,-16} pass {1,2}  fail {2,2}  skip {3,2}  notes {4,2}" -f `
        $mode, $stat.Pass, $stat.Fail, $stat.Skip, $stat.Notes)
}
if ($failed -gt 0) {
    Write-Host ''
    Write-Host "$failed syntax check(s) failed." -ForegroundColor Red
    exit 1
}
Write-Host ''
Write-Host 'All attempted syntax checks passed.' -ForegroundColor Green
exit 0
