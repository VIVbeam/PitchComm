param([string]$Voice = '', [string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) {
    $PythonPath = Join-Path $projectPath '.tools/venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $PythonPath)) { $PythonPath = (Get-Command python -ErrorAction Stop).Source }
}
$powerShellPath = (Get-Command powershell -ErrorAction Stop).Source
& $PythonPath (Join-Path $PSScriptRoot 'audio_transaction.py') "--voice=$Voice" --powershell $powerShellPath
if ($LASTEXITCODE -ne 0) { throw 'Audio generation failed; inspect the message above and any saved backup' }

