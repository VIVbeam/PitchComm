<#
.SYNOPSIS
Checks that this bench machine has what PitchComm needs.

.DESCRIPTION
Verifies the tools and repository layout a maintainer needs to build, flash,
and test the product:

  required: west, nrfutil, Python 3.10+, littlefs-python, a valid
            firmware/ncs_version.txt, the expected repository layout, and
            generated catalog files matching config/calls.json
  optional: arm-zephyr-eabi-size (image size reports), Node (GUI tests)

Prints PASS/FAIL with remediation for every item and exits nonzero when a
required item is missing. With -Json it prints one machine-readable object
instead of the human-readable report.

.EXAMPLE
tools\check_toolchain.ps1
Checks this bench and prints the report.

.EXAMPLE
tools\check_toolchain.ps1 -Json | ConvertFrom-Json
Returns the same results as objects for scripting.
#>
param(
    [switch]$Json,
    [string]$Root = ''
)
$ErrorActionPreference = 'Stop'
if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path -LiteralPath $Root).Path
$Tools = Join-Path $Root 'tools'

$checks = New-Object 'System.Collections.Generic.List[object]'

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Required,
        [Parameter(Mandatory = $true)][ValidateSet('PASS', 'FAIL', 'WARN')][string]$Status,
        [Parameter(Mandatory = $true)][string]$Detail,
        [string]$Remediation = ''
    )
    $checks.Add([pscustomobject]@{
        name = $Name
        required = $Required
        status = $Status
        detail = $Detail
        remediation = $Remediation
    })
}

function Find-App {
    param([string[]]$Names)
    foreach ($name in $Names) {
        $found = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.Source }
    }
    return $null
}

function Invoke-Version {
    param([string]$Program)
    try {
        $lines = @(& $Program --version 2>&1)
        $first = ''
        if ($lines.Count) { $first = ([string]($lines | Select-Object -First 1)).Trim() }
        return @{ Exit = $LASTEXITCODE; Text = $first }
    } catch {
        return @{ Exit = -1; Text = $_.Exception.Message }
    }
}

# --- required: west ---------------------------------------------------------
$west = Find-App @('west')
if (-not $west) {
    Add-Check 'west on PATH' $true 'FAIL' 'not found' `
        'Open the NCS toolchain shell (nrfutil sdk-manager toolchain launch --ncs-version v3.4.0 --terminal) or install west and set ZEPHYR_BASE; see dev/build.md.'
} else {
    $result = Invoke-Version $west
    if ($result.Exit -ne 0 -or -not $result.Text) {
        Add-Check 'west on PATH' $true 'FAIL' ('{0} did not run: {1}' -f $west, $result.Text) `
            'Open a working NCS v3.4.0 toolchain shell or reinstall west.'
    } else {
        Add-Check 'west on PATH' $true 'PASS' ('{0} ({1})' -f $result.Text, $west)
    }
}

# --- required: nrfutil ------------------------------------------------------
$nrfutil = Find-App @('nrfutil')
if (-not $nrfutil) {
    Add-Check 'nrfutil on PATH' $true 'FAIL' 'not found' `
        'Install nRF Util (winget install NordicSemiconductor.nrfutil or nrfutil.dev), then run: nrfutil install device nrf5sdk-tools.'
} else {
    $result = Invoke-Version $nrfutil
    if ($result.Exit -ne 0 -or -not $result.Text) {
        Add-Check 'nrfutil on PATH' $true 'FAIL' ('{0} did not run: {1}' -f $nrfutil, $result.Text) `
            'Reinstall nRF Util and check that the nrfutil device command is installed.'
    } else {
        Add-Check 'nrfutil on PATH' $true 'PASS' ('{0} ({1})' -f $result.Text, $nrfutil)
    }
}

# --- optional: ARM size tool ------------------------------------------------
$armSizeTool = Find-App @('arm-zephyr-eabi-size')
if ($armSizeTool) {
    Add-Check 'arm-zephyr-eabi-size (optional)' $false 'PASS' $armSizeTool
} else {
    $sizeFallback = Find-App @('arm-none-eabi-size', 'size')
    if ($sizeFallback) {
        Add-Check 'arm-zephyr-eabi-size (optional)' $false 'WARN' `
            ('not found; fallback {0} is accepted by tools\build_firmware.ps1' -f $sizeFallback) `
            'Install the NCS ARM toolchain for a matching arm-zephyr-eabi-size report.'
    } else {
        Add-Check 'arm-zephyr-eabi-size (optional)' $false 'WARN' `
            'not found; image size reports fall back to west rom_report' `
            'Install the NCS ARM toolchain to get IMAGE size reports from tools\build_firmware.ps1.'
    }
}

