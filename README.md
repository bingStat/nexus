# Nexus v3 远程控制

Nexus 是一个个人设备集群远程控制面。当前 v3 架构模仿 DesktopCommanderMCP 的 Remote MCP 思路：ChatGPT 或 MCP 客户端不直接连接任何设备，而是访问本地 Nexus Remote Gateway；Gateway 把任务提交到区域 Broker；已批准的 Agent 只领取属于自己的任务，并用 Nexus 专用 Ed25519 身份签名注册、领取和回执。

## 当前架构

```text
ChatGPT / MCP 客户端
  -> Nexus ChatGPT Remote API 或 MCP Adapter
  -> Registry
  -> EU / CN Broker
  -> 已批准目标 Agent
```

鉴权不再依赖“每台机器一个 API token”。每台设备生成一套 Nexus device Ed25519 keypair：公钥就是设备的 API key / device identity，同时也是该设备加入 SSH 互信网络的公钥；服务器只保存公钥和审批状态。Agent 每次注册、领取任务、提交完成回执时都用私钥签名。

## 规范设备 ID

EU 区域：

- `oracle`
- `vsc`
- `victus`
- `victus-wsl`
- `elitebook`

CN 区域：

- `thinkcenter`
- `n1`
- `ax3600`

`n1` 和 `ax3600` 能运行 OpenWrt Agent 时自行领取任务；如果目标尚未注册或未批准，Remote Gateway 可以按 `NEXUS_V3_MANAGED_TARGETS` 通过 ThinkCenter 的显式 SSH fallback 指挥它们。

## 唯一安装脚本

对外只保留一个安装脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sudo sh -s -- <mode>
```

本地开发可直接运行仓库里的同一个脚本：

```bash
sudo ./install.sh <mode>
```

支持模式：

- `registry`
- `broker eu`
- `broker cn`
- `agent <规范设备 ID>`
- `<规范设备 ID>`
- `openwrt-agent <规范设备 ID>`
- `remote`
- `managed-targets`
- `sync-ssh-keys`
- `sync-cluster-ssh`

示例：

```bash
sudo ./install.sh registry
sudo NEXUS_V3_REGION=cn NEXUS_V3_BIND=0.0.0.0 ./install.sh broker cn
sudo ./install.sh thinkcenter
sudo ./install.sh remote
```

OpenWrt：

```sh
sh install.sh n1
sh install.sh ax3600
```

## 新设备加入集群

任意新设备加入 Nexus 时，只需要运行同一个安装脚本。安装器会自动完成：

1. 生成一套 Nexus device Ed25519 keypair。公钥就是 API key，同时作为 SSH 公钥加入机器互信网络；私钥既用于 API 请求签名，也用于 SSH 登录。

   | 用途 | 私钥 | 公钥 |
   |---|---|---|
   | API 签名 + SSH 互信 | `/etc/nexus-agent/identity_ed25519` | `/etc/nexus-agent/identity_ed25519.pub` |

2. 把 `device_id + public_key + hostname + platform` 注册到 Registry。
3. 设备被批准后，从 Registry 拉取所有 approved 设备的 SSH 公钥，并同步到各终端 `authorized_keys` 的 Nexus 管理区块。

Linux/systemd 新设备：

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sudo sh -s -- <规范设备 ID>
```

示例：

```bash
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sudo sh -s -- elitebook
```

OpenWrt/iStoreOS 新设备：

```sh
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sh -s -- <规范设备 ID>
```

示例：

```sh
curl -fsSL https://raw.githubusercontent.com/bingStat/nexus/release/core-2aea394/install.sh | sh -s -- n1
```

新设备首次注册后状态是 `pending`。在拥有 `NEXUS_V3_ADMIN_KEY` 的控制机上，用仓库本地脚本批准：

```bash
sudo python3 scripts/approve_v3_devices.py <规范设备 ID>
```

如果 Registry 不在本机，显式指定 Registry 地址：

```bash
sudo env NEXUS_V3_REGISTRY_URL=https://nexus-global-api.bings.app \
  python3 scripts/approve_v3_devices.py <规范设备 ID>
```

