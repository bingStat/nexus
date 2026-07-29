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
