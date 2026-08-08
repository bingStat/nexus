# Nexus .ai 运行上下文索引

本目录只保留 Nexus 当前运维和决策上下文。旧 v2 / Supabase / Browser Bridge 结项材料不再作为当前事实来源；历史思想见根目录 `其他目标.md`。

## 当前权威架构

```text
ChatGPT / MCP / local operator
        │
        ▼
Nexus ChatGPT Remote / MCP adapter
        │
        ├── Registry: Oracle, https://nexus-global-api.bings.app
        │       └── approved device public keys + SSH public keys
        │
        ├── EU Broker: Oracle, https://nexus-eu-broker.bings.app
        │       ├── oracle
        │       ├── victus
        │       ├── victus-wsl
        │       └── vsc
        │
        └── CN Broker: ThinkCenter, http://100.103.12.14:18120
                ├── thinkcenter
                └── n1
```

## 当前已纳管设备

- `oracle`
- `thinkcenter`
- `n1`
- `victus`
- `victus-wsl`
- `vsc`

`ax3600` 和 `elitebook` 是预留 canonical device；纳管前不报告为已完成。

## 当前主线文件

- `README.md`：用户入口和源代码布局。
- `install.sh`：唯一安装脚本。
- `docs/NEXUS_V3_CLEAN_ARCHITECTURE.md`：当前架构。
- `docs/DEVICE_IDENTITY_AUTH.md`：Ed25519 API identity。
- `docs/RECOVERY_RUNBOOK.md`：恢复手册。
- `docs/SECURITY.md`：安全基线。
- `agent-council/integrations/`：ChatGPT Action prompt/OpenAPI。
- `dashboard/`：`https://nexus.bings.app/` 页面源文件。
- `其他目标.md`：历史目标和非主线目标摘要。

## 当前运行原则

1. Agent 使用 Nexus 专用 Ed25519 私钥签名请求；服务器只保存公钥。
2. 新设备注册后必须批准，不能自动信任。
3. SSH key 与 API identity 分离；approved 设备的 SSH public key 由 Registry 发布。
4. 不使用 cron/timer 同步 SSH key；安装或批准后触发一次同步。
5. 报告成功必须有真实 job result：`completed`、`exit_code` 和可验证 output。
6. 网络、重启、删除、凭据、firewall、Cloudflare/Tailscale 变更必须先确认风险。
