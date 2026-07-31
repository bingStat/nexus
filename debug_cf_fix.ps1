$apiKey = "${NEXUS_SECRET_FROM_ENV}"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }
$id = [System.Guid]::NewGuid().ToString()

$sshCmd = "ssh -o StrictHostKeyChecking=no root@192.168.31.88 ""sed -i 's/tunnel run/tunnel run --loglevel debug/' /etc/init.d/cloudflared && /etc/init.d/cloudflared restart"""

$payload = @{ id=$id; command=$sshCmd; target_device="thinkcenter"; status="pending"; timeout_ms=30000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload | Out-Null
Write-Host "Sent cmd $id"
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep 2
    $r = Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands?id=eq.$id&select=status,output" -Headers $headers
    if ($r.status -in "completed","failed") {
        Write-Host "STATUS: $($r.status)"
        Write-Host "OUTPUT: $($r.output)"
        exit 0
    }
}
Write-Host "TIMEOUT"

