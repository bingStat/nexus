$accountId = '${NEXUS_SECRET_FROM_ENV}'
$tunnelId = '${NEXUS_SECRET_FROM_ENV}'
$token = '${NEXUS_SECRET_FROM_ENV}'
$headers = @{ 'Authorization' = "Bearer $token"; 'Content-Type' = 'application/json' }
$uri = "${NEXUS_SECRET_FROM_ENV}"

try {
    $response = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
    $response | ConvertTo-Json -Depth 10
} catch {
    Write-Host "Error: $_"
    $_.Exception.Response.GetResponseStream() | %{ (New-Object System.IO.StreamReader($_)).ReadToEnd() }
}



