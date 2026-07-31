# Nexus .ai ä¸Šä¸‹æ–‡ä¸Žæž¶æž„ç´¢å¼•

æœ¬ç›®å½•ä¸º Nexus åˆ†å¸ƒå¼é›†ç¾¤æ™ºèƒ½æŽ§åˆ¶ç³»ç»Ÿçš„ä¹å¤§æ ¸å¿ƒæž¶æž„æ–‡æ¡£åº“ï¼Œéµå¾ªæ ‡å‡† AI ä¸Šä¸‹æ–‡è¿žç»­æ€§åè®®ã€‚

---

## æ ¸å¿ƒç›®æ ‡

æž„å»ºé«˜å¯ç”¨ã€é«˜å®‰å…¨æ€§ã€æ”¯æŒ FastMCP ä¸Ž Supabase Cloud åŒæ¨¡é€šä¿¡çš„åˆ†å¸ƒå¼ç¡¬ä»¶é›†ç¾¤æŽ§åˆ¶ä¸­æž¢ï¼Œå®žçŽ°è·¨å¹³å°ï¼ˆLinux / Windows / macOS / OpenWrt / HPCï¼‰çš„è¿œç¨‹è°ƒåº¦ä¸Žæ™ºèƒ½åŒ–äº¤äº’ã€‚

---

## é¡¹ç›®æž¶æž„å›¾

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

## é‡Œç¨‹ç¢‘è§„åˆ’ (Milestones)

- [x] **M1: æ ¸å¿ƒ CAS æž¶æž„ä¸Žå¤šèŠ‚ç‚¹ Agent å»ºç«‹** (å®Œæˆæ—¶é—´: 2026-07-26)
  - Supabase REST è¡¨ç»“æž„å»ºç«‹ (`devices` & `commands`)
  - `agent_v2.py` å¤šçº¿ç¨‹å¹¶å‘ä»»åŠ¡æŠ“å–ä¸Žå¿ƒè·³å›žä¼ 
- [x] **M2: Nexus å“ç‰Œé‡å‘½åä¸Žå…¨åº“è§„èŒƒåŒ–** (å®Œæˆæ—¶é—´: 2026-07-30)
  - å½»åº•æ¸…é™¤ `desktop-commander` é—ç•™åç§°ï¼Œç»Ÿä¸€ä¸º Nexus
  - é›¶å‚æ•°ä¸€é”®å®‰è£…è„šæœ¬ä½“ç³» (`install.sh` & `install.ps1`)
- [x] **M3: FastMCP Server åŒæ¨¡æž¶æž„ä¸Žé«˜å±é˜²çˆ†å±‚** (å®Œæˆæ—¶é—´: 2026-07-30)
  - FastMCP Tools (`list_devices`, `get_status`, `execute_command`, `get_job`)
  - æŽ¥å…¥ `nexus.bings.app/sse` å…¨å¤©å€™è¿œç¨‹è®¿é—®ä¸Ž Bearer é‰´æƒ
  - ç»Ÿä¸€ SSH å¯†é’¥è‡³ `C:/Users/Bing/.ssh/victus`

