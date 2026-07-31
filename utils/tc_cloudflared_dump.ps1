$apiKey = "${NEXUS_SECRET_FROM_ENV}"
$base = "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1"
$headers = @{
    "apikey" = $apiKey
    "Authorization" = "Bearer $apiKey"
    "Content-Type" = "application/json"
    "Prefer" = "return=representation"
}

$cmd = "find /root/.cloudflared /etc/cloudflared 2>/dev/null -name '*.yml' -o -name '*.json' | head -20; echo '---CONFIG---'; cat /root/.cloudflared/config.yml 2>/dev/null; echo '---JSON---'; ls /root/.cloudflared/*.json 2>/dev/null | head -3 | xargs -I{} sh -c 'echo {}; cat {}' 2>/dev/null; echo '---STATUS---'; systemctl is-active cloudflared 2>/dev/null"

$cmdId = [System.Guid]::NewGuid().ToString()
$payload = '{"id":"' + $cmdId + '","command":"' + $cmd.Replace('\','\\').Replace('"','\"') + '","target_device":"thinkcenter","status":"pending"}'

Invoke-RestMethod -Uri "$base/commands" -Method POST -Headers $headers -Body $payload | Out-Null
Write-Host "Sent to thinkcenter: $cmdId"

for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 3
    $result = Invoke-RestMethod -Uri "$base/commands?id=eq.$cmdId&select=status,output" -Headers $headers
    if ($result.status -eq "completed" -or $result.status -eq "failed") {
        Write-Host "Status: $($result.status)"
        Write-Host $result.output
        break
    }
    Write-Host "[$i] $($result.status)"
}

