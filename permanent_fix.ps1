$env:BWS_ACCESS_TOKEN="0.f48083d0-d9ff-409a-92c3-b49700d5f88b.CODIdvJ6l1fFK4KP563HvlsLxRwmE4:3FcS9d97d5+3z1xKU9VIzQ=="
$secretsJson = & C:\Users\Bing\bws\bws.exe secret list -o json | ConvertFrom-Json
$globalKey = ($secretsJson | Where-Object key -eq 'CLOUDFLARE_GLOBAL_API_KEY').value
$headers = @{ 'X-Auth-Email'='yang_bobby@qq.com'; 'X-Auth-Key'=$globalKey; 'Content-Type'='application/json' }
$zoneId = "04cd2b8cc98c9d4e71e02619924c98fc"

# The DNS has been overwritten AGAIN! Fix it permanently
$uri = "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records?name=modem.bings.app"
$existing = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
$recordId = $existing.result[0].id

$body = @{
    type = "CNAME"
    name = "modem.bings.app"
    content = "8fb4a8c3-7874-450b-8661-fad52c64e497.cfargotunnel.com"
    proxied = $true
    ttl = 1
    comment = "n1-modem proxy - DO NOT CHANGE"
} | ConvertTo-Json

$updateUri = "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records/$recordId"
$r = Invoke-RestMethod -Uri $updateUri -Headers $headers -Method PUT -Body $body
Write-Host "Fixed: $($r.success) -> $($r.result.content)"

# Now also update the thinkcenter-host-tunnel remote config to 
# explicitly exclude modem.bings.app (it's currently not in there, which is good)
# The real fix: we need to make sure the thinkcenter-host-tunnel doesn't manage modem.bings.app
# The thinkcenter-host-tunnel cloudflared process just reconnected and overwrote the DNS
# because it's a remote-config tunnel and Cloudflare's backend still associates 
# modem.bings.app with this tunnel at the route level.
# 
# The REAL fix is to update thinkcenter-host-tunnel's config PUT to explicitly declare
# all its hostnames so Cloudflare knows which routes belong to it.
# Currently the route to modem.bings.app is stored in Cloudflare's backend as belonging to 8ba09dab

$accountId = "222ffe916db1155102a45e4cfb4a4ec8"

# Rebuild the thinkcenter-host-tunnel config - same as current but making it explicit
# This forces cloudflare to sync and know modem.bings.app is NOT owned by this tunnel
$existingConfig = @{
    config = @{
        ingress = @(
            @{ hostname = "nexus.bings.app"; service = "http://dc-rest:3000"; originRequest = @{} }
            @{ hostname = "tc-ssh.bings.app"; service = "http://webssh:7681"; originRequest = @{} }
            @{ hostname = "victus-ssh.bings.app"; service = "http://100.95.7.20:7681"; originRequest = @{} }
            @{ hostname = "oracle-ssh.bings.app"; service = "http://100.116.89.65:7681"; originRequest = @{} }
            @{ hostname = "n1-ssh.bings.app"; service = "http://100.90.67.12:7681"; originRequest = @{} }
            @{ service = "http_status:404"; originRequest = @{} }
        )
        "warp-routing" = @{ enabled = $false }
    }
} | ConvertTo-Json -Depth 10

$configUri = "https://api.cloudflare.com/client/v4/accounts/$accountId/cfd_tunnel/8ba09dab-f25a-4dea-b361-14dcaf35a389/configurations"
$r2 = Invoke-RestMethod -Uri $configUri -Headers $headers -Method PUT -Body $existingConfig
Write-Host "Config updated: $($r2.success)"

