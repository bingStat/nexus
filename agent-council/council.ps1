param(
    [Parameter(Mandatory=$true)][ValidateSet('doctor','run','status')][string]$Command,
    [string]$Repo = 'C:\Users\Bing\aurora\Workstation\Nexus',
    [string]$TaskId,
    [string]$Task,
    [switch]$DiscussionOnly,
    [string[]]$AcceptCommand = @(),
    [int]$Timeout = 600
)
$ErrorActionPreference = 'Stop'
$env:Path = [Environment]::GetEnvironmentVariable('Path','User') + ';' + [Environment]::GetEnvironmentVariable('Path','Machine')
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = 'C:\Users\Bing\miniconda3\python.exe'
$ArgsList = @((Join-Path $Root 'council.py'), $Command)
if ($Command -ne 'doctor') {
    if (-not $TaskId) { throw '-TaskId is required.' }
    $ArgsList += @('--repo', $Repo, '--task-id', $TaskId)
}
if ($Command -eq 'run') {
    if (-not $Task) { throw '-Task is required.' }
    $ArgsList += @('--task', $Task, '--timeout', "$Timeout")
    if ($DiscussionOnly) { $ArgsList += '--discussion-only' }
    foreach ($Acceptance in $AcceptCommand) {
        $ArgsList += @('--accept-command', $Acceptance)
    }
}
& $Python @ArgsList
exit $LASTEXITCODE
