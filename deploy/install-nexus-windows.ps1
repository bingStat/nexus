param(
    [Parameter(Mandatory=$true)][string]$ApiToken,
    [string]$DeviceId = 'elitebook',
    [string]$DeviceName = 'EliteBook',
    [string]$ApiUrl = 'https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1',
    [string[]]$Aliases = @('elitebook'),
    [string]$PythonExe = ''
)

$ErrorActionPreference = 'Stop'
$AgentDir = Join-Path $env:USERPROFILE '.nexus-agent'
New-Item -ItemType Directory -Path $AgentDir -Force | Out-Null

if (-not $PythonExe) {
    $candidates = @(
        (Join-Path $env:USERPROFILE 'miniconda3\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
    ) | Where-Object { $_ -and (Test-Path $_) }
    $PythonExe = $candidates | Select-Object -First 1
}
if (-not $PythonExe) { throw 'Python 3 was not found.' }

$AgentUrl = 'https://raw.githubusercontent.com/bingStat/nexus/main/agent.py'
Invoke-WebRequest -UseBasicParsing -Uri $AgentUrl -OutFile (Join-Path $AgentDir 'agent.py')

$rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
$bytes = New-Object byte[] 32
$rng.GetBytes($bytes); $rng.Dispose()
$DeviceToken = ([BitConverter]::ToString($bytes)).Replace('-','').ToLowerInvariant()

$config = [ordered]@{
    api_url = $ApiUrl
    api_token = $ApiToken
    device_token = $DeviceToken
    device_id = $DeviceId.ToLowerInvariant()
    device_name = $DeviceName
    aliases = $Aliases
    poll_seconds = 2
    heartbeat_seconds = 15
    lease_seconds = 90
    max_workers = 2
    lock_port = 49158
    strict_rpc = $false
}
$config | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $AgentDir 'config.json') -Encoding UTF8
$DeviceToken | Set-Content (Join-Path $AgentDir 'device.token') -Encoding Ascii -NoNewline

$watchdog = @"
`$created = `$false
`$mutex = New-Object System.Threading.Mutex(`$true, 'Local\NexusAgentWatchdog-$($DeviceId.ToLowerInvariant())', [ref]`$created)
if (-not `$created) { exit 0 }
try {
  while (`$true) {
    `$env:NEXUS_CONFIG_FILE = '$AgentDir\config.json'
    & '$PythonExe' -u '$AgentDir\agent.py' 1>>'$AgentDir\agent.log' 2>>'$AgentDir\agent.err.log'
    Start-Sleep -Seconds 5
  }
} finally { `$mutex.Dispose() }
"@
$watchdog | Set-Content (Join-Path $AgentDir 'watchdog.ps1') -Encoding UTF8

$cmd = "@echo off`r`n`"C:\Program Files\PowerShell\7\pwsh.exe`" -NoProfile -NonInteractive -File `"$AgentDir\watchdog.ps1`"`r`n"
$cmd | Set-Content (Join-Path $AgentDir 'start-agent.cmd') -Encoding Ascii

$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$AgentDir\start-agent.cmd`""
$trigger1 = New-ScheduledTaskTrigger -AtLogOn
$trigger2 = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName 'NexusAgent' -Action $action -Trigger @($trigger1,$trigger2) -Settings $settings -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName 'NexusAgent'

Write-Host "Nexus Agent installed for $DeviceId."
Write-Host "Config: $AgentDir\config.json"
Write-Host "Task: NexusAgent"