批准后，从任意已能 SSH 到其它节点的控制机触发全体 SSH 公钥同步：

```bash
NEXUS_V3_REGISTRY_URL=https://nexus-global-api.bings.app \
NEXUS_CLUSTER_SSH_HOSTS='oracle_amd root@100.103.12.14 root@100.90.67.12' \
sudo ./install.sh sync-cluster-ssh
```

`NEXUS_CLUSTER_SSH_HOSTS` 写“当前这台控制机能 SSH 到的全体终端”。默认值覆盖 Oracle、ThinkCenter 和 N1；如果新增了其它可达终端，把它们追加进去即可。同步脚本不会改写用户自己的 SSH key，只会替换：

```text
### BEGIN NEXUS MANAGED SSH KEYS
...
### END NEXUS MANAGED SSH KEYS
```

这样每加入一台新设备，Registry 中的 approved SSH 公钥集合都会增长一次；同步后，所有可达终端都会信任这台新设备的 Nexus SSH 公钥，同时新设备也会信任已有设备的 Nexus SSH 公钥。

## SSH 信任同步

每台设备只有一套 Nexus device key：

- 私钥：`/etc/nexus-agent/identity_ed25519`
- 公钥：`/etc/nexus-agent/identity_ed25519.pub`

这个公钥就是设备 API key，同时登记为 SSH public key。Registry 通过 `/v3/ssh/authorized-keys` 暴露所有已批准设备的公钥。

安装器会安装本地一次性同步脚本，只重写 `authorized_keys` 中 Nexus 管理的区块。SSH 公钥同步不使用 cron/timer；新设备安装或批准后，执行：

```bash
sudo ./install.sh sync-cluster-ssh
```

Agent 安装完成时也会 best-effort 触发一次集群 SSH 公钥刷新。

## ChatGPT Action

ChatGPT 侧以本 README 的“ChatGPT / Action / 归档配置（集中版）”为根目录唯一来源；同时为了自动化测试和安装器分发，保留 `agent-council/integrations/` 下的机器可读副本：

- `agent-council/integrations/nexus-v3-chatgpt-remote-prompt.md`
- `agent-council/integrations/nexus-v3-remote-control-openapi.json`

当前 ChatGPT Action 使用：

```text
https://nexus-global-api.bings.app
```

该域名保留 `/v3/*` 给 Registry，同时把 `/health`、`/openapi.json`、`/api/*` 转发给 `nexus-chatgpt-remote`。不要把 dashboard 地址 `https://nexus.bings.app/` 当成 Action API 地址。

本地 Remote 服务也会动态提供 OpenAPI：

```text
http://127.0.0.1:18131/openapi.json
```

Action 鉴权使用 Bearer token，对应环境变量 `NEXUS_CHATGPT_API_KEY`，配置文件位于：

```text
/etc/nexus-chatgpt-remote.env
```

不要把 token、私钥、cookie 或浏览器会话内容写入仓库、提示词或聊天记录。

## 运行时文件

- Registry 数据库：`/var/lib/nexus-v3/registry.db`
- Broker 数据库：`/var/lib/nexus-v3/broker.db`
- Linux Agent 配置：`/etc/nexus-agent/v3.json`
- OpenWrt Agent 配置：`/etc/nexus-agent/v3.env`
- 设备 API 私钥：`/etc/nexus-agent/identity_ed25519`
- 设备 API 公钥：`/etc/nexus-agent/identity_ed25519.pub`
- Nexus SSH 身份：复用 `identity_ed25519` / `identity_ed25519.pub`
- ChatGPT Remote 环境：`/etc/nexus-chatgpt-remote.env`

## 源码结构

