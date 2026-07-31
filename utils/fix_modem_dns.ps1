$env:BWS_ACCESS_TOKEN="0.f48083d0-d9ff-409a-92c3-b49700d5f88b.CODIdvJ6l1fFK4KP563HvlsLxRwmE4:3FcS9d97d5+3z1xKU9VIzQ=="
$secretsJson = & C:\Users\Bing\bws\bws.exe secret list -o json | ConvertFrom-Json
$globalKey = ($secretsJson | Where-Object key -eq 'CLOUDFLARE_GLOBAL_API_KEY').value
$headers = @{ 'X-Auth-Email'='yang_bobby@qq.com'; 'X-Auth-Key'=$globalKey; 'Content-Type'='application/json' }
$accountId = "222ffe916db1155102a45e4cfb4a4ec8"
$zoneId = "04cd2b8cc98c9d4e71e02619924c98fc"

# Step 1: Get all DNS records for bings.app and find modem.bings.app
$uri = "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records?name=modem.bings.app"
$existing = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
Write-Host "Existing records for modem.bings.app:"
$existing.result | ForEach-Object { Write-Host "  ID=$($_.id) CNAME=$($_.content)" }

# Step 2: Update the CNAME to point to n1-modem (correct tunnel)
$recordId = $existing.result[0].id
$body = @{
    type = "CNAME"
    name = "modem.bings.app"
    content = "8fb4a8c3-7874-450b-8661-fad52c64e497.cfargotunnel.com"
    proxied = $true
    ttl = 1
    comment = "n1-modem proxy for modem 192.168.1.1"
} | ConvertTo-Json

$updateUri = "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records/$recordId"
$r = Invoke-RestMethod -Uri $updateUri -Headers $headers -Method PUT -Body $body
Write-Host "Update result: $($r.success) - Now points to: $($r.result.content)"
