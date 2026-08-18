#Requires -Version 5.1
<#
.SYNOPSIS
  Install and configure the Nexus MCP Gateway on a Windows machine.
  Listens on 127.0.0.1:18130, tunnelled via Cloudflare to nexus.bings.app/mcp.

.EXAMPLE
  # Interactive (prompts for secrets):
  .\setup-mcp-gateway.ps1

  # Non-interactive:
  $env:NEXUS_V3_ADMIN_KEY="<key>"; $env:NEXUS_MCP_BEARER_TOKEN="<token>"; .\setup-mcp-gateway.ps1

.NOTES
  Installs to: %LOCALAPPDATA%\NexusMcpGateway
  Starts at:   HKCU Run\NexusMcpGateway  (no admin required)
  Listens on:  127.0.0.1:18130
#>
param(
    [string]$InstallDir     = "$env:LOCALAPPDATA\NexusMcpGateway",
    [string]$NexusSourceDir = "",
    [string]$RegistryUrl    = "https://nexus-global-api.bings.app",
    [string]$EuBrokerUrl    = "https://nexus-eu-broker.bings.app",
    [string]$CnBrokerUrl    = "https://nexus-eu-broker.bings.app",
    [string]$BindAddr       = "127.0.0.1",
    [int]   $Port           = 18130
)
$ErrorActionPreference = "Stop"

function Info([string]$msg) { Write-Host "[nexus-mcp] $msg" -ForegroundColor Cyan }
function OK  ([string]$msg) { Write-Host "[nexus-mcp] OK: $msg" -ForegroundColor Green }
function Fail([string]$msg) { Write-Host "[nexus-mcp] ERROR: $msg" -ForegroundColor Red; exit 1 }

function Read-Secret([string]$prompt, [string]$envName) {
    $val = [System.Environment]::GetEnvironmentVariable($envName, "User")
    if (-not $val) { $val = [System.Environment]::GetEnvironmentVariable($envName, "Machine") }
    if (-not $val) {
        $envItem = Get-Item -Path "Env:$envName" -ErrorAction SilentlyContinue
        if ($null -ne $envItem) { $val = $envItem.Value }
    }
    if ($val) { return $val }
    $sec = Read-Host -AsSecureString $prompt
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    return [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
}

# ---------- secrets ----------------------------------------------------------
Info "Collecting secrets..."
$adminKey    = Read-Secret "Enter NEXUS_V3_ADMIN_KEY (Registry/Broker auth)" "NEXUS_V3_ADMIN_KEY"
$bearerToken = Read-Secret "Enter NEXUS_MCP_BEARER_TOKEN (ChatGPT/Claude Bearer)" "NEXUS_MCP_BEARER_TOKEN"

if (-not $adminKey) { Fail "NEXUS_V3_ADMIN_KEY is required" }
if (-not $bearerToken) {
    Info "No bearer token supplied; generating one..."
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $bearerToken = [Convert]::ToBase64String($bytes) -replace '[+/=]',''
    Write-Host ""
    Write-Host "  Generated Bearer Token: $bearerToken" -ForegroundColor Yellow
    Write-Host "  >>> SAVE THIS IN BITWARDEN AS 'Nexus MCP Bearer Token' <<<" -ForegroundColor Yellow
    Write-Host ""
}

# ---------- python -----------------------------------------------------------
$agentPython = "$env:LOCALAPPDATA\NexusAgentV3\.venv\Scripts\python.exe"
if (-not (Test-Path $agentPython)) { Fail "NexusAgentV3 venv not found. Run install.ps1 first." }

# ---------- directory --------------------------------------------------------
New-Item -ItemType Directory -Force -Path "$InstallDir\nexus_v3", "$InstallDir\logs" | Out-Null
Info "Install directory: $InstallDir"

# ---------- find / copy nexus_v3 package -------------------------------------
$sourceDir = $NexusSourceDir
if (-not $sourceDir -or -not (Test-Path "$sourceDir\nexus_v3")) {
    $candidate = "$env:USERPROFILE\aurora\Workstation\Nexus"
    if (Test-Path "$candidate\nexus_v3") { $sourceDir = $candidate }
}

$mcpFiles = @(
    "__init__.py",
    "common.py",
    "status.py",
    "remote_control.py",
    "mcp_contracts.py",
    "mcp_server.py",
    "chatgpt_api.py"
)

if ($sourceDir -and (Test-Path "$sourceDir\nexus_v3")) {
    Info "Copying nexus_v3 from $sourceDir..."
    foreach ($f in $mcpFiles) {
        $src = Join-Path $sourceDir "nexus_v3\$f"
        if (Test-Path $src) { Copy-Item $src (Join-Path $InstallDir "nexus_v3\$f") -Force }
    }
} else {
    $ghBase = "https://raw.githubusercontent.com/bingStat/nexus/main"
    Info "Downloading nexus_v3 from GitHub..."
    foreach ($f in $mcpFiles) {
        Invoke-WebRequest -UseBasicParsing "$ghBase/nexus_v3/$f" -OutFile (Join-Path $InstallDir "nexus_v3\$f")
    }
}
OK "nexus_v3 package ready"

# ---------- dedicated venv with mcp[cli] -------------------------------------
$venvPy = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Info "Creating MCP Gateway venv..."
    & $agentPython -m venv (Join-Path $InstallDir ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "venv creation failed" }
}
Info "Installing mcp[cli] into gateway venv..."
& $venvPy -m pip install --disable-pip-version-check --quiet "mcp[cli]>=1.26,<2" requests cryptography uvicorn
if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }
OK "gateway venv ready"