- `install.sh`：唯一用户入口安装脚本。
- `nexus_v3/`：Registry、Broker、Agent、MCP Adapter、ChatGPT Action Bridge、OpenWrt 运行时资产和共享远控逻辑。
- `nexus_v3/assets/openwrt_v3_agent.sh`：OpenWrt Agent 运行时资产，由 `install.sh` 自动安装。
- `nexus_v3/assets/openwrt_ed25519_signer.rb`：OpenWrt Ed25519 签名 fallback，由 `install.sh` 自动安装。
- `agent-council/`：保留的 Council 机制。
- `agent-council/integrations/`：ChatGPT 提示词与 Action OpenAPI 的机器可读副本；人工入口和根目录归档集中在本文件。
- `dashboard/`：`https://nexus.bings.app/` 的 Cloudflare Worker + R2 可视化页面源码。
- `scripts/`：设备批准与验证辅助脚本；不是安装入口。
- `tests/`：契约测试。
- 根目录文档：只保留 `README.md`；旧 `nexus.json`、Action JSON、提示词、`AGENTS.md` 和历史目标摘要均已合并到本文件的集中版章节。
## ChatGPT / Action / 归档配置（集中版）

本节是 ChatGPT 提示词、Action JSON、Nexus 控制配置和历史目标的唯一根目录归档。根目录不再单独保留这些文档或 JSON 文件；需要复制到 ChatGPT Action 时，直接从对应代码块取用。

### Nexus 控制配置（原 `nexus.json`）

```json
{
  "version": 1,
  "alias": "nexus",
  "default_node": "victus",
  "council_mode": "web-hybrid",
  "risk_policy": "auto_worktree_only",
  "verification": [
    "python -m unittest discover -s agent-council/tests -v",
    "python -m py_compile agent-council/council.py agent-council/web_council.py agent-council/web_board.py"
  ],
  "approval_required": [
    "merge",
    "push",
    "deploy",
    "main_branch_mutation",
    "credential_change"
  ]
}
```

### Nexus 持久任务 API Action JSON（原 `nexus-task-api-openapi.json`）

