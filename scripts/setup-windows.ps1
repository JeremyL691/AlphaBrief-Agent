$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

function Find-Python {
  $candidates = @("py -3.11", "py -3", "python")
  foreach ($candidate in $candidates) {
    try {
      $versionCheck = & cmd /c "$candidate -c ""import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"""
      if ($LASTEXITCODE -eq 0) {
        return $candidate
      }
    } catch {
    }
  }
  throw "Python 3.11+ not found. Install Python and re-run this installer."
}

Set-Location $ProjectRoot
Write-Host "`n==> Checking Python"
$PythonCommand = Find-Python

if (-not (Test-Path $VenvPython)) {
  Write-Host "`n==> Creating virtual environment"
  & cmd /c "$PythonCommand -m venv `"$VenvDir`""
}

Write-Host "`n==> Installing Python dependencies"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e ".[dev]"

if (-not (Test-Path (Join-Path $ProjectRoot ".env"))) {
  Write-Host "`n==> Creating .env from template"
  Copy-Item (Join-Path $ProjectRoot ".env.example") (Join-Path $ProjectRoot ".env")
}

Write-Host "`nAlphaBrief Agent setup completed."
Write-Host "Next step: double-click Start-AlphaBrief.bat"
