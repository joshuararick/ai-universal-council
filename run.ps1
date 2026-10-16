# Usage: .\run.ps1 [-Roster free] [directive...]
param([string]$Roster = "default", [Parameter(ValueFromRemainingArguments)][string[]]$Directive)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "py" }
& $python "$PSScriptRoot\core\council.py" --roster $Roster @Directive
