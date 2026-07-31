$apiKey = "${NEXUS_SECRET_FROM_ENV}"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }
$id = [System.Guid]::NewGuid().ToString()

$dockerCmd = "docker run -d --name cloudflared-tunnel --restart unless-stopped cloudflare/cloudflared:latest tunnel --no-autoupdate run --token eyJhIjoiMjIyZmZlOTE2ZGIxMTU1MTAyYTQ1ZTRjZmI0YTRlYzgiLCJ0IjoiOGZiNGE4YzMtNzg3NC00NTBiLTg2NjEtZmFkNTJjNjRlNDk3IiwicyI6Ik5XSmhabVJoTVRBdFpHUmhaUzAwT1RnekxXSmlaVE10TURsbE5tVTNNMk5qWTJGayJ9"
$sshCmd = "ssh -o StrictHostKeyChecking=no root@192.168.31.88 'docker rm -f cloudflared-tunnel 2>/dev/null; $dockerCmd'"

$payload = @{ id=$id; command=$sshCmd; target_device="thinkcenter"; status="pending"; timeout_ms=300000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload | Out-Null
Write-Host "Sent cmd $id"
for ($i = 0; $i -lt 35; $i++) {
    Start-Sleep 2
    $r = Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands?id=eq.$id&select=status,output" -Headers $headers
    if ($r.status -in "completed","failed") {
        Write-Host "STATUS: $($r.status)"
        Write-Host "OUTPUT: $($r.output)"
        exit 0
    }
}
Write-Host "TIMEOUT"

