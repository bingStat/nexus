$env:BWS_ACCESS_TOKEN="0.f48083d0-d9ff-409a-92c3-b49700d5f88b.CODIdvJ6l1fFK4KP563HvlsLxRwmE4:3FcS9d97d5+3z1xKU9VIzQ=="
$secretsJson = & C:\Users\Bing\bws\bws.exe secret list -o json | ConvertFrom-Json
$globalKey = ($secretsJson | Where-Object key -eq 'CLOUDFLARE_GLOBAL_API_KEY').value
$accountId = ($secretsJson | Where-Object key -eq 'CLOUDFLARE_ACCOUNT_ID').value
$headers = @{ 'X-Auth-Email'='yang_bobby@qq.com'; 'X-Auth-Key'=$globalKey; 'Content-Type'='application/json' }
$uri = "https://api.cloudflare.com/client/v4/accounts/$accountId/cfd_tunnel/8fb4a8c3-7874-450b-8661-fad52c64e497/configurations"

$r = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
$config = $r.result.config

# Modify the modem.bings.app ingress rule
foreach ($rule in $config.ingress) {
    if ($rule.hostname -eq "modem.bings.app") {
        $rule.service = "http://127.0.0.1:10080"
    }
}

$payload = @{ config = $config } | ConvertTo-Json -Depth 10 -Compress
Invoke-RestMethod -Uri $uri -Headers $headers -Method PUT -Body $payload | Out-Null
Write-Host "Updated Tunnel Config to point to N1 localhost!"
