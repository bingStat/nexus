$env:BWS_ACCESS_TOKEN="0.f48083d0-d9ff-409a-92c3-b49700d5f88b.CODIdvJ6l1fFK4KP563HvlsLxRwmE4:3FcS9d97d5+3z1xKU9VIzQ=="
$secretsJson = & C:\Users\Bing\bws\bws.exe secret list -o json | ConvertFrom-Json
$globalKey = ($secretsJson | Where-Object key -eq 'CLOUDFLARE_GLOBAL_API_KEY').value
$headers = @{ 'X-Auth-Email'='yang_bobby@qq.com'; 'X-Auth-Key'=$globalKey; 'Content-Type'='application/json' }
$accountId = "222ffe916db1155102a45e4cfb4a4ec8"
$zoneId = "04cd2b8cc98c9d4e71e02619924c98fc"

# Use the PUT endpoint to update thinkcenter-host-tunnel config
# We need to check if it has a stored route for modem.bings.app at the zone level
# The proper endpoint is /zones/{zone_id}/workers/services/by-script/{host}
# Actually let's just look at all DNS records for bings.app and see what tunnels they point to

$uri = "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records?type=CNAME&per_page=100"
$r = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
$r.result | Where-Object { $_.content -like "*.cfargotunnel.com" } | Select-Object name, content | Format-Table -AutoSize
