param(
    [Parameter(Mandatory=$false)][string]$DeviceId = "victus",
    [string]$RegistryUrl = "https://nexus-global-api.bings.app",
    [string]$BrokerUrl = "https://nexus-global-api.bings.app/v3/eu-broker",
    [string]$InstallDir = "$env:LOCALAPPDATA\NexusAgentV3",
    [string[]]$AllowedRoots = @($env:USERPROFILE)
)
$ErrorActionPreference = "Stop"
$SourceBase = if ($env:NEXUS_SOURCE_BASE) { $env:NEXUS_SOURCE_BASE.TrimEnd('/') } else { "https://raw.githubusercontent.com/bingStat/nexus/main" }

function Get-Python {
    $preferred = @("$env:USERPROFILE\miniconda3\python.exe", "$env:USERPROFILE\anaconda3\python.exe")
    foreach ($candidate in $preferred) { if (Test-Path $candidate) { return $candidate } }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "Python 3 is required"
}

$Python = Get-Python
New-Item -ItemType Directory -Force -Path "$InstallDir\nexus_v3", "$InstallDir\logs" | Out-Null
foreach ($file in @("__init__.py","common.py","agent.py","devspace_runtime.py","ledger.py")) {
    Invoke-WebRequest -UseBasicParsing "$SourceBase/nexus_v3/$file" -OutFile "$InstallDir\nexus_v3\$file"
}
if (-not (Test-Path "$InstallDir\.venv\Scripts\python.exe")) {
    & $Python -m venv "$InstallDir\.venv"
}
$RuntimePython = "$InstallDir\.venv\Scripts\python.exe"
& $RuntimePython -m pip install --disable-pip-version-check --quiet requests cryptography

$DevSpace = $null
$Node = Get-Command node -ErrorAction SilentlyContinue
$Npm = Get-Command npm -ErrorAction SilentlyContinue
if ($Node -and $Npm) {
    $nodeVersion = (& $Node.Source -p "process.versions.node").Trim()
    $parts = $nodeVersion.Split('.')
    if ([int]$parts[0] -gt 22 -or ([int]$parts[0] -eq 22 -and [int]$parts[1] -ge 19)) {
        $DevSpace = "$InstallDir\devspace-runtime"
        New-Item -ItemType Directory -Force -Path $DevSpace | Out-Null
        Invoke-WebRequest -UseBasicParsing "$SourceBase/runtime/devspace/package.json" -OutFile "$DevSpace\package.json"
        Invoke-WebRequest -UseBasicParsing "$SourceBase/runtime/devspace/package-lock.json" -OutFile "$DevSpace\package-lock.json"
        Invoke-WebRequest -UseBasicParsing "$SourceBase/runtime/devspace/bridge.mjs" -OutFile "$DevSpace\bridge.mjs"
        Push-Location $DevSpace
        try { & $Npm.Source ci --omit=dev --no-audit --no-fund; & $Node.Source .\bridge.mjs --self-test | Out-Host }
        finally { Pop-Location }
    }
}

$Config = [ordered]@{
    device_id = $DeviceId.ToLowerInvariant()
    registry_url = $RegistryUrl.TrimEnd('/')
    broker_url = $BrokerUrl.TrimEnd('/')
    identity_key = "$InstallDir\identity_ed25519"
    identity_public_key = "$InstallDir\identity_ed25519.pub"
    ssh_private_key = "$InstallDir\identity_ed25519"
    ssh_public_key = "$InstallDir\identity_ed25519.pub"
    wait_seconds = 20; poll_seconds = 1; request_timeout = 35
    execution_ledger = "$InstallDir\execution-ledger.db"
}
if ($DevSpace) {
    $Config.devspace = [ordered]@{
        bridge = "$DevSpace\bridge.mjs"
        node = $Node.Source
        allowed_roots = $AllowedRoots
        state_dir = "$InstallDir\devspace-state"
    }
}
$Config | ConvertTo-Json -Depth 8 | Set-Content "$InstallDir\v3.json" -Encoding utf8

$Runner = @"
@echo off
set NEXUS_V3_CONFIG=$InstallDir\v3.json
cd /d $InstallDir
"$RuntimePython" -m nexus_v3.agent >> "$InstallDir\logs\agent.log" 2>&1
"@
$Runner | Set-Content "$InstallDir\run-agent.cmd" -Encoding ascii

$TaskName = "Nexus v3 Agent ($($DeviceId.ToLowerInvariant()))"
schtasks.exe /Delete /TN $TaskName /F 2>$null | Out-Null
schtasks.exe /Create /SC ONLOGON /TN $TaskName /TR "`"$InstallDir\run-agent.cmd`"" /F | Out-Null
Start-Process -WindowStyle Hidden -FilePath "$InstallDir\run-agent.cmd"
Start-Sleep -Seconds 2

& $RuntimePython -m py_compile "$InstallDir\nexus_v3\agent.py" "$InstallDir\nexus_v3\ledger.py"
Write-Host "Nexus v3 installed for $DeviceId at $InstallDir"
Write-Host "Identity is Ed25519 and remains local; no shared fleet credential is stored on the device."
if ($DevSpace) { Write-Host "DevSpace runtime enabled for: $($AllowedRoots -join ', ')" }
else { Write-Host "DevSpace runtime skipped because Node >= 22.19 + npm were not available." }
