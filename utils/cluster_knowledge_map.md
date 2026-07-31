# Bing Yang ä¸ªäººä¸Žå¼€å‘é›†ç¾¤å…¨å±€æ™ºåŠ›å›¾è°± (Global Knowledge Map)

æœ¬æ–‡æ¡£ä¸º Custom GPT çš„åº•å±‚æ ¸å¿ƒçŸ¥è¯†åº“ï¼Œä¸“é—¨è¡¥å……ç‰¹å®šäºŽç”¨æˆ· Bing Yang çš„ç§æœ‰ä¸Šä¸‹æ–‡ã€åŸºç¡€è®¾æ–½åå½•ã€å­¦æœ¯ç ”å‘è¦æ±‚åŠåå¥½ã€‚

---

## 1. ä¸ªäººä¸Žå­¦æœ¯èƒŒæ™¯ (Academic & Profile)
- **èº«ä»½**ï¼šBing Yangï¼ŒKU Leuven æ•°å­¦ç³» Statistics & Data Science åšå£«ç”Ÿï¼ˆå¯¼å¸ˆï¼šProf. Stefan Van Aelstï¼›åˆä½œè€…ï¼šTim Verdonckï¼‰ã€‚
- **å­¦æœ¯åå¥½**ï¼šè¦æ±‚é«˜åº¦å¯å¤çŽ°æ€§ã€æ–‡ä»¶ç»“æž„æ¸…æ™°ã€ä¸¥æ ¼å¯¹åº”å®žéªŒä¸Žæ­£æ–‡ã€‚å›¾è¡¨ç¬¦åˆ Management Science / EJOR / Operations Research é¡¶åˆŠæŽ’ç‰ˆæ ‡å‡†ã€‚
- **ä¸»è¦é¡¹ç›®**ï¼š
  1. **Polaris**ï¼šSparse Prescription Learning (*Management Science* å‡†å¤‡ä¸­)ï¼Œä»£ç ä½äºŽ `bingStat/polaris`ã€‚
  2. **ECSLR**ï¼šDiverse Ensemble Cost-sensitive Logistic Regression (å·²å‘è¡¨äºŽ *EJOR*)ã€‚
  3. **tsproxy**ï¼šTailscale å¤šç›®æ ‡å®¹é”™ä»£ç†ç»„ä»¶ (`/home/bing/projects/family-disc-direct/tsproxy`)ã€‚
  4. **autoMedia & Portal**ï¼šå®¶åº­å½±éŸ³ä¸Žä»»åŠ¡è‡ªåŠ¨åŒ–ç³»ç»Ÿ (`https://portal.bings.app`)ã€‚

---

## 2. åŸºç¡€è®¾æ–½ä¸Žè®¾å¤‡å  å½• (Infrastructure Topology)

| èŠ‚ç‚¹å  ç§° (target_device) | ç¡¬ä»¶/çŽ¯å¢ƒç±»åž‹ | å…¸åž‹è·¯å¾„ä¸Žå…³é”®å·¥å…·é“¾ | æ ¸å¿ƒç”¨é€” |
| :--- | :--- | :--- | :--- |
| **`thinkcenter`** (é»˜è®¤ä¸»èŠ‚ç‚¹) | Ubuntu 24.04 æœ åŠ¡å™¨ | `/home/bing/nexus-backend/`, `/home/bing/tools/go-1.26.3/bin/go` | Nexus ä¸­æž¢ (`nexus.bings.app`), Docker, PostgREST, Jellyfin |
| **`victus`** | Windows 11 ä¸»åŠ›ç”µè„‘ (Victus, i7-12700, 64G RAM) | `C:\Users\Bing\` (PowerShell, Python 3.11) | æœ¬åœ° IDE å¼€å ‘ã€ æ–‡ä»¶å¤„ç †ä¸Žæœ¬åœ°æŽ§åˆ¶ |
| **`VSC`** | KU Leuven HPC è¶…ç®—é›†ç¾¤ | `/vsc-hard-mounts/leuven-data/356/vsc35603/polaris` | Polaris æ¨¡æ‹Ÿå®žéªŒã€ doMPI/foreach å¤§è§„æ¨¡è®¡ç®— (192GB RAM, 36æ ¸) |
| **`M720q`** | Ubuntu 24.04 (ä¸­å›½æ·®åŒ—) | æœ¬åœ°ç£ ç›˜å­˜å‚¨è·¯å¾„ | æ•°æ ®çš„æœ€ç»ˆæœ¬åœ°ç¦»çº¿å­˜å‚¨èŠ‚ç‚¹ |
| **`oracle`** | Oracle Cloud VPS | Tailscale èŠ‚ç‚¹ | äº‘ç«¯ä¸­ç»§ä¸Žè¿žæŽ¥å  è°ƒ |
| **`openwrt`** / `N1` | iStoreOS è½¯è·¯ç”± (`100.90.67.12`) | `/bin/sh`, SSH `root@100.90.67.12` | æ— è·¯ç”±ä¸Žå±€åŸŸç½‘é€šé “ |

---

## 3. æž é€Ÿä¸€é”®éƒ¨ç½²å‘½ä»¤è§„èŒƒ (One-Liner Installers)

å½“éœ€è¦ å°†ä»»æ„æ–°ç‰©ç †èŠ‚ç‚¹ï¼ˆå¦‚ `vsc` / `macbook`ï¼‰åŠ å…¥é›†ç¾¤æ—¶ï¼ŒæŒ‡ä»¤å¦‚ä¸‹ï¼š

- **å®˜æ–¹ GitHub ä»“åº“å®‰è£…**ï¼š
  ```bash
- **è®ºæ–‡æŽ’ç‰ˆ**ï¼šä½¿ç”¨ R / ggplot2 ç”Ÿæˆ PDF çŸ¢é‡å›¾ï¼Œç»Ÿä¸€ Panel ç•™ç™½ä¸Ž Caption è¯´æ˜Žã€‚
- **å®‰å…¨çº¢çº¿**ï¼šç»ä¸æ‰§è¡Œå¯èƒ½å¯¼è‡´ Tailscale / Cloudflare Tunnel / SSH æ–­è¿žçš„æ›´æ”¹ã€‚

