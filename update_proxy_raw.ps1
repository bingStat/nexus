$apiKey = "${NEXUS_SECRET_FROM_ENV}"
$headers = @{ "apikey" = $apiKey; "Authorization" = "Bearer $apiKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }
$id = [System.Guid]::NewGuid().ToString()

$pyCode = @"
import socket
import threading

def handle_client(client_socket):
    try:
        request = client_socket.recv(4096)
        if not request: return
        
        req_lines = request.split(b'\r\n')
        # We don't care about the body of the request for simple GET, if it's POST we might fail, but for login page GET is enough to test.
        # Let's just do a naive proxy that fixes the response.
        
        modem = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        modem.settimeout(5)
        modem.connect(('192.168.1.1', 80))
        request = request.replace(b"Host: modem.bings.app", b"Host: 192.168.1.1")
        request = request.replace(b"Host: 127.0.0.1:10080", b"Host: 192.168.1.1")
        modem.sendall(request)
        
        response = b""
        while True:
            try:
                chunk = modem.recv(4096)
                if not chunk: break
                response += chunk
            except socket.timeout:
                break
                
        # Now we parse and fix the response
        parts = response.split(b'\r\n\r\n', 1)
        if len(parts) == 2:
            headers_part, body_part = parts
            
            # Find </html> and truncate body!
            idx = body_part.lower().find(b"</html>")
            if idx != -1:
                body_part = body_part[:idx + 7]
            
            # Rebuild headers
            new_headers = b"HTTP/1.1 200 OK\r\n"
            new_headers += b"Content-Type: text/html; charset=utf-8\r\n"
            new_headers += b"Connection: close\r\n"
            new_headers += b"Content-Length: " + str(len(body_part)).encode() + b"\r\n\r\n"
            
            client_socket.sendall(new_headers + body_part)
        else:
            # Fallback
            client_socket.sendall(response)
    except Exception as e:
        pass
    finally:
        client_socket.close()

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('0.0.0.0', 10080))
server.listen(50)
print('Raw Proxy serving on 10080')
while True:
    client, addr = server.accept()
    threading.Thread(target=handle_client, args=(client,)).start()
"@

$sshCmd = "ssh -o StrictHostKeyChecking=no root@192.168.31.88 `"cat << 'EOF' > /root/modem_proxy.py`n" + $pyCode + "`nEOF`n docker restart modem_proxy`""

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

