import socket
import threading

def handle_client(client_socket):
    try:
        request = client_socket.recv(4096)
        if not request: return
        
        modem = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        modem.settimeout(5)
        modem.connect(('192.168.1.1', 80))
        
        lines = request.split(b'\r\n')
        for i in range(len(lines)):
            if lines[i].lower().startswith(b'host:'):
                lines[i] = b'Host: 192.168.1.1'
        
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
                
        parts = response.split(b'\r\n\r\n', 1)
        if len(parts) == 2:
            headers_part, body_part = parts
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

