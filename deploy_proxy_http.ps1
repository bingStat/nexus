$apiKey = "${NEXUS_SECRET_FROM_ENV}"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }
$id = [System.Guid]::NewGuid().ToString()

# Start HTTP server on ThinkCenter on port 10081 in background
$startHttpCmd = "start /B python -m http.server 10081 -d C:\Users\Bing"
$payload = @{ id=$id; command=$startHttpCmd; target_device="thinkcenter"; status="pending"; timeout_ms=30000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload | Out-Null
Write-Host "Started HTTP Server $id"

Start-Sleep 3

# Make N1 curl it and restart docker!
$id2 = [System.Guid]::NewGuid().ToString()
$sshCmd = "ssh -o StrictHostKeyChecking=no root@192.168.31.88 'curl -o /root/modem_proxy.py http://192.168.31.61:10081/modem_proxy.py && docker restart modem_proxy'"
$payload2 = @{ id=$id2; command=$sshCmd; target_device="thinkcenter"; status="pending"; timeout_ms=30000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload2 | Out-Null
Write-Host "Sent curl cmd $id2"
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep 2
    $r = Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands?id=eq.$id2&select=status,output" -Headers $headers
    if ($r.status -in "completed","failed") {
        Write-Host "STATUS: $($r.status)"
        Write-Host "OUTPUT: $($r.output)"
        exit 0
    }
}
Write-Host "TIMEOUT"

