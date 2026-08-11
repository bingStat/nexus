# Nexus v3 clean architecture

Nexus v3 的唯一生产链路：

```text
Client -> Remote API / MCP -> Registry -> Regional Broker -> exact target Agent
```

核心约束：

- Agent 不保存集群 API token，只保存本机 Ed25519 私钥。
- Registry 只负责身份、审批和 SSH 公钥目录；运行时在线状态由区域 Broker presence 提供。
- EU/CN Broker 负责任务队列、idempotency、lease 与回执。
- Broker 或网络故障切换不得改变 `target_device`。
- 设备离线、未批准或 runtime 不可用时直接失败，不允许由另一台机器代执行。

## 组件

| 组件 | 生产位置 | 本机监听 | 权威存储 |
|---|---|---:|---|
| Registry | Oracle | `127.0.0.1:18101` | `/var/lib/nexus-v3/registry.db` |
| EU Broker | Oracle | `127.0.0.1:18102` | `/var/lib/nexus-v3/eu-broker.db` |
| CN Broker | ThinkCenter | `127.0.0.1:18120` | `/var/lib/nexus-v3/broker.db` |
| Linux Agent | Linux/VSC | systemd or user process | v3 config + local execution ledger |
| Windows Agent | Victus/Windows | Scheduled Task | `%LOCALAPPDATA%\NexusAgentV3` |
| OpenWrt Agent | N1/AX3600 | procd | `/etc/nexus-agent/v3.env` |
| Remote API/MCP | Oracle | `18131` / `18130` | no task database |
| Ops | Oracle | systemd timers | `/var/lib/nexus/ops/` |

## Device identity

Linux/OpenWrt:

```text
/etc/nexus-agent/identity_ed25519
/etc/nexus-agent/identity_ed25519.pub
```

Windows:

```text
%LOCALAPPDATA%\NexusAgentV3\identity_ed25519
%LOCALAPPDATA%\NexusAgentV3\identity_ed25519.pub
```

注册使用 Ed25519 proof；后续 Agent claim、complete 使用带 timestamp 与 nonce 的签名请求。Broker 拒绝签名重放；正常 claim long-poll 同时更新设备 presence。

Registry 公开 approved 设备 SSH 公钥集合。SSH key 同步是显式操作，不使用周期 cron/timer：

```bash
sudo ./install.sh sync-cluster-ssh
```

## Broker reliability

每个 job 有稳定 ID 与 idempotency key。Broker 为 running job 设置 lease；Agent 消失后 lease 过期，任务可以安全回到 pending。Agent 本地 execution ledger 记录终态结果，因此“命令已经执行但回执丢失”的 job 再次出现时只重放结果，不再次执行副作用。

## DevSpace

有 Node >= 22.19 的设备可以启用 upstream DevSpace runtime。Nexus 只负责路由与身份，workspace/worktree、read、patch、process session 语义由 DevSpace 提供。Remote API 在提交 workspace 操作前检查目标是否声明 `runtime=devspace`。

## API

Registry：`/v3/health`, `/v3/devices/register`, `/v3/devices/{id}/public-key`, `/v3/ssh/authorized-keys`, `/v3/admin/devices*`。

Broker：`/v3/health`, `POST /v3/jobs`, `GET /v3/jobs`, `/v3/jobs/claim`, `/v3/jobs/complete`。

Remote API：`/api/status`, `/api/devices`, `/api/commands`, `/api/commands/batch`, `/api/runtime`, `/api/jobs/{region}/{job_id}`。

## Install

Linux：

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/install.sh | sudo sh -s -- agent thinkcenter
```

OpenWrt：

```sh
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/install.sh | sh -s -- openwrt-agent n1
```

Windows 使用根目录 `install.ps1`。生产代码只从 GitHub `main` 获取；不保留 release/v2/compatibility download path。
