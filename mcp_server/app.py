from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from fastapi import FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from mcp_server.client import (
    list_devices as api_list_devices,
    list_recent_commands as api_list_recent_commands,
    parse_timestamp,
)
from mcp_server.server import mcp

app = FastAPI(
    title="Nexus MCP Server",
    description="MCP Remote Control Hub Endpoint for Nexus Cluster",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://nexus.bings.app"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

security = HTTPBearer(auto_error=False)

CANONICAL = {
    "thinkcenter": {"thinkcenter", "ThinkCenter"},
    "victus": {"victus", "Yang", "YANG", "victus-windows"},
    "oracle": {"oracle", "oracle-amd"},
    "vsc": {"vsc"},
    "n1": {"n1"},
    "ax3600": {"ax3600"},
}
DISPLAY = {
    "thinkcenter": "ThinkCenter",
    "victus": "Victus",
    "oracle": "Oracle",
    "vsc": "VSC",
    "n1": "N1",
    "ax3600": "AX3600",
}


def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    expected = os.getenv("NEXUS_MCP_TOKEN", "")
    if expected and (not credentials or credentials.credentials != expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Authorization Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _canonical_id(row: dict) -> str:
    raw = str(row.get("device_id") or row.get("name") or "").strip()
    for canonical, aliases in CANONICAL.items():
        if raw in aliases:
            return canonical
    return raw.lower()


def _state(last_seen):
    parsed = parse_timestamp(last_seen)
    if not parsed:
        return "unknown", None
    age = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    if age < 30:
        return "online", age
    if age < 60:
        return "degraded", age
    return "offline", age


def normalized_devices():
    selected = {}
    for row in api_list_devices():
        canonical = _canonical_id(row)
        parsed = parse_timestamp(row.get("last_seen"))
        current = selected.get(canonical)
        current_time = parse_timestamp(current.get("last_seen")) if current else None
        if current is None or (parsed and (not current_time or parsed > current_time)):
            selected[canonical] = row
    result = []
    for canonical, row in selected.items():
        state, age = _state(row.get("last_seen"))
        result.append({
            "device_id": canonical,
            "name": DISPLAY.get(canonical, row.get("name") or canonical),
            "state": state,
            "age_seconds": age,
            "last_seen": row.get("last_seen"),
            "reported_status": row.get("status"),
            "platform": row.get("platform"),
            "agent_version": row.get("agent_version"),
        })
    return sorted(result, key=lambda x: (x["state"] != "online", x["name"].lower()))


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "Nexus MCP Server", "version": "1.1.0"}


@app.get("/dashboard/devices")
def dashboard_devices():
    return normalized_devices()


@app.get("/dashboard/summary")
def dashboard_summary():
    devices = normalized_devices()
    counts = {key: 0 for key in ("online", "degraded", "offline", "unknown")}
    for device in devices:
        counts[device["state"]] = counts.get(device["state"], 0) + 1
    return {"counts": counts, "total": len(devices), "generated_at": datetime.now(timezone.utc).isoformat()}


@app.get("/dashboard/commands")
def dashboard_commands(limit: int = 20):
    return api_list_recent_commands(limit=limit)


DASHBOARD_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nexus Cluster</title><style>
:root{color-scheme:dark;background:#0b1020;color:#e8edf7;font-family:system-ui,-apple-system,sans-serif}body{margin:0;padding:24px;max-width:1180px;margin:auto}.top{display:flex;justify-content:space-between;gap:16px;align-items:center}h1{font-size:24px;margin:0}.muted{color:#9aa7bd}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:22px 0}.card{background:#121a2d;border:1px solid #27334d;border-radius:14px;padding:16px}.value{font-size:30px;font-weight:700}table{width:100%;border-collapse:collapse;background:#121a2d;border-radius:14px;overflow:hidden}th,td{text-align:left;padding:12px;border-bottom:1px solid #27334d;font-size:14px}.badge{display:inline-block;padding:4px 9px;border-radius:999px;font-size:12px}.online{background:#153a2b;color:#7fe0ae}.degraded{background:#4a3b12;color:#ffd978}.offline{background:#4a1f26;color:#ff9ca9}.unknown{background:#293246;color:#bac5da}section{margin-top:24px}button{background:#4466ee;color:white;border:0;border-radius:9px;padding:9px 13px;cursor:pointer}code{color:#b8c6ff}@media(max-width:640px){body{padding:14px}th:nth-child(4),td:nth-child(4){display:none}}
</style></head><body>
<div class="top"><div><h1>Nexus Cluster</h1><div class="muted">设备、连接与任务集中视图</div></div><button id="refresh">刷新</button></div>
<div class="grid" id="metrics"></div>
<section><h2>设备</h2><table><thead><tr><th>设备</th><th>状态</th><th>最后心跳</th><th>版本</th></tr></thead><tbody id="devices"></tbody></table></section>
<section><h2>最近任务</h2><table><thead><tr><th>目标</th><th>状态</th><th>时间</th></tr></thead><tbody id="commands"></tbody></table></section>
<p class="muted" id="updated"></p><script>
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const age=n=>n==null?"未知":n<60?`${n}秒前`:n<3600?`${Math.floor(n/60)}分钟前`:`${Math.floor(n/3600)}小时前`;
async function load(){const [summary,devices,commands]=await Promise.all([fetch("/dashboard/summary").then(r=>r.json()),fetch("/dashboard/devices").then(r=>r.json()),fetch("/dashboard/commands?limit=12").then(r=>r.json())]);const c=summary.counts;document.querySelector("#metrics").innerHTML=[["在线",c.online],["降级",c.degraded],["离线",c.offline],["设备总数",summary.total]].map(([k,v])=>`<div class="card"><div class="muted">${k}</div><div class="value">${v}</div></div>`).join("");document.querySelector("#devices").innerHTML=devices.map(d=>`<tr><td><strong>${esc(d.name)}</strong><br><code>${esc(d.device_id)}</code></td><td><span class="badge ${esc(d.state)}">${esc(d.state)}</span></td><td>${age(d.age_seconds)}</td><td>${esc(d.agent_version||"—")}</td></tr>`).join("");document.querySelector("#commands").innerHTML=commands.map(x=>`<tr><td>${esc(x.target_device)}</td><td><span class="badge ${x.status==="completed"?"online":x.status==="failed"?"offline":"degraded"}">${esc(x.status)}</span></td><td>${esc((x.created_at||"").replace("T"," ").slice(0,19))}</td></tr>`).join("");document.querySelector("#updated").textContent=`更新时间：${new Date().toLocaleString()}`;}
document.querySelector("#refresh").addEventListener("click",load);load().catch(e=>document.querySelector("#updated").textContent="加载失败："+e);setInterval(load,15000);
</script></body></html>'''


@app.get("/", response_class=HTMLResponse)
def dashboard_home():
    return HTMLResponse(DASHBOARD_HTML)


sse_app = mcp.sse_app()
app.mount("/mcp", sse_app)
app.mount("/sse", sse_app)

if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))
