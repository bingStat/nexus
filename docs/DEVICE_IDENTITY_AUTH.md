# Device identity and authentication

## Agent identity

Every v3 Agent owns one local Ed25519 keypair. Registry stores the public key, key fingerprint, canonical device metadata and approval status; private keys never leave the device.

| Platform | Private key | Configuration |
| --- | --- | --- |
| Linux/systemd | `/etc/nexus-agent/identity_ed25519` | `/etc/nexus-agent/v3.json` |
| Windows | `%LOCALAPPDATA%\NexusAgentV3\identity_ed25519` | `%LOCALAPPDATA%\NexusAgentV3\v3.json` |
| VSC/user-local | `~/.local/nexus-agent-v3/identity_ed25519` | `~/.config/nexus-agent/v3.json` |
| OpenWrt | `/etc/nexus-agent/identity_ed25519` | `/etc/nexus-agent/v3.env` |

A public key is an identity, not a bearer token. Claim and completion requests require proof from the corresponding private key.

## Signed requests

```text
X-Nexus-Device
X-Nexus-Key-Id
X-Nexus-Timestamp
X-Nexus-Nonce
X-Nexus-Signature
```

The signature covers HTTP method, path/query, timestamp, nonce, canonical device ID and SHA-256 body hash. Broker verifies approved identity, key ID, a 300-second timestamp window and nonce replay protection.

New registrations are `pending`; an administrator must explicitly approve them before they can claim jobs.
## SSH trust

The Nexus device public key can also populate the managed SSH block distributed by Registry. Sync changes only the `### BEGIN/END NEXUS MANAGED SSH KEYS` section; it must not rewrite unrelated `authorized_keys` entries. VSC inbound SSH remains subject to KU Leuven certificate policy and is not bypassed by Nexus keys.

## Human login authentication

Human passwords are a separate trust domain from Agent identity:

- **Bitwarden Password Manager** is authoritative for human-facing logins such as Nexus Dashboard, VSC/code-server and OpenList.
- **Bitwarden Secrets Manager** is reserved for machine/API credentials such as Cloudflare/R2 tokens, Nexus service keys and automation credentials.
- Nexus Dashboard uses a Cloudflare Worker runtime secret copy of the Password Manager value and issues a `__Host-nexus_session` HttpOnly, Secure, SameSite=Strict cookie.
- VSC code-server stores only an Argon2 hash locally through `HASHED_PASSWORD`; the plaintext is not kept in BSM or on VSC.

Do not use a shared human password as an Agent credential, and do not place Ed25519 private keys in Password Manager for convenience.