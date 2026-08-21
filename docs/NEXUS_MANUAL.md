# Nexus v3 完整使用说明书 (User Manual & Operator Guide)

> **版本**：v3.1.0  
> **核心定位**：基于 Ed25519 密码学与 DevSpace 运行时的分布式多设备集群控制平面与 AI MCP 网关。

---

## 1. 系统总览与架构设计

Nexus 将分布在不同网络（公网 VPS、内网工作站、家用软路由、超算集群等）中的计算设备聚合为一个受统一权限与调度控制的超级集群。

```
                                  ┌────────────────────────┐
                                  │   ChatGPT / Claude /   │
                                  │   AI Agent / 浏览器    │
                                  └───────────┬────────────┘
                                              │ OAuth 2.0 / MCP (JSON-RPC)
                                              ▼
                                 ┌───────────────────────────┐
                                 │   Cloudflare Edge Worker  │
                                 │   (https://nexus.bings.app)
                                 └─────────────┬─────────────┘
                                               │
                        ┌──────────────────────┴──────────────────────┐
                        │ REST API (X-Nexus-Admin-Key / Bearer Auth)  │
                        ▼                                             ▼
          ┌───────────────────────────┐                 ┌───────────────────────────┐
          │     Oracle Global API     │                 │   ThinkCenter Guard /     │
          │   & EU Regional Broker    │                 │   CN Regional Broker      │
          │  (127.0.0.1:18101/18102)  │                 │  (100.86.0.66:18120)    │
          └─────────────┬─────────────┘                 └─────────────┬─────────────┘
                        │                                             │
      ┌─────────────────┼─────────────────┐                           │
      ▼                 ▼                 ▼                           ▼
┌───────────┐     ┌───────────┐     ┌───────────┐               ┌───────────┐
│  oracle   │     │  victus   │     │victus-wsl │               │thinkcenter│
│ (DevSpace)│     │ (DevSpace)│     │ (DevSpace)│               │ (DevSpace)│
└───────────┘     └───────────┘     └───────────┘               └───────────┘
      │                 │
      ▼                 ▼
┌───────────┐     ┌───────────┐
│    vsc    │     │    n1     │
│  (Shell)  │     │(OpenWrt)  │
└───────────┘     └───────────┘
```

### 核心设计守则 (Invariant Contracts)
1. **单一生产路径**：`Client -> MCP/API -> Registry -> Regional Broker -> Target Agent`。
2. **零共享凭证**：每台设备本地生成 Ed25519 私钥，绝不在网络中传递或共享 Fleet Token。
3. **确定性目标寻址**：所有任务与工作区操作必须明确指定 `device_id`，禁止 `all` / `broadcast` 或模糊代换。
4. **单密码统一入口**：通过 Bitwarden 管理的主密码，实现网页看盘与 ChatGPT/Claude OAuth MCP 授权的单点登录。

---

## 2. 网页控制与看板访问

* **访问入口**：`https://nexus.bings.app`
* **认证方式**：输入您的 Nexus 主密码（通过 Bitwarden 保存）。
* **核心功能**：
  * **集群节点大盘**：实时展示所有 6 台基线设备（`oracle`, `thinkcenter`, `victus`, `victus-wsl`, `vsc`, `n1`）的心跳状态、最后活跃时间与运行时能力（DevSpace / Shell）。
  * **Broker 拓扑监控**：监控 EU（Oracle）与 CN（ThinkCenter）双 Broker 的健康状态。
  * **安全退出**：支持一键 `/logout` 清除安全会话 Cookie。

---

## 3. ChatGPT / Claude 网页端配置指南

Nexus 提供了原生 OAuth 2.0 自动握手能力，在 AI 对话框中无需繁琐配置 API Key：

### 快速接入步骤
1. 打开 **ChatGPT** 或 **Claude** 的 **Settings（设置）-> Connectors / Custom MCP**。
2. 添加新的 MCP Server：
   * **Server URL**：`https://nexus.bings.app/mcp`
   * **Authentication Type（认证方式）**：选择 **OAuth**
3. 保存后，系统将自动弹出 Nexus 授权页面（`https://nexus.bings.app/authorize`）。
4. 输入您的 **Nexus 主密码**，点击 **【批准并授权】**。
5. 授权完成后，ChatGPT 会自动加载全部 10 个集群控制工具。

---

## 4. MCP 可用工具清单及使用规范

