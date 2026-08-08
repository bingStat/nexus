# Nexus v3 远程控制

Nexus 是一个个人设备集群远程控制面。当前 v3 架构模仿 DesktopCommanderMCP 的 Remote MCP 思路：ChatGPT 或 MCP 客户端不直接连接任何设备，而是访问本地 Nexus Remote Gateway；Gateway 把任务提交到区域 Broker；已批准的 Agent 只领取属于自己的任务，并用 Nexus 专用 Ed25519 身份签名注册、领取和回执。

## 当前架构

```text
ChatGPT / MCP 客户端
  -> Nexus ChatGPT Remote API 或 MCP Adapter
  -> Registry
  -> EU / CN Broker
  -> 已批准目标 Agent
```

鉴权不再依赖“每台机器一个 API token”。每台设备生成一套 Nexus device Ed25519 keypair：公钥就是设备的 API key / device identity，同时也是该设备加入 SSH 互信网络的公钥；服务器只保存公钥和审批状态。Agent 每次注册、领取任务、提交完成回执时都用私钥签名。

## 规范设备 ID

EU 区域：

- `oracle`
- `vsc`
- `victus`
- `victus-wsl`
- `elitebook`

CN 区域：

- `thinkcenter`
- `n1`
- `ax3600`

`n1` 和 `ax3600` 能运行 OpenWrt Agent 时自行领取任务；如果目标尚未注册或未批准，Remote Gateway 可以按 `NEXUS_V3_MANAGED_TARGETS` 通过 ThinkCenter 的显式 SSH fallback 指挥它们。

## 唯一安装脚本

对外只保留一个安装脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sudo sh -s -- <mode>
```

本地开发可直接运行仓库里的同一个脚本：

```bash
sudo ./install.sh <mode>
```

支持模式：

- `registry`
- `broker eu`
- `broker cn`
- `agent <规范设备 ID>`
- `<规范设备 ID>`
- `openwrt-agent <规范设备 ID>`
- `remote`
- `managed-targets`
- `sync-ssh-keys`
- `sync-cluster-ssh`

示例：

```bash
sudo ./install.sh registry
sudo NEXUS_V3_REGION=cn NEXUS_V3_BIND=0.0.0.0 ./install.sh broker cn
sudo ./install.sh thinkcenter
sudo ./install.sh remote
```

OpenWrt：

```sh
sh install.sh n1
sh install.sh ax3600
```

## 新设备加入集群

任意新设备加入 Nexus 时，只需要运行同一个安装脚本。安装器会自动完成：

1. 生成一套 Nexus device Ed25519 keypair。公钥就是 API key，同时作为 SSH 公钥加入机器互信网络；私钥既用于 API 请求签名，也用于 SSH 登录。

   | 用途 | 私钥 | 公钥 |
   |---|---|---|
   | API 签名 + SSH 互信 | `/etc/nexus-agent/identity_ed25519` | `/etc/nexus-agent/identity_ed25519.pub` |

2. 把 `device_id + public_key + hostname + platform` 注册到 Registry。
3. 设备被批准后，从 Registry 拉取所有 approved 设备的 SSH 公钥，并同步到各终端 `authorized_keys` 的 Nexus 管理区块。

Linux/systemd 新设备：

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sudo sh -s -- <规范设备 ID>
```

示例：

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sudo sh -s -- elitebook
```

OpenWrt/iStoreOS 新设备：

```sh
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sh -s -- <规范设备 ID>
```

示例：

```sh
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sh -s -- n1
```

新设备首次注册后状态是 `pending`。在拥有 `NEXUS_V3_ADMIN_KEY` 的控制机上，用仓库本地脚本批准：

```bash
sudo python3 scripts/approve_v3_devices.py <规范设备 ID>
```

如果 Registry 不在本机，显式指定 Registry 地址：

```bash
sudo env NEXUS_V3_REGISTRY_URL=https://nexus-global-api.bings.app \
  python3 scripts/approve_v3_devices.py <规范设备 ID>
