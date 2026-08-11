# Nexus 设备身份签名鉴权

状态：Nexus v3 当前设计。每台设备只持有本机 Nexus 专用 Ed25519 私钥；Registry 保存公钥和批准状态，Broker 按公钥验签。

## 本机存储

| 平台 | 私钥 | 公钥 | 配置 |
|---|---|---|---|
| Linux/systemd | `/etc/nexus-agent/identity_ed25519` | `/etc/nexus-agent/identity_ed25519.pub` | `/etc/nexus-agent/v3.json` |
| OpenWrt/procd | `/etc/nexus-agent/identity_ed25519` | `/etc/nexus-agent/identity_ed25519.pub` | `/etc/nexus-agent/v3.env`；签名辅助脚本 `/opt/nexus-agent/openwrt_ed25519_signer.rb` |

`identity_ed25519.pub` 就是设备 API key / device identity，同时也是加入 SSH 互信网络的 public key。服务器不保存私钥；所有 API 请求仍必须由对应私钥签名。

私钥只在本机，权限限制为 root/SYSTEM/管理员可读。公钥不是 token，不能直接作为凭据；请求必须用私钥签名。

OpenWrt/iStoreOS 上的 OpenSSL 1.1.1 不一定支持 `pkeyutl` Ed25519 signing。OpenWrt Agent 会先尝试系统 OpenSSL；失败时使用 Nexus 随安装器下载的纯 Ruby signer。该 signer 只读取本机 PKCS#8 Ed25519 私钥并输出 64 字节签名，不保存 token。

## API 与权威存储

| 用途 | API 地址 | 存储 |
|---|---|---|
| 设备注册 | `POST {registry}/v3/devices/register` | `/var/lib/nexus-v3/registry.db` |
| 待批准列表 | `GET {registry}/v3/admin/devices?status=pending` | 同上 |
| 批准 | `POST {registry}/v3/admin/devices/{device_id}/approve` | 同上 |
| 拒绝 | `POST {registry}/v3/admin/devices/{device_id}/reject` | 同上 |
| 撤销 | `POST {registry}/v3/admin/devices/{device_id}/revoke` | 同上 |
| approved 公钥查询 | `GET {registry}/v3/devices/{device_id}/public-key` | 同上 |
| Broker 领取 | `GET {regional_broker}/v3/jobs/claim?...` | `/var/lib/nexus-v3/broker.db` |
| Broker 回执 | `POST {regional_broker}/v3/jobs/complete` | 同上 |

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
NEXUS-V3-ED25519
<HTTP_METHOD_UPPERCASE>
<PATH_AND_QUERY>
<X-Nexus-Timestamp>
<X-Nexus-Nonce>
<X-Nexus-Device>
<hex_sha256_request_body>
```

验签规则：规范设备 ID、approved 公钥、key_id 匹配、时间窗口 300 秒、nonce 10 分钟防重放、body hash 按原始请求体计算。
