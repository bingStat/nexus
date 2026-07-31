$env:BWS_ACCESS_TOKEN="0.f48083d0-d9ff-409a-92c3-b49700d5f88b.CODIdvJ6l1fFK4KP563HvlsLxRwmE4:3FcS9d97d5+3z1xKU9VIzQ=="
$secretsJson = & C:\Users\Bing\bws\bws.exe secret list -o json | ConvertFrom-Json
$globalKey = ($secretsJson | Where-Object key -eq 'CLOUDFLARE_GLOBAL_API_KEY').value
$headers = @{ 'X-Auth-Email'='yang_bobby@qq.com'; 'X-Auth-Key'=$globalKey; 'Content-Type'='application/json' }
$zoneId = "04cd2b8cc98c9d4e71e02619924c98fc"

# Get all routes associated with the bings.app zone - these show which tunnels own which hostnames
$uri = "https://api.cloudflare.com/client/v4/zones/$zoneId/tunnels"
$r = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
Write-Host "Result: $($r.success)"
$r.result | ConvertTo-Json -Depth 5

