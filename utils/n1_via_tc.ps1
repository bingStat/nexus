$apiKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
$base = "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1"
$headers = @{
    "apikey" = $apiKey
    "Authorization" = "Bearer $apiKey"
    "Content-Type" = "application/json"
    "Prefer" = "return=representation"
}

function Send-NexusCmd {
    param([string]$target, [string]$cmd, [int]$waitSec = 30)
    $id = [System.Guid]::NewGuid().ToString()
    $payload = @{ id=$id; command=$cmd; target_device=$target; status="pending" } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri "$base/commands" -Method POST -Headers $headers -Body $payload | Out-Null
    Write-Host "[$target] Sent: $($cmd.Substring(0,[Math]::Min(60,$cmd.Length)))..."
    for ($i = 0; $i -lt ($waitSec/3); $i++) {
        Start-Sleep 3
        $r = Invoke-RestMethod -Uri "$base/commands?id=eq.$id&select=status,output" -Headers $headers
        if ($r.status -in "completed","failed") {
            Write-Host "[$target] $($r.status.ToUpper()):"
            Write-Host $r.output
            return $r.output
        }
    }
    Write-Host "[$target] TIMEOUT"
    return ""
}

# Step 1: Check N1 SSH reachability and architecture from ThinkCenter
Write-Host "=== Step 1: Probe N1 via ThinkCenter SSH ==="
$out = Send-NexusCmd -target "thinkcenter" -cmd "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@192.168.31.88 'uname -m && cat /etc/openwrt_release 2>/dev/null | head -5 && ip route | grep default && curl -s --max-time 3 -o /dev/null -w \"%{http_code}\" http://192.168.1.1/ 2>/dev/null && which cloudflared 2>/dev/null || echo cloudflared_missing'" -waitSec 30

Write-Host "=== Step 2: Check modem IP from ThinkCenter directly ==="
Send-NexusCmd -target "thinkcenter" -cmd "curl -s --max-time 3 -o /dev/null -w 'modem_192.168.1.1_http=%{http_code}' http://192.168.1.1/ 2>/dev/null; curl -s --max-time 3 -o /dev/null -w ' modem_192.168.31.1_http=%{http_code}' http://192.168.31.1/ 2>/dev/null" -waitSec 20