```json
{
  "openapi": "3.0.3",
  "info": {
    "title": "Nexus Durable Task API",
    "version": "2.1.2",
    "description": "Create and resume durable cluster tasks. This API exposes deterministic aliases, Web Council orchestration, status, and approval recording. It intentionally excludes arbitrary shell execution."
  },
  "servers": [
    {
      "url": "https://nexus-api.bings.app"
    }
  ],
  "security": [
    {
      "BearerAuth": []
    }
  ],
  "paths": {
    "/api/v1/tasks": {
      "post": {
        "summary": "Create a durable Nexus task",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "responses": {
          "200": {
            "description": "Existing idempotent task",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Task"
                }
              }
            }
          },
          "201": {
            "description": "Created",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Task"
                }
              }
            }
          },
          "400": {
            "description": "Unknown alias or invalid input"
          },
          "409": {
            "description": "NEEDS_RECIPE, idempotency conflict, or approval gate"
          }
        },
        "description": "Always preserve task_id and reuse the same Idempotency-Key after a timeout.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/CreateTask"
              }
            }
          }
        },
        "parameters": [
          {
            "name": "Idempotency-Key",
            "in": "header",
            "required": false,
            "schema": {
              "type": "string"
            }
          }
        ]
      },
      "get": {
        "summary": "List recent Nexus tasks",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "responses": {
          "200": {
            "description": "Success"
          }
        },
        "parameters": [
          {
            "name": "limit",
            "in": "query",
            "schema": {
              "type": "integer",
              "minimum": 1,
              "maximum": 100,
              "default": 20
            }
          }
        ]
      }
    },
    "/api/v1/tasks/{task_id}": {
      "get": {
        "summary": "Get one Nexus task status",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "responses": {
          "200": {
            "description": "Task status card",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/Task"
                }
              }
            }
          },
          "404": {
            "description": "Task not found"
          }
        },
        "parameters": [
          {
            "name": "task_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ]
      }
    },
    "/api/v1/tasks/{task_id}/events": {
      "get": {
        "summary": "Get the durable task event log",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "responses": {
          "200": {
            "description": "Success"
          }
        },
        "parameters": [
          {
            "name": "task_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ]
      }
    },
    "/api/v1/tasks/{task_id}/responses": {
      "post": {
        "summary": "Submit an explicitly user-provided Web Council reply",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "responses": {
          "200": {
            "description": "Success"
          }
        },
        "description": "This endpoint never reads browser tabs or provider credentials.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/WebResponse"
              }
            }
          }
        },
        "parameters": [
          {
            "name": "task_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ]
      }
    },
    "/api/v1/tasks/{task_id}/advance": {
      "post": {
        "summary": "Advance Web Council to cross-review",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "responses": {
          "200": {
            "description": "Success"
          }
        },
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": false
              }
            }
          }
        },
        "parameters": [
          {
            "name": "task_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ]
      }
    },
    "/api/v1/tasks/{task_id}/finalize": {
      "post": {
        "summary": "Start final Council synthesis",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "responses": {
          "200": {
            "description": "Success"
          }
        },
        "description": "Returns quickly. Poll the same task_id until terminal.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": false
              }
            }
          }
        },
        "parameters": [
          {
            "name": "task_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ]
      }
    },
    "/api/v1/tasks/{task_id}/approve": {
      "post": {
        "summary": "Record explicit approval for a gated task",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "responses": {
          "200": {
            "description": "Success"
          }
        },
        "description": "Approval is recorded only. This API does not execute merge, push, deploy, main-branch mutation, or credential changes.",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/Approval"
              }
            }
          }
        },
        "parameters": [
          {
            "name": "task_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ]
      }
    }
  },
  "components": {
    "securitySchemes": {
      "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "Nexus connector key"
      }
    },
    "schemas": {
      "CreateTask": {
        "type": "object",
        "required": [
          "alias",
          "prompt"
        ],
        "properties": {
          "alias": {
            "type": "string",
            "description": "Exact registered alias, for example nexus or thinkcenter:jellyfin"
          },
          "prompt": {
            "type": "string"
          },
          "mode": {
            "type": "string",
            "enum": [
              "web-discussion",
              "web-hybrid",
              "council-standard"
            ],
            "default": "web-discussion"
          },
          "requested_actions": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "default": [
              "analyze"
            ]
          },
          "risk_policy": {
            "type": "string",
            "default": "auto_worktree_only"
          },
          "idempotency_key": {
            "type": "string",
            "description": "Optional body fallback; prefer Idempotency-Key header"
          }
        }
      },
      "WebResponse": {
        "type": "object",
        "required": [
          "provider",
          "round",
          "response"
        ],
        "properties": {
          "provider": {
            "type": "string",
            "enum": [
              "chatgpt",
              "claude",
              "gemini"
            ]
          },
          "round": {
            "type": "integer",
            "enum": [
              1,
              2
            ]
          },
          "response": {
            "type": "string"
          }
        }
      },
      "Approval": {
        "type": "object",
        "required": [
          "approval_code"
        ],
        "properties": {
          "approval_code": {
            "type": "string"
          },
          "approved_by": {
            "type": "string",
            "default": "user"
          }
        }
      },
      "Task": {
        "type": "object",
        "properties": {
          "task_id": {
            "type": "string"
          },
          "status": {
            "type": "string"
          },
          "phase": {
            "type": "string"
          },
          "alias": {
            "type": "string"
          },
          "target_device": {
            "type": "string"
          },
          "repo_path": {
            "type": [
              "string",
              "null"
            ]
          },
          "nexus_job_id": {
            "type": [
              "string",
              "null"
            ]
          },
          "nexus_execution_status": {
            "type": "string"
          },
          "council_verdict": {
            "type": [
              "string",
              "null"
            ]
          },
          "machine_acceptance_passed": {
            "type": [
              "boolean",
              "null"
            ]
          },
          "deployment_status": {
            "type": "string"
          },
          "approval": {
            "type": "object"
          },
          "next_action": {
            "type": "string"
          },
          "markdown_digest": {
            "type": "string"
          }
        }
      }
    }
  }
}
```

### Nexus 远程控制 ChatGPT 提示词（原 `nexus-v3-chatgpt-remote-prompt.md`）

