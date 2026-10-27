# One-time setup: venv, hash-pinned deps, API key, secret-blocking hook, tests, model check.
# Usage: .\setup.ps1         (safe to re-run; never prints your API key)
#        .\setup.ps1 -Local  (no key at all: installs Ollama + downloads local models)
# Skipping the key prompt also sets up local mode.
param([switch]$Local)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -m venv .venv } else { & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv - is Python 3.11+ installed?" }
}

Write-Host "Installing hash-pinned dependencies..." -ForegroundColor Cyan
& $venvPython -m pip install -q --disable-pip-version-check --require-hashes -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed" }

# API key -> .env (git-ignored). Skipped if one already exists anywhere the app looks.
$haveKey = $env:OPENROUTER_API_KEY -or
    ((Test-Path .env) -and (Select-String -Path .env -Pattern '^\s*OPENROUTER_API_KEY\s*=\s*\S' -Quiet)) -or
    ((Test-Path "$HOME\.secrets\api-keys.env") -and (Select-String -Path "$HOME\.secrets\api-keys.env" -Pattern '^\s*OPENROUTER_(API_)?KEY\s*=\s*\S' -Quiet))
if (-not $haveKey -and -not $Local) {
    $secure = Read-Host "Paste your OpenRouter API key (input hidden, Enter to skip and run locally)" -AsSecureString
    $key = [System.Net.NetworkCredential]::new('', $secure).Password
    if ($key) { Set-Content -Path .env -Value "OPENROUTER_API_KEY=$key" -Encoding ascii; Write-Host "Saved to .env" }
    else { $Local = $true }
}

if (Get-Command git -ErrorAction SilentlyContinue) {
    git config core.hooksPath .githooks   # blocks commits that contain API keys
}

Write-Host "`nRunning offline tests..." -ForegroundColor Cyan
& $venvPython -m unittest
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

Write-Host "`nChecking every model ID against OpenRouter..." -ForegroundColor Cyan
& $venvPython -m council --check
if ($LASTEXITCODE -ne 0) { Write-Host "Some model IDs need updating in council.toml (see above)." -ForegroundColor Yellow }

if ($Local) {
    Write-Host "`nSetting up local mode (Ollama: models run on this PC, no key)..." -ForegroundColor Cyan
    $ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue) -and -not (Test-Path $ollamaExe)) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw "Install Ollama from https://ollama.com/download, then re-run .\setup.ps1 -Local"
        }
        Write-Host "Installing Ollama..." -ForegroundColor Cyan
        winget install --id Ollama.Ollama -e --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) { throw "Ollama install failed. Get it from https://ollama.com/download" }
    }
    # Pick up the new PATH in this window, then download the models (resumes if interrupted).
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    Write-Host "Downloading local models (one time, ~10 GB)..." -ForegroundColor Cyan
    & $venvPython -m council --roster local --pull
    if ($LASTEXITCODE -ne 0) { throw "Local model download failed (see above). Re-run .\setup.ps1 -Local to resume." }
    Write-Host "`nAll set. Ask it something:  .\run.ps1 -Roster local `"What should I build next?`"" -ForegroundColor Green
} else {
    Write-Host "`nAll set. Ask it something:  .\run.ps1 `"What should I build next?`"" -ForegroundColor Green
}
