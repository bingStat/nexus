# Nexus v3

Nexus 是个人设备集群的远程控制面与分布式开发空间。当前只有一套生产架构：

```text
ChatGPT / MCP
      |
      v
Remote API / MCP Adapter
      |
      +--> Registry (device identity / approval / SSH public keys)
      |
      +--> EU Broker --------> EU Agent
      |
      +--> CN Broker --------> CN Agent
```

每个 Agent 使用本机 Ed25519 身份签名请求；Broker 只向**明确指定的目标设备**交付任务。网络或 Broker 故障切换不得改变 `target_device`。

## 核心能力

- Ed25519 设备身份与 Registry 审批
- EU / CN 区域 Broker
- 单设备 shell 执行与最多 16 个任务的 batch
- DevSpace workspace：read / patch / exec / interactive session
- Broker idempotency、lease 超时恢复
- Agent execution ledger，防止回执丢失导致重复执行
- Broker long-poll presence 与 online / degraded / offline 状态
- 3/5 分钟低频监控、抖动抑制、Telegram 批量告警
- Agent Council 多 Agent 评审/实施模块

## 项目结构

```text
nexus_v3/       核心控制面：Registry、Broker、Agent、Remote API、MCP、DevSpace adapter
runtime/        上游 DevSpace runtime bridge
ops/            健康快照、告警、Telegram、状态归档、systemd units
scripts/        审批、验证、runtime 更新工具
dashboard/      nexus.bings.app 静态面板与 Worker
agent-council/  多 Agent Council；与 Nexus 控制面解耦
docs/           架构、安全、恢复说明
tests/          v3 契约与回归测试
```

根目录只有两个安装入口：

- `install.sh`：Linux / OpenWrt / 服务端组件
- `install.ps1`：Windows Agent

`.bak/` 仅用于本地迁移归档，并被 Git 忽略。

## Canonical device IDs

`oracle`, `thinkcenter`, `n1`, `vsc`, `victus`, `victus-wsl`, `elitebook`, `ax3600`

不支持 `all`、`broadcast`、模糊 alias 或“目标设备离线后换另一台机器代执行”。

## 安装

Linux Agent：

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/install.sh | sudo sh -s -- agent <device-id>
```

OpenWrt / iStoreOS：

```sh
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/main/install.sh | sh -s -- openwrt-agent <n1-or-ax3600>
```

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/bingStat/nexus/main/install.ps1 -OutFile $env:TEMP\nexus-install.ps1
& $env:TEMP\nexus-install.ps1 -DeviceId victus
```

服务端组件：

```bash
sudo ./install.sh registry
sudo ./install.sh broker eu
sudo ./install.sh broker cn
sudo ./install.sh remote
sudo ./install.sh ops
```

## 设备身份与配置

Linux/OpenWrt 默认身份：

```text
/etc/nexus-agent/identity_ed25519
/etc/nexus-agent/identity_ed25519.pub
```

Windows 默认身份：

```text
%LOCALAPPDATA%\NexusAgentV3\identity_ed25519
%LOCALAPPDATA%\NexusAgentV3\identity_ed25519.pub
```

私钥只留在本机。Registry 只保存公钥与批准状态。Agent 正常 long-poll 区域 Broker 时顺带刷新 presence，不产生额外 heartbeat 流量；控制面按 Broker 最近 presence 计算 runtime state。

若目标存在 Node >= 22.19 与 npm，安装器会启用 DevSpace；Linux 用 `NEXUS_DEVSPACE_ALLOWED_ROOTS` 指定可访问根目录，Windows 用 `-AllowedRoots`。

## 新设备批准

首次注册为 `pending`，在有 `NEXUS_V3_ADMIN_KEY` 的管理节点执行：

```bash
NEXUS_V3_REGISTRY_URL=https://nexus-global-api.bings.app \
python3 scripts/approve_v3_devices.py <device-id>
```

## Remote API / MCP

ChatGPT 接入说明见 [NEXUS_CHATGPT_PROMPT.md](NEXUS_CHATGPT_PROMPT.md)。机器可读资产：

- `agent-council/integrations/nexus-v3-remote-control-openapi.json`
- `agent-council/integrations/nexus-v3-chatgpt-remote-prompt.md`

主要接口：`getFleetStatus`, `listDevices`, `getDevice`, `executeCommand`, `executeBatch`, `executeRuntimeOperation`, `getJob`。

## 运维策略

`ops/` 不依赖 Supabase。默认 cadence：

- health snapshot：3 分钟
- alert evaluation：3 分钟
- Telegram：5 分钟
- state archive：5 分钟

告警默认需要连续失败确认，恢复也需要连续成功确认；30 分钟内再次抖动会提高 reopen 阈值。详见 `ops/README.md`。

## 验证

```bash
python -m pytest -q
python scripts/verify_v3.py
sh -n install.sh ops/install.sh runtime/devspace/install.sh nexus_v3/assets/openwrt_v3_agent.sh
```

生产基线以 GitHub `main` 为唯一代码事实源；Victus 和 VSC 工作副本必须与同一 `main` commit 对齐。
