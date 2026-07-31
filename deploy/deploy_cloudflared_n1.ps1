$apiKey = "${NEXUS_SECRET_FROM_ENV}"
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
    Write-Host "[$target] Cmd sent, waiting up to ${waitSec}s..."
    for ($i = 0; $i -lt ($waitSec/3); $i++) {
        Start-Sleep 3
        $r = Invoke-RestMethod -Uri "$base/commands?id=eq.$id&select=status,output" -Headers $headers
        if ($r.status -in "completed","failed") {
            Write-Host "[$target] $($r.status.ToUpper()):"
            Write-Host $r.output
            return $r.output
        }
    }
    Write-Host "[$target] TIMEOUT after ${waitSec}s"
    return "TIMEOUT"
}

# The modem token - this needs to be obtained from Cloudflare Dashboard
# We'll use cloudflared tunnel create approach via TC -> N1
# Step 1: Download cloudflared arm64 to ThinkCenter, then scp to N1
Write-Host "=== Step 1: Download cloudflared arm64 to ThinkCenter ==="
$dl = Send-NexusCmd -target "thinkcenter" -cmd "cd /tmp && wget -q 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64' -O cloudflared-arm64 2>&1 && chmod +x cloudflared-arm64 && ./cloudflared-arm64 --version" -waitSec 90

if ($dl -like "*TIMEOUT*" -or $dl -like "*failed*") {
    Write-Host "Direct download failed, trying via proxy..."
    Send-NexusCmd -target "thinkcenter" -cmd "cd /tmp && curl -L 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64' -o cloudflared-arm64 && chmod +x cloudflared-arm64 && ./cloudflared-arm64 --version" -waitSec 90
}

# Step 2: Copy to N1
Write-Host "=== Step 2: Copy cloudflared to N1 ==="
Send-NexusCmd -target "thinkcenter" -cmd "scp -o StrictHostKeyChecking=no /tmp/cloudflared-arm64 root@192.168.31.88:/usr/bin/cloudflared && ssh -o StrictHostKeyChecking=no root@192.168.31.88 cloudflared --version" -waitSec 30

Write-Host "Done. Next: create tunnel token via Cloudflare Dashboard and deploy config to N1."

