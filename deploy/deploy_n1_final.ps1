$apiKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
$base = "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1"
$headers = @{
    "apikey" = $apiKey
    "Authorization" = "Bearer $apiKey"
    "Content-Type" = "application/json"
    "Prefer" = "return=representation"
}

function Send-NexusCmd {
    param([string]$target, [string]$cmd, [int]$waitSec = 60)
    $id = [System.Guid]::NewGuid().ToString()
    $payload = @{ id=$id; command=$cmd; target_device=$target; status="pending"; timeout_ms=($waitSec*1000) } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri "$base/commands" -Method POST -Headers $headers -Body $payload | Out-Null
    Write-Host "[$target] Sent $id waiting ${waitSec}s..."
    for ($i = 0; $i -lt ($waitSec/2); $i++) {
        Start-Sleep 2
        $r = Invoke-RestMethod -Uri "$base/commands?id=eq.$id&select=status,output" -Headers $headers
        if ($r.status -in "completed","failed") {
            Write-Host "[$target] $($r.status.ToUpper()): $($r.output)"
            return $r.output
        }
    }
    Write-Host "[$target] TIMEOUT"
    return "TIMEOUT"
}

$n1IP = "192.168.31.88"

# Step 1: TC downloads from ghproxy
Write-Host "=== Step 1: TC pulls cloudflared from ghproxy ==="
$out = Send-NexusCmd -target "thinkcenter" -cmd "curl -L https://ghproxy.net/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -o /tmp/cloudflared && chmod +x /tmp/cloudflared && stat -c %s /tmp/cloudflared" -waitSec 120

if ($out -notlike "*TIMEOUT*" -and $out -match "\d{5,}") {
    Write-Host "=== Download OK ==="
} else {
    Write-Host "ERROR: download failed. Output: $out"
    exit 1
}

# Step 2: SCP from TC to N1 /tmp
Write-Host "=== Step 2: SCP cloudflared to N1 /tmp ==="
$out2 = Send-NexusCmd -target "thinkcenter" -cmd "scp -o StrictHostKeyChecking=no /tmp/cloudflared root@${n1IP}:/tmp/cloudflared && echo SCP_OK" -waitSec 40
if ($out2 -notlike "*SCP_OK*") { Write-Host "SCP failed: $out2"; exit 1 }

# Step 3: Install to persistent location on N1
Write-Host "=== Step 3: Install to /usr/bin on N1 ==="
Send-NexusCmd -target "thinkcenter" -cmd "ssh -o StrictHostKeyChecking=no root@${n1IP} 'chmod +x /tmp/cloudflared; cp /tmp/cloudflared /usr/bin/cloudflared 2>/dev/null && echo USR_OK || (mkdir -p /opt/bin && cp /tmp/cloudflared /opt/bin/cloudflared && echo OPT_OK); /usr/bin/cloudflared --version 2>/dev/null || /opt/bin/cloudflared --version 2>/dev/null'" -waitSec 30

Write-Host "=== All done. Waiting for tunnel TOKEN from Cloudflare Dashboard. ==="
