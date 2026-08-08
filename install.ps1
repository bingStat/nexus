[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet("victus","elitebook")][string]$DeviceId,
    [uri]$BrokerUrl = "http://127.0.0.1:18000",
    [uri]$ApiUrl = "https://nexus-global-api.bings.app",
    [string]$SourceBase = "https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394"
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
$identityKey = Join-Path $installDir "identity_ed25519"
$identityPub = Join-Path $installDir "identity_ed25519.pub"
New-Item -ItemType Directory -Path $installDir -Force | Out-Null

Invoke-WebRequest "$($SourceBase.TrimEnd('/'))/agent/windows_agent.py" -OutFile $agentFile
& $python -m pip install --disable-pip-version-check --quiet requests cryptography
if ($LASTEXITCODE -ne 0) { throw "Failed to install Python dependencies." }

$config = [ordered]@{
    device_id = $DeviceId
    device_name = $DeviceId
    broker_urls = @($BrokerUrl.AbsoluteUri.TrimEnd('/'))
    api_url = $ApiUrl.AbsoluteUri.TrimEnd('/')
    identity_key_path = $identityKey
    identity_public_key_path = $identityPub
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

if (-not (Test-Path $identityKey)) {
    $keygen = @"
import sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
private_path, public_path = map(Path, sys.argv[1:])
key = Ed25519PrivateKey.generate()
private_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
public_path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
"@
    & $python -c $keygen $identityKey $identityPub
    if ($LASTEXITCODE -ne 0) { throw "Failed to generate Nexus identity key." }
}
foreach ($path in @($identityKey, $identityPub)) {
    $itemAcl = Get-Acl $path
    $itemAcl.SetAccessRuleProtection($true, $false)
    $itemAcl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("SYSTEM","FullControl","Allow")))
    $itemAcl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("$env:USERDOMAIN\$env:USERNAME","FullControl","Allow")))
    Set-Acl $path $itemAcl
}

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
