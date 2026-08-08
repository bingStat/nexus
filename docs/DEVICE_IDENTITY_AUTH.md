# Nexus 设备身份签名鉴权

状态：v2.6 实施目标。Agent 不再保存 `NEXUS_API_TOKEN` / `apikey`；每台设备持有 Nexus 专用 Ed25519 私钥，Global API 保存公钥和批准状态，Broker 按公钥验签。

## 本机存储

| 平台 | 私钥 | 公钥 | 配置 |
|---|---|---|---|
| Linux/systemd | `/etc/nexus-agent/identity_ed25519` | `/etc/nexus-agent/identity_ed25519.pub` | `/etc/nexus-agent/config.json` |
| OpenWrt/procd | `/etc/nexus-agent/identity_ed25519` | `/etc/nexus-agent/identity_ed25519.pub` | `/etc/nexus-agent/config.env` |
| Windows/Scheduled Task | `C:\ProgramData\NexusAgent\identity_ed25519` | `C:\ProgramData\NexusAgent\identity_ed25519.pub` | `C:\ProgramData\NexusAgent\config.json` |

私钥只在本机，权限限制为 root/SYSTEM/管理员可读。公钥不是 token，不能直接作为凭据；请求必须用私钥签名。

## API 与权威存储

| 用途 | API 地址 | 存储 |
|---|---|---|
| 设备注册 | `POST https://nexus-global-api.bings.app/api/device-identities/register` | Oracle `/var/lib/nexus-global-api/device_identities.db` |
| 待批准列表 | `GET https://nexus-global-api.bings.app/api/admin/device-identities?status=pending` | 同上 |
| 批准 | `POST https://nexus-global-api.bings.app/api/admin/device-identities/{device_id}/approve` | 同上 |
| 拒绝 | `POST https://nexus-global-api.bings.app/api/admin/device-identities/{device_id}/reject` | 同上 |
| 撤销 | `POST https://nexus-global-api.bings.app/api/admin/device-identities/{device_id}/revoke` | 同上 |
| approved 公钥查询 | `GET https://nexus-global-api.bings.app/api/device-identities/{device_id}/public-key` | 同上 |
| Agent 心跳 | `POST https://nexus-global-api.bings.app/api/devices/heartbeat` | Global API 写 Supabase `public.devices` 镜像 |
| Broker 领取 | `GET {regional_broker}/claim?...` | Broker 热队列；公钥从 `https://nexus-global-api.bings.app` 查询并短 TTL 缓存 |
| Broker 回执 | `POST {regional_broker}/complete` | Broker job store；异步镜像任务结果 |
| Supabase 目录镜像 | `https://iyqzgmzlykufsbtmykpw.supabase.co/rest/v1/device_identities` | 非权威审计/目录镜像 |

## 签名头

```text
X-Nexus-Device: <canonical-device-id>
X-Nexus-Key-Id: sha256:<public-key-fingerprint>
X-Nexus-Timestamp: <UTC ISO-8601>
X-Nexus-Nonce: <128-bit-random-base64url>
X-Nexus-Signature: <base64url-ed25519-signature>
```

签名输入：

```text
NEXUS-ED25519-V1
<HTTP_METHOD_UPPERCASE>
<PATH_AND_QUERY>
<X-Nexus-Timestamp>
<X-Nexus-Nonce>
<X-Nexus-Device>
<hex_sha256_request_body>
```

验签规则：规范设备 ID、approved 公钥、key_id 匹配、时间窗口 300 秒、nonce 10 分钟防重放、body hash 按原始请求体计算。
