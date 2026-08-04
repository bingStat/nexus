# Nexus Agent Council

该目录部署在 Victus，提供 Nexus → Herdr → 多 Agent 的可审计协作流程。

## 角色与执行环境

| 角色 | Agent | 权限与环境 |
|---|---|---|
| architect | Antigravity CLI | `plan + sandbox`，只读设计 |
| reviewer | Antigravity CLI | `plan + sandbox`，独立反方审核 |
| implementer | Codex CLI | Victus WSL，`workspace-write`，仅独立 worktree |
| verifier | Codex CLI | Windows read-only，内联完整证据，不访问仓库 |
| orchestrator | Python | 轮次、状态、Git、机器验收和最终裁决 |

流程：独立提案 → 交叉审核 → 加权裁决 → 实施 → diff 审核 → 机器验收 → 最终验证。

## 入口

```powershell
# 健康检查
powershell.exe -NoProfile -NonInteractive -File C:\Users\Bing\aurora\Workstation\Nexus\agent-council\council.ps1 doctor

# 只讨论，不修改代码
powershell.exe -NoProfile -NonInteractive -File C:\Users\Bing\aurora\Workstation\Nexus\agent-council\council.ps1 run `
  -Repo C:\path\to\repo -TaskId issue-127 -Task "任务描述" -DiscussionOnly

# 完整实施；机器验收命令可重复
powershell.exe -NoProfile -NonInteractive -File C:\Users\Bing\aurora\Workstation\Nexus\agent-council\council.ps1 run `
  -Repo C:\path\to\repo -TaskId issue-127 -Task "任务描述" `
  -AcceptCommand @('pytest -q', 'npm run lint')
```

## 结果判定

只有同时满足以下条件，完整任务才返回 0：

1. 产生非空 staged diff；
2. `git diff --cached --check` 通过；
3. 所有 `-AcceptCommand` 返回 0；
4. Reviewer 完成 diff 审核；
5. Verifier 第一行 verdict 为 `ACCEPT`。

`REVISE`、`REJECT` 或机器验收失败均返回非零退出码，并保留 implementer worktree 供修订。

## 持久状态

- Herdr session：`nexus-council`
- Windows 计划任务：`NexusHerdrCouncil`
- 讨论记录：`%LOCALAPPDATA%\Nexus\agent-council\rooms\<repo>\<task-id>`
- 工作树：`%LOCALAPPDATA%\Nexus\agent-council\worktrees\<repo>\<task-id>\<role>`
- 成功后自动关闭所有 pane；只讨论模式移除全部临时 worktree；完整模式仅保留 implementer worktree。
