# Nexus FastMCP Server

标准化 Model Context Protocol (MCP) 服务模块，用于远程控制与统一调度 Nexus 桌面与服务器集群（ThinkCenter, Victus, Oracle, VSC, N1 等）。

---

## 核心工具 (Exposed MCP Tools)

| 工具名称 | 功能描述 | 核心参数 |
| :--- | :--- | :--- |
| **`list_devices`** | 获取全集群注册设备列表与在线状态 | 无 |
| **`get_status`** | 查询特定设备的详细心跳与信息 | `device_id: str` |
| **`execute_command`** | 安全派发 Shell 命令至目标设备 | `device: str`, `command: str`, `wait_seconds: int = 10`, `allow_dangerous: bool = False` |
| **`get_job`** | 轮询/查询指定 Command ID 的执行状态与输出 | `job_id: str` |

---

## 本地 STDIO 模式配置 (Cursor / Claude Desktop / Antigravity)

在本地 AI 客户端配置文件（如 `claude_desktop_config.json` 或 `mcpServers` 设置）中加入：

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

## 远程 SSE / HTTP 模式配置 (nexus.bings.app)

在 ThinkCenter (Ubuntu) 服务器上通过 Cloudflare Tunnel / Nginx 暴露全天候 SSE 服务：

### 1. 部署到 ThinkCenter

```bash
cd /home/bing/nexus-backend
pip install mcp fastapi uvicorn requests

# 启动 SSE 服务
python3 -m mcp_server.app
```

### 2. Systemd 守护进程

复制 `mcp_server/systemd/nexus-mcp.service` 到 `/etc/systemd/system/`：

```bash
sudo cp mcp_server/systemd/nexus-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nexus-mcp
```

### 3. Cloudflare Tunnel 路径绑定

在 Cloudflare Tunnel 配置中，将 `nexus.bings.app/sse` 或 `/mcp` 路由到 `http://localhost:8000`。

ChatGPT 或远程 Custom GPTs 可直接配置 MCP Endpoint URL：
`https://nexus.bings.app/sse`

---

## 安全防爆说明 (Security Interceptor)

`mcp_server/security.py` 内置高危指令防爆拦截逻辑。针对以下类型命令：
- `rm -rf /`
- `del /s /q`
- `shutdown` / `reboot`
- `mkfs` / `format`
- `iptables -F`

直接调用 `execute_command` 将被拒绝。如确认需执行高危指令，必须显式传递 `allow_dangerous=True` 参数。