# --- required: Python 3.10+ and littlefs-python -----------------------------
$python = Find-App @('python', 'python3')
$pythonReady = $false
if (-not $python) {
    Add-Check 'Python 3.10+' $true 'FAIL' 'python not found on PATH' `
        'Install Python 3.10 or newer with "Add python.exe to PATH" enabled, then run: python -m pip install -r tools\requirements.txt.'
} else {
    $probe = @(& $python -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>&1)
    $versionText = ''
    if ($probe.Count) { $versionText = ([string]($probe | Select-Object -First 1)).Trim() }
    $parsed = [version]'0.0'
    if ($LASTEXITCODE -eq 0 -and [version]::TryParse($versionText, [ref]$parsed)) {
        if ($parsed -ge [version]'3.10') {
            $pythonReady = $true
            Add-Check 'Python 3.10+' $true 'PASS' ('{0} ({1})' -f $versionText, $python)
        } else {
            Add-Check 'Python 3.10+' $true 'FAIL' ('{0} is older than 3.10' -f $versionText) `
                'Install Python 3.10 or newer and rerun this check.'
        }
    } else {
        Add-Check 'Python 3.10+' $true 'FAIL' ('could not run {0}' -f $python) `
            'Install Python 3.10 or newer and enable "Add python.exe to PATH".'
    }
}

if (-not $pythonReady) {
    Add-Check 'littlefs-python' $true 'FAIL' 'skipped: Python 3.10+ is not usable' `
        'Install Python 3.10 or newer, then run: python -m pip install -r tools\requirements.txt.'
} else {
    $probe = @(& $python -c "import littlefs; print(getattr(littlefs, '__version__', 'unknown'))" 2>&1)
    $probeText = ''
    if ($probe.Count) { $probeText = ([string]($probe | Select-Object -First 1)).Trim() }
    if ($LASTEXITCODE -eq 0) {
        Add-Check 'littlefs-python' $true 'PASS' ('import littlefs {0} ({1})' -f $probeText, $python)
    } else {
        Add-Check 'littlefs-python' $true 'FAIL' 'import littlefs failed' `
            ('Run: {0} -m pip install -r tools\requirements.txt.' -f $python)
    }
}

# --- optional: Node ---------------------------------------------------------
$node = Find-App @('node')
if ($node) {
    $result = Invoke-Version $node
    Add-Check 'Node (optional, GUI tests)' $false 'PASS' ('{0} ({1})' -f $result.Text, $node)
} else {
    Add-Check 'Node (optional, GUI tests)' $false 'WARN' `
        'not found; GUI test scripts will be skipped' `
        'Install Node 18 or newer only if you run the GUI tests.'
}

# --- required: NCS version pin ----------------------------------------------
$ncsPath = Join-Path $Root 'firmware/ncs_version.txt'
if (-not (Test-Path -LiteralPath $ncsPath -PathType Leaf)) {
    Add-Check 'firmware/ncs_version.txt' $true 'FAIL' 'missing' `
        'Restore one line like v3.4.0; see dev/build.md.'
} else {
    $raw = Get-Content -LiteralPath $ncsPath -Raw
    $text = $raw.Trim()
    $lines = @($raw -split "`r?`n" | Where-Object { $_.Trim() })
    if ($lines.Count -ne 1 -or $text -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$') {
        Add-Check 'firmware/ncs_version.txt' $true 'FAIL' ('invalid content: {0}' -f $text) `
            'Restore one line like v3.4.0; see dev/build.md.'
    } else {
        Add-Check 'firmware/ncs_version.txt' $true 'PASS' $text
    }
}

# --- required: repository layout --------------------------------------------
$layout = @(
    'firmware/CMakeLists.txt',
    'firmware/Kconfig',
    'firmware/prj.conf',
    'firmware/src/main.cpp',
    'firmware/roles/field-common.conf',
    'firmware/boards/xiao_nrf54l15_nrf54l15_cpuapp.conf',
    'firmware/include/pc/catalog.h',
    'config/calls.json',
    'data/audio',
    'tools/build_firmware.ps1',
    'tools/build_audio_fs.py',
    'tools/preflight.py',
    'gui/index.html',
    'gui/catalog.json',
    'cad/unbranded/README.md',
    'cad/unbranded/exports'
)
$missing = @($layout | Where-Object { -not (Test-Path -LiteralPath (Join-Path $Root $_)) })
if ($missing.Count) {
    Add-Check 'repository layout' $true 'FAIL' ('missing: {0}' -f ($missing -join ', ')) `
        'Restore the missing paths (git checkout -- <path>) or clone the full repository.'
} else {
    Add-Check 'repository layout' $true 'PASS' ('{0} expected paths present' -f $layout.Count)
}

# --- required: generated catalog files --------------------------------------
$catalogFiles = @('firmware/include/pc/catalog.h', 'gui/catalog.json')
if (-not $pythonReady) {
    $missingCatalog = @($catalogFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $Root $_)) })
    if ($missingCatalog.Count) {
        Add-Check 'generated catalog' $true 'FAIL' ('missing: {0}' -f ($missingCatalog -join ', ')) `
            'Run python tools/generate_catalog.py.'
    } else {
        Add-Check 'generated catalog' $true 'PASS' 'both files present (content not checked without Python)'
    }
} else {
    $probe = @'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import generate_catalog
root = Path(sys.argv[2])
version, files = generate_catalog.rendered(root)
bad = []
for name, expected in files.items():
    try:
        actual = (root / name).read_text(encoding='utf-8')
    except OSError:
        actual = None
    if actual != expected:
        bad.append(name)
print('%08x' % version)
print(','.join(bad))
'@
    $out = @($probe | & $python - $Tools $Root 2>&1)
    if ($LASTEXITCODE -ne 0) {
        $detail = 'render failed'
        if ($out.Count) { $detail = 'render failed: ' + (($out | Select-Object -First 3) -join ' ') }
        Add-Check 'generated catalog' $true 'FAIL' $detail 'Run python tools/generate_catalog.py from the repository root.'
    } else {
        $version = ''
        if ($out.Count) { $version = ([string]$out[0]).Trim() }
        $bad = @()
        if ($out.Count -gt 1 -and [string]$out[1]) {
            $bad = @(([string]$out[1]).Split(',') | Where-Object { $_ })
        }
        if ($bad.Count) {
            Add-Check 'generated catalog' $true 'FAIL' ('stale: {0}' -f ($bad -join ', ')) `
                'Run python tools/generate_catalog.py, then rebuild the units and reload the GUI.'
        } else {
            Add-Check 'generated catalog' $true 'PASS' ('catalog.h and catalog.json match, dictionary {0}' -f $version)
        }
    }
}

