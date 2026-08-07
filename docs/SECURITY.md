# Nexus 安全基线

- 不在聊天、命令输出、日志、Git 或 transcript 中保存 Token、密码、Cookie、私钥。
- Browser Bridge Token 仅保存在本地 secret 文件；启动脚本只读取等号右侧实际值。
- Agent 在线时直接向规范目标设备调度；SSH、Desktop Commander 和 WSL 仅为标明的救援通道。
- 设备别名只用于匹配，不创建重复设备记录。
- 所有任务使用 UUID、lease、attempt、execution ledger 与 idempotency key。
- 不自动绕过 Claude/Google 的 CAPTCHA、MFA 或安全验证。
- 高风险操作执行前需要明确确认，并保留备份、原子替换和回滚路径。
