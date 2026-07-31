$apiKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }

$pyCode = [System.IO.File]::ReadAllText("C:\Users\Bing\aurora\Workstation\Nexus\modem_proxy_unified.py")

$id = [System.Guid]::NewGuid().ToString()
$encoded = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($pyCode))
$localCmd = "echo '$encoded' | base64 -d > /tmp/modem_proxy.py"

$payload1 = @{ id=$id; command=$localCmd; target_device="thinkcenter"; status="pending"; timeout_ms=30000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload1 | Out-Null
Start-Sleep 3

$id2 = [System.Guid]::NewGuid().ToString()
$scpCmd = "scp -o StrictHostKeyChecking=no /tmp/modem_proxy.py root@192.168.31.88:/root/modem_proxy.py && ssh -o StrictHostKeyChecking=no root@192.168.31.88 'docker restart modem_proxy'"
$payload2 = @{ id=$id2; command=$scpCmd; target_device="thinkcenter"; status="pending"; timeout_ms=30000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload2 | Out-Null
Write-Host "Sent scp cmd $id2"
for ($i = 0; $i -lt 25; $i++) {
    Start-Sleep 2
    $r = Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands?id=eq.$id2&select=status,output" -Headers $headers
    if ($r.status -in "completed","failed") {
        Write-Host "STATUS: $($r.status)"
        Write-Host "OUTPUT: $($r.output)"
        exit 0
    }
}
