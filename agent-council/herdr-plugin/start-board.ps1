param(
    [string]$Repo = 'C:\Users\Bing\aurora\Workstation\Nexus',
    [Parameter(Mandatory=$true)][string]$TaskId,
    [int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Council = Join-Path $Root 'council.ps1'
powershell.exe -NoProfile -NoExit -File $Council web-serve -Repo $Repo -TaskId $TaskId -Port $Port
