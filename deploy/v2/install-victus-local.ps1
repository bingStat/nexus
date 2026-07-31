param(
    [string]$PackageRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$AgentDir = 'C:\Users\Bing\.nexus-agent',
    [string]$DeviceId = 'victus',
    [string]$NodeName = 'Victus Workstation',
    [switch]$CompatibilityMode
)

$ErrorActionPreference = 'Stop'
$OldRunner = Join-Path $AgentDir 'run_win_agent.py'
$AgentSource = Join-Path $PackageRoot 'agent\agent_v2.py'
if (-not (Test-Path $AgentSource)) { throw "Missing $AgentSource" }

$ApiUrl = $env:NEXUS_API_URL
$ApiToken = if ($env:NEXUS_API_TOKEN) { $env:NEXUS_API_TOKEN } else { $env:NEXUS_API_KEY }
$DeviceToken = $env:NEXUS_DEVICE_TOKEN
if ((!$ApiUrl -or !$ApiToken) -and (Test-Path $OldRunner)) {
    $Legacy = Get-Content -Raw -LiteralPath $OldRunner
    if (!$ApiUrl -and $Legacy -match '(?m)^\s*API_URL\s*=\s*["'']([^"'']+)') {
        $ApiUrl = $Matches[1]
    }
    if (!$ApiToken -and $Legacy -match '(?m)^\s*API_KEY\s*=\s*["'']([^"'']+)') {
        $ApiToken = $Matches[1]
    }
}
if (!$ApiUrl -or !$ApiToken) { throw 'Existing Nexus API credentials were not found' }
if (!$DeviceToken) {
    if (!$CompatibilityMode) { throw 'NEXUS_DEVICE_TOKEN is required outside compatibility mode' }
    $DeviceToken = 'pending-device-enrollment'
}

$Python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (!$Python -and (Test-Path 'C:\Users\Bing\miniconda3\python.exe')) {
    $Python = 'C:\Users\Bing\miniconda3\python.exe'
}
if (!$Python) { throw 'Python was not found' }
New-Item -ItemType Directory -Force -Path $AgentDir | Out-Null
$BackupDir = Join-Path $AgentDir ('backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
foreach ($Name in @('run_win_agent.py','agent.py','config.json','start-agent.cmd')) {
    $Existing = Join-Path $AgentDir $Name
    if (Test-Path $Existing) { Copy-Item $Existing $BackupDir -Force }
}

$AgentPath = Join-Path $AgentDir 'agent.py'
$ConfigPath = Join-Path $AgentDir 'config.json'
$StartPath = Join-Path $AgentDir 'start-agent.cmd'
$LogPath = Join-Path $AgentDir 'agent-v2.log'
$ErrPath = Join-Path $AgentDir 'agent-v2.err.log'
Copy-Item $AgentSource $AgentPath -Force
& $Python -m pip install --disable-pip-version-check -q 'requests>=2.31,<3'
if ($LASTEXITCODE -ne 0) { throw 'Failed to install requests' }

$Config = [ordered]@{
    api_url = $ApiUrl
    api_token = $ApiToken
    device_token = $DeviceToken
    strict_rpc = (-not $CompatibilityMode)
    device_id = $DeviceId
    device_name = $NodeName
    aliases = @('yang','victus-workspace')
    poll_seconds = 2
    heartbeat_seconds = 15
    lease_seconds = 90
    max_workers = 2
    lock_port = 49158
}
$Config | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ConfigPath -Encoding UTF8

$StartCode = @"
@echo off
set "NEXUS_CONFIG_FILE=$ConfigPath"
"$Python" -u "$AgentPath" 1>>"$LogPath" 2>>"$ErrPath"
"@
Set-Content -LiteralPath $StartPath -Value $StartCode -Encoding ASCII

Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'run_win_agent.py|\\.nexus-agent\\agent.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$Action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument "/c `"$StartPath`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)
Unregister-ScheduledTask -TaskName 'NexusAgent' -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName 'NexusAgent' -Action $Action -Trigger $Trigger `
    -Settings $Settings -User $env:USERNAME -Force | Out-Null
Start-ScheduledTask -TaskName 'NexusAgent'
Start-Sleep -Seconds 5

$Process = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match '\\.nexus-agent\\agent.py' } |
    Select-Object -First 1
if (!$Process) { throw "Nexus Agent v2 did not start; inspect $ErrPath" }
Write-Output ('DEPLOYED device=' + $DeviceId)
Write-Output ('PID=' + $Process.ProcessId)
Write-Output ('MODE=' + $(if ($CompatibilityMode) { 'compatibility' } else { 'strict-rpc' }))
Write-Output ('BACKUP=' + $BackupDir)
