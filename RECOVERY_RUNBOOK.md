# Nexus 恢复手册

1. 先检查 `GET /health` 与 `/api/devices`，区分入口、Broker、心跳和 worker 故障。
2. Agent 在线但任务不领取：重启目标节点的 Agent 监督器；不得改派目标。
3. Victus：运行计划任务 `NexusAgent`；检查 `C:\Users\Bing\.nexus-agent\agent.py` 和 ledger。
4. Victus WSL：检查 `~/.nexus-agent/agent.py`、单实例锁和日志。
5. Browser Bridge：确认 Chrome Profile 3 扩展存在，Windows MCP 由 `F:\NexusBrowser\start-pw-mcp.cmd` 启动。
6. Claude/Gemini 登录失效时由用户在常用 Chrome 完成人工登录或验证；不得自动绕过 CAPTCHA/MFA。
7. Broker 故障只能切换传输路径；必须保持 `target_device` 不变并依赖 execution ledger 防重复。
8. 整机重启、网络核心修改或数据删除必须先确认维护窗口、备份和回滚路径。
