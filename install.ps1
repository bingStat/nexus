param(
    [Parameter(Mandatory=$false)][string]$DeviceId = "victus",
    [string]$RegistryUrl = "https://nexus-global-api.bings.app",
    [string]$BrokerUrl = "https://nexus-eu-broker.bings.app",
    [string]$InstallDir = "$env:LOCALAPPDATA\NexusAgentV3",
    [string[]]$AllowedRoots = @($env:USERPROFILE)
)
$ErrorActionPreference = "Stop"
$SourceBase = if ($env:NEXUS_SOURCE_BASE) { $env:NEXUS_SOURCE_BASE.TrimEnd('/') } else { "https://nexus.bings.app/bootstrap" }

function Get-Python {
    $preferred = @("$env:USERPROFILE\miniconda3\python.exe", "$env:USERPROFILE\anaconda3\python.exe")
    foreach ($candidate in $preferred) { if (Test-Path $candidate) { return $candidate } }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "Python 3 is required"
}

function Test-RuntimePython([string]$Path) {
    if (-not (Test-Path $Path)) { return $false }
    try {
        & $Path -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}
$Python = Get-Python
New-Item -ItemType Directory -Force -Path "$InstallDir\nexus_v3", "$InstallDir\logs" | Out-Null
foreach ($file in @("__init__.py","common.py","agent.py","devspace_runtime.py","ledger.py")) {
    Invoke-WebRequest -UseBasicParsing "$SourceBase/nexus_v3/$file" -OutFile "$InstallDir\nexus_v3\$file"
}

$RuntimePython = "$InstallDir\.venv\Scripts\python.exe"
if (-not (Test-RuntimePython $RuntimePython)) {
    if (Test-Path "$InstallDir\.venv") { Remove-Item "$InstallDir\.venv" -Recurse -Force }
    & $Python -m venv "$InstallDir\.venv"
    if ($LASTEXITCODE -ne 0 -or -not (Test-RuntimePython $RuntimePython)) {
        throw "Failed to create a usable Nexus Python runtime"
    }
}
& $RuntimePython -m pip install --disable-pip-version-check --quiet requests cryptography
if ($LASTEXITCODE -ne 0) { throw "Failed to install Nexus Python dependencies" }

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
        try {
            & $Npm.Source ci --omit=dev --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw "DevSpace npm install failed" }
            & $Node.Source .\bridge.mjs --self-test | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "DevSpace self-test failed" }
        } finally { Pop-Location }
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
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText("$InstallDir\v3.json", ($Config | ConvertTo-Json -Depth 8), $Utf8NoBom)

$Runner = @"
@echo off
set NEXUS_V3_CONFIG=$InstallDir\v3.json
cd /d $InstallDir
"$RuntimePython" -m nexus_v3.agent >> "$InstallDir\logs\agent.log" 2>&1
"@
$Runner | Set-Content "$InstallDir\run-agent.cmd" -Encoding ascii

$LegacyTaskNames = @(
    "NexusAgent",
    "NexusV3Agent",
    "Nexus v3 Agent ($($DeviceId.ToLowerInvariant()))"
)
foreach ($TaskName in $LegacyTaskNames) {
    try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch {}
    try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
}
$InstallDirPattern = [regex]::Escape($InstallDir)
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.ProcessId -ne $PID -and
        $_.CommandLine -and
        $_.CommandLine -match "nexus_v3\.agent" -and
        $_.CommandLine -match $InstallDirPattern
    } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$LegacyDir = "$env:USERPROFILE\.nexus-agent"
if (Test-Path $LegacyDir) { Remove-Item $LegacyDir -Recurse -Force -ErrorAction SilentlyContinue }
Remove-Item "$InstallDir\agent.log", "$InstallDir\ssh_ed25519.pub" -Force -ErrorAction SilentlyContinue

$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
New-Item -Path $RunKey -Force | Out-Null
$RunCommand = 'cmd.exe /d /s /c ""{0}""' -f "$InstallDir\run-agent.cmd"
New-ItemProperty -Path $RunKey -Name "NexusV3Agent" -PropertyType String -Value $RunCommand -Force | Out-Null

& $RuntimePython -m py_compile "$InstallDir\nexus_v3\agent.py" "$InstallDir\nexus_v3\ledger.py"
if ($LASTEXITCODE -ne 0) { throw "Nexus Python compile check failed" }
Start-Process -WindowStyle Hidden -FilePath "$InstallDir\run-agent.cmd"
Start-Sleep -Seconds 2
Write-Host "Nexus v3 installed for $DeviceId at $InstallDir"
Write-Host "Startup: HKCU Run\NexusV3Agent (no administrator privilege required)."
Write-Host "Identity is Ed25519 and remains local; no shared fleet credential is stored on the device."
if ($DevSpace) { Write-Host "DevSpace runtime enabled for: $($AllowedRoots -join ', ')" }
else { Write-Host "DevSpace runtime skipped because Node >= 22.19 + npm were not available." }