```markdown
# Nexus 远程控制器（ChatGPT Instructions）

你通过 Nexus Remote Control API 控制我的设备集群。该 API 模仿 DesktopCommanderMCP 的 Remote MCP 设计：ChatGPT 不直接 SSH、不直接访问本地 shell、不假设自己拥有桌面控制权；所有设备操作都必须通过 Nexus Action 完成。

## 设备与目标规则

1. 只能使用明确的规范设备 ID（canonical device IDs）：`oracle`、`thinkcenter`、`n1`、`vsc`、`victus`、`victus-wsl`、`elitebook`、`ax3600`。
2. 不支持 `all`、`broadcast`、模糊别名或自动猜测目标。
3. 故障切换时不能改变逻辑目标。Nexus 内部可以切换传输路径，例如 ThinkCenter 管理 `n1` / `ax3600` 的 SSH fallback，但你对用户报告的目标仍必须是用户指定的设备。
4. 当设备在线状态、批准状态或区域不明确时，先调用 `listDevices` 或 `getDevice`。

## 可用 Action

- `listDevices`：列出 Nexus 设备，默认只看 `approved`。
- `getDevice`：查询单台已批准设备的公开身份信息。
- `executeCommand`：在一个明确设备上提交一条命令。
- `getJob`：根据 `region` 和 `job_id` 查询任务状态。

## 执行规则

1. 每次 `executeCommand` 只面向一台设备，只提交一条清晰命令。
2. 优先做只读诊断：`hostname`、`uname -a`、`systemctl status`、`df -h`、`ip addr`、`journalctl` 等。
3. 涉及修改时按顺序执行：检查当前状态、备份或保留可恢复路径、最小化变更、验证、必要时 reload/restart、再次验证。
4. 必须等待并报告真实任务结果。不要在没有回执时声称成功。
5. 输出中必须包含 `job_id`、`status`、`exit_code`、`broker_region` 和关键 stdout/stderr。
6. 如果任务未完成，使用 `getJob` 继续查询，不要编造结果。

## 高风险操作

执行以下操作前必须停止并请求用户明确确认：

- 删除大量文件、递归删除、清空目录或不可恢复覆盖。
- reboot、shutdown、断网、修改 SSH/firewall/VPN/路由。
- 修改密码、token、私钥、证书、cookie、MFA 或权限边界。
- 格式化磁盘、改分区、改挂载、改系统启动项。
- 将服务暴露到公网、改变访问控制或反向代理安全策略。

永远不要泄露 token、密码、私钥、cookie、浏览器会话、Bitwarden 机密值或 MFA 内容。需要引用凭据时只说明“使用已配置的环境变量/密钥文件”。

## VSC 特殊约束

VSC 可能位于 HPC 环境，Tailscale 以用户态方式运行。入站 SSH 可能受 HPC 证书策略限制；如需从 VSC 出站访问 tailnet，可使用 Nexus 记录的 ProxyCommand / `tailscale nc` 方案。不要假设 VSC 可以被任意节点直接入站连接。

## 回答格式

每次执行后用以下结构简洁回复：

- 结果：成功、失败、部分完成或等待中。
- 目标：设备 ID 与关键路径。
- 证据：`job_id`、`status`、`exit_code`、`broker_region`、关键输出。
- 变更：实际改动了什么；只读任务写“无”。
- 风险：剩余问题或需要用户确认的下一步。
```

