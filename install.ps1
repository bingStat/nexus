param(
    [Parameter(Mandatory=$false)][string]$DeviceId = "auto",
    [string]$RegistryUrl = "https://nexus-global-api.bings.app",
    [string]$BrokerUrl = "https://nexus-eu-broker.bings.app",
    [string]$InstallDir = "$env:LOCALAPPDATA\NexusAgentV3",
    [string[]]$AllowedRoots = @($env:USERPROFILE),
    [string]$AdminKey = $env:NEXUS_V3_ADMIN_KEY
)
$ErrorActionPreference = "Stop"
if (-not $DeviceId -or $DeviceId -eq "auto") {
    $DeviceId = $env:COMPUTERNAME.ToLowerInvariant() -replace '[^a-z0-9_.-]', ''
}
$SourceBase = if ($env:NEXUS_SOURCE_BASE) { $env:NEXUS_SOURCE_BASE.TrimEnd('/') } else { "https://raw.githubusercontent.com/bingStat/nexus/main" }

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
foreach ($file in @("__init__.py","common.py","agent.py","devspace_runtime.py","ledger.py","ssh_fleet.py")) {
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
& $RuntimePython -m pip install --disable-pip-version-check --quiet requests
if ($LASTEXITCODE -ne 0) { throw "Failed to install Nexus Python dependencies" }

$SshDir = Join-Path $env:USERPROFILE ".ssh"
$SshKey = Join-Path $SshDir ("id_ed25519_{0}" -f $DeviceId.ToLowerInvariant())
$SshPub = "$SshKey.pub"
$SshAuthorizedKeys = Join-Path $SshDir "authorized_keys"
New-Item -ItemType Directory -Force -Path $SshDir | Out-Null
$SshKeygen = Get-Command ssh-keygen -ErrorAction SilentlyContinue
if (-not $SshKeygen) { throw "OpenSSH ssh-keygen is required" }

if (-not (Test-Path $SshKey)) {
    $SourceSshKey = $env:NEXUS_SSH_SOURCE_KEY
    if (-not $SourceSshKey) {
        $generic = Join-Path $SshDir "id_ed25519"
        if (Test-Path $generic) { $SourceSshKey = $generic }
    }
    if ($SourceSshKey -and (Test-Path $SourceSshKey)) {
        Move-Item -LiteralPath $SourceSshKey -Destination $SshKey
        if (Test-Path "$SourceSshKey.pub") { Move-Item -LiteralPath "$SourceSshKey.pub" -Destination $SshPub }
    } else {
        & $SshKeygen.Source -q -t ed25519 -N "" -C "nexus-$($DeviceId.ToLowerInvariant())@$env:COMPUTERNAME" -f $SshKey
        if ($LASTEXITCODE -ne 0) { throw "Failed to create the per-device SSH key: $SshKey" }
    }
}
if (-not (Test-Path $SshPub)) {
    $publicBody = (& $SshKeygen.Source -y -f $SshKey).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $publicBody) { throw "Failed to derive SSH public key: $SshPub" }
    [System.IO.File]::WriteAllText($SshPub, "$publicBody nexus-$($DeviceId.ToLowerInvariant())@$env:COMPUTERNAME`n", (New-Object System.Text.UTF8Encoding($false)))
}

$DeviceKey = "$InstallDir\device.key"
if (-not (Test-Path $DeviceKey)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $hex = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    [System.IO.File]::WriteAllText($DeviceKey, "nxk_$hex`n", (New-Object System.Text.UTF8Encoding($false)))
}
Remove-Item "$InstallDir\identity_ed25519", "$InstallDir\identity_ed25519.pub" -Force -ErrorAction SilentlyContinue

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
    device_key = $DeviceKey
    ssh_private_key = $SshKey
    ssh_public_key = $SshPub
    ssh_authorized_keys = $SshAuthorizedKeys
    ssh_sync_interval = 300
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
`$ErrorActionPreference = "Stop"
`$env:NEXUS_V3_CONFIG = "$InstallDir\v3.json"
`$env:PYTHONUTF8 = "1"
`$env:PYTHONIOENCODING = "utf-8"
`$logDir = "$InstallDir\logs"
`$logPath = Join-Path `$logDir "agent.log"
New-Item -ItemType Directory -Force -Path `$logDir | Out-Null

