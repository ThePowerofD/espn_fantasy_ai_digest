# Run the ESPN digest from any folder:  .\digest.ps1 [--rules] [--stdout] [--debug] [--open]
# Uses the project's own venv and source folder, so no activate or PYTHONPATH needed.
# --open is handled here, not by Python: on success it opens the newest digest in Notepad.

$root = $PSScriptRoot
$open = $args -contains "--open"
$pyArgs = @($args | Where-Object { $_ -ne "--open" })
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "No venv at $root\.venv - create it with: python -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt"
    exit 1
}

$env:PYTHONPATH = Join-Path $root "src"
Push-Location $root  # .env and .\output are resolved relative to the project folder
try {
    & $python -m espn_digest.cli @pyArgs
    $code = $LASTEXITCODE
    if ($open -and $code -eq 0) {
        $latest = Get-ChildItem (Join-Path $root "output\digest_*.md") |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($latest) { Start-Process notepad.exe $latest.FullName }
    }
}
finally {
    Pop-Location
}
exit $code
