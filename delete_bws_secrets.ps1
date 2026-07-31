$env:BWS_ACCESS_TOKEN="0.f48083d0-d9ff-409a-92c3-b49700d5f88b.CODIdvJ6l1fFK4KP563HvlsLxRwmE4:3FcS9d97d5+3z1xKU9VIzQ=="
$secretsJson = & C:\Users\Bing\bws\bws.exe secret list -o json | ConvertFrom-Json

$keysToDelete = @("RCLONE_GUI_URL", "RCLONE_GUI_TAILSCALE_URL", "RCLONE_GUI_USER", "RCLONE_GUI_PASS")

foreach ($secret in $secretsJson) {
    if ($keysToDelete -contains $secret.key) {
        Write-Host "Deleting secret $($secret.key) (ID: $($secret.id))"
        & C:\Users\Bing\bws\bws.exe secret delete $secret.id
    }
}

Write-Host "Deletion process complete."

