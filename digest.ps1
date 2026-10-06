# Run the ESPN digest from any folder:  .\digest.ps1 [--rules] [--stdout] [--debug]
# Uses the project's own venv and source folder, so no activate or PYTHONPATH needed.

$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "No venv at $root\.venv - create it with: python -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt"
    exit 1
}

$env:PYTHONPATH = Join-Path $root "src"
Push-Location $root  # .env and .\output are resolved relative to the project folder
try {
    & $python -m espn_digest.cli @args
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $code