if ((Test-Path `$logPath) -and (Get-Item `$logPath).Length -ge 10MB) {
    `$archive = Join-Path `$logDir ("agent-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
    Move-Item `$logPath `$archive -Force
}
Get-ChildItem `$logDir -Filter "agent-*.log" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 5 |
    Remove-Item -Force -ErrorAction SilentlyContinue

Set-Location "$InstallDir"
try {
    & "$RuntimePython" -m nexus_v3.agent *>> `$logPath
    `$exitCode = `$LASTEXITCODE
    if (`$exitCode -eq 42) { exit 0 }
    exit `$exitCode
}
catch {
    Add-Content -Path `$logPath -Encoding UTF8 -Value ("[{0}] supervisor error: {1}" -f (Get-Date -Format o), `$_.Exception.Message)
    exit 1
}
"@
[System.IO.File]::WriteAllText("$InstallDir\run-agent.ps1", $Runner, $Utf8NoBom)

$FunctionalWatchdog = @"
`$ErrorActionPreference = "Stop"
`$installDir = "$InstallDir"
`$configPath = Join-Path `$installDir "v3.json"
`$logDir = Join-Path `$installDir "logs"
`$logPath = Join-Path `$logDir "watchdog.log"
`$maxAgeSeconds = 120
New-Item -ItemType Directory -Force -Path `$logDir | Out-Null

function Write-WatchdogLog([string]`$Message) {
    Add-Content -Path `$logPath -Encoding UTF8 -Value ("[{0}] {1}" -f (Get-Date -Format o), `$Message)
}

function Restart-NexusAgent([string]`$Reason) {
    Write-WatchdogLog ("restart: " + `$Reason)
    try { Stop-ScheduledTask -TaskName "NexusV3Agent" -ErrorAction SilentlyContinue } catch {}
    `$pattern = [regex]::Escape(`$installDir)
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            `$_.CommandLine -and
            `$_.CommandLine -match `$pattern -and
            `$_.CommandLine -match "nexus_v3\.agent"
        } |
        ForEach-Object { Stop-Process -Id `$_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
    Start-ScheduledTask -TaskName "NexusV3Agent" -ErrorAction Stop
}

try {
    `$config = Get-Content -LiteralPath `$configPath -Raw | ConvertFrom-Json
    `$deviceId = [string]`$config.device_id
    `$broker = ([string]`$config.broker_url).TrimEnd('/')
    `$deviceKey = (Get-Content -LiteralPath ([string]`$config.device_key) -Raw).Trim()
    if (-not `$deviceId -or -not `$broker -or -not `$deviceKey) { throw "incomplete agent configuration" }

    `$headers = @{
        "X-Nexus-Device" = `$deviceId
        "X-Nexus-Device-Key" = `$deviceKey
    }
    `$presence = Invoke-RestMethod -Uri "`$broker/v3/agents/self" -Headers `$headers -Method Get -TimeoutSec 8
    `$lastSeen = [DateTimeOffset]::Parse([string]`$presence.last_seen).ToUniversalTime()
    `$age = ([DateTimeOffset]::UtcNow - `$lastSeen).TotalSeconds
    if (`$age -gt `$maxAgeSeconds) {
        Restart-NexusAgent ("broker presence stale: {0:N0}s" -f `$age)
    }
} catch {
    Restart-NexusAgent ("functional check failed: " + `$_.Exception.Message)
}
"@
[System.IO.File]::WriteAllText("$InstallDir\watchdog.ps1", $FunctionalWatchdog, $Utf8NoBom)

