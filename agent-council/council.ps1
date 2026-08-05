param(
    [Parameter(Mandatory=$true)][ValidateSet('doctor','run','status','web-start','web-submit','web-advance','web-finalize','web-status','web-serve','advisor-turn')][string]$Command,
    [string]$Repo = 'C:\Users\Bing\aurora\Workstation\Nexus',
    [string]$TaskId,
    [string]$Task,
    [ValidateSet('web-discussion','web-hybrid')][string]$Mode = 'web-discussion',
    [ValidateSet('chatgpt','claude','gemini')][string]$Provider,
    [int]$Round,
    [string]$ResponseFile,
    [switch]$Overwrite,
    [string]$Bind = '127.0.0.1',
    [int]$Port = 8765,
    [string]$Token,
    [switch]$DiscussionOnly,
    [string[]]$AcceptCommand = @(),
    [string]$CurrentUserMessage = '',
    [string]$OrchestratorMessage = '',
    [string]$Synthesis = '',
    [string]$Providers = 'claude,gemini',
    [string]$IdempotencyKey,
    [int]$ByteLimit = 200000,
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
if ($Command -eq 'web-start') {
    if (-not $Task) { throw '-Task is required.' }
    $ArgsList += @('--task', $Task, '--mode', $Mode)
}
if ($Command -eq 'web-submit') {
    if (-not $Provider) { throw '-Provider is required.' }
    if ($Round -ne 1 -and $Round -ne 2) { throw '-Round must be 1 or 2.' }
    $ArgsList += @('--provider', $Provider, '--round', "$Round")
    if ($ResponseFile) { $ArgsList += @('--response-file', $ResponseFile) }
    if ($Overwrite) { $ArgsList += '--overwrite' }
}
if ($Command -eq 'web-finalize') {
    $ArgsList += @('--timeout', "$Timeout")
    foreach ($Acceptance in $AcceptCommand) {
        $ArgsList += @('--accept-command', $Acceptance)
    }
}
if ($Command -eq 'web-serve') {
    $ArgsList += @('--bind', $Bind, '--port', "$Port")
    if ($Token) { $ArgsList += @('--token', $Token) }
}
if ($Command -eq 'advisor-turn') {
    if (-not $IdempotencyKey) { throw '-IdempotencyKey is required.' }
    if ($Task) { $ArgsList += @('--task', $Task) }
    if ($CurrentUserMessage) { $ArgsList += @('--current-user-message', $CurrentUserMessage) }
    if ($OrchestratorMessage) { $ArgsList += @('--orchestrator-message', $OrchestratorMessage) }
    if ($Synthesis) { $ArgsList += @('--synthesis', $Synthesis) }
    $ArgsList += @('--providers', $Providers, '--idempotency-key', $IdempotencyKey, '--byte-limit', "$ByteLimit", '--timeout', "$Timeout")
}
& $Python @ArgsList
exit $LASTEXITCODE
