$apiKey = "${NEXUS_SECRET_FROM_ENV}"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }
$id = [System.Guid]::NewGuid().ToString()

$n1IP = "192.168.31.88"
$token = "eyJhIjoiMjIyZmZlOTE2ZGIxMTU1MTAyYTQ1ZTRjZmI0YTRlYzgiLCJ0IjoiOGZiNGE4YzMtNzg3NC00NTBiLTg2NjEtZmFkNTJjNjRlNDk3IiwicyI6Ik5XSmhabVJoTVRBdFpHUmhaUzAwT1RnekxXSmlaVE10TURsbE5tVTNNMk5qWTJGayJ9"

$sshCmd = "ssh -o StrictHostKeyChecking=no root@${n1IP} '/etc/init.d/cloudflared stop; rm -f /etc/init.d/cloudflared; /usr/bin/cloudflared service install $token; /etc/init.d/cloudflared enable; /etc/init.d/cloudflared start; sleep 2; ps | grep cloudflared'"

$payload = @{ id=$id; command=$sshCmd; target_device="thinkcenter"; status="pending"; timeout_ms=120000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload | Out-Null
Write-Host "Sent cmd $id"
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep 2
    $r = Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands?id=eq.$id&select=status,output" -Headers $headers
    if ($r.status -in "completed","failed") {
        Write-Host "STATUS: $($r.status)"
        Write-Host "OUTPUT: $($r.output)"
        exit 0
    }
}
Write-Host "TIMEOUT"

