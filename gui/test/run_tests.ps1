# Runs the offline PitchComm coach GUI test suite from the repository root.
# Node 24 treats positional test paths as glob patterns, so the test files are
# passed as a glob instead of the bare directory.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $root
try {
  node --test gui/test/*.test.mjs
  $code = $LASTEXITCODE
} finally {
  Pop-Location
}
exit $code
