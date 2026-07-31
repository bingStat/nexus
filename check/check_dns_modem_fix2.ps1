$env:BWS_ACCESS_TOKEN="0.f48083d0-d9ff-409a-92c3-b49700d5f88b.CODIdvJ6l1fFK4KP563HvlsLxRwmE4:3FcS9d97d5+3z1xKU9VIzQ=="
$secretsJson = & C:\Users\Bing\bws\bws.exe secret list -o json | ConvertFrom-Json
$dnsToken = ($secretsJson | Where-Object key -eq 'CF_TOKEN_ZONE_DNS').value
$headers = @{ 'Authorization'="Bearer $dnsToken"; 'Content-Type'='application/json' }
$zoneId = "1a57b0fb845fc86b03375cd5cd650f97" # bings.app

$uri = "https://api.cloudflare.com/client/v4/zones/$zoneId/dns_records?name=modem.bings.app"
$r = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
$r.result | ConvertTo-Json -Depth 5
