[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet("victus","elitebook")][string]$DeviceId,
    [Parameter(Mandatory)][uri]$BrokerUrl,
    [Parameter(Mandatory)][string]$Token,
    [string]$SourceBase = "https://raw.githubusercontent.com/bingStat/nexus/main"
)

$ErrorActionPreference = "Stop"
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run PowerShell as Administrator."
}

$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python) { throw "python.exe is required." }

$installDir = Join-Path $env:ProgramData "NexusAgent"
$configFile = Join-Path $installDir "config.json"
$agentFile = Join-Path $installDir "agent.py"
New-Item -ItemType Directory -Path $installDir -Force | Out-Null

Invoke-WebRequest "$($SourceBase.TrimEnd('/'))/agent/windows_agent.py" -OutFile $agentFile
& $python -m pip install --disable-pip-version-check --quiet requests
if ($LASTEXITCODE -ne 0) { throw "Failed to install Python dependency: requests" }

$config = [ordered]@{
    device_id = $DeviceId
    device_name = $DeviceId
    broker_urls = @($BrokerUrl.AbsoluteUri.TrimEnd('/'))
    api_token = $Token
    poll_seconds = 0.5
    heartbeat_seconds = 30
    max_workers = 2
}
$config | ConvertTo-Json -Depth 4 | Set-Content -Path $configFile -Encoding UTF8
$acl = Get-Acl $configFile
$acl.SetAccessRuleProtection($true, $false)
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("SYSTEM","FullControl","Allow")))
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("$env:USERDOMAIN\$env:USERNAME","FullControl","Allow")))
Set-Acl $configFile $acl

$taskName = "NexusAgent"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$agentFile`"" -WorkingDirectory $installDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -User "SYSTEM" -RunLevel Highest -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 2
if ((Get-ScheduledTask -TaskName $taskName).State -notin @("Running","Ready")) { throw "NexusAgent scheduled task did not start." }
Write-Host "Nexus agent installed for $DeviceId."
