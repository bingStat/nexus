# Nexus v3 clean architecture

目标：停止在旧 Global API/Broker 上继续打补丁，部署一套职责清晰、可并行验证、可回滚的新链路。Agent 不保存 API token；设备只保存 Nexus 专用 Ed25519 私钥。

## 组件

| 组件 | 生产位置 | 本机监听 | 外部入口 | 权威存储 |
|---|---|---:|---|---|
| Registry | Oracle | `127.0.0.1:18101` | `https://nexus-global-api.bings.app/v3` | `/var/lib/nexus-v3/registry.db` |
| EU Broker | Oracle | `127.0.0.1:18102` | `https://nexus-global-api.bings.app/v3/eu-broker`（可选） | `/var/lib/nexus-v3/eu-broker.db` |
| CN Broker | ThinkCenter | `127.0.0.1:18120` | `https://nexus-broker.bings.app/v3` 或 LAN `http://100.103.12.14:18120/v3` | `/var/lib/nexus-v3/broker.db` |
| Linux Agent | 每台 Linux 机器 | systemd `nexus-v3-agent.service` | outbound only | `/etc/nexus-agent/v3.json` |
| OpenWrt Agent | N1/iStoreOS/AX3600 if capable | procd `nexus-v3-agent` | outbound only | `/etc/nexus-agent/v3.env` |
| Managed target fallback | ThinkCenter | SSH client | LAN only | `/etc/nexus-managed-targets/targets.env` |

## 设备本机身份存储

| 平台 | 私钥 | 公钥 | v3 配置 |
|---|---|---|---|
| Linux/systemd | `/etc/nexus-agent/identity_ed25519` | `/etc/nexus-agent/identity_ed25519.pub` | `/etc/nexus-agent/v3.json` |
| OpenWrt/procd | `/etc/nexus-agent/identity_ed25519` | `/etc/nexus-agent/identity_ed25519.pub` | `/etc/nexus-agent/v3.env` |
| Windows/Scheduled Task | `C:\ProgramData\NexusAgent\identity_ed25519` | `C:\ProgramData\NexusAgent\identity_ed25519.pub` | `C:\ProgramData\NexusAgent\v3.json` |

OpenWrt 的仓库内运行时资产位于 `nexus_v3/assets/`；安装后 Ed25519 fallback signer 存储在 `/opt/nexus-agent/openwrt_ed25519_signer.rb`。它只做本机私钥签名，不保存 token。

## SSH 公钥增长

Nexus API identity 和 SSH identity 分离。每台机器额外生成 `/etc/nexus-agent/ssh_ed25519` 和 `/etc/nexus-agent/ssh_ed25519.pub`，注册时只把 SSH 公钥交给 Registry。Registry 通过 `GET /v3/ssh/authorized-keys` 发布 approved 设备的 SSH 公钥列表。

各设备安装 `/opt/nexus-agent/sync_ssh_authorized_keys.sh`，但不使用 cron 或 systemd timer。新机器安装或审批后，运行一次 `install.sh sync-cluster-ssh`，由当前控制节点调动集群内可达设备同步 `authorized_keys` 的 Nexus 管理区块。

## v3 API

### Registry

- `GET /v3/health`
- `POST /v3/devices/register`
- `GET /v3/devices/{device_id}/public-key`
- `GET /v3/ssh/authorized-keys`
- `GET /v3/admin/devices?status=pending`
- `POST /v3/admin/devices/{device_id}/approve`
- `POST /v3/admin/devices/{device_id}/reject`
- `POST /v3/admin/devices/{device_id}/revoke`

### Broker

- `GET /v3/health`
- `POST /v3/jobs`，管理员提交任务
- `GET /v3/jobs?id={job_id}`，管理员查询任务
- `GET /v3/jobs/claim?device_id={device_id}&agent_id={agent_id}&wait=20`，Agent 签名领取
- `POST /v3/jobs/complete`，Agent 签名回执

## 签名协议

注册 proof：

```text
NEXUS-V3-REGISTER
sha256(canonical_json_without_proof)
```

请求签名：

```text
NEXUS-V3-ED25519
METHOD
PATH_AND_QUERY
X-Nexus-Timestamp
X-Nexus-Nonce
X-Nexus-Device
sha256(raw_body)
```

请求头：

```text
X-Nexus-Device: <canonical-device-id>
X-Nexus-Key-Id: sha256:<public-key-der-sha256>
X-Nexus-Timestamp: <UTC ISO-8601>
X-Nexus-Nonce: <random-base64url>
X-Nexus-Signature: <base64url-ed25519-signature>
```

## 一键安装

Linux/systemd：

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sudo sh -s -- thinkcenter
```

OpenWrt/N1/AX3600：

```sh
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sh -s -- n1
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sh -s -- ax3600
```

如果 OpenWrt 不能稳定访问 GitHub raw，可用 ThinkCenter LAN mirror 设置 `NEXUS_SOURCE_BASE=http://100.103.12.14:18085` 后执行安装。

`n1` 和 `ax3600` 优先作为独立 Agent 自己领取命令。若某个目标不能运行 OpenWrt Agent 或没有被 Registry 批准，ChatGPT Remote gateway 可以按 `NEXUS_V3_MANAGED_TARGETS` 把请求转成 ThinkCenter 上的 SSH 指挥命令。
