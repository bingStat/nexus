$env:BWS_ACCESS_TOKEN="0.f48083d0-d9ff-409a-92c3-b49700d5f88b.CODIdvJ6l1fFK4KP563HvlsLxRwmE4:3FcS9d97d5+3z1xKU9VIzQ=="
$secretsJson = & C:\Users\Bing\bws\bws.exe secret list -o json | ConvertFrom-Json
$globalKey = ($secretsJson | Where-Object key -eq 'CLOUDFLARE_GLOBAL_API_KEY').value
$headers = @{ 'X-Auth-Email'='yang_bobby@qq.com'; 'X-Auth-Key'=$globalKey; 'Content-Type'='application/json' }
$accountId = "222ffe916db1155102a45e4cfb4a4ec8"

# The correct API for listing all ingress rules across all remote-config tunnels
# Use the ingress rules endpoint to find all hostname->tunnel mappings
$uri = "https://api.cloudflare.com/client/v4/accounts/$accountId/cfd_tunnel/8ba09dab-f25a-4dea-b361-14dcaf35a389"
$r = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
Write-Host "Tunnel name: $($r.result.name)"
Write-Host "Status: $($r.result.status)"
Write-Host "remote_config: $($r.result.remote_config)"
$r.result | ConvertTo-Json -Depth 5
