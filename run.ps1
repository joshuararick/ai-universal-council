# Ask the Council.
#   .\run.ps1 "Should I use Postgres or SQLite?"
#   .\run.ps1 -Roster free "question"      (free models, no credits needed)
#   .\run.ps1 --check                      (verify model IDs, no key needed)
# PositionalBinding off: a bare question must never be taken as the -Roster value.
[CmdletBinding(PositionalBinding = $false)]
param([string]$Roster = "default", [Parameter(ValueFromRemainingArguments)][string[]]$Rest)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { Write-Host "Run .\setup.ps1 first." -ForegroundColor Red; exit 1 }
Push-Location $PSScriptRoot
try { & $python -m council --roster $Roster @Rest } finally { Pop-Location }
exit $LASTEXITCODE
