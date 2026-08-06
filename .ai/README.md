# Nexus .ai 上下文与架构索引

本目录为 Nexus 分布式集群智能控制系统的九大核心架构文档库，遵循标准 AI 上下文连续性协议。

---

## 核心目标

构建高可用、高安全性、支持 FastMCP 与 Supabase Cloud 双模通信的分布式硬件集群控制中枢，实现跨平台（Linux / Windows / macOS / OpenWrt / HPC）的远程调度与智能化交互。

---

## 项目架构图

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
(devices & commands 统一状态库)                  (Victus 本地开发/调试入口)
            ^
            | (心跳与指令轮询)
+-----------+-----------+
|                       |
Victus Agent          N1 / Oracle / VSC Agent
```

---

## 里程碑规划 (Milestones)

- [x] **M1: 核心 CAS 架构与多节点 Agent 建立** (完成时间: 2026-07-26)
  - Supabase REST 表结构建立 (`devices` & `commands`)
  - `agent_v2.py` 多线程并发任务抓取与心跳回传
- [x] **M2: Nexus 品牌重命名与全库规范化** (完成时间: 2026-07-30)
  - 彻底清除 `desktop-commander` 遗留名称，统一为 Nexus
  - 零参数一键安装脚本体系 (`install.sh` & `install.ps1`)
- [x] **M3: FastMCP Server 双模架构与高危防爆层** (完成时间: 2026-07-30)
  - FastMCP Tools (`list_devices`, `get_status`, `execute_command`, `get_job`)
  - 接入 `nexus.bings.app/sse` 全天候远程访问与 Bearer 鉴权
  - 统一 SSH 密钥至 `C:/Users/Bing/.ssh/victus`

---

## 2026-08-06 最终生产基线

> 本节是当前权威架构；上方早期架构图仅作为历史演进记录。

```text
ChatGPT / Control Client
        │
        ▼
https://nexus-api.bings.app
Oracle Global API 2.1.4
   ┌────┴────┐
   ▼         ▼
EU Broker    CN Broker
Oracle       ThinkCenter
   │         │
   ├─ oracle ├─ thinkcenter
   ├─ vsc    ├─ n1
   ├─ victus └─ ax3600 (managed target)
   └─ victus-wsl
```

浏览器顾问主链路：

```text
ChatGPT → Nexus → victus-wsl → Windows Playwright MCP
→ Chrome Profile 3 Playwright Extension → Claude / Gemini
```

最终原则：Agent 在线时直接向规范 `target_device` 下发；Broker 只能改变传输路径，不得改派目标。Supabase 只承担设备目录、心跳与审计镜像，不作为正常热队列。

### 结项状态

- 软件与服务级结项：**GO**；
- Release commit：`297d3db`；
- Release tag：`nexus-v2.5-final-20260806`；
- 完整报告：[`结项报告-2026-08-06.md`](./结项报告-2026-08-06.md)；
- 唯一维护期验证项：Victus Windows 整机重启演练。
