# Usage: .\run.ps1 [-Roster free] [directive...]
param([string]$Roster = "default", [Parameter(ValueFromRemainingArguments)][string[]]$Directive)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
& py "$PSScriptRoot\core\council.py" --roster $Roster @Directive