# ---------- compile check ----------------------------------------------------
& $venvPy -m py_compile `
    (Join-Path $InstallDir "nexus_v3\mcp_contracts.py") `
    (Join-Path $InstallDir "nexus_v3\mcp_server.py")
if ($LASTEXITCODE -ne 0) { Fail "mcp_server.py compile check failed" }

# ---------- env file ---------------------------------------------------------
$envFile = Join-Path $InstallDir "nexus-mcp.env"
$envContent = "NEXUS_V3_ADMIN_KEY=$adminKey`r`nNEXUS_V3_REGISTRY_URL=$RegistryUrl`r`nNEXUS_V3_EU_BROKER_URL=$EuBrokerUrl`r`nNEXUS_V3_CN_BROKER_URL=$CnBrokerUrl`r`nNEXUS_V3_MCP_BIND=$BindAddr`r`nNEXUS_V3_MCP_PORT=$Port`r`nNEXUS_MCP_BEARER_TOKEN=$bearerToken`r`nNEXUS_V3_ALLOW_DANGEROUS=0`r`n"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($envFile, $envContent, $utf8NoBom)
# Restrict permissions to owner only
$acl = Get-Acl $envFile
$acl.SetAccessRuleProtection($true, $false)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule($env:USERNAME, "FullControl", "Allow")
$acl.AddAccessRule($rule)
Set-Acl $envFile $acl
OK "env file written (owner-only ACL)"

# ---------- run-mcp.cmd ------------------------------------------------------
$runCmdContent = @"
@echo off
setlocal
for /f "usebackq tokens=1,* delims==" %%A in ("$envFile") do (
    if not "%%A"=="" set "%%A=%%B"
)
cd /d "$InstallDir"
:restart
"$venvPy" -m nexus_v3.mcp_server >> "$InstallDir\logs\mcp.log" 2>&1
echo [%DATE% %TIME%] nexus_v3.mcp_server exited; restarting in 5s >> "$InstallDir\logs\mcp.log"
timeout /t 5 /nobreak >nul
goto restart
"@
[System.IO.File]::WriteAllText((Join-Path $InstallDir "run-mcp.cmd"), $runCmdContent, $utf8NoBom)

# ---------- run-mcp-silent.vbs -----------------------------------------------
$runCmdPath = Join-Path $InstallDir "run-mcp.cmd"
$vbsPath = Join-Path $InstallDir "run-mcp-silent.vbs"
$vbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd.exe /c ""$runCmdPath""", 0, False
"@
[System.IO.File]::WriteAllText($vbsPath, $vbsContent, $utf8NoBom)
OK "Launcher scripts written"

# ---------- stop any running instance ----------------------------------------
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -and
    $_.CommandLine -match [regex]::Escape($InstallDir) -and
    ($_.CommandLine -match "mcp_server" -or $_.CommandLine -match "run-mcp")
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# ---------- register in HKCU Run ---------------------------------------------
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
New-ItemProperty -Path $runKey -Name "NexusMcpGateway" -PropertyType String `
    -Value ('wscript.exe "{0}"' -f $vbsPath) -Force | Out-Null
OK "Registered: HKCU Run\NexusMcpGateway"

# ---------- launch now -------------------------------------------------------
Start-Process -WindowStyle Hidden -FilePath "wscript.exe" `
    -ArgumentList ('"{0}"' -f $vbsPath)
Start-Sleep -Seconds 4

# ---------- verify -----------------------------------------------------------
try {
    $resp = Invoke-WebRequest -Uri "http://${BindAddr}:${Port}/mcp" -Method GET `
        -Headers @{ Authorization = "Bearer $bearerToken" } -TimeoutSec 6 -ErrorAction Stop
    OK "MCP Server is responding (HTTP $($resp.StatusCode))"
} catch {
    $code = $null
    if ($null -ne $_.Exception.Response) {
        $code = [int]$_.Exception.Response.StatusCode
    }
    if ($code -in 200,401,405) {
        OK "MCP Server is listening (HTTP $code)"
    } else {
        Write-Host "[nexus-mcp] Warning: health check inconclusive ($($_.Exception.Message))" -ForegroundColor Yellow
        Write-Host "[nexus-mcp] Check logs: $(Join-Path $InstallDir 'logs\mcp.log')" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host ("=" * 56) -ForegroundColor Green
Write-Host " Nexus MCP Gateway installed successfully!" -ForegroundColor Green
Write-Host ("=" * 56) -ForegroundColor Green
Write-Host " Public URL:    https://nexus.bings.app/mcp"
Write-Host " Local port:    http://${BindAddr}:${Port}/mcp"
Write-Host " Bearer token:  $bearerToken"
Write-Host ""
Write-Host " To connect from Claude / ChatGPT:"
Write-Host "   MCP Server URL: https://nexus.bings.app/mcp"
Write-Host "   Auth type:      Bearer"
Write-Host "   Token:          $bearerToken"
Write-Host ""
Write-Host " Logs: $(Join-Path $InstallDir 'logs\mcp.log')"
