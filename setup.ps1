# Sets up a local venv, installs hash-pinned deps, runs offline tests, and checks model IDs.
# Usage: .\setup.ps1        (safe to re-run; never reads or prints your API key)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    & py -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv (is the 'py' launcher installed?)" }
}

Write-Host "Installing hash-pinned dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install -q --disable-pip-version-check --require-hashes -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed" }

Write-Host "`nRunning offline tests..." -ForegroundColor Cyan
& $venvPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

Write-Host "`nChecking every model ID against OpenRouter..." -ForegroundColor Cyan
& $venvPython core\council.py --check
if ($LASTEXITCODE -ne 0) { throw "Some model IDs are unavailable - update config\council.json" }

Write-Host "`nAll good. Run the council with .\run.ps1" -ForegroundColor Green
