# Nexus v3 — ChatGPT / MCP 接入

Nexus 只有一条生产路径：

```text
ChatGPT / MCP -> Remote API -> Registry -> EU/CN Broker -> exact target Agent
```

不存在 Supabase 队列、旧 token Agent、`all`/`broadcast`、目标设备替换或旧 API 兼容入口。

## ChatGPT Action

- Base URL: `https://nexus-global-api.bings.app`
- Schema: `agent-council/integrations/nexus-v3-remote-control-openapi.json`
- Instructions: `agent-council/integrations/nexus-v3-chatgpt-remote-prompt.md`
- Authentication: Bearer token from the protected `NEXUS_CHATGPT_API_KEY` deployment secret.

`NEXUS_CHATGPT_API_KEY` 只放在受保护的 Action / 服务配置中，不写入 Git、Prompt、浏览器 JavaScript 或聊天记录。

## 当前 Action

- `getFleetStatus`
- `listDevices`
- `getDevice`
- `executeCommand`
- `executeBatch`
- `executeRuntimeOperation`
- `getJob`

## 使用原则

- 每条任务必须指向一个明确 canonical device ID。
- Broker/网络故障切换不得改变 `target_device`。
- 设备离线或未批准时明确失败，不允许让 ThinkCenter、Oracle 等替目标设备执行。
- 编码任务若目标声明 `runtime=devspace`，优先使用 `workspace.open/read/apply_patch/exec/write_stdin`。
- 长任务只根据原 `job_id` 查询，不重复提交。
- 回答必须基于真实回执，至少报告设备、`job_id`、`status`、`exit_code` 和 `broker_region`。

## 验证

导入后先执行：

```text
Call getFleetStatus.
Call listDevices with status=approved.
```

再选择一个在线设备执行只读命令，例如：

```text
Call executeCommand on victus with command: hostname
```

Agent Council 是独立的多 Agent 评审/实现模块，保留在 `agent-council/`；它不构成另一套 Nexus 控制面，也没有旧 Task API 兼容要求。