### Nexus 远程控制 API Action JSON（原 `nexus-v3-remote-control-openapi.json`）

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Nexus 远程控制 API",
    "version": "3.0.0",
    "description": "供 ChatGPT 安全调用的 Nexus v3 远程控制适配器，设计形态模仿 DesktopCommanderMCP Remote Gateway。它只暴露已批准设备列表、公开身份查询、单设备命令提交和任务状态查询。"
  },
  "servers": [
    {
      "url": "https://nexus-global-api.bings.app"
    }
  ],
  "security": [
    {
      "BearerAuth": []
    }
  ],
  "paths": {
    "/api/devices": {
      "get": {
        "operationId": "listDevices",
        "summary": "按审批状态列出 Nexus 设备",
        "description": "默认列出 approved 设备。需要排查注册或审批状态时，可传入 pending 等状态。",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "name": "status",
            "in": "query",
            "required": false,
            "description": "设备审批状态，默认 approved。",
            "schema": {
              "type": "string",
              "default": "approved"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "成功返回设备列表。"
          },
          "401": {
            "description": "Bearer token 无效或缺失。"
          },
          "502": {
            "description": "Registry 依赖不可用。"
          }
        }
      }
    },
    "/api/devices/{device_id}": {
      "get": {
        "operationId": "getDevice",
        "summary": "查询一台已批准 Nexus 设备的公开身份",
        "description": "用于确认规范设备 ID、区域、主机名、平台和公开密钥记录。不会返回私钥或 token。",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "name": "device_id",
            "in": "path",
            "required": true,
            "description": "规范设备 ID，例如 thinkcenter、n1、oracle、vsc、victus、victus-wsl、elitebook 或 ax3600。",
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "成功返回设备公开身份。"
          },
          "401": {
            "description": "Bearer token 无效或缺失。"
          },
          "404": {
            "description": "设备不存在或未批准。"
          },
          "502": {
            "description": "Registry 依赖不可用。"
          }
        }
      }
    },
    "/api/commands": {
      "post": {
        "operationId": "executeCommand",
        "summary": "在一台明确指定的 Nexus 设备上执行一条命令",
        "description": "提交一个单设备、单命令任务。默认等待短时间返回终态；若仍在运行，会返回 job_id 与 broker_region，之后用 getJob 继续查询。",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "additionalProperties": false,
                "required": [
                  "device_id",
                  "command"
                ],
                "properties": {
                  "device_id": {
                    "type": "string",
                    "description": "规范设备 ID。"
                  },
                  "command": {
                    "type": "string",
                    "description": "要执行的一条 shell 命令。高风险命令会被安全策略拒绝，除非服务端显式放开。"
                  },
                  "timeout_ms": {
                    "type": "integer",
                    "description": "Agent 侧命令超时时间，单位毫秒。",
                    "default": 30000,
                    "minimum": 1000,
                    "maximum": 86400000
                  },
                  "wait_seconds": {
                    "type": "integer",
                    "description": "Remote Gateway 等待任务完成的秒数。返回非终态时继续用 getJob 查询。",
                    "default": 20,
                    "minimum": 0,
                    "maximum": 120
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "返回终态任务结果，或返回已接受但仍在运行的任务卡片。"
          },
          "400": {
            "description": "请求字段缺失或格式无效。"
          },
          "401": {
            "description": "Bearer token 无效或缺失。"
          },
          "403": {
            "description": "命令被安全策略拒绝。"
          },
          "502": {
            "description": "Registry 或 Broker 依赖不可用。"
          }
        }
      }
    },
    "/api/jobs/{region}/{job_id}": {
      "get": {
        "operationId": "getJob",
        "summary": "从 EU 或 CN Broker 查询 Nexus 任务",
        "description": "根据 executeCommand 返回的 broker_region 和 job_id 查询任务状态与输出。",
        "security": [
          {
            "BearerAuth": []
          }
        ],
        "parameters": [
          {
            "name": "region",
            "in": "path",
            "required": true,
            "description": "Broker 区域。",
            "schema": {
              "type": "string",
              "enum": [
                "eu",
                "cn"
              ]
            }
          },
          {
            "name": "job_id",
            "in": "path",
            "required": true,
            "description": "任务 ID。",
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "成功返回任务状态、退出码和输出。"
          },
          "401": {
            "description": "Bearer token 无效或缺失。"
          },
          "404": {
            "description": "任务不存在。"
          },
          "502": {
            "description": "Broker 依赖不可用。"
          }
        }
      }
    }
  },
  "components": {
    "schemas": {},
    "securitySchemes": {
      "BearerAuth": {
        "type": "http",
        "scheme": "bearer"
      }
    }
  }
}
```

### Nexus Web Assistant 系统提示词（原 `WEB_NEXUS_SYSTEM_PROMPT.md`）

```markdown
# Nexus Web Assistant System Prompt

你可以通过 Nexus 的结构化 Task API 或 MCP 工具操作我的个人集群。

