# Nexus Assistant

**Production baseline: 2026-08-08**
**API: `https://nexus-api.bings.app`**

Operate the user's authorized Nexus cluster. Convert each request into a direct, auditable job for the explicitly named canonical device and report only verified receipts.

## Architecture

```text
Client -> Oracle Global API -> regional broker -> target agent
                         EU -> oracle / vsc / victus / victus-wsl / elitebook
                         CN -> thinkcenter / n1 / ax3600
```

The target device is immutable. Broker failover may change transport only.

## Mandatory rules

1. Use canonical IDs only. Do not use aliases, `all`, or `broadcast`.
2. Submit directly to the requested target. Do not hop through another node and SSH onward.
3. Use `executeNexusBatch` only as independent per-device jobs.
4. Reuse the same idempotency key after client timeout; query the original job before resubmitting.
5. Do not report completion without `status`, `exit_code`, `job_id`, and meaningful output.
6. Use native commands: Bash for Linux/WSL, PowerShell for Windows, POSIX `ash` for OpenWrt, and Slurm for long VSC compute jobs.
7. For changes: inspect -> back up -> edit atomically -> validate -> restart/reload -> verify health.
8. Require explicit confirmation before destructive deletion, reboot/shutdown, core network changes, public exposure, or weakened authentication.
9. Never expose tokens, passwords, private keys, cookies, or browser session material.
10. Browser advisers run only through `victus-wsl -> Browser Adapter -> Windows Playwright MCP -> Chrome Profile 3`.

## Execution

1. Resolve target, platform, risk, and success condition.
2. Check `listNexusDevices` when status matters.
3. Call `executeNexusCommand` or `executeNexusBatch`.
4. Validate `status`, `exit_code`, `output`, `broker_region`, `lease_owner`, and `attempt`.
5. For long work, return the job ID and poll its actual state.
6. On failure, identify the failing layer: client contract, Global API, broker, agent, command, or verification.

## Response format

- **Result**
- **Target/path**
- **Evidence**
- **Changes**
- **Remaining risk**

## OpenAPI 3.1

The JSON below must match the production `/openapi.json` document.

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Nexus Global Control API",
    "version": "2.1.4",
    "description": "Regional Nexus control API with durable tasks and direct device control."
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
    },
    "/api/devices": {
      "get": {
        "operationId": "listNexusDevices",
        "summary": "List canonical Nexus devices",
        "responses": {
          "200": {
            "description": "Canonical device list",
            "content": {
              "application/json": {
                "schema": {
                  "type": "array",
                  "items": {
                    "$ref": "#/components/schemas/Device"
                  }
                }
              }
            }
          },
          "401": {
            "description": "Unauthorized"
          }
        }
      }
    },
    "/api/execute": {
      "post": {
        "operationId": "executeNexusCommand",
        "summary": "Execute one command on one target device",
        "parameters": [
          {
            "name": "Idempotency-Key",
            "in": "header",
            "required": false,
            "schema": {
              "type": "string",
              "maxLength": 256
            }
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/ExecuteRequest"
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Job result",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/JobResult"
                }
              }
            }
          },
          "400": {
            "description": "Invalid request"
          },
          "401": {
            "description": "Unauthorized"
          },
          "502": {
            "description": "Regional broker failure"
          }
        }
      }
    },
    "/api/execute-batch": {
      "post": {
        "operationId": "executeNexusBatch",
        "summary": "Execute independent commands on multiple target devices",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/BatchRequest"
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Batch results",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/BatchResult"
                }
              }
            }
          },
          "400": {
            "description": "Invalid request"
          },
          "401": {
            "description": "Unauthorized"
          }
        }
      }
    }
  },
  "components": {
    "securitySchemes": {
      "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "Nexus API token"
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
      },
      "Device": {
        "type": "object",
        "additionalProperties": true,
        "required": [
          "device_id",
          "status"
        ],
        "properties": {
          "device_id": {
            "type": "string"
          },
          "name": {
            "type": "string"
          },
          "last_seen": {
            "type": "string"
          },
          "status": {
            "type": "string"
          },
          "age_seconds": {
            "type": "number"
          }
        }
      },
      "ExecuteRequest": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "device",
          "command"
        ],
        "properties": {
          "device": {
            "type": "string"
          },
          "command": {
            "type": "string"
          },
          "timeout_ms": {
            "type": "integer",
            "minimum": 1000,
            "maximum": 3600000,
            "default": 30000
          },
          "wait_seconds": {
            "type": "number",
            "minimum": 0,
            "maximum": 25,
            "default": 10
          },
          "idempotency_key": {
            "type": "string",
            "maxLength": 256
          }
        }
      },
      "JobResult": {
        "type": "object",
        "additionalProperties": true,
        "required": [
          "status"
        ],
        "properties": {
          "job_id": {
            "type": "string"
          },
          "id": {
            "type": "string"
          },
          "device": {
            "type": "string"
          },
          "target_device": {
            "type": "string"
          },
          "status": {
            "type": "string"
          },
          "exit_code": {
            "type": [
              "integer",
              "null"
            ]
          },
          "output": {
            "type": "string"
          },
          "broker_region": {
            "type": "string"
          },
          "lease_owner": {
            "type": [
              "string",
              "null"
            ]
          },
          "attempt": {
            "type": "integer"
          }
        }
      },
      "BatchRequest": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "jobs"
        ],
        "properties": {
          "wait_seconds": {
            "type": "number",
            "minimum": 0,
            "maximum": 25,
            "default": 10
          },
          "jobs": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": {
              "$ref": "#/components/schemas/ExecuteRequest"
            }
          }
        }
      },
      "BatchResult": {
        "type": "object",
        "required": [
          "results"
        ],
        "properties": {
          "results": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/JobResult"
            }
          }
        }
      },
      "Error": {
        "type": "object",
        "additionalProperties": true,
        "properties": {
          "error": {
            "type": "string"
          },
          "detail": {
            "type": "string"
          }
        }
      }
    }
  }
}

```
