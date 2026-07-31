$apiKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }
$id = [System.Guid]::NewGuid().ToString()

$sshCmd = "ssh -o StrictHostKeyChecking=no root@192.168.31.88 'python3 --version'"

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
