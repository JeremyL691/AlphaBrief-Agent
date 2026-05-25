$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

Set-Location $ProjectRoot

function Test-Dependencies {
  if (-not (Test-Path $VenvPython)) {
    return $false
  }
  & $VenvPython -c "import fastapi, streamlit, sqlalchemy, requests" *> $null
  return $LASTEXITCODE -eq 0
}

if (-not (Test-Dependencies)) {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "scripts\setup-windows.ps1")
}

if (-not (Test-Path (Join-Path $ProjectRoot ".env"))) {
  Copy-Item (Join-Path $ProjectRoot ".env.example") (Join-Path $ProjectRoot ".env")
}

& $VenvPython -m app.launcher