1. 用户要求“使用 Nexus”时，调用 `nexus_create_task` 或 `POST /api/v1/tasks`，不要构造 PowerShell、SSH、shell 或底层 `/api/execute` 请求。
2. 只使用已注册的精确 alias。未知 alias 时展示 Nexus 返回的可用 alias，不自行猜测节点或路径。
3. 保存并明确返回 `task_id`。提交超时后使用相同 idempotency key 或查询原 task，禁止重复创建。
4. 长任务只通过 `nexus_get_task` 或 `GET /api/v1/tasks/{task_id}` 查询。区分：Nexus execution、Council verdict、machine acceptance 与 deployment status。
5. 多模型顾问默认使用 `advisor-turn`：当前 ChatGPT 对话是唯一 orchestrator，Claude Web 与 Gemini Web 只是 advisor。每次 advisor turn 必须发送完整 deterministic `FULL_CONTEXT`，包含原始任务、所有 user/orchestrator/synthesis 事件、所有先前 advisor prompt 和 verbatim response；不得截断、不得摘要、不得默认增量发送，超过 byte limit 时返回 `CONTEXT_TOO_LARGE`。
6. `advisor-turn` 输出必须是稳定 JSON，并保留 room 下 `advisor/transcript.jsonl` 与 deterministic Markdown。重复 idempotency key 不得重复发送；同 key 不同 payload 必须 conflict。
7. 自动 advisor flow 不可用或用户明确要求手动 fallback 时，使用 `web-discussion`；需要在独立 Git worktree 实施时使用 `web-hybrid`。
8. Web Council 的 ChatGPT、Claude、Gemini 回复必须由用户主动提交；不得读取、抓取或控制任何提供商网页、标签页、Cookie、浏览器存储、登录状态或验证码。
9. read-only 与 isolated worktree write 可按策略自动执行。merge、push、deploy、主分支修改、凭据修改及未分类操作必须停在审批门禁，等待用户明确批准。
10. 只有 `machine_acceptance_passed=true` 且 Council verdict 为 `ACCEPT` 时，才能报告实现已验收。除非 `deployment_status` 明确为 completed，否则不得称为已部署。
11. 不因连接中断重新提交任务。保留 task_id 并恢复状态。
12. 最终回复应列出：task_id、节点、repo、状态、Council verdict、验证结果、是否部署及下一步。
```

### Nexus 其他目标与历史思路摘要（原 `其他目标.md`）

```markdown
# Nexus 其他目标与历史思路摘要

本文只保留不属于当前 Nexus v3 主线、但仍有参考价值的目标和设计思想。旧代码、旧验收材料和旧入口已删除，不再作为当前运行事实来源。例外：council 机制保留在 `agent-council/`。

## 当前主线之外的历史架构

### v1：直接 SSH / Webhook

早期思路是让控制端直接 SSH 或通过同步 HTTP 调用执行命令。核心问题是超时、审计弱、失败重试和重复执行难以处理。该方向只保留为“紧急救援通道”的思想，不再作为 Nexus 主链路。

### v2：Supabase CAS 任务队列

v2 使用 Supabase `devices` / `commands` 表做设备目录、心跳和异步任务队列，通过 `pending -> running -> completed` 的 CAS 状态机规避网页端 30 秒超时。这个方案证明了“Agent pull + 后台 job + 可轮询结果”的价值，但缺点是 token 分发、数据库耦合和区域 broker 职责不清。

当前 v3 继承的核心思想：

- 任务异步化，控制端提交后通过 job id 查询结果；
- 目标设备不可随意改派；
- 任务必须有 lease、状态和真实回执；
- 不把长任务绑定在前端 HTTP 请求生命周期上。

被 v3 替代的部分：

- 每设备 token / API key；
- Supabase 作为热队列；
- 旧 Global API / Broker 补丁式演进；
- 旧 Windows/Linux agent 分叉实现。

### v2.5：区域 Broker 与浏览器顾问链路

v2.5 引入 Oracle EU Broker、ThinkCenter CN Broker、目标不可变、execution ledger、Windows worker 超时治理，以及 Claude/Gemini 网页顾问 transcript。旧验收原文已删除，只保留这里的核心思想。

当前 v3 继承的核心思想：

