$apiKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }

function Send-NexusCmd {
    param([string]$target, [string]$cmd, [int]$waitSec = 60)
    $id = [System.Guid]::NewGuid().ToString()
    $payload = @{ id=$id; command=$cmd; target_device=$target; status="pending"; timeout_ms=($waitSec*1000) } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload | Out-Null
    Write-Host "[$target] Sent $id waiting ${waitSec}s..."
    for ($i = 0; $i -lt ($waitSec/2); $i++) {
        Start-Sleep 2
        $r = Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands?id=eq.$id&select=status,output" -Headers $headers
        if ($r.status -in "completed","failed") {
            Write-Host "[$target] $($r.status.ToUpper()): $($r.output)"
            return $r.output
        }
    }
    Write-Host "[$target] TIMEOUT"
    return "TIMEOUT"
}

$n1IP = "192.168.31.88"
$tunnelURL = "https://rca-enable-lesson-assignment.trycloudflare.com/cloudflared-arm64"
$token = "eyJhIjoiMjIyZmZlOTE2ZGIxMTU1MTAyYTQ1ZTRjZmI0YTRlYzgiLCJ0IjoiOGZiNGE4YzMtNzg3NC00NTBiLTg2NjEtZmFkNTJjNjRlNDk3IiwicyI6Ik5XSmhabVJoTVRBdFpHUmhaUzAwT1RnekxXSmlaVE10TURsbE5tVTNNMk5qWTJGayJ9"

# N1 downloads binary directly
$cmd = "ssh -o StrictHostKeyChecking=no root@${n1IP} 'curl -L $tunnelURL -o /tmp/cloudflared && chmod +x /tmp/cloudflared && cp /tmp/cloudflared /usr/bin/cloudflared 2>/dev/null || (mkdir -p /opt/bin && cp /tmp/cloudflared /opt/bin/cloudflared); /opt/bin/cloudflared service install $token || /usr/bin/cloudflared service install $token'"
Send-NexusCmd -target "thinkcenter" -cmd $cmd -waitSec 120
