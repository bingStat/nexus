# AGENTS.md

## 工程原则

- 不保留向后兼容。旧路径、旧协议和旧脚本应删除或移入明确归档，而不是继续叠加兼容层、fallback 或迁移逻辑。
- 选择能完整满足当前需求的最简单实现。避免投机式抽象、过度配置和不必要的间接层。
- 分层增长：先做出最小可端到端运行的版本，再在稳定产品上增加能力。
- 模块职责保持清晰：Registry 管身份，Broker 管任务队列，Agent 管本机执行，Remote Gateway 管 ChatGPT/MCP 调用入口。
- 优先使用成熟、维护良好的依赖；已有依赖能解决时不重复造轮子。
- 架构决策面向长期使用，不接受临时补丁式设计作为主线。

## Nexus 项目规则

1. 生产路径固定为：`client -> Nexus remote gateway -> registry -> regional broker -> target agent`。
2. 故障切换不能改变逻辑目标设备。
3. Agent 只消费所属区域 Broker 的任务。
4. 必须使用规范设备 ID；不支持别名、`all` 或 `broadcast`。
5. `install.sh` 是唯一用户入口安装脚本。
6. Linux 使用 systemd，OpenWrt 使用 procd。
7. `n1` 与 `ax3600` 能运行 OpenWrt Agent 时自行领取任务；否则由 ThinkCenter 通过显式 SSH fallback 管理。
8. 凭据只能来自显式参数或环境变量，并仅保存到权限受限的配置文件。
9. ChatGPT Action OpenAPI 与提示词保存在 `agent-council/integrations/`。
10. 完成标准：语法检查、测试、服务健康检查和真实只读命令回执均通过。
