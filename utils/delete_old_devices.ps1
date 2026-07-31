$apiKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json" }
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/devices?device_id=eq.Yang" -Headers $headers -Method DELETE
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/devices?device_id=eq.victus" -Headers $headers -Method DELETE
