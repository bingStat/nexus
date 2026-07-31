$apiKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }
$id = [System.Guid]::NewGuid().ToString()

$pyCode = @"
import http.server
import urllib.request
import socketserver

class Proxy(http.server.SimpleHTTPRequestHandler):
    def handle_req(self, req):
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                content = response.read()
                self.send_response(response.status)
                for k, v in response.headers.items():
                    if k.lower() not in ('transfer-encoding', 'content-length', 'connection', 'cache-control', 'expires', 'pragma'):
                        self.send_header(k, v)
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
        except urllib.error.HTTPError as e:
            content = e.read()
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ('transfer-encoding', 'content-length', 'connection', 'cache-control'):
                    self.send_header(k, v)
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, str(e))

    def do_GET(self):
        url = 'http://192.168.1.1' + self.path
        req = urllib.request.Request(url, headers={'Host': '192.168.1.1'})
        self.handle_req(req)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        post_data = self.rfile.read(length) if length > 0 else None
        url = 'http://192.168.1.1' + self.path
        ctype = self.headers.get('Content-Type', 'application/x-www-form-urlencoded')
        req = urllib.request.Request(url, data=post_data, headers={'Host': '192.168.1.1', 'Content-Type': ctype})
        self.handle_req(req)

try:
    with socketserver.TCPServer(('0.0.0.0', 10080), Proxy) as httpd:
        print('Proxy serving on 10080')
        httpd.serve_forever()
except Exception as e:
    print(e)
"@

$encoded = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($pyCode))
$sshCmd = "echo $encoded | base64 -d > /root/modem_proxy.py && docker rm -f modem_proxy || true && docker run -d --name modem_proxy --restart always --network host -v /root/modem_proxy.py:/modem_proxy.py python:3-alpine python3 /modem_proxy.py"

$payload = @{ id=$id; command=$sshCmd; target_device="thinkcenter"; status="pending"; timeout_ms=30000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload | Out-Null
Write-Host "Sent cmd $id"
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep 2
    $r = Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands?id=eq.$id&select=status,output" -Headers $headers
    if ($r.status -in "completed","failed") {
        Write-Host "STATUS: $($r.status)"
        Write-Host "OUTPUT: $($r.output)"
        exit 0
    }
}
Write-Host "TIMEOUT"
