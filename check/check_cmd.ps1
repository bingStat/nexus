$apiKey = "${NEXUS_SECRET_FROM_ENV}"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey" }
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands?id=eq.2cbc6661-dce3-4974-95a0-baa5b0e605ae&select=status,output" -Headers $headers | ConvertTo-Json