| 工具名称 | 输入参数 | 核心功能与使用场景 |
| :--- | :--- | :--- |
| **`list_devices`** | `status` (默认 `approved`) | 列出集群内所有在线节点及其运行时类型（`devspace` 或 `shell`）。 |
| **`get_device`** | `device_id` | 获取单个节点的详细元数据与 Ed25519 身份公钥。 |
| **`fleet_status`** | 无 | 快速获取集群节点健康度、在线率与区域 Broker 运行状态。 |
| **`execute_command`** | `device_id`, `command`, `timeout_ms`, `wait_seconds` | 在指定设备上执行单条 Shell 命令（支持长命令与异步结果返回）。 |
| **`execute_batch`** | `jobs` (包含 `device_id` 和 `command` 的数组) | 跨设备并发执行最多 16 个命令任务，并按顺序聚合结果。 |
| **`open_workspace`** | `device_id`, `path`, `mode` (`checkout` \| `worktree`), `base_ref` | 在支持 DevSpace 的设备上打开项目目录或 Git Worktree 隔离工作区，返回 `workspace_id`。 |
| **`read_workspace`** | `device_id`, `workspace_id`, `path`, `offset`, `limit` | 通过 DevSpace 运行时精确读取目标工作区内的文件内容。 |
| **`apply_workspace_patch`** | `device_id`, `workspace_id`, `patch` | 在工作区内应用标准 Unified Diff 代码补丁（原子性修改）。 |
| **`exec_workspace_command`** | `device_id`, `workspace_id`, `command`, `working_directory`, `tty` | 在指定工作区上下文内执行测试、构建或脚本任务。 |
| **`write_workspace_stdin`** | `device_id`, `workspace_id`, `session_id`, `chars` | 与工作区中运行的交互式进程进行 stdin 通信与轮询。 |
| **`get_job`** | `job_id`, `region` (`eu` \| `cn`) | 异步查询已提交的长耗时任务执行状态与结构化回执。 |




---

## 5. 新设备一键加入集群指南 (One-Command Join)

为新设备安装 Nexus Agent 极其简单，支持全自动推断设备 ID 与自动入群。

### 5.1 Linux / macOS / WSL 机器

#### 普通用户模式（推荐，无须 root，写入 `~/.profile` 守护）：
```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/install.sh | sh
```

#### 系统服务模式（作为 root 运行，创建 systemd 服务）：
```bash
sudo curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/install.sh | sudo sh
```

#### 带 Admin Key 自动批准入群：
```bash
NEXUS_V3_ADMIN_KEY="<your-admin-key>" curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/install.sh | sh
```

---

### 5.2 Windows 机器 (PowerShell)

在 PowerShell 中执行（无须管理员权限，自动注册 `HKCU\Run` 静默自启）：
```powershell
irm https://raw.githubusercontent.com/bingStat/nexus/main/install.ps1 | iex
```

带 Admin Key 自动批准入群：
```powershell
$env:NEXUS_V3_ADMIN_KEY="<your-admin-key>"; irm https://raw.githubusercontent.com/bingStat/nexus/main/install.ps1 | iex
```

---

### 5.3 OpenWrt 路由器 (N1 / AX3600)

```bash
# 在路由器终端执行
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/install.sh | sh -s openwrt-agent n1
```

---

### 5.4 安装后配置卡片示例
安装完成后，终端会打印出标准化信息卡片：
```text
================================================================
        Nexus v3 Agent Installed Successfully                  
================================================================
 Device ID:     victus
 Platform:      Windows-11-10.0.26200-SP0
 Install Dir:   C:\Users\Bing\AppData\Local\NexusAgentV3
 Startup:       HKCU Run\NexusV3Agent (user-level, no admin needed)
 Registry:      https://nexus-global-api.bings.app
 Broker:        https://nexus-eu-broker.bings.app
 Cluster State: Approved & Active
 DevSpace:      Enabled (Node: C:\Program Files\nodejs\node.exe)
 Dashboard:     https://nexus.bings.app
 MCP Endpoint:  https://nexus.bings.app/mcp
================================================================
```

---

## 6. 排障与日常运维 Runbook

### 1. 检查各组件健康状态
```bash
# Registry 健康
curl -s https://nexus-global-api.bings.app/v3/health

# EU Broker 健康
curl -s https://nexus-eu-broker.bings.app/v3/health

# 查看全集群在线设备
curl -s -H "X-Nexus-Admin-Key: <admin-key>" "https://nexus-global-api.bings.app/v3/admin/devices?status=approved"
```

### 2. 手动批准待审设备
```bash
python3 scripts/approve_v3_devices.py <device-id>
```

### 3. 本地 MCP 网关重启 (Windows)
```powershell
Stop-Process -Name python -ErrorAction SilentlyContinue
wscript.exe "C:\Users\Bing\AppData\Local\NexusMcpGateway\run-mcp-silent.vbs"
```
