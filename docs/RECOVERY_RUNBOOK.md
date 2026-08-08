# Nexus v3 恢复手册

本文只覆盖当前 v3 主线：Registry、Broker、Agent、ChatGPT Remote、SSH key sync。旧 v2/Supabase/Browser Bridge 恢复步骤已删除，核心思想保留在根目录 `其他目标.md`。

## 1. 先判断故障层

按顺序检查：

1. Registry：`GET /v3/health`
2. Broker：`GET /v3/health`
3. 设备是否 approved：`GET /v3/admin/devices`
4. Agent 是否注册并在轮询
5. job 是否进入目标 broker
6. job 是否被 claim
7. job 是否 complete 并返回真实 `exit_code`
8. SSH key sync 是否只影响 Nexus 管理区块

不要在未定位故障层时重装全部服务。

## 2. 常用健康检查

本机 / WSL：

```bash
sudo systemctl is-active nexus-v3-registry nexus-v3-eu-broker nexus-v3-broker nexus-v3-agent
curl -fsS http://127.0.0.1:18101/v3/health
curl -fsS http://127.0.0.1:18102/v3/health
```

Oracle：

```bash
ssh oracle_amd 'systemctl is-active nexus-v3-registry nexus-v3-eu-broker nexus-v3-agent'
ssh oracle_amd 'curl -fsS http://127.0.0.1:18101/v3/health && curl -fsS http://127.0.0.1:18102/v3/health'
```

ThinkCenter：

```bash
ssh root@100.103.12.14 'systemctl is-active nexus-v3-broker nexus-v3-agent'
ssh root@100.103.12.14 'curl -fsS http://127.0.0.1:18120/v3/health'
```

Windows Victus：

```powershell
Get-ScheduledTask -TaskName NexusV3Agent
Get-Content C:\Users\Bing\AppData\Local\NexusAgentV3\agent.log -Tail 40
```

VSC：

```bash
ssh vsc 'pgrep -af "python3 -m nexus_v3.agent"; tail -40 ~/.local/nexus-agent-v3/agent.log'
```

## 3. Agent 不领取任务

1. 确认设备在 global registry 中是 `approved`。
2. 确认 agent 配置使用正确 registry/broker：
   - EU：`https://nexus-global-api.bings.app` + `https://nexus-eu-broker.bings.app`
   - CN：ThinkCenter broker `http://100.103.12.14:18120` 或本机 `127.0.0.1:18120`
3. 查看 agent 日志中的 `agent.registered` 和 `agent.error`。
4. 如果出现 `device_not_approved`，重新批准设备。
5. 如果出现 Cloudflare `1010`，从 broker 所在机器本机接口验证，避免把 Cloudflare 浏览器策略误判为 broker 故障。

## 4. SSH key sync 修复

全局公钥源：

```bash
curl -fsS https://nexus-global-api.bings.app/v3/ssh/authorized-keys
```

Linux/systemd 节点：

```bash
sudo NEXUS_V3_REGISTRY_URL=https://nexus-global-api.bings.app /opt/nexus-agent/sync_ssh_authorized_keys.sh
```

OpenWrt/N1：

- `/root/.ssh/authorized_keys` 不是唯一入口；
- Dropbear 还需要 `/etc/dropbear/authorized_keys`；
- BusyBox 命令参数兼容性较差，复杂同步建议通过 Nexus job 下发明确脚本。

VSC：

- 已安装用户态 Tailscale，但使用 `--tun=userspace-networking`；
- 普通 `ssh 100.x` 不会自动走 Tailscale；
- 从 VSC 主动 SSH tailnet 节点时使用 `tailscale nc` / `ProxyCommand`。

## 5. Windows 配置注意事项

PowerShell 可能写出带 UTF-8 BOM 的 JSON。当前 agent 已用 `utf-8-sig` 读取配置，避免 `JSONDecodeError: Unexpected UTF-8 BOM`。

Windows OpenSSH 作为源节点时建议显式加：

```powershell
-o IdentitiesOnly=yes
```

否则可能先尝试过多默认 key，导致目标返回 `Too many authentication failures`。

## 6. 不能自动处理的情况

以下情况需要明确人工确认或外部平台操作：

- VSC inbound SSH：KU Leuven HPC 要求 SSH certificate，普通 Nexus public key 不足以登录；
- Windows/ThinkCenter/N1 重启；
- 网络核心变更，如 Tailscale、Cloudflare Tunnel、路由、防火墙；
- 删除数据库、私钥、authorized_keys 非 Nexus 管理区块；
- 改变公网暴露面或 Basic Auth/ChatGPT bearer token。
