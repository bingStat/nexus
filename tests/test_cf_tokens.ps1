$required = @('CLOUDFLARE_API_TOKEN','CLOUDFLARE_ACCOUNT_ID','CLOUDFLARE_ZONE_ID')
$missing = $required | Where-Object { -not [Environment]::GetEnvironmentVariable($_) }
if ($missing) {
    Write-Error ('Missing required environment variables: ' + ($missing -join ', '))
    exit 1
}
Write-Output 'Cloudflare credential environment variables are configured.'
