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

## Web Council 模式

Web Council 让用户手动邀请 ChatGPT、Claude、Gemini 网页会话参与讨论，但不抓取、不远控、不读取浏览器页面，也不保存任何 provider 凭据。Nexus 只生成 prompt；用户打开官方网页、复制 prompt、粘贴回复，并在本机 Council Board 中点击 Submit。

Provider ID 固定为：`chatgpt`、`claude`、`gemini`。

模式：

- `web-discussion`：三家 Web provider 完成独立提案与交叉审核，本地 Codex verifier 综合最终决策，不实施。
- `web-hybrid`：同样完成 Web 讨论后，继续使用既有本地 Codex WSL implementer、reviewer、verifier 和机器验收规则实施。

命令：

```powershell
# 1. 创建 room，并生成 round 1 prompt 文件；命令立即返回
powershell.exe -NoProfile -NonInteractive -File C:\Users\Bing\aurora\Workstation\Nexus\agent-council\council.ps1 web-start `
  -Repo C:\path\to\repo -TaskId issue-127 -Task "任务描述" -Mode web-discussion

# 2. 启动本机 Board；默认 127.0.0.1，未传 Token 时自动生成一次性 bearer token
powershell.exe -NoProfile -NonInteractive -File C:\Users\Bing\aurora\Workstation\Nexus\agent-council\council.ps1 web-serve `
  -Repo C:\path\to\repo -TaskId issue-127 -Port 8765

# 3. 也可不用 Board，从文件或 stdin 手动提交回复
powershell.exe -NoProfile -NonInteractive -File C:\Users\Bing\aurora\Workstation\Nexus\agent-council\council.ps1 web-submit `
  -Repo C:\path\to\repo -TaskId issue-127 -Provider chatgpt -Round 1 -ResponseFile C:\path\chatgpt-r1.md

# 4. 三个 round 1 回复齐全后，生成 round 2 交叉审核 prompt
powershell.exe -NoProfile -NonInteractive -File C:\Users\Bing\aurora\Workstation\Nexus\agent-council\council.ps1 web-advance `
  -Repo C:\path\to\repo -TaskId issue-127

# 5. 三个 round 2 回复齐全后，由本地 Codex verifier 生成最终决策；web-hybrid 会继续实施与验收
powershell.exe -NoProfile -NonInteractive -File C:\Users\Bing\aurora\Workstation\Nexus\agent-council\council.ps1 web-finalize `
  -Repo C:\path\to\repo -TaskId issue-127 -AcceptCommand @('pytest -q')

# 6. 查询机器可读状态；stderr 同时给出简洁摘要
powershell.exe -NoProfile -NonInteractive -File C:\Users\Bing\aurora\Workstation\Nexus\agent-council\council.ps1 web-status `
  -Repo C:\path\to\repo -TaskId issue-127
```

持久文件位于原 room 下：

- `web/state.json`
- `web/prompts/<round>/<provider>.md`
- `web/responses/<round>/<provider>.md`
- `web/events.jsonl`
- `messages/` 中同步导入带 provider、round、task_id 元数据的 Web 回复
- `decisions/final-decision.md`

状态 phase 显式限定为：`initialized`、`awaiting-web-proposals`、`awaiting-web-cross-review`、`ready-to-finalize`、`implementing`、`accepted`、`revision-required`、`rejected`、`decision-complete`。

重复提交相同内容会幂等成功；同一 provider/round 的不同内容默认拒绝。`-Overwrite` 只允许在该 round 尚未冻结时使用：`web-advance` 后 round 1 冻结，进入 `ready-to-finalize` 后 round 2 冻结。

Herdr 本地插件位于 `agent-council\herdr-plugin`，提供 Board 启动 action 与 status pane 入口；不需要修改 Herdr core。

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

## Web Council 安全与工作区存储

- `/api/status` 与所有写接口都要求 Council Board Bearer Token。
- 浏览器提交必须带与本地 Board 完全一致的 `Origin`（主机和端口均匹配）；无 `Origin` 的命令行调用还必须显式发送 `X-Nexus-Client: nexus-cli`。
- 可设置 `NEXUS_COUNCIL_WORKTREE_ROOT` 把隔离 worktree 放到数据盘。Victus 使用 `F:\NexusCouncilWorktrees`，避免占用已满的系统盘，并让 WSL/Codex 直接使用真实磁盘路径。
- 网页回复始终由用户主动复制、粘贴或选择文件后提交。Board 不读取 ChatGPT、Claude、Gemini 标签页，不访问浏览器存储、登录状态或页面内容。
