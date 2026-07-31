$apiKey = "${NEXUS_SECRET_FROM_ENV}"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }
$id = [System.Guid]::NewGuid().ToString()

# Check that the container network mode is host and if port 10080 is bound on 0.0.0.0
$cmd = "ssh -o StrictHostKeyChecking=no root@192.168.31.88 'netstat -tlnp 2>/dev/null | grep 10080 || ss -tlnp | grep 10080'"
$payload = @{ id=$id; command=$cmd; target_device="thinkcenter"; status="pending"; timeout_ms=30000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload | Out-Null
Write-Host "Sent $id"
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep 2
    $r = Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands?id=eq.$id&select=status,output" -Headers $headers
    if ($r.status -in "completed","failed") { Write-Host $r.status; Write-Host $r.output; exit 0 }
}
Write-Host "TIMEOUT"

