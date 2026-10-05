<#
.SYNOPSIS
Writes the LittleFS audio image to the pitcher unit.

.DESCRIPTION
This is a data image, not a firmware ELF, so west flash does not apply. It is
programmed with nRF Util at the raw slot address recorded in the Intel HEX:

  nrfutil device program --firmware data/audio/littlefs.hex `
    --options chip_erase_mode=ERASE_RANGES,verify=VERIFY_READ

Run this once on the pitcher unit after flashing its firmware with
tools\flash_firmware.ps1. nrfutil (nRF Util) and its device command must be on
PATH; install with `nrfutil install device` if needed. Use -Serial to pick a
probe when several are attached.

.EXAMPLE
tools\flash_audio.ps1
Programs the default image onto the single attached board.

.EXAMPLE
tools\flash_audio.ps1 -Serial 000000000000
Programs the image onto the probe with that serial number.
#>
param(
    [string]$Image = '',
    [string]$Serial = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Image) { $Image = Join-Path $root 'data/audio/littlefs.hex' }
if (-not (Test-Path -LiteralPath $Image)) {
    throw "Audio image not found: $Image. Restore the complete audio package."
}
$metadata = Join-Path (Split-Path -Parent $Image) 'package.json'
if (-not (Test-Path -LiteralPath $metadata -PathType Leaf)) { throw 'Audio package metadata is missing.' }
$Image = (Resolve-Path -LiteralPath $Image).Path
$pythonPath = (Get-Command python -ErrorAction Stop).Source
& $pythonPath (Join-Path $PSScriptRoot 'check_setup.py') --root $root --audio-image $Image
if ($LASTEXITCODE -ne 0) { throw 'Audio package verification failed; no programming was attempted.' }
$nrfutil = (Get-Command nrfutil -ErrorAction SilentlyContinue).Source
if (-not $nrfutil) {
    throw 'nrfutil was not found on PATH. Install nRF Util (and `nrfutil install device`) before flashing the audio image.'
}
$arguments = @('device', 'program', '--firmware', $Image,
    '--options', 'chip_erase_mode=ERASE_RANGES,verify=VERIFY_READ')
if ($Serial) { $arguments += @('--serial-number', $Serial) }
Write-Host "==> nrfutil $($arguments -join ' ')"
& $nrfutil @arguments
if ($LASTEXITCODE -ne 0) { throw "Audio image flashing failed (exit $LASTEXITCODE)" }
Write-Host "Flashed $Image."
