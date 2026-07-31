$apiKey = "${NEXUS_SECRET_FROM_ENV}"
$base = "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1"
$headers = @{
    "apikey" = $apiKey
    "Authorization" = "Bearer $apiKey"
    "Content-Type" = "application/json"
    "Prefer" = "return=representation"
}

function Send-NexusCmd {
    param([string]$target, [string]$cmd, [int]$waitSec = 40)
    $id = [System.Guid]::NewGuid().ToString()
    $payload = @{ id=$id; command=$cmd; target_device=$target; status="pending" } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri "$base/commands" -Method POST -Headers $headers -Body $payload | Out-Null
    Write-Host "[$target] Sent cmd $id"
    for ($i = 0; $i -lt ($waitSec/3); $i++) {
        Start-Sleep 3
        $r = Invoke-RestMethod -Uri "$base/commands?id=eq.$id&select=status,output" -Headers $headers
        if ($r.status -in "completed","failed") {
            Write-Host "[$target] $($r.status.ToUpper()): $($r.output.Substring(0,[Math]::Min(500,$r.output.Length)))"
            return $r.output
        }
    }
    Write-Host "[$target] TIMEOUT"
    return ""
}

# Step 1: Check N1 SSH from ThinkCenter (simple command, no nested quotes)
Write-Host "=== Step 1: SSH to N1 from ThinkCenter ==="
Send-NexusCmd -target "thinkcenter" -cmd "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 root@192.168.31.88 uname -m" -waitSec 30

Write-Host "=== Step 2: N1 OS detection ==="
Send-NexusCmd -target "thinkcenter" -cmd "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 root@192.168.31.88 cat /etc/openwrt_release" -waitSec 30

Write-Host "=== Step 3: N1 CPU arch and memory ==="
Send-NexusCmd -target "thinkcenter" -cmd "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 root@192.168.31.88 'uname -m; free -m | head -2; df -h / | tail -1'" -waitSec 30

