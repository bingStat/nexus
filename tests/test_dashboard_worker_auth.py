from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "dashboard" / "nexus-dashboard-worker.js"
WRANGLER = ROOT / "dashboard" / "wrangler.toml"


def test_dashboard_uses_single_password_session_auth() -> None:
    source = WORKER.read_text(encoding="utf-8")
    assert "env.NEXUS_PASSWORD" in source
    assert "__Host-nexus_session" in source
    assert "HttpOnly" in source
    assert "SameSite=Strict" in source
    assert "path === '/login'" in source
    assert "path === '/logout'" in source
    assert "WWW-Authenticate" not in source
    assert "AUTH_USER" not in source
    assert 'name="username"' not in source
    assert 'Bitwarden Password Manager' in source
    assert 'Bitwarden Secrets Manager' not in source
    assert "'/install.sh': 'install.sh'" in source
    assert "path.startsWith('/bootstrap/')" in source
    assert "path.startsWith('/docs/')" in source


def test_dashboard_password_is_not_a_wrangler_plaintext_var() -> None:
    config = WRANGLER.read_text(encoding="utf-8")
    assert "NEXUS_PASSWORD" not in config
    assert "AUTH_USER" not in config
