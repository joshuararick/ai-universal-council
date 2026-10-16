# Ask the Council.
#   .\run.ps1 "Should I use Postgres or SQLite?"
#   .\run.ps1 -Roster free "question"      (free models, no credits needed)
#   .\run.ps1 -Roster local "question"     (models on this PC via Ollama, no key at all)
#   .\run.ps1 --check                      (verify model IDs, no key needed)
# No -Roster and no OpenRouter key? It runs locally automatically.
param([string]$Roster = "", [Parameter(ValueFromRemainingArguments)][string[]]$Rest)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { Write-Host "Run .\setup.ps1 first." -ForegroundColor Red; exit 1 }
Push-Location $PSScriptRoot
$rosterArgs = if ($Roster) { @("--roster", $Roster) } else { @() }
try { & $python -m council @rosterArgs @Rest } finally { Pop-Location }
exit $LASTEXITCODE
