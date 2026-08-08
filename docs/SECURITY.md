# Nexus v3 安全基线

## 1. 身份模型

- Agent 不保存共享 API token。
- 每台设备拥有 Nexus 专用 Ed25519 API identity：
  - Linux/OpenWrt：`/etc/nexus-agent/identity_ed25519`
  - Windows：`C:\Users\Bing\AppData\Local\NexusAgentV3\identity_ed25519`
  - VSC：`~/.local/nexus-agent-v3/identity_ed25519`
- Registry 只保存 public key、key_id、设备元数据和批准状态。
- 新设备注册后默认为 `pending`，必须批准为 `approved` 后才能领取任务。

## 2. 请求签名

Agent 对 claim 和 complete 请求签名，必须携带：

```text
X-Nexus-Device
X-Nexus-Key-Id
X-Nexus-Timestamp
X-Nexus-Nonce
X-Nexus-Signature
```

Broker 验证：

- device id；
- approved public key；
- key_id；
- timestamp 窗口；
- nonce 防重放；
- request body hash。

## 3. SSH trust

- SSH identity 与 API identity 分离。
- 每台设备单独生成 Nexus SSH key。
- Registry 通过 `/v3/ssh/authorized-keys` 发布 approved 设备 SSH public keys。
- 同步脚本只改写 `authorized_keys` 中的 Nexus 管理区块：
  - `### BEGIN NEXUS MANAGED SSH KEYS`
  - `### END NEXUS MANAGED SSH KEYS`
- 不使用 cron/timer 自动轮询；新设备批准后手动或安装时触发一次同步。

## 4. 命令执行边界

- 命令必须指定 canonical device id。
- Broker 可以改变传输路径，但不能把逻辑目标改派到别的设备。
- `n1` / `ax3600` 优先自领取；不能自领取时才通过 ThinkCenter managed target。
- 高危命令默认拦截，除非显式配置 `NEXUS_V3_ALLOW_DANGEROUS=1` 并获得人工确认。

高危操作包括但不限于：

- 删除大范围文件或数据库；
- 修改网络、路由、防火墙、Tailscale、Cloudflare Tunnel；
- 重启/关机；
- 修改密码、密钥、token、authorized_keys 非 Nexus 管理区块；
- 格式化磁盘、分区、擦除设备。

## 5. Secret 处理

不得提交或打印：

- private key；
- `NEXUS_V3_ADMIN_KEY`；
- `NEXUS_CHATGPT_API_KEY`；
- dashboard Basic Auth；
- Cloudflare / Bitwarden / Supabase / browser session secrets；
- cookie、localStorage、MFA 材料。

ChatGPT Remote 的 bearer token 存储在服务端 env 文件中，不进入 dashboard 静态页面。

## 6. VSC 特殊限制

VSC 已加入 Tailscale，但使用 userspace networking：

- VSC outbound SSH tailnet 节点必须使用 `tailscale nc` 或 `ProxyCommand`；
- 其他节点 inbound 到 VSC 会被 KU Leuven HPC SSH certificate policy 拦截；
- 不能用普通 `authorized_keys` 变更绕过 HPC 登录策略。

## 7. 验收标准

不能只凭“服务 active”报告成功。至少需要：

- registry/broker health；
- device approved；
- agent registered；
- job completed；
- exit_code 符合预期；
- output 可验证；
- 对 SSH trust，至少验证 public key 数量和一条真实 SSH 登录路径。
