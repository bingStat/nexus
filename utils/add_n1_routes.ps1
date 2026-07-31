$accountId = '222ffe916db1155102a45e4cfb4a4ec8'
$tunnelId = '8fb4a8c3-7874-450b-8661-fad52c64e497'
$token = $env:CLOUDFLARE_API_TOKEN
$headers = @{ 'Authorization' = "Bearer $token"; 'Content-Type' = 'application/json' }
$uri = "https://api.cloudflare.com/client/v4/accounts/$accountId/cfd_tunnel/$tunnelId/configurations"

$r = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
$config = $r.result.config

# Filter out the catch-all
$newIngress = $config.ingress | Where-Object { $_.service -ne "http_status:404" }

# Function to add if not exists
function Add-Route($hostname, $service) {
    global $newIngress
    $exists = $newIngress | Where-Object { $_.hostname -eq $hostname }
    if (-not $exists) {
        $newIngress += @{ hostname = $hostname; service = $service }
        Write-Host "Added $hostname -> $service"
    }
}

Add-Route "adguard.bings.app" "http://127.0.0.1:3000"
Add-Route "terminal.bings.app" "http://127.0.0.1:7681"
Add-Route "alist.bings.app" "http://127.0.0.1:5244"
Add-Route "linkease.bings.app" "http://127.0.0.1:8897"
Add-Route "mihomo.bings.app" "http://127.0.0.1:9090"

# Add back catch-all
$newIngress += @{ service = "http_status:404" }
$config.ingress = $newIngress

$payload = @{ config = $config } | ConvertTo-Json -Depth 10

try {
    $putRes = Invoke-RestMethod -Uri $uri -Headers $headers -Method PUT -Body $payload
    Write-Host "UPDATE SUCCESS!"
} catch {
    Write-Host "Error: $_"
    $_.Exception.Response.GetResponseStream() | %{ (New-Object System.IO.StreamReader($_)).ReadToEnd() }
}