- EU/CN broker 分区；
- command result 必须有 `completed`、`exit_code` 和真实输出；
- 高危命令需要明确确认；
- 浏览器登录态不能被复制或导出；
- Claude/Gemini 之类网页顾问只能作为受控工具，不进入设备鉴权核心。

被 v3 弱化或归档的部分：

- 旧 Browser Bridge 和 Agent Council 运行时；
- Herdr / SuperAssistant 旧插件路径；
- Supabase 目录镜像作为权威状态；
- 旧 `nexus_system_prompt.md` 和旧 Action contract。

## 当前 v3 主线外的可选目标

### 1. VSC inbound SSH

VSC 已加入 Tailscale，用户态节点为 `vsc-tier2`，tailnet IP 为 `100.123.110.53`。因为 VSC 使用 `--tun=userspace-networking`，普通 `ssh 100.x` 不会自动走 Tailscale 路由；VSC 主动访问 tailnet 节点需要使用 `tailscale nc` 或 `ProxyCommand`。

已验证：

- VSC → Oracle / ThinkCenter / N1 / Victus：可通过 `tailscale nc` + Nexus SSH key 登录。
- 其他节点 → VSC：会被 KU Leuven HPC SSH certificate policy 拦截，普通 Nexus public key 不足以登录。

后续若要完成 VSC inbound full mesh，需要走 VSC/HPC 官方 SSH certificate 或门户 key 注册机制，而不是单纯改 `authorized_keys`。

### 2. AX3600 独立 Agent

设计上 AX3600 与 N1 一样，优先作为 OpenWrt agent 自己领取任务；如果设备资源、依赖或网络限制导致自领取不稳定，则由 ThinkCenter 通过 SSH managed target 指挥。

当前判断标准：

- 能稳定运行 `nexus_v3/assets/openwrt_v3_agent.sh`：作为独立 Nexus device；
- 不能稳定自领取：保留在 `NEXUS_V3_MANAGED_TARGETS`，由 ThinkCenter 执行。

### 3. EliteBook 纳管

`elitebook` 已作为 canonical EU device 预留，但未作为当前核心验收节点。后续纳管流程与 `victus` 相同：生成 Nexus API identity、生成 Nexus SSH key、注册到 global registry、管理员批准、同步 SSH public keys、执行只读命令验收。

### 4. Dashboard 动态化

当前 dashboard 以静态布局和可选 `/status.json` 为主。后续可以把 registry/broker 只读状态做成实时聚合，但不能把 admin key、ChatGPT bearer token 或设备私钥暴露给浏览器。

可做但不属于核心控制面的目标：

- 设备在线状态实时刷新；
- 最近任务只读展示；
- SSH mesh 覆盖矩阵；
- VSC userspace Tailscale 状态提示；
- broker region health 卡片。

### 5. 浏览器顾问系统

Claude/Gemini 网页顾问、transcript、cross-review 机制可以作为独立“研究/决策辅助”工具保留，但不应该和 Nexus 设备控制面混在一起。它的核心原则仍然有效：

- 不读取 cookie、密码、localStorage 或 MFA 材料；
- 不绕过 CAPTCHA / 人机验证；
- transcript 必须可审计；
- 失败时明确区分登录、页面、selector、模型响应和超时。

## 已删除的旧目录

- 旧 `mcp_server/`：旧 FastMCP/SSE 服务。
- 旧 `deploy/`：旧 Supabase / Worker / schema 部署材料。
- 旧 `docs/evidence/`：旧架构、验收报告和证据。
- 旧 `install*.sh`、`install.ps1`：旧安装器。
- 旧 `browser-bridge/`：旧 Claude/Gemini browser adapter。
- 旧缓存、临时备份、R2 工具、SuperAssistant 实验文件。

保留例外：`agent-council/`。Council 机制仍可作为 Claude/Gemini 顾问流和交叉讨论机制使用，但不进入 Nexus v3 设备鉴权核心。

恢复原则：需要恢复某个旧思想时，先写成当前 v3 设计，再实现；不要恢复旧运行时代码。
```

### Agent 工作规范（原 `AGENTS.md`）

```markdown
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
```
