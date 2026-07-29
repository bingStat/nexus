# 🌐 Nexus: Multi-Node Distributed Cluster Agent & FastMCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/Protocol-Model_Context_Protocol_(MCP)-green.svg)](https://modelcontextprotocol.io/)
[![Cloudflare Tunnel](https://img.shields.io/badge/Transport-Cloudflare_Tunnel-orange.svg)](https://nexus.bings.app)

**Nexus** 是一套高性能、低延迟的**跨端分布式硬件集群智能控制中枢**。系统打破了传统局域网限制与 30 秒 HTTP 超时壁垒，实现了对 Linux 服务器（ThinkCenter / Oracle）、Windows 主力工作站（Victus）、KU Leuven HPC 超算集群（VSC）以及 OpenWrt 软路由（N1）的统一调度与全天候远程操控。

---

## 🌟 核心特性 (Key Features)

- ⚡ **双传输模式 (Dual Transport)**: 
  - **STDIO 模式**: 供 Cursor / Antigravity / Claude Desktop 本地直接高并发调用。
  - **HTTP / SSE 模式**: 基于 FastAPI/Uvicorn 暴露 `/sse` 节点，挂载于 `https://nexus.bings.app/sse`，供网页版 ChatGPT / Gemini / Claude 全天候无缝连接。
- 🛡️ **高危指令防爆拦截器 (Security Interceptor)**: 内置对 `rm -rf`, `shutdown`, `reboot`, `format`, `del /s /q`, `iptables` 等毁灭性指令的正则拦截逻辑，强制二次安全确认。
- 🚀 **零参数一键安装 (One-Liner Installers)**: 任意 Linux / macOS / Windows 新节点只需一行命令，自动提取本机 Hostname 完成常驻守护部署。
- 🔄 **30 秒超时免疫机制 (The Pull & CAS Protocol)**: 通过 Supabase Cloud REST API + 状态 CAS 锁，彻底规避 Web AI 客户端 30 秒强制超时断连。

---

## 📐 架构拓扑 (Architecture Topology)

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

## 🚀 极速一键部署 (One-Liner Installers)

在任意物理机器（Linux / macOS / Windows / 软路由 / HPC）上，自动识别主机名完成常驻 Agent 部署：

### 1. Linux / macOS / 云服务器 / 软路由 (Bash 零参数安装)
```bash
curl -sSL https://nexus.bings.app/install.sh | bash
```

### 2. Windows 工作站 (PowerShell 零参数安装)
```powershell
irm https://nexus.bings.app/install.ps1 | iex
```

---

## 🛠️ FastMCP 工具集 (Exposed MCP Tools)

| 工具名称 | 功能描述 | 核心参数 |
| :--- | :--- | :--- |
| **`list_devices`** | 获取全集群注册设备列表、在线状态与最后心跳时间 | 无 |
| **`get_status`** | 查询指定节点的详细运行状态与硬件心跳 | `device_id: str` |
| **`execute_command`** | 安全派发 Shell / PowerShell 命令至目标设备并同步获取回执 | `device: str`, `command: str`, `wait_seconds: int = 10`, `allow_dangerous: bool = False` |
| **`get_job`** | 轮询/查询指定 Command ID 的执行状态与控制台输出 | `job_id: str` |

---

## 🤖 AI 网页端接入指南 (System Prompt & Guidance)

详细的系统提示词与典型使用场景示范请参阅：[nexus_system_prompt.md](nexus_system_prompt.md)。

---

## 📄 开源协议 (License)

本项目基于 [MIT License](LICENSE) 协议开源。
