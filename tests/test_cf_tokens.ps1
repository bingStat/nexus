$tokens = @(
    $env:CLOUDFLARE_API_TOKEN
)

foreach ($token in $tokens) {
    Write-Host "Testing token: $token"
    $headers = @{ 'Authorization' = "Bearer $token"; 'Content-Type' = 'application/json' }
    try {
        $r = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/user" -Headers $headers -Method GET
        Write-Host "SUCCESS! Email: $($r.result.email)"
        
        # Test Tunnel API
        $accountId = '222ffe916db1155102a45e4cfb4a4ec8'
        $tunnelId = '8fb4a8c3-7874-450b-8661-fad52c64e497'
        $uri = "https://api.cloudflare.com/client/v4/accounts/$accountId/cfd_tunnel/$tunnelId/configurations"
        try {
            $tr = Invoke-RestMethod -Uri $uri -Headers $headers -Method GET
            Write-Host "TUNNEL API SUCCESS!"
            $tr | ConvertTo-Json -Depth 10
        } catch {
            Write-Host "Tunnel API Failed with this token"
        }

    } catch {
        Write-Host "Failed"
    }
    Write-Host "-----------------"
}
