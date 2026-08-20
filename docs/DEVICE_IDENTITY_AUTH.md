# Device identity and authentication

## Agent device key

Every Nexus v3 Agent owns one opaque random device key. The key is a bearer credential used only for Nexus Agent authentication; it is not an SSH keypair. The Registry stores only its SHA-256 hash (`key_id`) together with canonical device metadata and approval state. The plaintext device key stays on the device.

| Platform | Device key | Agent configuration |
| --- | --- | --- |
| Linux/systemd | `/etc/nexus-agent/device.key` | `/etc/nexus-agent/v3.json` |
| Windows | `%LOCALAPPDATA%\NexusAgentV3\device.key` | `%LOCALAPPDATA%\NexusAgentV3\v3.json` |
| VSC production | `/vsc-hard-mounts/leuven-data/356/vsc35603/services/nexus-agent-v3/device.key` | same persistent service directory |
| OpenWrt | `/etc/nexus-agent/device.key` | `/etc/nexus-agent/v3.env` |

Registration sends the device key once to Registry over the configured transport. Registry derives `sha256:<digest>` and never stores the plaintext. Approved devices remain approved only when the presented key hashes to the existing `key_id`; a changed key returns the device to `pending`.

## Agent requests

Agent-to-Broker requests use only these authentication headers:

```text
X-Nexus-Device
X-Nexus-Device-Key
```

Broker resolves the approved device in Registry and compares the SHA-256 hash of the presented key with the stored `key_id` using constant-time comparison. The retired Ed25519 signing protocol, public signing keys, timestamps, nonces and signature headers are not part of v3.2.1.

New registrations are `pending`; an administrator must explicitly approve them before they can claim jobs.

## SSH trust

SSH is a separate trust domain. Every device keeps its own SSH private key locally, normally named `id_ed25519_<device>`. Registry stores only each approved device's SSH **public** key and exposes the canonical fleet set at `/v3/ssh/authorized-keys`.

Agents periodically replace only the bounded block below and preserve all unrelated `authorized_keys` content:

```text
### BEGIN NEXUS MANAGED SSH KEYS
... approved fleet public keys ...
### END NEXUS MANAGED SSH KEYS
```

Linux uses the target user's `~/.ssh/authorized_keys`; OpenWrt uses `/etc/dropbear/authorized_keys`. Private SSH keys are never centralized or copied between devices. VSC inbound SSH remains subject to KU Leuven network/login-node policy.

## Human login authentication

Human passwords are separate from Agent authentication:

- **Bitwarden Password Manager** is authoritative for human-facing logins such as Nexus Dashboard, VSC/code-server and OpenList.
- **Bitwarden Secrets Manager** is reserved for machine/API credentials such as Cloudflare/R2 tokens, Nexus service keys and automation credentials.
- Nexus Dashboard uses a Cloudflare Worker runtime secret copy of the Password Manager value and issues a `__Host-nexus_session` HttpOnly, Secure, SameSite=Strict cookie.
- VSC code-server stores only an Argon2 hash locally through `HASHED_PASSWORD`; plaintext is not kept on VSC.

Do not reuse a human password as a device key, and do not place SSH private keys in the central Registry.
