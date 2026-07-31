$env:BWS_ACCESS_TOKEN="0.f48083d0-d9ff-409a-92c3-b49700d5f88b.CODIdvJ6l1fFK4KP563HvlsLxRwmE4:3FcS9d97d5+3z1xKU9VIzQ=="
$secretsJson = & C:\Users\Bing\bws\bws.exe secret list -o json | ConvertFrom-Json
$globalKey = ($secretsJson | Where-Object key -eq 'CLOUDFLARE_GLOBAL_API_KEY').value
$accountId = ($secretsJson | Where-Object key -eq 'CLOUDFLARE_ACCOUNT_ID').value
$headers = @{ 'X-Auth-Email'='yang_bobby@qq.com'; 'X-Auth-Key'=$globalKey; 'Content-Type'='application/json' }

$tunnels = @(
    "7abed2c8-7152-4b53-a52e-7fd8503326fa",
    "4da40a5f-e757-4e93-92b6-1c12a2ae9106",
    "69537a5a-0e93-47da-8334-fe56011c648a"
)

foreach ($t in $tunnels) {
    $uri = "https://api.cloudflare.com/client/v4/accounts/$accountId/cfd_tunnel/$t/configurations"
    $r = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
    Write-Host "Tunnel $t :"
    $r.result.config.ingress | Select-Object hostname | ConvertTo-Json
}