$LegacyTaskNames = @(
    "NexusAgent",
    "Nexus v3 Agent ($($DeviceId.ToLowerInvariant()))",
    "NexusV3Agent-Watchdog",
    "NexusV3Watchdog",
    "NexusV3FunctionalWatchdog"
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
        $_.CommandLine -match $InstallDirPattern -and
        ($_.CommandLine -match "nexus_v3\.agent" -or $_.CommandLine -match "run-agent\.cmd" -or $_.CommandLine -match "run-agent\.ps1")
    } |
    Sort-Object { if ($_.Name -eq 'cmd.exe' -or $_.Name -eq 'powershell.exe') { 0 } else { 1 } } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$LegacyDir = "$env:USERPROFILE\.nexus-agent"
if (Test-Path $LegacyDir) { Remove-Item $LegacyDir -Recurse -Force -ErrorAction SilentlyContinue }
Remove-Item "$InstallDir\agent.log", "$InstallDir\ssh_ed25519.pub" -Force -ErrorAction SilentlyContinue
Remove-Item "$InstallDir\run-agent.cmd", "$InstallDir\run-agent-silent.vbs", "$InstallDir\run-silent.vbs" -Force -ErrorAction SilentlyContinue
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "NexusV3Agent" -ErrorAction SilentlyContinue

$TaskName = "NexusV3Agent"
try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch {}
try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
$TaskAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}\run-agent.ps1"' -f $InstallDir)
$TaskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$TaskPrincipal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$TaskSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $TaskAction -Trigger $TaskTrigger -Principal $TaskPrincipal -Settings $TaskSettings | Out-Null

$WatchdogTaskName = "NexusV3FunctionalWatchdog"
$WatchdogAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}\watchdog.ps1"' -f $InstallDir)
$WatchdogTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 2)
$WatchdogSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $WatchdogTaskName -Action $WatchdogAction -Trigger $WatchdogTrigger -Principal $TaskPrincipal -Settings $WatchdogSettings | Out-Null

& $RuntimePython -m py_compile "$InstallDir\nexus_v3\agent.py" "$InstallDir\nexus_v3\ledger.py"
if ($LASTEXITCODE -ne 0) { throw "Nexus Python compile check failed" }
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3


# Auto-approve device in cluster if admin key is available
$approvalStatus = "pending (awaiting cluster approval)"
if ($AdminKey) {
    try {
        $approveUri = "$($RegistryUrl.TrimEnd('/'))/v3/admin/devices/$DeviceId/approve"
        $resp = Invoke-RestMethod -Uri $approveUri -Method Post -Headers @{ "X-Nexus-Admin-Key" = $AdminKey } -Body "{}" -ContentType "application/json" -TimeoutSec 10 -ErrorAction SilentlyContinue
        if ($resp.status -eq "approved") { $approvalStatus = "Approved & Active" }
    } catch {}
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "        Nexus v3 Agent Installed Successfully                  " -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " Device ID:     $DeviceId"
Write-Host " Platform:      $([System.Environment]::OSVersion.VersionString)"
Write-Host " Install Dir:   $InstallDir"
Write-Host " Startup:       Task Scheduler\NexusV3Agent + functional watchdog"
Write-Host " Registry:      $RegistryUrl"
Write-Host " Broker:        $BrokerUrl"
Write-Host " Device Auth:   per-device key"
Write-Host " SSH key:       $SshKey"
$clusterColor = if ($approvalStatus -match "Approved") { "Green" } else { "Yellow" }
Write-Host " Cluster State: $approvalStatus" -ForegroundColor $clusterColor
if ($DevSpace) {
    Write-Host " DevSpace:      Enabled (Node: $($Node.Source))" -ForegroundColor Green
    Write-Host " Allowed Roots: $($AllowedRoots -join ', ')"
} else {
    Write-Host " DevSpace:      Skipped (Node >= 22.19 not detected)" -ForegroundColor DarkGray
}
Write-Host " Dashboard:     https://nexus.bings.app"
Write-Host " MCP Endpoint:  https://nexus.bings.app/mcp"
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
