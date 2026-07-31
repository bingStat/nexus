# Nexus FastMCP Server

æ ‡å‡†åŒ– Model Context Protocol (MCP) æœåŠ¡æ¨¡å—ï¼Œç”¨äºŽè¿œç¨‹æŽ§åˆ¶ä¸Žç»Ÿä¸€è°ƒåº¦ Nexus æ¡Œé¢ä¸ŽæœåŠ¡å™¨é›†ç¾¤ï¼ˆThinkCenter, Victus, Oracle, VSC, N1 ç­‰ï¼‰ã€‚

---

## æ ¸å¿ƒå·¥å…· (Exposed MCP Tools)

| å·¥å…·åç§° | åŠŸèƒ½æè¿° | æ ¸å¿ƒå‚æ•° |
| :--- | :--- | :--- |
| **`list_devices`** | èŽ·å–å…¨é›†ç¾¤æ³¨å†Œè®¾å¤‡åˆ—è¡¨ä¸Žåœ¨çº¿çŠ¶æ€ | æ—  |
| **`get_status`** | æŸ¥è¯¢ç‰¹å®šè®¾å¤‡çš„è¯¦ç»†å¿ƒè·³ä¸Žä¿¡æ¯ | `device_id: str` |
| **`execute_command`** | å®‰å…¨æ´¾å‘ Shell å‘½ä»¤è‡³ç›®æ ‡è®¾å¤‡ | `device: str`, `command: str`, `wait_seconds: int = 10`, `allow_dangerous: bool = False` |
| **`get_job`** | è½®è¯¢/æŸ¥è¯¢æŒ‡å®š Command ID çš„æ‰§è¡ŒçŠ¶æ€ä¸Žè¾“å‡º | `job_id: str` |

---

## æœ¬åœ° STDIO æ¨¡å¼é…ç½® (Cursor / Claude Desktop / Antigravity)

åœ¨æœ¬åœ° AI å®¢æˆ·ç«¯é…ç½®æ–‡ä»¶ï¼ˆå¦‚ `claude_desktop_config.json` æˆ– `mcpServers` è®¾ç½®ï¼‰ä¸­åŠ å…¥ï¼š

```json
{
  "mcpServers": {
    "nexus": {
      "command": "C:\\Users\\Bing\\miniconda3\\python.exe",
      "args": ["-m", "mcp_server.server"],
      "cwd": "C:\\Users\\Bing\\aurora\\Workstation\\Nexus",
      "env": {
        "NEXUS_API_URL": "https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1",
        "NEXUS_API_KEY": ""
      }
    }
  }
}
```

---

## è¿œç¨‹ SSE / HTTP æ¨¡å¼é…ç½® (nexus.bings.app)

åœ¨ ThinkCenter (Ubuntu) æœåŠ¡å™¨ä¸Šé€šè¿‡ Cloudflare Tunnel / Nginx æš´éœ²å…¨å¤©å€™ SSE æœåŠ¡ï¼š

### 1. éƒ¨ç½²åˆ° ThinkCenter

```bash
cd /home/bing/nexus-backend
pip install mcp fastapi uvicorn requests

# å¯åŠ¨ SSE æœåŠ¡
python3 -m mcp_server.app
```

### 2. Systemd å®ˆæŠ¤è¿›ç¨‹

å¤åˆ¶ `mcp_server/systemd/nexus-mcp.service` åˆ° `/etc/systemd/system/`ï¼š

```bash
sudo cp mcp_server/systemd/nexus-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nexus-mcp
```

### 3. Cloudflare Tunnel è·¯å¾„ç»‘å®š

åœ¨ Cloudflare Tunnel é…ç½®ä¸­ï¼Œå°† `nexus.bings.app/sse` æˆ– `/mcp` è·¯ç”±åˆ° `http://localhost:8000`ã€‚

ChatGPT æˆ–è¿œç¨‹ Custom GPTs å¯ç›´æŽ¥é…ç½® MCP Endpoint URLï¼š
`https://nexus.bings.app/sse`

---

## å®‰å…¨é˜²çˆ†è¯´æ˜Ž (Security Interceptor)

`mcp_server/security.py` å†…ç½®é«˜å±æŒ‡ä»¤é˜²çˆ†æ‹¦æˆªé€»è¾‘ã€‚é’ˆå¯¹ä»¥ä¸‹ç±»åž‹å‘½ä»¤ï¼š
- `rm -rf /`
- `del /s /q`
- `shutdown` / `reboot`
- `mkfs` / `format`
- `iptables -F`

ç›´æŽ¥è°ƒç”¨ `execute_command` å°†è¢«æ‹’ç»ã€‚å¦‚ç¡®è®¤éœ€æ‰§è¡Œé«˜å±æŒ‡ä»¤ï¼Œå¿…é¡»æ˜¾å¼ä¼ é€’ `allow_dangerous=True` å‚æ•°ã€‚