# --- report -----------------------------------------------------------------
$requiredFailures = @($checks | Where-Object { $_.required -and $_.status -eq 'FAIL' })
$warnings = @($checks | Where-Object { $_.status -eq 'WARN' })
$passed = @($checks | Where-Object { $_.status -eq 'PASS' }).Count
$ok = $requiredFailures.Count -eq 0

if ($Json) {
    [pscustomobject]@{
        ok = $ok
        root = $Root
        passed = $passed
        required_failures = $requiredFailures.Count
        warnings = $warnings.Count
        checks = $checks
    } | ConvertTo-Json -Depth 5
} else {
    Write-Host ''
    Write-Host "PitchComm bench check: $Root"
    Write-Host ''
    $colors = @{ PASS = 'Green'; FAIL = 'Red'; WARN = 'Yellow' }
    foreach ($check in $checks) {
        Write-Host ('[{0}] {1}: {2}' -f $check.status, $check.name, $check.detail) -ForegroundColor $colors[$check.status]
        if ($check.remediation) {
            Write-Host ('       fix: {0}' -f $check.remediation) -ForegroundColor DarkGray
        }
    }
    Write-Host ''
    if ($ok) {
        Write-Host ('Toolchain ready: {0} checks passed, {1} optional warning(s).' -f $passed, $warnings.Count) -ForegroundColor Green
    } else {
        Write-Host ('Toolchain not ready: {0} required item(s) failed.' -f $requiredFailures.Count) -ForegroundColor Red
    }
}

if (-not $ok) { exit 1 }
exit 0
