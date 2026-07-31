import socket
import threading

PORTAL_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <meta name="theme-color" content="#08111f">
  <title>Bings æœåŠ¡ä¸­å¿ƒ & å…‰çŒ«</title>
  <style>
    :root{color-scheme:dark;--bg:#07101d;--panel:rgba(17,29,48,.72);--line:rgba(255,255,255,.10);--text:#f5f7fb;--muted:#aab6c8;--accent:#82b7ff}
    *{box-sizing:border-box} body{margin:0;min-height:100vh;font-family:Inter,"SF Pro Display","PingFang SC","Microsoft YaHei",sans-serif;color:var(--text);background:radial-gradient(circle at 15% 5%,#18365c 0,transparent 32%),radial-gradient(circle at 88% 18%,#18304b 0,transparent 28%),linear-gradient(145deg,#050b14,#0a1728 58%,#07101d);background-attachment:fixed}
    body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);background-size:36px 36px;mask-image:linear-gradient(to bottom,black,transparent 80%)}
    main{width:min(1120px,calc(100% - 32px));margin:auto;padding:20px 0 58px;position:relative}
    header{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:34px}
    .eyebrow{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);font-weight:700}
    h1{font-size:clamp(34px,6vw,62px);line-height:1.03;margin:9px 0 12px;letter-spacing:-.045em}
    .lead{margin:0;color:var(--muted);font-size:15px;line-height:1.7;max-width:620px}
    .shield{flex:0 0 auto;border:1px solid var(--line);background:rgba(4,12,23,.48);backdrop-filter:blur(16px);padding:10px 14px;border-radius:999px;color:#c9d5e6;font-size:12px}
    
    /* Tabs Styles */
    .tab-bar {
       display: flex;
       justify-content: center;
       gap: 16px;
       margin-top: 15px;
       padding-bottom: 5px;
       position: relative;
       z-index: 100;
    }
    .tab-btn {
       background: rgba(17,29,48,.5);
       border: 1px solid var(--line);
       color: var(--muted);
       padding: 8px 24px;
       border-radius: 999px;
       cursor: pointer;
       font-family: inherit;
       font-size: 14px;
       font-weight: 500;
       transition: all 0.2s;
       backdrop-filter: blur(8px);
    }
    .tab-btn:hover {
       background: rgba(17,29,48,.8);
       color: #fff;
    }
    .tab-btn.active {
       background: rgba(130,183,255,.15);
       color: #fff;
       border-color: rgba(130,183,255,.46);
       box-shadow: 0 0 15px rgba(130,183,255,.1);
    }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    
    .modem-container {
       width: 100%;
       height: calc(100vh - 70px);
       padding: 0;
       margin: 0;
    }
    .modem-frame {
       width: 100%;
       height: 100%;
       border: none;
       background: #fff;
    }
  </style>
  <style>
    section{margin-top:30px}.section-head{display:flex;align-items:center;justify-content:space-between;margin:0 2px 13px}.section-head h2{font-size:15px;margin:0;letter-spacing:.03em}.section-head span{font-size:12px;color:var(--muted)}
    .grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.card{min-height:176px;text-decoration:none;color:inherit;border:1px solid var(--line);border-radius:22px;padding:21px;background:linear-gradient(145deg,rgba(25,40,63,.82),rgba(11,22,38,.72));backdrop-filter:blur(18px);box-shadow:0 16px 44px rgba(0,0,0,.18);display:flex;flex-direction:column;transition:transform .18s ease,border-color .18s ease,background .18s ease}
    .card:hover{transform:translateY(-4px);border-color:rgba(130,183,255,.46);background:linear-gradient(145deg,rgba(31,51,80,.9),rgba(13,27,47,.82))}.top{display:flex;align-items:start;justify-content:space-between;gap:12px}.icon{width:45px;height:45px;border-radius:14px;display:grid;place-items:center;background:rgba(255,255,255,.075);border:1px solid rgba(255,255,255,.08);font-size:23px}.badge{font-size:10px;font-weight:700;letter-spacing:.08em;padding:5px 8px;border-radius:999px;background:rgba(73,190,128,.13);color:#8ee2b3;border:1px solid rgba(73,190,128,.22)}
    .badge.private{background:rgba(255,180,75,.12);color:#ffd08d;border-color:rgba(255,180,75,.2)}.card h3{font-size:20px;margin:22px 0 5px;letter-spacing:-.02em}.card p{font-size:13px;color:var(--muted);margin:0;line-height:1.55}.arrow{margin-top:auto;padding-top:14px;color:#d8e6fb;font-size:12px}.arrow:after{content:"  â†—";color:var(--accent)}
    footer{margin-top:34px;padding-top:20px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:16px;color:#8290a5;font-size:11px;line-height:1.6}
    @media(max-width:800px){main{padding-top:20px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.shield{display:none}}
    @media(max-width:520px){main{width:min(100% - 22px,1120px);padding-top:10px}.grid{grid-template-columns:1fr}.card{min-height:155px}header{margin-bottom:24px}}
    @media(prefers-reduced-motion:reduce){.card{transition:none}.card:hover{transform:none}}
  </style>
</head><body>

  <div class="tab-bar">
     <button class="tab-btn active" onclick="switchTab('portal', event)">å¯¼èˆªä¸­å¿ƒ</button>
     <button class="tab-btn" onclick="switchTab('modem', event)">å…‰çŒ«ç®¡ç†</button>
  </div>

  <div id="tab-portal" class="tab-content active">
    <main>
      <header>
        <div>
          <div class="eyebrow">Bings Infrastructure</div>
          <h1>æœåŠ¡ä¸­å¿ƒ</h1>
          <p class="lead">å®¶åº­å½±éŸ³ã€æ–‡ä»¶å­˜å‚¨ã€ç½‘ç»œä¸Žç³»ç»Ÿç®¡ç†çš„ç»Ÿä¸€å…¥å£ã€‚ç®¡ç†ç±»æœåŠ¡ä»…é™å—ä¿¡ä»»è®¾å¤‡ä½¿ç”¨ã€‚</p>
        </div>
        <div class="shield">â— ç§æœ‰æœåŠ¡å¯¼èˆª</div>
      </header>
      <section>
        <div class="section-head"><h2>å½±éŸ³ä¸Žæ–‡ä»¶</h2><span>å…¬ç½‘å¯è®¿é—®</span></div>
        <div class="grid">
          <a class="card" href="https://jellyfin.bings.app" target="_blank" rel="noopener">
            <div class="top"><div class="icon">â–¶</div><span class="badge">å…¬ç½‘</span></div>
            <h3>Jellyfin</h3><p>å®¶åº­å½±éŸ³ä¸­å¿ƒï¼Œæµè§ˆä¸Žæ’­æ”¾ç”µå½±ã€å‰§é›†å’Œæˆæ›²å†…å®¹ã€‚</p><div class="arrow">æ‰“å¼€å½±éŸ³ä¸­å¿ƒ</div>
          </a>
          <a class="card" href="https://openlist.bings.app" target="_blank" rel="noopener">
            <div class="top"><div class="icon">â—«</div><span class="badge">å…¬ç½‘</span></div>
            <h3>OpenList</h3><p>å®¶åº­æ–‡ä»¶ä¸­å¿ƒã€åº”ç”¨ä¸‹è½½ä¸Žäº‘ç›˜èµ„æºç®¡ç†ã€‚</p><div class="arrow">æ‰“å¼€æ–‡ä»¶ä¸­å¿ƒ</div>
          </a>
          <a class="card" href="https://xiaoya.bings.app" target="_blank" rel="noopener">
            <div class="top"><div class="icon">A</div><span class="badge">å…¬ç½‘</span></div>
            <h3>å°é›… AList</h3><p>å°é›…èµ„æºç›®å½•ã€‚è¿™é‡Œçš„ AList ä¸“æŒ‡ Xiaoya AListã€‚</p><div class="arrow">æ‰“å¼€å°é›… AList</div>
          </a>
        </div>
      </section>
      <section>
        <div class="section-head"><h2>ç³»ç»Ÿä¸Žç½‘ç»œ</h2><span>ç®¡ç†å‘˜å…¥å£</span></div>
        <div class="grid">
          <a class="card" href="https://browser.bings.app" target="_blank" rel="noopener">
            <div class="top"><div class="icon">ðŸŒ</div><span class="badge">å…¬ç½‘</span></div>
            <h3>ðŸŒ æµè§ˆå™¨</h3><p>å®‰å…¨è®¿é—®äº’è”ç½‘</p><div class="arrow">æ‰“å¼€æµè§ˆå™¨</div>
          </a>
          <a class="card" href="https://panel.bings.app/fe849e2a95" target="_blank" rel="noopener">
            <div class="top"><div class="icon">â–¦</div><span class="badge private">ç®¡ç†</span></div>
            <h3>1Panel</h3><p>æœåŠ¡å™¨ã€å®¹å™¨ã€ç½‘ç«™ä¸Žç³»ç»ŸæœåŠ¡ç®¡ç†é¢æ¿ã€‚</p><div class="arrow">æ‰“å¼€ç®¡ç†é¢æ¿</div>
          </a>
          <a class="card" href="https://router.bings.app" target="_blank" rel="noopener">
            <div class="top"><div class="icon">âŒ</div><span class="badge private">ç®¡ç†</span></div>
            <h3>Router</h3><p>å®¶åº­è·¯ç”±å™¨ä¸Žå±€åŸŸç½‘è®¾å¤‡ç®¡ç†å…¥å£ã€‚</p><div class="arrow">æ‰“å¼€è·¯ç”±å™¨</div>
          </a>
        </div>
      </section>
      <section>
        <div class="section-head"><h2>AI åŠ©æ‰‹</h2><span>ä»…é™ Tailscale</span></div>
        <div class="grid">
          <a class="card" href="http://100.103.12.14:19119/" target="_blank" rel="noopener">
            <div class="top"><div class="icon">H</div><span class="badge private">Tailscale</span></div>
            <h3>Hermes Agent</h3><p>ThinkCenter ä¸Šçš„ AI åŠ©æ‰‹æŽ§åˆ¶å°ï¼Œç”¨äºŽå¯¹è¯ã€ä¼šè¯ã€é…ç½®ä¸Žä»»åŠ¡ç®¡ç†ã€‚</p><div class="arrow">æ‰“å¼€ Hermes Agent</div>
          </a>
        </div>
      </section>
      <section>
        <div class="section-head"><h2>N1 ç½‘ç»œæœåŠ¡</h2><span>ä»…é™ Tailscale</span></div>
        <div class="grid">
          <a class="card" href="http://100.90.67.12/" target="_blank" rel="noopener">
            <div class="top"><div class="icon">N1</div><span class="badge private">Tailscale</span></div>
            <h3>iStoreOS</h3><p>N1 è½¯è·¯ç”±ç³»ç»Ÿã€ç½‘ç»œæŽ¥å£ã€æ’ä»¶ä¸Žè®¾å¤‡ç®¡ç†ã€‚</p><div class="arrow">æ‰“å¼€ iStoreOS</div>
          </a>
          <a class="card" href="http://100.90.67.12:3000/" target="_blank" rel="noopener">
            <div class="top"><div class="icon">AD</div><span class="badge private">Tailscale</span></div>
            <h3>AdGuard Home</h3><p>N1 æä¾›çš„ DNS è¿‡æ»¤ã€å¹¿å‘Šæ‹¦æˆªä¸ŽæŸ¥è¯¢æ—¥å¿—ç®¡ç†ã€‚</p><div class="arrow">æ‰“å¼€ AdGuard Home</div>
          </a>
          <a class="card" href="http://100.90.67.12/cgi-bin/luci/admin/services/smartdns" target="_blank" rel="noopener">
            <div class="top"><div class="icon">DNS</div><span class="badge private">Tailscale</span></div>
            <h3>SmartDNS</h3><p>N1 ä¸Šçš„ SmartDNS ä¸Šæ¸¸ã€æµ‹é€Ÿä¸Žè§£æžç­–ç•¥ç®¡ç†ã€‚</p><div class="arrow">æ‰“å¼€ SmartDNS</div>
          </a>
        </div>
      </section>
      <section>
        <div class="section-head"><h2>åª’ä½“è‡ªåŠ¨åŒ–</h2><span>éƒ¨åˆ†å…¥å£éœ€è¦ Tailscale</span></div>
        <div class="grid">
          <a class="card" href="https://mp.bings.app" target="_blank" rel="noopener">
            <div class="top"><div class="icon">M</div><span class="badge">å…¬ç½‘</span></div>
            <h3>MoviePilot</h3><p>åª’ä½“è®¢é˜…ã€æ•´ç†ä¸Žè‡ªåŠ¨åŒ–ç®¡ç†ã€‚</p><div class="arrow">æ‰“å¼€ MoviePilot</div>
          </a>
          <a class="card" href="http://100.103.12.14:8080" target="_blank" rel="noopener">
            <div class="top"><div class="icon">â†“</div><span class="badge private">Tailscale</span></div>
            <h3>qBittorrent</h3><p>ä¸‹è½½ä»»åŠ¡ã€é€Ÿåº¦ä¸Žé˜Ÿåˆ—ç®¡ç†ã€‚</p><div class="arrow">æ‰“å¼€ä¸‹è½½ç®¡ç†</div>
          </a>
          <a class="card" href="http://100.103.12.14:9696" target="_blank" rel="noopener">
            <div class="top"><div class="icon">P</div><span class="badge private">Tailscale</span></div>
            <h3>Prowlarr</h3><p>ç´¢å¼•å™¨ã€æœç´¢æºä¸Žåª’ä½“å·¥å…·è¿žæŽ¥ç®¡ç†ã€‚</p><div class="arrow">æ‰“å¼€ Prowlarr</div>
          </a>
        </div>
      </section>
      <footer>
        <span>Bings Service Portal Â· ThinkCenter</span>
        <span>ç®¡ç†å…¥å£è¯·å‹¿åˆ†äº«ç»™éžå—ä¿¡ä»»ç”¨æˆ·</span>
      </footer>
    </main>
  </div>

  <div id="tab-modem" class="tab-content">
     <div class="modem-container">
        <iframe id="modem-iframe" class="modem-frame" data-src="/modem_ui"></iframe>
     </div>
  </div>

  <script>
    if (window.top !== window.self) {
        window.top.location = window.self.location;
    }
    function switchTab(tabId, event) {
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
        
        event.target.classList.add('active');
        document.getElementById('tab-' + tabId).classList.add('active');
        
        if (tabId === 'modem') {
            const iframe = document.getElementById('modem-iframe');
            if (!iframe.src || iframe.src === window.location.href) {
                iframe.src = iframe.getAttribute('data-src');
            }
        }
    }
  </script>
</body>
</html>
"""

def handle_client(client_socket):
    try:
        request = client_socket.recv(4096)
        if not request: return
        
        # Split headers
        header_end = request.find(b'\r\n\r\n')
        if header_end == -1:
            header_end = len(request)
            
        headers_block = request[:header_end]
        lines = headers_block.split(b'\r\n')
        if not lines:
            return
            
        first_line = lines[0].decode('utf-8', errors='ignore')
        parts = first_line.split(' ')
        if len(parts) >= 2:
            method = parts[0]
            path = parts[1]
            
            # æ‹¦æˆªæ ¹ç›®å½•ï¼Œç›´æŽ¥è¿”å›žåˆå¹¶çš„ Portal é¡µé¢
            if method == 'GET' and (path == '/' or path == '/portal'):
                response_body = PORTAL_HTML.encode('utf-8')
                new_headers = b"HTTP/1.1 200 OK\r\n"
                new_headers += b"Content-Type: text/html; charset=utf-8\r\n"
                new_headers += b"Connection: close\r\n"
                new_headers += b"Content-Length: " + str(len(response_body)).encode() + b"\r\n\r\n"
                client_socket.sendall(new_headers + response_body)
                return
                
            # æ‹¦æˆª iframe åŠ è½½çš„ /modem_uiï¼Œè½¬æ¢ä¸ºå…‰çŒ«æ ¹ç›®å½• /
            if path == '/modem_ui':
                path = '/'
                # Rewrite first line
                parts[1] = path
                lines[0] = ' '.join(parts).encode('utf-8')
        
        # Rewrite Host header to 192.168.1.1
        for i in range(len(lines)):
            if lines[i].lower().startswith(b'host:'):
                lines[i] = b'Host: 192.168.1.1'
        
        modem_request = b'\r\n'.join(lines)
        if len(request) > header_end + 4:
            modem_request += b'\r\n\r\n' + request[header_end+4:]
        else:
            modem_request += b'\r\n\r\n'
            
        modem = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        modem.settimeout(5)
        modem.connect(('192.168.1.1', 80))
        modem.sendall(modem_request)
        
        response = b""
        while True:
            try:
                chunk = modem.recv(4096)
                if not chunk: break
                response += chunk
            except socket.timeout:
                break
                
        # å…‰çŒ«æœ¬èº«æœ‰ HTML æˆªæ–­ä¿®å¤é€»è¾‘ï¼ˆå¦‚å‰ï¼‰
        parts = response.split(b'\r\n\r\n', 1)
        if len(parts) == 2:
            headers_part, body_part = parts
            idx = body_part.lower().find(b'</html>')
            if idx != -1:
                body_part = body_part[:idx + 7]
                
                new_headers = b"HTTP/1.1 200 OK\r\n"
                # Keep content-type if exists, else text/html
                if b'content-type:' not in headers_part.lower():
                    new_headers += b"Content-Type: text/html; charset=utf-8\r\n"
                # Reconstruct original headers minus Content-Length and Transfer-Encoding
                for hline in headers_part.split(b'\r\n')[1:]:
                    if not hline.lower().startswith(b'content-length:') and not hline.lower().startswith(b'transfer-encoding:'):
                        new_headers += hline + b"\r\n"
                new_headers += b"Content-Length: " + str(len(body_part)).encode() + b"\r\n\r\n"
                
                client_socket.sendall(new_headers + body_part)
            else:
                client_socket.sendall(response)
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
print("Unified Portal + Modem Proxy running on 0.0.0.0:10080")
while True:
    client, addr = server.accept()
    threading.Thread(target=handle_client, args=(client,)).start()

