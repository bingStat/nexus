$accountId = '222ffe916db1155102a45e4cfb4a4ec8'
$tunnelId = '8fb4a8c3-7874-450b-8661-fad52c64e497'
$token = $env:CLOUDFLARE_API_TOKEN
$headers = @{ 'Authorization' = "Bearer $token"; 'Content-Type' = 'application/json' }
$uri = "https://api.cloudflare.com/client/v4/accounts/$accountId/cfd_tunnel/$tunnelId/configurations"

try {
    $response = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
    $response | ConvertTo-Json -Depth 10
} catch {
    Write-Host "Error: $_"
    $_.Exception.Response.GetResponseStream() | %{ (New-Object System.IO.StreamReader($_)).ReadToEnd() }
}
