# Opens the Council in your browser. Double-click "Start Council.bat" to run this.
# First time: installs everything (asks for an OpenRouter key; press Enter to run on this PC instead).
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    & .\setup.ps1
} else {
    # No key anywhere and no Ollama yet? Set up local mode so there's something to run.
    & $python -c "from council.config import load_api_key as k; raise SystemExit(0 if k() else 1)"
    $haveKey = $LASTEXITCODE -eq 0
    $ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    $haveOllama = (Get-Command ollama -ErrorAction SilentlyContinue) -or (Test-Path $ollamaExe)
    if (-not $haveKey -and -not $haveOllama) { & .\setup.ps1 -Local }
}

Write-Host "`nOpening the Council in your browser..." -ForegroundColor Green
& $python -m council --web
