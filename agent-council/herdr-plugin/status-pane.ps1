param(
    [string]$Repo = 'C:\Users\Bing\aurora\Workstation\Nexus',
    [Parameter(Mandatory=$true)][string]$TaskId
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Council = Join-Path $Root 'council.ps1'
while ($true) {
    Clear-Host
    powershell.exe -NoProfile -NonInteractive -File $Council web-status -Repo $Repo -TaskId $TaskId
    Start-Sleep -Seconds 5
}
