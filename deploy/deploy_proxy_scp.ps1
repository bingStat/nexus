$apiKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }
$id = [System.Guid]::NewGuid().ToString()

$pyCode = @"
import socket
import threading

def handle_client(client_socket):
    try:
        request = client_socket.recv(4096)
        if not request: return
        
        modem = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        modem.settimeout(5)
        modem.connect(('192.168.1.1', 80))
        
        # We need to replace the Host header
        lines = request.split(b'\r\n')
        for i in range(len(lines)):
            if lines[i].lower().startswith(b'host:'):
                lines[i] = b'Host: 192.168.1.1'
        
        # Reconstruct request
        modem_request = b'\r\n'.join(lines)
        modem.sendall(modem_request)
        
        response = b""
        while True:
            try:
                chunk = modem.recv(4096)
                if not chunk: break
                response += chunk
            except socket.timeout:
                break
                
        # Parse response
        parts = response.split(b'\r\n\r\n', 1)
        if len(parts) == 2:
            headers_part, body_part = parts
            
            # Remove trailing headers after HTML
            idx = body_part.lower().find(b'</html>')
            if idx != -1:
                body_part = body_part[:idx + 7]
                
            new_headers = b"HTTP/1.1 200 OK\r\n"
            new_headers += b"Content-Type: text/html; charset=utf-8\r\n"
            new_headers += b"Connection: close\r\n"
            new_headers += b"Content-Length: " + str(len(body_part)).encode() + b"\r\n\r\n"
            
            client_socket.sendall(new_headers + body_part)
        else:
            client_socket.sendall(response)
    except Exception as e:
        pass
    finally:
        try:
            client_socket.close()
        except:
            pass

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('0.0.0.0', 10080))
server.listen(50)
while True:
    client, addr = server.accept()
    threading.Thread(target=handle_client, args=(client,)).start()
"@

# Write to a file locally on ThinkCenter first via the Supabase agent
$encoded = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($pyCode))
$localCmd = "powershell -Command `" [System.IO.File]::WriteAllBytes('C:\Users\Bing\modem_proxy.py', [Convert]::FromBase64String('$encoded')) `""

$payload1 = @{ id=$id; command=$localCmd; target_device="thinkcenter"; status="pending"; timeout_ms=30000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload1 | Out-Null
Start-Sleep 3

# Then SCP it to N1 and restart docker
$id2 = [System.Guid]::NewGuid().ToString()
$scpCmd = "scp -o StrictHostKeyChecking=no C:\Users\Bing\modem_proxy.py root@192.168.31.88:/root/modem_proxy.py && ssh -o StrictHostKeyChecking=no root@192.168.31.88 'docker restart modem_proxy'"
$payload2 = @{ id=$id2; command=$scpCmd; target_device="thinkcenter"; status="pending"; timeout_ms=30000 } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands" -Method POST -Headers $headers -Body $payload2 | Out-Null
Write-Host "Sent scp cmd $id2"
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep 2
    $r = Invoke-RestMethod -Uri "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/commands?id=eq.$id2&select=status,output" -Headers $headers
    if ($r.status -in "completed","failed") {
        Write-Host "STATUS: $($r.status)"
        Write-Host "OUTPUT: $($r.output)"
        exit 0
    }
}