```

批准后，从任意已能 SSH 到其它节点的控制机触发全体 SSH 公钥同步：

```bash
NEXUS_V3_REGISTRY_URL=https://nexus-global-api.bings.app \
NEXUS_CLUSTER_SSH_HOSTS='oracle_amd root@100.103.12.14 root@100.90.67.12' \
sudo ./install.sh sync-cluster-ssh
```

`NEXUS_CLUSTER_SSH_HOSTS` 写“当前这台控制机能 SSH 到的全体终端”。默认值覆盖 Oracle、ThinkCenter 和 N1；如果新增了其它可达终端，把它们追加进去即可。同步脚本不会改写用户自己的 SSH key，只会替换：

```text
### BEGIN NEXUS MANAGED SSH KEYS
...
### END NEXUS MANAGED SSH KEYS
```

这样每加入一台新设备，Registry 中的 approved SSH 公钥集合都会增长一次；同步后，所有可达终端都会信任这台新设备的 Nexus SSH 公钥，同时新设备也会信任已有设备的 Nexus SSH 公钥。

## SSH 信任同步

每台设备只有一套 Nexus device key：

- 私钥：`/etc/nexus-agent/identity_ed25519`
- 公钥：`/etc/nexus-agent/identity_ed25519.pub`

这个公钥就是设备 API key，同时登记为 SSH public key。Registry 通过 `/v3/ssh/authorized-keys` 暴露所有已批准设备的公钥。

安装器会安装本地一次性同步脚本，只重写 `authorized_keys` 中 Nexus 管理的区块。SSH 公钥同步不使用 cron/timer；新设备安装或批准后，执行：

```bash
sudo ./install.sh sync-cluster-ssh
```

Agent 安装完成时也会 best-effort 触发一次集群 SSH 公钥刷新。

## ChatGPT Action

ChatGPT 侧使用以下两个文件：

- `agent-council/integrations/nexus-v3-chatgpt-remote-prompt.md`
- `agent-council/integrations/nexus-v3-remote-control-openapi.json`

当前 ChatGPT Action 使用：

```text
https://nexus-global-api.bings.app
```

该域名保留 `/v3/*` 给 Registry，同时把 `/health`、`/openapi.json`、`/api/*` 转发给 `nexus-chatgpt-remote`。不要把 dashboard 地址 `https://nexus.bings.app/` 当成 Action API 地址。

本地 Remote 服务也会动态提供 OpenAPI：

```text
http://127.0.0.1:18131/openapi.json
```

Action 鉴权使用 Bearer token，对应环境变量 `NEXUS_CHATGPT_API_KEY`，配置文件位于：

```text
/etc/nexus-chatgpt-remote.env
```

不要把 token、私钥、cookie 或浏览器会话内容写入仓库、提示词或聊天记录。

## 运行时文件

- Registry 数据库：`/var/lib/nexus-v3/registry.db`
- Broker 数据库：`/var/lib/nexus-v3/broker.db`
- Linux Agent 配置：`/etc/nexus-agent/v3.json`
- OpenWrt Agent 配置：`/etc/nexus-agent/v3.env`
- 设备 API 私钥：`/etc/nexus-agent/identity_ed25519`
- 设备 API 公钥：`/etc/nexus-agent/identity_ed25519.pub`
- Nexus SSH 身份：复用 `identity_ed25519` / `identity_ed25519.pub`
- ChatGPT Remote 环境：`/etc/nexus-chatgpt-remote.env`

## 源码结构

- `install.sh`：唯一用户入口安装脚本。
- `nexus_v3/`：Registry、Broker、Agent、MCP Adapter、ChatGPT Action Bridge、OpenWrt 运行时资产和共享远控逻辑。
- `nexus_v3/assets/openwrt_v3_agent.sh`：OpenWrt Agent 运行时资产，由 `install.sh` 自动安装。
- `nexus_v3/assets/openwrt_ed25519_signer.rb`：OpenWrt Ed25519 签名 fallback，由 `install.sh` 自动安装。
- `agent-council/`：保留的 Council 机制。
- `agent-council/integrations/`：ChatGPT 提示词与 Action OpenAPI；不再单独保留 README，入口说明集中在本文件。
- `dashboard/`：`https://nexus.bings.app/` 的 Cloudflare Worker + R2 可视化页面源码。
- `scripts/`：设备批准与验证辅助脚本；不是安装入口。
- `tests/`：契约测试。
- `其他目标.md`：已退役设计、非主线目标和后续可选方向摘要。
