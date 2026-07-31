$apiKey = "${NEXUS_SECRET_FROM_ENV}"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json" }
$r = Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/devices?limit=1" -Headers $headers -Method GET
$r | ConvertTo-Json -Depth 5

