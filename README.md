# ðŸŒ Nexus: Multi-Node Distributed Cluster Agent & FastMCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/Protocol-Model_Context_Protocol_(MCP)-green.svg)](https://modelcontextprotocol.io/)
[![Cloudflare Tunnel](https://img.shields.io/badge/Transport-Cloudflare_Tunnel-orange.svg)](https://nexus.bings.app)

**Nexus** æ˜¯ä¸€å¥—é«˜æ€§èƒ½ã€ä½Žå»¶è¿Ÿçš„**è·¨ç«¯åˆ†å¸ƒå¼ç¡¬ä»¶é›†ç¾¤æ™ºèƒ½æŽ§åˆ¶ä¸­æž¢**ã€‚ç³»ç»Ÿæ‰“ç ´äº†ä¼ ç»Ÿå±€åŸŸç½‘é™åˆ¶ä¸Ž 30 ç§’ HTTP è¶…æ—¶å£åž’ï¼Œå®žçŽ°äº†å¯¹ Linux æœåŠ¡å™¨ï¼ˆThinkCenter / Oracleï¼‰ã€Windows ä¸»åŠ›å·¥ä½œç«™ï¼ˆVictusï¼‰ã€KU Leuven HPC è¶…ç®—é›†ç¾¤ï¼ˆVSCï¼‰ä»¥åŠ OpenWrt è½¯è·¯ç”±ï¼ˆN1ï¼‰çš„ç»Ÿä¸€è°ƒåº¦ä¸Žå…¨å¤©å€™è¿œç¨‹æ“æŽ§ã€‚

---

## ðŸŒŸ æ ¸å¿ƒç‰¹æ€§ (Key Features)

- âš¡ **åŒä¼ è¾“æ¨¡å¼ (Dual Transport)**: 
  - **STDIO æ¨¡å¼**: ä¾› Cursor / Antigravity / Claude Desktop æœ¬åœ°ç›´æŽ¥é«˜å¹¶å‘è°ƒç”¨ã€‚
  - **HTTP / SSE æ¨¡å¼**: åŸºäºŽ FastAPI/Uvicorn æš´éœ² `/sse` èŠ‚ç‚¹ï¼ŒæŒ‚è½½äºŽ `https://nexus.bings.app/sse`ï¼Œä¾›ç½‘é¡µç‰ˆ ChatGPT / Gemini / Claude å…¨å¤©å€™æ— ç¼è¿žæŽ¥ã€‚
- ðŸ›¡ï¸ **é«˜å±æŒ‡ä»¤é˜²çˆ†æ‹¦æˆªå™¨ (Security Interceptor)**: å†…ç½®å¯¹ `rm -rf`, `shutdown`, `reboot`, `format`, `del /s /q`, `iptables` ç­‰æ¯ç­æ€§æŒ‡ä»¤çš„æ­£åˆ™æ‹¦æˆªé€»è¾‘ï¼Œå¼ºåˆ¶äºŒæ¬¡å®‰å…¨ç¡®è®¤ã€‚
- ðŸš€ **é›¶å‚æ•°ä¸€é”®å®‰è£… (One-Liner Installers)**: ä»»æ„ Linux / macOS / Windows æ–°èŠ‚ç‚¹åªéœ€ä¸€è¡Œå‘½ä»¤ï¼Œè‡ªåŠ¨æå–æœ¬æœº Hostname å®Œæˆå¸¸é©»å®ˆæŠ¤éƒ¨ç½²ã€‚
- ðŸ”„ **30 ç§’è¶…æ—¶å…ç–«æœºåˆ¶ (The Pull & CAS Protocol)**: é€šè¿‡ Supabase Cloud REST API + çŠ¶æ€ CAS é”ï¼Œå½»åº•è§„é¿ Web AI å®¢æˆ·ç«¯ 30 ç§’å¼ºåˆ¶è¶…æ—¶æ–­è¿žã€‚

---

## ðŸ“ æž¶æž„æ‹“æ‰‘ (Architecture Topology)

```text
                  +-----------------------------------+
                  |      ChatGPT / Custom GPTs        |
                  |     / Remote AI Assistants        |
                  +-----------------+-----------------+
                                    |
                                    | HTTPS SSE Remote Connection
                                    v
                     nexus.bings.app (Cloudflare Tunnel)
                                    |
                                    v
                        ThinkCenter (Ubuntu 24.04)
                     Nexus FastMCP Server (SSE Mode)
                                    |
            +-----------------------+-----------------------+
            |                                               |
            v                                               v
   Supabase Cloud (PostgreSQL)                     Local STDIO MCP Server
(devices & commands ç»Ÿä¸€çŠ¶æ€åº“)                  (Victus æœ¬åœ°å¼€å‘/è°ƒè¯•å…¥å£)
            ^
            | (å¿ƒè·³ä¸ŽæŒ‡ä»¤è½®è¯¢)
+-----------+-----------+
|                       |
Victus Agent          N1 / Oracle / VSC Agent
```

---

## ðŸš€ æžé€Ÿä¸€é”®éƒ¨ç½² (One-Liner Installers)

åœ¨ä»»æ„ç‰©ç†æœºå™¨ï¼ˆLinux / macOS / Windows / è½¯è·¯ç”± / HPCï¼‰ä¸Šï¼Œè‡ªåŠ¨è¯†åˆ«ä¸»æœºåå®Œæˆå¸¸é©» Agent éƒ¨ç½²ï¼š

### 1. Linux / macOS / äº‘æœåŠ¡å™¨ / è½¯è·¯ç”± (Bash é›¶å‚æ•°å®‰è£…)
```bash
curl -sSL https://nexus.bings.app/install.sh | bash
```

### 2. Windows å·¥ä½œç«™ (PowerShell é›¶å‚æ•°å®‰è£…)
```powershell
irm https://nexus.bings.app/install.ps1 | iex
```

---

## ðŸ› ï¸ FastMCP å·¥å…·é›† (Exposed MCP Tools)

| å·¥å…·åç§° | åŠŸèƒ½æè¿° | æ ¸å¿ƒå‚æ•° |
| :--- | :--- | :--- |
| **`list_devices`** | èŽ·å–å…¨é›†ç¾¤æ³¨å†Œè®¾å¤‡åˆ—è¡¨ã€åœ¨çº¿çŠ¶æ€ä¸Žæœ€åŽå¿ƒè·³æ—¶é—´ | æ—  |
| **`get_status`** | æŸ¥è¯¢æŒ‡å®šèŠ‚ç‚¹çš„è¯¦ç»†è¿è¡ŒçŠ¶æ€ä¸Žç¡¬ä»¶å¿ƒè·³ | `device_id: str` |
| **`execute_command`** | å®‰å…¨æ´¾å‘ Shell / PowerShell å‘½ä»¤è‡³ç›®æ ‡è®¾å¤‡å¹¶åŒæ­¥èŽ·å–å›žæ‰§ | `device: str`, `command: str`, `wait_seconds: int = 10`, `allow_dangerous: bool = False` |
| **`get_job`** | è½®è¯¢/æŸ¥è¯¢æŒ‡å®š Command ID çš„æ‰§è¡ŒçŠ¶æ€ä¸ŽæŽ§åˆ¶å°è¾“å‡º | `job_id: str` |

---

## ðŸ¤– AI ç½‘é¡µç«¯æŽ¥å…¥æŒ‡å— (System Prompt & Guidance)

è¯¦ç»†çš„ç³»ç»Ÿæç¤ºè¯ä¸Žå…¸åž‹ä½¿ç”¨åœºæ™¯ç¤ºèŒƒè¯·å‚é˜…ï¼š[nexus_system_prompt.md](nexus_system_prompt.md)ã€‚

---

## ðŸ“„ å¼€æºåè®® (License)

æœ¬é¡¹ç›®åŸºäºŽ [MIT License](LICENSE) åè®®å¼€æºã€‚

