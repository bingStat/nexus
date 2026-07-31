import socket
import threading

PORTAL_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <meta name="robots" content="noindex,nofollow,noarchive">
  <meta name="theme-color" content="#08111f">
  <title>Bings 服务中心 & 光猫</title>
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
    .badge.private{background:rgba(255,180,75,.12);color:#ffd08d;border-color:rgba(255,180,75,.2)}.card h3{font-size:20px;margin:22px 0 5px;letter-spacing:-.02em}.card p{font-size:13px;color:var(--muted);margin:0;line-height:1.55}.arrow{margin-top:auto;padding-top:14px;color:#d8e6fb;font-size:12px}.arrow:after{content:"  ↗";color:var(--accent)}
    footer{margin-top:34px;padding-top:20px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:16px;color:#8290a5;font-size:11px;line-height:1.6}
    @media(max-width:800px){main{padding-top:20px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.shield{display:none}}
    @media(max-width:520px){main{width:min(100% - 22px,1120px);padding-top:10px}.grid{grid-template-columns:1fr}.card{min-height:155px}header{margin-bottom:24px}}
    @media(prefers-reduced-motion:reduce){.card{transition:none}.card:hover{transform:none}}
  </style>
</head><body>

  <div class="tab-bar">
     <button class="tab-btn active" onclick="switchTab('portal', event)">导航中心</button>
     <button class="tab-btn" onclick="switchTab('modem', event)">光猫管理</button>
  </div>

  <div id="tab-portal" class="tab-content active">
    <main>
      <header>
        <div>
          <div class="eyebrow">Bings Infrastructure</div>
          <h1>服务中心</h1>
          <p class="lead">家庭影音、文件存储、网络与系统管理的统一入口。管理类服务仅限受信任设备使用。</p>
        </div>
        <div class="shield">● 私有服务导航</div>
      </header>
      <section>
        <div class="section-head"><h2>影音与文件</h2><span>公网可访问</span></div>
        <div class="grid">
          <a class="card" href="https://jellyfin.bings.app" target="_blank" rel="noopener">
            <div class="top"><div class="icon">▶</div><span class="badge">公网</span></div>
            <h3>Jellyfin</h3><p>家庭影音中心，浏览与播放电影、剧集和戏曲内容。</p><div class="arrow">打开影音中心</div>
          </a>
          <a class="card" href="https://openlist.bings.app" target="_blank" rel="noopener">
            <div class="top"><div class="icon">◫</div><span class="badge">公网</span></div>
            <h3>OpenList</h3><p>家庭文件中心、应用下载与云盘资源管理。</p><div class="arrow">打开文件中心</div>
          </a>
          <a class="card" href="https://xiaoya.bings.app" target="_blank" rel="noopener">
            <div class="top"><div class="icon">A</div><span class="badge">公网</span></div>
            <h3>小雅 AList</h3><p>小雅资源目录。这里的 AList 专指 Xiaoya AList。</p><div class="arrow">打开小雅 AList</div>
          </a>
        </div>
      </section>
      <section>
        <div class="section-head"><h2>系统与网络</h2><span>管理员入口</span></div>
        <div class="grid">
          <a class="card" href="https://browser.bings.app" target="_blank" rel="noopener">
            <div class="top"><div class="icon">🌐</div><span class="badge">公网</span></div>
            <h3>🌐 浏览器</h3><p>安全访问互联网</p><div class="arrow">打开浏览器</div>
          </a>
          <a class="card" href="https://panel.bings.app/fe849e2a95" target="_blank" rel="noopener">
            <div class="top"><div class="icon">▦</div><span class="badge private">管理</span></div>
            <h3>1Panel</h3><p>服务器、容器、网站与系统服务管理面板。</p><div class="arrow">打开管理面板</div>
          </a>
          <a class="card" href="https://router.bings.app" target="_blank" rel="noopener">
            <div class="top"><div class="icon">⌁</div><span class="badge private">管理</span></div>
            <h3>Router</h3><p>家庭路由器与局域网设备管理入口。</p><div class="arrow">打开路由器</div>
          </a>
        </div>
      </section>
      <section>
        <div class="section-head"><h2>AI 助手</h2><span>仅限 Tailscale</span></div>
        <div class="grid">
          <a class="card" href="http://100.103.12.14:19119/" target="_blank" rel="noopener">
            <div class="top"><div class="icon">H</div><span class="badge private">Tailscale</span></div>
            <h3>Hermes Agent</h3><p>ThinkCenter 上的 AI 助手控制台，用于对话、会话、配置与任务管理。</p><div class="arrow">打开 Hermes Agent</div>
          </a>
        </div>
      </section>
      <section>
        <div class="section-head"><h2>N1 网络服务</h2><span>仅限 Tailscale</span></div>
        <div class="grid">
          <a class="card" href="http://100.90.67.12/" target="_blank" rel="noopener">
            <div class="top"><div class="icon">N1</div><span class="badge private">Tailscale</span></div>
            <h3>iStoreOS</h3><p>N1 软路由系统、网络接口、插件与设备管理。</p><div class="arrow">打开 iStoreOS</div>
          </a>
          <a class="card" href="http://100.90.67.12:3000/" target="_blank" rel="noopener">
            <div class="top"><div class="icon">AD</div><span class="badge private">Tailscale</span></div>
            <h3>AdGuard Home</h3><p>N1 提供的 DNS 过滤、广告拦截与查询日志管理。</p><div class="arrow">打开 AdGuard Home</div>
          </a>
          <a class="card" href="http://100.90.67.12/cgi-bin/luci/admin/services/smartdns" target="_blank" rel="noopener">
            <div class="top"><div class="icon">DNS</div><span class="badge private">Tailscale</span></div>
            <h3>SmartDNS</h3><p>N1 上的 SmartDNS 上游、测速与解析策略管理。</p><div class="arrow">打开 SmartDNS</div>
          </a>
        </div>
      </section>
      <section>
        <div class="section-head"><h2>媒体自动化</h2><span>部分入口需要 Tailscale</span></div>
        <div class="grid">
          <a class="card" href="https://mp.bings.app" target="_blank" rel="noopener">
            <div class="top"><div class="icon">M</div><span class="badge">公网</span></div>
            <h3>MoviePilot</h3><p>媒体订阅、整理与自动化管理。</p><div class="arrow">打开 MoviePilot</div>
          </a>
          <a class="card" href="http://100.103.12.14:8080" target="_blank" rel="noopener">
            <div class="top"><div class="icon">↓</div><span class="badge private">Tailscale</span></div>
            <h3>qBittorrent</h3><p>下载任务、速度与队列管理。</p><div class="arrow">打开下载管理</div>
          </a>
          <a class="card" href="http://100.103.12.14:9696" target="_blank" rel="noopener">
            <div class="top"><div class="icon">P</div><span class="badge private">Tailscale</span></div>
            <h3>Prowlarr</h3><p>索引器、搜索源与媒体工具连接管理。</p><div class="arrow">打开 Prowlarr</div>
          </a>
        </div>
      </section>
      <footer>
        <span>Bings Service Portal · ThinkCenter</span>
        <span>管理入口请勿分享给非受信任用户</span>
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
            
            # 拦截根目录，直接返回合并的 Portal 页面
            if method == 'GET' and (path == '/' or path == '/portal'):
                response_body = PORTAL_HTML.encode('utf-8')
                new_headers = b"HTTP/1.1 200 OK\r\n"
                new_headers += b"Content-Type: text/html; charset=utf-8\r\n"
                new_headers += b"Connection: close\r\n"
                new_headers += b"Content-Length: " + str(len(response_body)).encode() + b"\r\n\r\n"
                client_socket.sendall(new_headers + response_body)
                return
                
            # 拦截 iframe 加载的 /modem_ui，转换为光猫根目录 /
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
                
        # 光猫本身有 HTML 截断修复逻辑（如前）
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
