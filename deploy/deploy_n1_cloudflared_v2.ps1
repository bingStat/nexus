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
    Write-Host "[$target] Waiting ${waitSec}s..."
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

# Victus Tailscale IP is 100.95.7.20, HTTP server on port 19876
# ThinkCenter pulls cloudflared from Victus, then SCPs to N1, then configures
$victusIP = "100.95.7.20"
$modemIP = "192.168.1.1"
$n1IP = "192.168.31.88"

Write-Host "=== Step 1: ThinkCenter downloads cloudflared from Victus ==="
$out = Send-NexusCmd -target "thinkcenter" -cmd "curl -f http://${victusIP}:19876/cloudflared-arm64 -o /tmp/cloudflared-arm64 && chmod +x /tmp/cloudflared-arm64 && echo SIZE=$(stat -c%s /tmp/cloudflared-arm64)" -waitSec 40

if ($out -like "*SIZE=*") {
    Write-Host "Download successful!"
} else {
    Write-Host "Download failed, aborting."
    exit 1
}

Write-Host "=== Step 2: SCP cloudflared to N1 (try /tmp first due to read-only /usr) ==="
Send-NexusCmd -target "thinkcenter" -cmd "scp -o StrictHostKeyChecking=no /tmp/cloudflared-arm64 root@${n1IP}:/tmp/cloudflared && ssh -o StrictHostKeyChecking=no root@${n1IP} 'chmod +x /tmp/cloudflared && /tmp/cloudflared --version'" -waitSec 30

Write-Host "=== Step 3: Check if N1 /usr/bin is writable, else use /tmp ==="
Send-NexusCmd -target "thinkcenter" -cmd "ssh -o StrictHostKeyChecking=no root@${n1IP} 'mount | grep -E /usr' " -waitSec 15

Write-Host "=== Step 4: Make cloudflared persistent on N1 ==="
# iStoreOS uses overlay fs - /tmp is volatile. Copy to overlay-able location
Send-NexusCmd -target "thinkcenter" -cmd "ssh -o StrictHostKeyChecking=no root@${n1IP} 'cp /tmp/cloudflared /usr/bin/cloudflared 2>/dev/null || (mkdir -p /opt/bin && cp /tmp/cloudflared /opt/bin/cloudflared); ls -la /usr/bin/cloudflared /opt/bin/cloudflared 2>/dev/null'" -waitSec 20

Write-Host "=== Step 5: Create cloudflared config on N1 ==="
# The TOKEN will be injected after user gets it from Cloudflare Dashboard
$configCmd = "ssh -o StrictHostKeyChecking=no root@${n1IP} 'mkdir -p /etc/cloudflared && cat > /etc/cloudflared/config.yml << EOF`ntunnel: REPLACE_WITH_TUNNEL_ID`ncredentials-file: /etc/cloudflared/tunnel.json`n`ningress:`n  - hostname: modem.bings.app`n    service: http://${modemIP}`n  - service: http_status:404`nEOF`necho CONFIG_WRITTEN'"
Send-NexusCmd -target "thinkcenter" -cmd $configCmd -waitSec 20

Write-Host "=== Done: cloudflared installed on N1. Now need tunnel token from Cloudflare Dashboard. ==="
