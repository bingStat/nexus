$env:BWS_ACCESS_TOKEN="0.f48083d0-d9ff-409a-92c3-b49700d5f88b.CODIdvJ6l1fFK4KP563HvlsLxRwmE4:3FcS9d97d5+3z1xKU9VIzQ=="
$secretsJson = & C:\Users\Bing\bws\bws.exe secret list -o json | ConvertFrom-Json
$token = ($secretsJson | Where-Object key -eq 'CLOUDFLARE_API_TOKEN').value
$headers = @{ 'Authorization'="Bearer $token"; 'Content-Type'='application/json' }
$accountId = "4dfa98e8bf3e7b1a6b0c279326e5fc3a"

# Get thinkcenter-host-tunnel configuration
$uri = "https://api.cloudflare.com/client/v4/accounts/$accountId/cfd_tunnel/8ba09dab-f25a-4dea-b361-14dcaf35a389/configurations"
$r = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
$r.result.config.ingress | ConvertTo-Json -Depth 10
