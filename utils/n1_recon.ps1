$apiKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
$base = "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1"
$headers = @{
    "apikey" = $apiKey
    "Authorization" = "Bearer $apiKey"
    "Content-Type" = "application/json"
    "Prefer" = "return=representation"
}

# Check N1 device status
Write-Host "=== N1 Device Status ==="
try {
    $devices = Invoke-RestMethod -Uri "$base/devices?select=device_id,name,status,last_seen" -Headers $headers
    $devices | Where-Object { $_.device_id -like "*n1*" -or $_.name -like "*n1*" } | Format-Table -AutoSize
    Write-Host "All devices:"
    $devices | Format-Table -AutoSize
} catch {
    Write-Host "Error: $_"
}

# Send recon command to n1
Write-Host "=== Sending recon command to n1 ==="
$cmdId = [System.Guid]::NewGuid().ToString()
$body = @{
    id = $cmdId
    command = "uname -m && cat /etc/openwrt_release 2>/dev/null || cat /etc/os-release 2>/dev/null && ip route | head -5 && curl -s --max-time 3 http://192.168.31.1/ | head -5 2>/dev/null || echo 'modem_192.168.31.1_unreachable' && curl -s --max-time 3 http://192.168.1.1/ | head -5 2>/dev/null || echo 'modem_192.168.1.1_unreachable' && which cloudflared 2>/dev/null || echo 'cloudflared_not_installed'"
    target_device = "n1"
    status = "pending"
} | ConvertTo-Json
Invoke-RestMethod -Uri "$base/commands" -Method POST -Headers $headers -Body $body | Format-List
Write-Host "Command ID: $cmdId"

# Wait and poll
Write-Host "Waiting for result..."
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 3
    $result = Invoke-RestMethod -Uri "$base/commands?id=eq.$cmdId&select=status,output" -Headers $headers
    Write-Host "[$i] Status: $($result.status)"
    if ($result.status -eq "completed" -or $result.status -eq "failed") {
        Write-Host "Output:"
        Write-Host $result.output
        break
    }
}
