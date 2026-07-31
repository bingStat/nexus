$apiKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }
$id = [System.Guid]::NewGuid().ToString()

$pyCode = @"
import http.server, socketserver, os
class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers['Content-Length'])
        with open('/tmp/cloudflared', 'wb') as f:
            f.write(self.rfile.read(length))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Upload success')
socketserver.TCPServer(('', 19877), CustomHTTPRequestHandler).serve_forever()
"@

$pyBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pyCode))
$cmd = "echo $pyBase64 | base64 -d > /tmp/upload_server.py && nohup python3 /tmp/upload_server.py > /dev/null 2>&1 &"

$payload = @{ id=$id; command=$cmd; target_device="thinkcenter"; status="pending"; timeout_ms=30000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload | Out-Null
Write-Host "Started Python upload server on ThinkCenter"
