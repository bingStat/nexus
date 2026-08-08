# Nexus v3 架构与安装

Nexus 是个人设备集群远程控制面。ChatGPT 不直接 SSH 到设备，而是调用 Nexus Remote API；任务进入区域 Broker 后，由已批准 Agent 自行领取并用本机 `identity_ed25519` 签名回执。

```text
ChatGPT / MCP -> Nexus Remote API -> Registry -> EU/CN Broker -> Agent
```

ChatGPT 导入提示词和 Action JSON 单独放在 [NEXUS_CHATGPT_PROMPT.md](NEXUS_CHATGPT_PROMPT.md)。

## 当前节点

| 设备 ID | 区域 | 状态 | 说明 |
|---|---:|---|---|
| `oracle` | EU | 已部署 | Registry、EU Broker、ChatGPT Remote、MCP；有 admin key 与 ChatGPT bearer token |
| `thinkcenter` | CN | 已部署 | CN Broker、Agent；有 admin key |
| `n1` | CN | 已部署 | OpenWrt/iStoreOS Agent，自行领取任务 |
| `vsc` | EU | 已部署 | HPC 用户态 Agent；入站 SSH 受 VSC/HPC 策略限制 |
| `victus` | EU | 已部署 | Windows Agent，计划任务运行 |
| `victus-wsl` | EU | 已部署 | WSL Agent |
| `elitebook` | EU | 预留 | 新设备 ID |
| `ax3600` | CN | 预留 | OpenWrt；可自领任务，必要时 ThinkCenter 指挥 |

## 设备身份

每个节点只保留一套 Nexus 身份。私钥本地保存，Agent 自动用它签名；公钥登记为 API identity，同时进入 SSH 互信网络。

```text
/etc/nexus-agent/identity_ed25519      # 私钥：API 签名 + SSH 登录
/etc/nexus-agent/identity_ed25519.pub  # 公钥：设备 API key + SSH public key
```

Windows Victus 路径：

```text
C:\Users\Bing\AppData\Local\NexusAgentV3\identity_ed25519
C:\Users\Bing\AppData\Local\NexusAgentV3\identity_ed25519.pub
```

## 一键安装

Linux/systemd：

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sudo sh -s -- <设备ID>
```

OpenWrt/iStoreOS：

```sh
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sh -s -- <设备ID>
```

常用示例：

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sudo sh -s -- elitebook
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sh -s -- n1

sudo ./install.sh registry
sudo ./install.sh broker eu
sudo ./install.sh broker cn
sudo ./install.sh remote
sudo ./install.sh thinkcenter
```

## 批准新设备

新设备首次注册为 `pending`。当前有 admin key 的机器：

- `oracle`：`/etc/nexus-v3.env` 内有 `NEXUS_V3_ADMIN_KEY`
- `thinkcenter`：`/etc/nexus-v3.env` 内有 `NEXUS_V3_ADMIN_KEY`

批准命令：

```bash
sudo env NEXUS_V3_REGISTRY_URL=https://nexus-global-api.bings.app \
  python3 scripts/approve_v3_devices.py <设备ID>
```

批准后同步 SSH 公钥。SSH 同步不使用 cron；只在安装/批准新机器后触发一次：

```bash
NEXUS_V3_REGISTRY_URL=https://nexus-global-api.bings.app \
NEXUS_CLUSTER_SSH_HOSTS='oracle_amd root@100.103.12.14 root@100.90.67.12' \
sudo ./install.sh sync-cluster-ssh
```

同步脚本只替换 `authorized_keys` 中这个区块，不改用户自己的 key：

```text
### BEGIN NEXUS MANAGED SSH KEYS
...
### END NEXUS MANAGED SSH KEYS
```

OpenWrt/Dropbear 写入 `/etc/dropbear/authorized_keys`；Linux root 写入 `/root/.ssh/authorized_keys`；VSC/Windows 用户路径需按该用户环境同步。

## 运行时位置

| 项 | 路径 |
|---|---|
| Registry DB | `/var/lib/nexus-v3/registry.db` |
| Broker DB | `/var/lib/nexus-v3/broker.db` |
| Linux Agent 配置 | `/etc/nexus-agent/v3.json` |
| OpenWrt Agent 配置 | `/etc/nexus-agent/v3.env` |
| ChatGPT Remote 环境 | `/etc/nexus-chatgpt-remote.env` |
| 设备批准脚本 | `scripts/approve_v3_devices.py` |
| 验证脚本 | `scripts/verify_v3.py` |
| 机器可读 Action 文件 | `agent-council/integrations/` |

## Nexus 控制配置（原 `nexus.json`）

```json
{
  "version": 1,
  "alias": "nexus",
  "default_node": "victus",
  "council_mode": "web-hybrid",
  "risk_policy": "auto_worktree_only",
  "verification": [
    "python -m unittest discover -s agent-council/tests -v",
    "python -m py_compile agent-council/council.py agent-council/web_council.py agent-council/web_board.py"
  ],
  "approval_required": [
    "merge",
    "push",
    "deploy",
    "main_branch_mutation",
    "credential_change"
  ]
}
```

## 保留原则

- 根目录文档只保留 `README.md` 和 `NEXUS_CHATGPT_PROMPT.md`。
- `install.sh` 是唯一安装入口。
- `agent-council/` 保留 Council 机制。
- `agent-council/integrations/` 保留机器可读副本，供测试和安装器使用。
- 旧 Supabase、旧 webhook、旧 browser bridge、旧多脚本安装方案不再作为当前事实来源。
