#!/usr/bin/env node
import readline from "node:readline";
import { mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

import { loadConfig } from "@waishnav/devspace/dist/config.js";
import { WorkspaceRegistry } from "@waishnav/devspace/dist/workspaces.js";
import { readFileTool } from "@waishnav/devspace/dist/pi-tools.js";
import { applyPatch } from "@waishnav/devspace/dist/apply-patch.js";
import { ProcessSessionManager } from "@waishnav/devspace/dist/process-sessions.js";

const VERSION = "0.1.0";
const roots = (process.env.NEXUS_DEVSPACE_ALLOWED_ROOTS || process.cwd())
  .split(process.platform === "win32" ? ";" : ":")
  .map((value) => value.trim())
  .filter(Boolean)
  .map((value) => resolve(value));
const stateRoot = resolve(
  process.env.NEXUS_DEVSPACE_STATE_DIR || join(homedir(), ".nexus", "devspace"),
);
mkdirSync(stateRoot, { recursive: true });

const config = loadConfig({
  ...process.env,
  DEVSPACE_OAUTH_OWNER_TOKEN: "nexus-local-runtime-not-http-exposed",
  DEVSPACE_ALLOWED_ROOTS: roots.join(","),
  DEVSPACE_STATE_DIR: join(stateRoot, "state"),
  DEVSPACE_WORKTREE_ROOT: join(stateRoot, "worktrees"),
  DEVSPACE_WIDGETS: "off",
  DEVSPACE_TOOL_MODE: "codex",
  DEVSPACE_LOG_LEVEL: "silent",
  DEVSPACE_LOG_REQUESTS: "0",
  DEVSPACE_LOG_TOOL_CALLS: "0",
});

const workspaces = new WorkspaceRegistry(config);
const processes = new ProcessSessionManager();

function textContent(content = []) {
  return content
    .filter((item) => item?.type === "text")
    .map((item) => item.text)
    .join("\n");
}

function workspaceSummary(context) {
  const { workspace } = context;
  return {
    workspaceId: workspace.id,
    root: workspace.root,
    mode: workspace.mode,
    sourceRoot: workspace.sourceRoot,
    worktree: workspace.worktree,
    workspaceReused: context.workspaceReused,
    agentsFiles: context.agentsFiles,
    availableAgentsFiles: context.availableAgentsFiles,
    skills: workspace.skills.map(({ name, description, path }) => ({ name, description, path })),
    agents: workspace.agentProfiles.map(({ name, description, provider, model, thinking }) => ({
      name,
      description,
      provider,
      model,
      thinking,
    })),
  };
}

async function dispatch(request) {
  const operation = String(request.operation || "");
  const input = request.input || {};

  if (operation === "runtime.info") {
    const pkg = await import("@waishnav/devspace/package.json", { with: { type: "json" } });
    return {
      bridgeVersion: VERSION,
      devspaceVersion: pkg.default.version,
      allowedRoots: config.allowedRoots,
      operations: [
        "workspace.open",
        "workspace.read",
        "workspace.apply_patch",
        "workspace.exec",
        "workspace.write_stdin",
      ],
    };
  }

  if (operation === "workspace.open") {
    const context = await workspaces.openWorkspace({
      path: input.path,
      mode: input.mode || "checkout",
      ...(input.baseRef ? { baseRef: input.baseRef } : {}),
    });
    return workspaceSummary(context);
  }

  const workspaceId = String(input.workspaceId || "");
  if (!workspaceId) throw new Error(`${operation} requires workspaceId`);
  const workspace = workspaces.getWorkspace(workspaceId);

  if (operation === "workspace.read") {
    const readPath = workspaces.resolveReadPath(workspace, String(input.path || ""));
    const response = await readFileTool(
      {
        path: readPath.absolutePath,
        ...(input.offset !== undefined ? { offset: Number(input.offset) } : {}),
        ...(input.limit !== undefined ? { limit: Number(input.limit) } : {}),
      },
      { cwd: workspace.root, root: workspace.root, readRoots: readPath.readRoots },
    );
    if (response.isError) throw new Error(textContent(response.content) || "DevSpace read failed");
    workspaces.markReadPathLoaded(workspace, readPath);
    return { content: response.content, text: textContent(response.content) };
  }

  if (operation === "workspace.apply_patch") {
    const applied = await applyPatch(workspace.root, String(input.patch || ""));
    return applied;
  }

  if (operation === "workspace.exec") {
    const cwd = workspaces.resolveWorkingDirectory(workspace, input.workingDirectory);
    return await processes.start({
      workspaceId,
      command: String(input.command || ""),
      cwd,
      workspaceRoot: workspace.root,
      tty: Boolean(input.tty),
      ...(input.yieldTimeMs !== undefined ? { yieldTimeMs: Number(input.yieldTimeMs) } : {}),
      ...(input.maxOutputTokens !== undefined
        ? { maxOutputTokens: Number(input.maxOutputTokens) }
        : {}),
    });
  }

  if (operation === "workspace.write_stdin") {
    return await processes.write({
      workspaceId,
      sessionId: Number(input.sessionId),
      ...(input.chars !== undefined ? { chars: String(input.chars) } : {}),
      ...(input.columns !== undefined ? { columns: Number(input.columns) } : {}),
      ...(input.rows !== undefined ? { rows: Number(input.rows) } : {}),
      ...(input.yieldTimeMs !== undefined ? { yieldTimeMs: Number(input.yieldTimeMs) } : {}),
      ...(input.maxOutputTokens !== undefined
        ? { maxOutputTokens: Number(input.maxOutputTokens) }
        : {}),
    });
  }

  throw new Error(`unsupported DevSpace runtime operation: ${operation}`);

}

async function handleLine(line) {
  const request = JSON.parse(line);
  const id = request.id ?? null;
  try {
    return { id, ok: true, result: await dispatch(request) };
  } catch (error) {
    return {
      id,
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

if (process.argv.includes("--self-test")) {
  const response = await handleLine(JSON.stringify({ id: "self-test", operation: "runtime.info" }));
  process.stdout.write(`${JSON.stringify(response)}\n`);
  process.exit(response.ok ? 0 : 1);
}

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of rl) {
  if (!line.trim()) continue;
  const response = await handleLine(line);
  process.stdout.write(`${JSON.stringify(response)}\n`);
}
processes.shutdown();
