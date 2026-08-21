from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "dashboard" / "nexus-dashboard-worker.js"
WRANGLER = ROOT / "dashboard" / "wrangler.toml"
INDEX = ROOT / "dashboard" / "index.html"


def test_dashboard_uses_single_password_session_auth() -> None:
    source = WORKER.read_text(encoding="utf-8")
    assert "env.NEXUS_PASSWORD" in source
    assert "__Host-nexus_session" in source
    assert "HttpOnly" in source
    assert "SameSite=Strict" in source
    assert "path === '/login'" in source
    assert "path === '/logout'" in source
    assert "Basic " not in source
    assert "AUTH_USER" not in source
    assert 'name="username"' not in source
    assert 'Bitwarden Password Manager' in source
    assert 'Bitwarden Secrets Manager' not in source
    assert "path === '/release.json'" in source
    assert "path === '/status.json'" in source
    assert "path === '/authorize'" in source
    assert "path === '/token'" in source
    assert "path === '/mcp'" in source
    assert "live status source is not configured" in source
    assert "live status source unavailable" in source
    assert "'/install.sh': 'install.sh'" not in source
    assert "path.startsWith('/bootstrap/')" not in source
    assert "path.startsWith('/docs/')" not in source



def test_dashboard_password_is_not_a_wrangler_plaintext_var() -> None:
    config = WRANGLER.read_text(encoding="utf-8")
    assert "NEXUS_PASSWORD" not in config
    assert "NEXUS_CHATGPT_API_KEY" not in config
    assert 'NEXUS_STATUS_SOURCE_URL = "https://nexus-global-api.bings.app/api/status"' in config
    assert "AUTH_USER" not in config


def test_dashboard_compact_layout_and_live_status_contract() -> None:
    source = INDEX.read_text(encoding="utf-8")
    assert "raw.last_seen_at" in source
    assert "status: String(raw.runtime_status || 'unknown')" in source
    assert "runtime_status from the Nexus control plane is the single source of truth" in source
    assert "statusAgeMs" not in source
    assert "STATUS ERROR" in source
    assert 'class="panel compact-details inspector-panel"' in source
    assert 'class="panel compact-details task-panel"' in source
    assert 'id="console-output"' not in source
    assert 'id="cmd-input"' not in source
    assert "roles.slice(0, 2)" in source
    assert "['index.html', 'release.json']" in source
    assert "grid-template-columns: minmax(0,1fr) 258px" in source
