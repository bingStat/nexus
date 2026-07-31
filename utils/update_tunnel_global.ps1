$env:BWS_ACCESS_TOKEN="0.f48083d0-d9ff-409a-92c3-b49700d5f88b.CODIdvJ6l1fFK4KP563HvlsLxRwmE4:3FcS9d97d5+3z1xKU9VIzQ=="
$bws = "C:\Users\Bing\bws\bws.exe"

$secretsJson = & $bws secret list -o json | ConvertFrom-Json
$secrets = @{}
foreach ($s in $secretsJson) {
    $secrets[$s.key] = $s.value
}

$globalKey = $secrets["CLOUDFLARE_GLOBAL_API_KEY"]
$accountId = $secrets["CLOUDFLARE_ACCOUNT_ID"]
$email = "yang_bobby@qq.com"

# The tunnel ID we found earlier
$tunnelId = '8fb4a8c3-7874-450b-8661-fad52c64e497'

$headers = @{ 
    'X-Auth-Email' = $email
    'X-Auth-Key' = $globalKey
    'Content-Type' = 'application/json' 
}
$uri = "https://api.cloudflare.com/client/v4/accounts/$accountId/cfd_tunnel/$tunnelId/configurations"

Write-Host "Fetching current config..."
$r = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
$config = $r.result.config

$newIngress = @($config.ingress | Where-Object { $_.service -ne "http_status:404" })

function Add-Route($hostname, $service) {
    $exists = $script:newIngress | Where-Object { $_.hostname -eq $hostname }
    if (-not $exists) {
        $script:newIngress += @{ hostname = $hostname; service = $service }
        Write-Host "Added $hostname -> $service"
    }
}

# The N1 services
Add-Route "adguard.bings.app" "http://127.0.0.1:3000"
Add-Route "terminal.bings.app" "http://127.0.0.1:7681"
# AList was stopped by the user, so omitting it:
# Add-Route "alist.bings.app" "http://127.0.0.1:5244"
Add-Route "mihomo.bings.app" "http://127.0.0.1:9090"
Add-Route "linkease.bings.app" "http://127.0.0.1:8897"

$script:newIngress += @{ service = "http_status:404" }
$config.ingress = $script:newIngress

$payload = @{ config = $config } | ConvertTo-Json -Depth 10 -Compress

Write-Host "Updating tunnel config..."
try {
    $putRes = Invoke-RestMethod -Uri $uri -Headers $headers -Method PUT -Body $payload
    Write-Host "UPDATE SUCCESS! Routes added."
} catch {
    Write-Host "Error: $_"
    $_.Exception.Response.GetResponseStream() | %{ (New-Object System.IO.StreamReader($_)).ReadToEnd() }
}

