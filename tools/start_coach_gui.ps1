$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonPath = (Get-Command python -ErrorAction Stop).Source
& $pythonPath (Join-Path $PSScriptRoot 'serve_gui.py')
if ($LASTEXITCODE -ne 0) { throw 'Coach desk did not start; see the message above' }
