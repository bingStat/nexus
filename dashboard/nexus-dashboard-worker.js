const SESSION_COOKIE = '__Host-nexus_session';
const SESSION_TTL_SECONDS = 7 * 24 * 60 * 60;
const AUTH_CODE_TTL_MS = 10 * 60 * 1000;
const ACCESS_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60;

function securityHeaders(extra = {}) {
  return {
    'X-Frame-Options': 'SAMEORIGIN',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    ...extra,
  };
}

function corsHeaders(extra = {}) {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS, HEAD',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, Accept',
    'Access-Control-Max-Age': '86400',
    ...extra,
  };
}

function safeTarget(raw) {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//')) return '/';
  return raw;
}

function htmlEscape(value) {
  if (!value) return '';
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function bytesEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

async function digestText(value) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)));
}

async function passwordMatches(submitted, expected) {
  if (!submitted || !expected) return false;
  const [a, b] = await Promise.all([digestText(submitted), digestText(expected)]);
  return bytesEqual(a, b);
}

function base64url(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function fromBase64url(value) {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = normalized + '='.repeat((4 - normalized.length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, c => c.charCodeAt(0));
}

async function hmacSign(secret, data) {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  return new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(data)));
}

async function signSession(secret, expires) {
  return hmacSign(secret, `nexus:${expires}`);
}

async function sessionCookie(secret) {
  const expires = Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS;
  const signature = base64url(await signSession(secret, expires));
  return `${SESSION_COOKIE}=${expires}.${signature}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${SESSION_TTL_SECONDS}`;
}

function clearSessionCookie() {
  return `${SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`;
}

function cookieValue(request, name) {
  const header = request.headers.get('Cookie') || '';
  for (const part of header.split(';')) {
    const [key, ...rest] = part.trim().split('=');
    if (key === name) return rest.join('=');
  }
  return '';
}

async function hasValidSession(request, secret) {
  const value = cookieValue(request, SESSION_COOKIE);
  const match = /^(\d+)\.([A-Za-z0-9_-]+)$/.exec(value);
  if (!match) return false;
  const expires = Number(match[1]);
  if (!Number.isFinite(expires) || expires <= Math.floor(Date.now() / 1000)) return false;
  try {
    return bytesEqual(fromBase64url(match[2]), await signSession(secret, expires));
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// OAuth 2.0 Helpers (PKCE + Authorization Code + Refresh Tokens)
// ---------------------------------------------------------------------------

async function createAuthCode(secret, payload) {
  const data = JSON.stringify({
    ...payload,
    exp: Date.now() + AUTH_CODE_TTL_MS,
  });
  const dataB64 = base64url(new TextEncoder().encode(data));
  const sig = base64url(await hmacSign(secret, `code:${dataB64}`));
  return `${dataB64}.${sig}`;
}

async function verifyAuthCode(secret, code) {
  const parts = (code || '').split('.');
  if (parts.length !== 2) return null;
  const [dataB64, sig] = parts;
  try {
    const expectedSig = base64url(await hmacSign(secret, `code:${dataB64}`));
    if (sig !== expectedSig) return null;
    const json = new TextDecoder().decode(fromBase64url(dataB64));
    const payload = JSON.parse(json);
    if (!payload.exp || Date.now() > payload.exp) return null;
    return payload;
  } catch {
    return null;
  }
}

async function createAccessToken(secret, sub = 'nexus-user') {
  const exp = Math.floor(Date.now() / 1000) + ACCESS_TOKEN_TTL_SECONDS;
  const data = JSON.stringify({ sub, exp, scope: 'mcp fleet devspace' });
  const dataB64 = base64url(new TextEncoder().encode(data));
  const sig = base64url(await hmacSign(secret, `token:${dataB64}`));
  return `nxt_${dataB64}.${sig}`;
}

async function createRefreshToken(secret, sub = 'nexus-user') {
  const exp = Math.floor(Date.now() / 1000) + (ACCESS_TOKEN_TTL_SECONDS * 2);
  const data = JSON.stringify({ sub, exp, type: 'refresh' });
  const dataB64 = base64url(new TextEncoder().encode(data));
  const sig = base64url(await hmacSign(secret, `ref:${dataB64}`));
  return `nxr_${dataB64}.${sig}`;
}

async function verifyAccessToken(token, secret, apiKey = '') {
  if (!token) return false;
  if (apiKey && token === apiKey) return true;
  if (!token.startsWith('nxt_')) return false;
  const raw = token.slice(4);
  const parts = raw.split('.');
  if (parts.length !== 2) return false;
  const [dataB64, sig] = parts;
  try {
    const secrets = [apiKey, secret].filter((value, index, all) => value && all.indexOf(value) === index);
    let signatureOk = false;
    for (const signingSecret of secrets) {
      const expectedSig = base64url(await hmacSign(signingSecret, `token:${dataB64}`));
      if (sig === expectedSig) { signatureOk = true; break; }
    }
    if (!signatureOk) return false;
    const json = new TextDecoder().decode(fromBase64url(dataB64));
    const payload = JSON.parse(json);
    if (!payload.exp || Math.floor(Date.now() / 1000) > payload.exp) return false;
    return true;
  } catch {
    return false;
  }
}

async function verifyRefreshToken(token, secret, apiKey = '') {
  if (!token || !token.startsWith('nxr_')) return null;
  const raw = token.slice(4);
  const parts = raw.split('.');
  if (parts.length !== 2) return null;
  const [dataB64, sig] = parts;
  try {
    const secrets = [apiKey, secret].filter((value, index, all) => value && all.indexOf(value) === index);
    let signatureOk = false;
    for (const signingSecret of secrets) {
      const expectedSig = base64url(await hmacSign(signingSecret, `ref:${dataB64}`));
      if (sig === expectedSig) { signatureOk = true; break; }
    }
    if (!signatureOk) return null;
    const json = new TextDecoder().decode(fromBase64url(dataB64));
    const payload = JSON.parse(json);
    if (!payload.exp || Math.floor(Date.now() / 1000) > payload.exp) return null;
    return payload;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// HTML Templates
// ---------------------------------------------------------------------------

function loginHtml({ error = false, target = '/' } = {}) {
  const safe = safeTarget(target);
  const action = `/login?to=${encodeURIComponent(safe)}`;
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nexus &#30331;&#24405;</title>
<script>
(() => {
  try {
    const saved = localStorage.getItem('nexus:theme');
    const systemDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.dataset.theme = saved || (systemDark ? 'dark' : 'light');
  } catch (_) { document.documentElement.dataset.theme = 'light'; }
})();
</script>
<style>
:root{color-scheme:light;--font:-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display","Helvetica Neue","Segoe UI","Noto Sans SC",Arial,sans-serif;--bg:#f5f5f7;--surface:rgba(255,255,255,.88);--text:#1d1d1f;--muted:#6e6e73;--border:rgba(0,0,0,.08);--field:#fff;--field-border:#d2d2d7;--blue:#0071e3;--blue-hover:#0077ed;--danger:#d70015;--danger-soft:rgba(215,0,21,.07);--header:rgba(250,250,252,.82);--shadow:0 24px 70px rgba(0,0,0,.08)}
:root[data-theme="dark"]{color-scheme:dark;--bg:#000;--surface:rgba(28,28,30,.90);--text:#f5f5f7;--muted:#a1a1a6;--border:rgba(255,255,255,.10);--field:#2c2c2e;--field-border:rgba(255,255,255,.16);--blue:#2997ff;--blue-hover:#64b5ff;--danger:#ff453a;--danger-soft:rgba(255,69,58,.10);--header:rgba(22,22,23,.82);--shadow:0 24px 70px rgba(0,0,0,.36)}
*{box-sizing:border-box}html{background:var(--bg)}body{margin:0;min-height:100vh;background:var(--bg);color:var(--text);font-family:var(--font);-webkit-font-smoothing:antialiased;letter-spacing:-.005em}
body::before{content:"";position:fixed;inset:0;pointer-events:none;background:radial-gradient(circle at 50% 18%,rgba(0,113,227,.08),transparent 32rem)}
.topbar{position:fixed;inset:0 0 auto;z-index:10;height:48px;background:var(--header);border-bottom:1px solid var(--border);backdrop-filter:saturate(180%) blur(20px);-webkit-backdrop-filter:saturate(180%) blur(20px)}
.topbar-inner{width:min(1164px,100%);height:100%;margin:0 auto;padding:0 32px;display:flex;align-items:center;justify-content:space-between}.wordmark{display:flex;align-items:center;gap:9px}.mark{width:26px;height:26px;border-radius:8px;background:linear-gradient(145deg,#0a84ff,#0066cc);display:grid;place-items:center;color:white;font-size:.84rem;box-shadow:inset 0 1px 0 rgba(255,255,255,.25)}.wordmark-text{display:flex;flex-direction:column}.wordmark strong{font-size:.93rem;font-weight:600;line-height:1.05;letter-spacing:-.02em}.wordmark span{margin-top:2px;color:var(--muted);font-size:.61rem}
.auth-shell{min-height:100vh;padding:88px 20px 40px;display:grid;place-items:center}.card{width:min(420px,100%);padding:34px 34px 30px;background:var(--surface);border:1px solid var(--border);border-radius:24px;box-shadow:var(--shadow);backdrop-filter:blur(22px);-webkit-backdrop-filter:blur(22px)}
.eyebrow{margin:0 0 10px;color:var(--blue);font-size:.72rem;font-weight:600}.title{margin:0;font-size:1.82rem;line-height:1.12;font-weight:600;letter-spacing:-.035em}.lead{margin:10px 0 26px;color:var(--muted);font-size:.91rem;line-height:1.55}
label{display:block;margin:0 0 8px;font-size:.78rem;font-weight:500;color:var(--text)}input{width:100%;height:48px;padding:0 14px;border:1px solid var(--field-border);border-radius:12px;background:var(--field);color:var(--text);font:inherit;font-size:1rem;outline:none;transition:border-color .18s,box-shadow .18s}input:focus{border-color:var(--blue);box-shadow:0 0 0 4px color-mix(in srgb,var(--blue) 16%,transparent)}
button{width:100%;height:46px;margin-top:14px;border:0;border-radius:12px;background:var(--blue);color:#fff;font:inherit;font-size:.94rem;font-weight:600;cursor:pointer;transition:background .18s,transform .08s}button:hover{background:var(--blue-hover)}button:active{transform:scale(.995)}.error{margin:-8px 0 18px;padding:11px 12px;border-radius:12px;background:var(--danger-soft);color:var(--danger);font-size:.78rem;line-height:1.4}.foot{margin-top:20px;text-align:center;color:var(--muted);font-size:.7rem;line-height:1.45}
@media(max-width:520px){.topbar-inner{padding:0 18px}.card{padding:28px 22px 24px;border-radius:20px}.title{font-size:1.58rem}.auth-shell{padding:76px 14px 24px}}
</style></head>
<body><header class="topbar"><div class="topbar-inner"><div class="wordmark"><div class="mark">&#8984;</div><div class="wordmark-text"><strong>Nexus</strong><span>&#38598;&#32676;&#25511;&#21046;&#20013;&#24515;</span></div></div><span style="color:var(--muted);font-size:.7rem">Secure Access</span></div></header><main class="auth-shell"><section class="card"><p class="eyebrow">NEXUS CONTROL PLANE</p><h1 class="title">&#30331;&#24405; Nexus</h1><p class="lead">&#35775;&#38382;&#38598;&#32676;&#29366;&#24577;&#12289;&#35774;&#22791;&#25299;&#25169;&#19982;&#36828;&#31243;&#25511;&#21046;&#26381;&#21153;&#12290;</p>${error ? '<p class="error">&#23494;&#30721;&#38169;&#35823;&#65292;&#35831;&#37325;&#35797;&#12290;</p>' : ''}<form method="post" action="${action}"><label for="password">&#23494;&#30721;</label><input id="password" name="password" type="password" autocomplete="current-password" autofocus required><button type="submit">&#30331;&#24405;</button></form><div class="foot">&#23494;&#30721;&#30001; Bitwarden Password Manager &#31649;&#29702;</div></section></main></body></html>`;
}

function authorizeHtml({ error = false, params = {} } = {}) {
  const clientName = htmlEscape(params.client_name || params.client_id || 'AI Assistant');
  const scopeDesc = 'Nexus 集群管理、远程命令执行与 DevSpace 工作区控制';

  const hiddenFields = Object.entries(params)
    .filter(([k, v]) => v !== undefined && k !== 'client_name')
    .map(([k, v]) => `<input type="hidden" name="${htmlEscape(k)}" value="${htmlEscape(v)}" />`)
    .join('\n');

  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>授权 Nexus MCP 连接</title>
<script>
(() => {
  try {
    const saved = localStorage.getItem('nexus:theme');
    const systemDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.dataset.theme = saved || (systemDark ? 'dark' : 'light');
  } catch (_) {
    document.documentElement.dataset.theme = 'light';
  }
})();
</script>
<style>
:root{
  color-scheme:light;
  --font:-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display","Helvetica Neue","Segoe UI","Noto Sans SC",Arial,sans-serif;
  --bg:#f5f5f7;--surface:#fff;--surface2:#fbfbfd;--text:#1d1d1f;--muted:#6e6e73;
  --border:rgba(0,0,0,.08);--field:#fff;--field-border:#d2d2d7;--blue:#0066cc;
  --blue-hover:#0077ed;--blue-soft:#e8f2ff;--danger:#d70015;--danger-soft:rgba(215,0,21,.07);
  --header:rgba(250,250,252,.82);--shadow:0 18px 54px rgba(0,0,0,.07);
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#000;--surface:#1c1c1e;--surface2:#2c2c2e;--text:#f5f5f7;--muted:#a1a1a6;
  --border:rgba(255,255,255,.10);--field:#2c2c2e;--field-border:rgba(255,255,255,.16);
  --blue:#2997ff;--blue-hover:#64b5ff;--blue-soft:rgba(41,151,255,.15);
  --danger:#ff453a;--danger-soft:rgba(255,69,58,.10);--header:rgba(22,22,23,.82);
  --shadow:0 18px 54px rgba(0,0,0,.34);
}
*{box-sizing:border-box}
html{background:var(--bg)}
body{
  margin:0;min-height:100vh;background:var(--bg);color:var(--text);font-family:var(--font);
  -webkit-font-smoothing:antialiased;letter-spacing:-.005em;
}
.topbar{
  position:fixed;inset:0 0 auto;z-index:10;height:48px;background:var(--header);
  border-bottom:1px solid var(--border);backdrop-filter:saturate(180%) blur(20px);
  -webkit-backdrop-filter:saturate(180%) blur(20px);
}
.topbar-inner{
  width:min(1164px,100%);height:100%;margin:0 auto;padding:0 32px;
  display:flex;align-items:center;justify-content:space-between;
}
.wordmark{display:flex;flex-direction:column;justify-content:center}
.wordmark strong{font-size:1.08rem;font-weight:600;line-height:1.15;letter-spacing:-.02em}
.wordmark span{margin-top:1px;color:var(--muted);font-size:.66rem}
.theme-toggle{
  width:32px;height:32px;padding:0;border:0;border-radius:999px;display:inline-flex;
  align-items:center;justify-content:center;background:rgba(0,0,0,.045);color:var(--text);
  font:inherit;font-size:1rem;line-height:1;cursor:pointer;transition:background .18s ease;
}
.theme-toggle:hover{background:rgba(0,0,0,.085)}
:root[data-theme="dark"] .theme-toggle{background:rgba(255,255,255,.09)}
:root[data-theme="dark"] .theme-toggle:hover{background:rgba(255,255,255,.15)}
.theme-toggle:focus-visible{outline:3px solid rgba(0,102,204,.22);outline-offset:2px}
.auth-shell{min-height:100vh;padding:88px 20px 40px;display:grid;place-items:center}
.card{
  width:min(480px,100%);padding:36px;background:var(--surface);border:1px solid var(--border);
  border-radius:24px;box-shadow:var(--shadow);
}
.eyebrow{margin:0 0 10px;color:var(--blue);font-size:.72rem;font-weight:600;letter-spacing:.01em}
h1{margin:0;font-size:1.8rem;line-height:1.12;font-weight:600;letter-spacing:-.035em}
.lead{margin:10px 0 0;color:var(--muted);font-size:.91rem;line-height:1.55}
.scope-box{
  display:flex;gap:13px;align-items:flex-start;margin:24px 0;padding:16px;
  border-radius:16px;background:var(--surface2);
}
.scope-icon{
  width:30px;height:30px;flex:0 0 auto;border-radius:9px;display:grid;place-items:center;
  background:var(--blue-soft);color:var(--blue);font-size:.9rem;font-weight:700;
}
.scope-copy{min-width:0;color:var(--muted);font-size:.82rem;line-height:1.5}
.scope-copy strong{display:block;margin-bottom:3px;color:var(--text);font-size:.88rem;font-weight:600}
.error{
  margin:0 0 16px;padding:11px 13px;border-radius:12px;background:var(--danger-soft);
  color:var(--danger);font-size:.8rem;line-height:1.45;
}
label{display:block;margin-bottom:8px;color:var(--muted);font-size:.75rem;font-weight:500}
input[type="password"]{
  width:100%;height:50px;padding:0 14px;border:1px solid var(--field-border);border-radius:12px;
  background:var(--field);color:var(--text);font:inherit;font-size:1rem;outline:none;
  transition:border-color .18s ease,box-shadow .18s ease;
}
input[type="password"]:focus{border-color:var(--blue);box-shadow:0 0 0 4px rgba(0,102,204,.12)}
button[type="submit"]{
  width:100%;height:48px;margin-top:16px;border:0;border-radius:999px;background:var(--blue);
  color:#fff;font:inherit;font-size:.9rem;font-weight:600;cursor:pointer;
  transition:background .18s ease,transform .18s ease;
}
button[type="submit"]:hover{background:var(--blue-hover)}
button[type="submit"]:active{transform:scale(.99)}
button[type="submit"]:focus-visible{outline:3px solid rgba(0,102,204,.22);outline-offset:2px}
.foot{margin-top:18px;text-align:center;color:var(--muted);font-size:.69rem;line-height:1.45}
@media(max-width:620px){
  .topbar-inner{padding:0 16px}.wordmark span{display:none}
  .auth-shell{padding:74px 12px 24px}.card{padding:28px 22px;border-radius:20px}
  h1{font-size:1.6rem}.scope-box{margin:20px 0;padding:14px}
}
</style></head>
<body>
<header class="topbar">
  <div class="topbar-inner">
    <div class="wordmark"><strong>Nexus</strong><span>集群控制中心</span></div>
    <button class="theme-toggle" id="theme-toggle" type="button" aria-label="切换夜间模式" title="切换夜间模式"><span id="theme-toggle-icon" aria-hidden="true">☾</span></button>
  </div>
</header>
<main class="auth-shell">
  <section class="card" aria-labelledby="auth-title">
    <p class="eyebrow">Nexus MCP</p>
    <h1 id="auth-title">授权连接</h1>
    <p class="lead">确认此客户端可以连接你的 Nexus 控制平面。</p>
    <div class="scope-box">
      <div class="scope-icon" aria-hidden="true">N</div>
      <div class="scope-copy">
        <strong>${clientName} 请求访问</strong>
        ${scopeDesc}
      </div>
    </div>
    ${error ? '<p class="error" role="alert">密码不正确，请重新输入 Nexus 主密码。</p>' : ''}
    <form method="post" action="/authorize">
      ${hiddenFields}
      <label for="password">Nexus 密码</label>
      <input id="password" name="password" type="password" autocomplete="current-password" autofocus required>
      <button type="submit">批准并授权</button>
    </form>
    <div class="foot">密码由 Bitwarden 管理 · 单点认证访问全部设备</div>
  </section>
</main>
<script>
(() => {
  const root = document.documentElement;
  const button = document.getElementById('theme-toggle');
  const icon = document.getElementById('theme-toggle-icon');
  const sync = () => {
    const dark = root.dataset.theme === 'dark';
    icon.textContent = dark ? '☀' : '☾';
    button.setAttribute('aria-label', dark ? '切换浅色模式' : '切换夜间模式');
    button.setAttribute('title', dark ? '切换浅色模式' : '切换夜间模式');
  };
  button.addEventListener('click', () => {
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('nexus:theme', next); } catch (_) {}
    sync();
  });
  sync();
})();
</script>
</body></html>`;
}
function contentTypeForObject(key) {
  if (key.endsWith('.html')) return 'text/html; charset=utf-8';
  if (key.endsWith('.md')) return 'text/markdown; charset=utf-8';
  if (key.endsWith('.json')) return 'application/json; charset=utf-8';
  if (key.endsWith('.ps1')) return 'text/plain; charset=utf-8';
  if (key.endsWith('.sh')) return 'application/x-sh; charset=utf-8';
  if (key.endsWith('.py')) return 'text/x-python; charset=utf-8';
  if (key.endsWith('.rb')) return 'text/plain; charset=utf-8';
  if (key.endsWith('.mjs')) return 'text/javascript; charset=utf-8';
  return 'application/octet-stream';
}

async function serveR2(env, key, cacheControl = 'public, max-age=60') {
  const obj = await env.NEXUS_BUCKET.get(key);
  if (!obj) return new Response(`R2 object not found: ${key}`, { status: 404, headers: securityHeaders({ 'Content-Type': 'text/plain; charset=utf-8' }) });
  return new Response(await obj.arrayBuffer(), {
    headers: securityHeaders({ 'Content-Type': contentTypeForObject(key), 'Cache-Control': cacheControl, 'X-Powered-By': 'Nexus v3 Remote Control' }),
  });
}

function loginResponse(options = {}, status = 200) {
  return new Response(loginHtml(options), {
    status,
    headers: securityHeaders({
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
    }),
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';
    const origin = url.origin;

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    // -----------------------------------------------------------------------
    // Public Static & R2 Releases
    // -----------------------------------------------------------------------
    if (request.method === 'GET' && path === '/release.json') {
      return serveR2(env, 'release.json');
    }

    // -----------------------------------------------------------------------
    // OAuth 2.0 Discovery Endpoints (RFC 8414 & Protected Resource Metadata)
    // -----------------------------------------------------------------------
    if (path === '/.well-known/oauth-protected-resource') {
      return new Response(JSON.stringify({
        resource: `${origin}/mcp`,
        authorization_servers: [origin],
        scopes_supported: ['mcp', 'fleet', 'devspace'],
        bearer_methods_supported: ['header'],
      }), {
        headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'public, max-age=3600' }),
      });
    }

    if (path === '/.well-known/oauth-authorization-server' || path === '/.well-known/openid-configuration') {
      return new Response(JSON.stringify({
        issuer: origin,
        authorization_endpoint: `${origin}/authorize`,
        token_endpoint: `${origin}/token`,
        registration_endpoint: `${origin}/register`,
        response_types_supported: ['code'],
        grant_types_supported: ['authorization_code', 'refresh_token'],
        code_challenge_methods_supported: ['S256', 'plain'],
        token_endpoint_auth_methods_supported: ['none', 'client_secret_post', 'client_secret_basic'],
        scopes_supported: ['mcp', 'fleet', 'devspace'],
      }), {
        headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'public, max-age=3600' }),
      });
    }

    // -----------------------------------------------------------------------
    // Dynamic Client Registration (RFC 7591)
    // -----------------------------------------------------------------------
    if (path === '/register' && request.method === 'POST') {
      let body = {};
      try { body = await request.json(); } catch {}
      const clientId = `nexus_client_${crypto.randomUUID()}`;
      const clientSecret = crypto.randomUUID().replace(/-/g, '');
      return new Response(JSON.stringify({
        client_id: clientId,
        client_secret: clientSecret,
        client_name: body.client_name || 'ChatGPT/Claude MCP Client',
        redirect_uris: body.redirect_uris || [],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: body.token_endpoint_auth_method || 'none',
        client_id_issued_at: Math.floor(Date.now() / 1000),
      }), {
        status: 201,
        headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }),
      });
    }

    const password = env.NEXUS_PASSWORD;
    if (!password) return new Response('NEXUS_PASSWORD is not configured', { status: 500 });
    const sessionSigningSecret = env.NEXUS_SESSION_SIGNING_SECRET || env.NEXUS_CHATGPT_API_KEY || password;

    // -----------------------------------------------------------------------
    // OAuth Authorization Endpoint (/authorize)
    // -----------------------------------------------------------------------
    if (path === '/authorize') {
      if (request.method === 'GET') {
        const params = {
          client_id: url.searchParams.get('client_id') || '',
          redirect_uri: url.searchParams.get('redirect_uri') || '',
          response_type: url.searchParams.get('response_type') || 'code',
          scope: url.searchParams.get('scope') || '',
          state: url.searchParams.get('state') || '',
          code_challenge: url.searchParams.get('code_challenge') || '',
          code_challenge_method: url.searchParams.get('code_challenge_method') || '',
        };
        return new Response(authorizeHtml({ params }), {
          headers: securityHeaders({ 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' }),
        });
      }

      if (request.method === 'POST') {
        const form = await request.formData();
        const submitted = String(form.get('password') || '');
        const redirectUri = String(form.get('redirect_uri') || '');
        const state = String(form.get('state') || '');
        const clientId = String(form.get('client_id') || '');
        const codeChallenge = String(form.get('code_challenge') || '');
        const codeChallengeMethod = String(form.get('code_challenge_method') || '');

        const params = {
          client_id: clientId,
          redirect_uri: redirectUri,
          state,
          code_challenge: codeChallenge,
          code_challenge_method: codeChallengeMethod,
        };

        if (!(await passwordMatches(submitted, password))) {
          return new Response(authorizeHtml({ error: true, params }), {
            status: 401,
            headers: securityHeaders({ 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' }),
          });
        }

        if (!redirectUri) {
          return new Response('Missing redirect_uri', { status: 400, headers: corsHeaders() });
        }

        const code = await createAuthCode(password, {
          client_id: clientId,
          redirect_uri: redirectUri,
          code_challenge: codeChallenge,
          code_challenge_method: codeChallengeMethod,
        });

        const targetUrl = new URL(redirectUri);
        targetUrl.searchParams.set('code', code);
        if (state) targetUrl.searchParams.set('state', state);

        return Response.redirect(targetUrl.toString(), 302);
      }
      return new Response('Method Not Allowed', { status: 405, headers: { Allow: 'GET, POST' } });
    }

    // -----------------------------------------------------------------------
    // OAuth Token Endpoint (/token)
    // -----------------------------------------------------------------------
    if (path === '/token' && request.method === 'POST') {
      let formParams = new URLSearchParams();
      const contentType = request.headers.get('Content-Type') || '';
      if (contentType.includes('application/json')) {
        try {
          const json = await request.json();
          for (const [k, v] of Object.entries(json)) formParams.set(k, String(v));
        } catch {}
      } else {
        const text = await request.text();
        formParams = new URLSearchParams(text);
      }

      const grantType = formParams.get('grant_type') || '';

      if (grantType === 'authorization_code') {
        const code = formParams.get('code') || '';
        const redirectUri = formParams.get('redirect_uri') || '';
        const codeVerifier = formParams.get('code_verifier') || '';

        const authPayload = await verifyAuthCode(password, code);
        if (!authPayload) {
          return new Response(JSON.stringify({ error: 'invalid_grant', error_description: 'Authorization code is invalid or expired' }), {
            status: 400,
            headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
          });
        }

        if (authPayload.redirect_uri && redirectUri && authPayload.redirect_uri !== redirectUri) {
          return new Response(JSON.stringify({ error: 'invalid_grant', error_description: 'redirect_uri mismatch' }), {
            status: 400,
            headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
          });
        }

        // Verify PKCE
        if (authPayload.code_challenge) {
          if (!codeVerifier) {
            return new Response(JSON.stringify({ error: 'invalid_grant', error_description: 'Missing code_verifier' }), {
              status: 400,
              headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
            });
          }
          let computedChallenge = codeVerifier;
          if (authPayload.code_challenge_method === 'S256') {
            computedChallenge = base64url(await digestText(codeVerifier));
          }
          if (computedChallenge !== authPayload.code_challenge) {
            return new Response(JSON.stringify({ error: 'invalid_grant', error_description: 'PKCE verification failed' }), {
              status: 400,
              headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
            });
          }
        }

        const oauthSigningSecret = env.NEXUS_CHATGPT_API_KEY || password;
        const accessToken = await createAccessToken(oauthSigningSecret, authPayload.client_id);
        const refreshToken = await createRefreshToken(oauthSigningSecret, authPayload.client_id);

        return new Response(JSON.stringify({
          access_token: accessToken,
          token_type: 'Bearer',
          expires_in: ACCESS_TOKEN_TTL_SECONDS,
          refresh_token: refreshToken,
          scope: 'mcp fleet devspace',
        }), {
          status: 200,
          headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }),
        });
      }

      if (grantType === 'refresh_token') {
        const refreshToken = formParams.get('refresh_token') || '';
        const refreshPayload = await verifyRefreshToken(refreshToken, password, env.NEXUS_CHATGPT_API_KEY || '');
        if (!refreshPayload) {
          return new Response(JSON.stringify({ error: 'invalid_grant', error_description: 'Refresh token is invalid or expired' }), {
            status: 400,
            headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
          });
        }
        const oauthSigningSecret = env.NEXUS_CHATGPT_API_KEY || password;
        const accessToken = await createAccessToken(oauthSigningSecret, refreshPayload.sub);
        const newRefreshToken = await createRefreshToken(oauthSigningSecret, refreshPayload.sub);
        return new Response(JSON.stringify({
          access_token: accessToken,
          token_type: 'Bearer',
          expires_in: ACCESS_TOKEN_TTL_SECONDS,
          refresh_token: newRefreshToken,
          scope: 'mcp fleet devspace',
        }), {
          status: 200,
          headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }),
        });
      }

      return new Response(JSON.stringify({ error: 'unsupported_grant_type' }), {
        status: 400,
        headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
      });
    }

    // -----------------------------------------------------------------------
    // MCP Protocol Handler (/mcp & /mcp/*)
    // Supports SSE streaming and Streamable HTTP JSON-RPC 2.0
    // -----------------------------------------------------------------------
    if (path === '/mcp' || path.startsWith('/mcp/')) {
      const authHeader = request.headers.get('Authorization') || '';
      let bearer = '';
      if (authHeader.startsWith('Bearer ')) {
        bearer = authHeader.slice(7).trim();
      }

      const isValidToken = await verifyAccessToken(bearer, password, env.NEXUS_CHATGPT_API_KEY || '');
      if (!isValidToken) {
        return new Response(JSON.stringify({
          jsonrpc: '2.0',
          error: { code: -32000, message: 'Unauthorized: valid OAuth Bearer token required' },
        }), {
          status: 401,
          headers: corsHeaders({
            'Content-Type': 'application/json; charset=utf-8',
            'WWW-Authenticate': `Bearer realm="Nexus MCP", resource_metadata="${origin}/.well-known/oauth-protected-resource"`,
          }),
        });
      }

      // Handle SSE initial handshake (GET /mcp)
      const acceptHeader = request.headers.get('Accept') || '';
      if (request.method === 'GET') {
        if (acceptHeader.includes('text/event-stream')) {
          const endpointUrl = `${origin}/mcp`;
          const sseBody = `event: endpoint\ndata: ${endpointUrl}\n\n`;
          return new Response(sseBody, {
            headers: corsHeaders({
              'Content-Type': 'text/event-stream',
              'Cache-Control': 'no-cache',
              'Connection': 'keep-alive',
            }),
          });
        }
        return new Response(JSON.stringify({
          name: 'Nexus',
          version: '3.2.2',
          protocolVersion: '2024-11-05',
          transport: 'streamable-http',
        }), {
          headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
        });
      }

      // Handle POST JSON-RPC messages
      if (request.method === 'POST') {
        let rpc = {};
        try {
          rpc = await request.json();
        } catch {
          return new Response(JSON.stringify({
            jsonrpc: '2.0',
            id: null,
            error: { code: -32700, message: 'Parse error' },
          }), {
            status: 400,
            headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
          });
        }

        const id = rpc.id !== undefined ? rpc.id : null;
        const method = rpc.method;
        const params = rpc.params || {};

        // 1. initialize
        if (method === 'initialize') {
          return new Response(JSON.stringify({
            jsonrpc: '2.0',
            id,
            result: {
              protocolVersion: '2024-11-05',
              serverInfo: { name: 'Nexus', version: '3.2.2' },
              capabilities: { tools: { listChanged: false } },
              instructions: 'Nexus is the canonical production control interface. When the user says Nexus or @Nexus, use this namespace first. Determine availability from tools registered in the current turn, not prior failures. Call self_test to distinguish client/tool-routing problems from Registry/Broker/Agent failures. Never substitute the target device.',
            },
          }), {
            headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
          });
        }

        // 2. notifications/initialized or ping
        if (method === 'notifications/initialized' || method === 'ping') {
          return new Response(JSON.stringify({ jsonrpc: '2.0', id, result: {} }), {
            headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
          });
        }

        // 3. tools/list
        if (method === 'tools/list') {
          return new Response(JSON.stringify({
            jsonrpc: '2.0',
            id,
            result: {
              tools: [
                {
                  name: 'self_test',
                  description: 'Diagnose the Nexus production control path: Registry, EU/CN Brokers, and Agent presence. Use this before substituting any fallback control path.',
                  inputSchema: { type: 'object', properties: {} },
                },
                {
                  name: 'list_devices',
                  description: 'List all Nexus fleet devices and their live capabilities (devspace/shell).',
                  inputSchema: {
                    type: 'object',
                    properties: { status: { type: 'string', default: 'approved' } },
                  },
                },
                {
                  name: 'get_device',
                  description: 'Get details and public key for a specific named device.',
                  inputSchema: {
                    type: 'object',
                    required: ['device_id'],
                    properties: { device_id: { type: 'string' } },
                  },
                },
                {
                  name: 'fleet_status',
                  description: 'Get real-time operational status for all approved cluster nodes and regional brokers.',
                  inputSchema: { type: 'object', properties: {} },
                },
                {
                  name: 'execute_command',
                  description: 'Execute a shell command on an explicitly named Nexus device (e.g. victus, thinkcenter, oracle, vsc).',
                  inputSchema: {
                    type: 'object',
                    required: ['device_id', 'command'],
                    properties: {
                      device_id: { type: 'string' },
                      command: { type: 'string' },
                      timeout_ms: { type: 'integer', default: 30000 },
                      wait_seconds: { type: 'integer', default: 20 },
                    },
                  },
                },
                {
                  name: 'execute_batch',
                  description: 'Execute up to 16 shell commands concurrently across different named devices.',
                  inputSchema: {
                    type: 'object',
                    required: ['jobs'],
                    properties: {
                      jobs: {
                        type: 'array',
                        items: {
                          type: 'object',
                          required: ['device_id', 'command'],
                          properties: { device_id: { type: 'string' }, command: { type: 'string' } },
                        },
                      },
                      wait_seconds: { type: 'integer', default: 20 },
                    },
                  },
                },
                {
                  name: 'open_workspace',
                  description: 'Open an upstream DevSpace project folder or managed worktree on a named device.',
                  inputSchema: {
                    type: 'object',
                    required: ['device_id', 'path'],
                    properties: {
                      device_id: { type: 'string' },
                      path: { type: 'string' },
                      mode: { type: 'string', enum: ['checkout', 'worktree'], default: 'checkout' },
                      base_ref: { type: 'string', default: '' },
                      wait_seconds: { type: 'integer', default: 20 },
                    },
                  },
                },
                {
                  name: 'read_workspace',
                  description: 'Read a file through the DevSpace runtime on the target device.',
                  inputSchema: {
                    type: 'object',
                    required: ['device_id', 'workspace_id', 'path'],
                    properties: {
                      device_id: { type: 'string' },
                      workspace_id: { type: 'string' },
                      path: { type: 'string' },
                      offset: { type: 'integer' },
                      limit: { type: 'integer' },
                    },
                  },
                },
                {
                  name: 'apply_workspace_patch',
                  description: 'Apply a code patch in an opened DevSpace workspace on the target device.',
                  inputSchema: {
                    type: 'object',
                    required: ['device_id', 'workspace_id', 'patch'],
                    properties: {
                      device_id: { type: 'string' },
                      workspace_id: { type: 'string' },
                      patch: { type: 'string' },
                    },
                  },
                },
                {
                  name: 'exec_workspace_command',
                  description: 'Run a command inside an opened DevSpace workspace.',
                  inputSchema: {
                    type: 'object',
                    required: ['device_id', 'workspace_id', 'command'],
                    properties: {
                      device_id: { type: 'string' },
                      workspace_id: { type: 'string' },
                      command: { type: 'string' },
                      working_directory: { type: 'string' },
                      tty: { type: 'boolean', default: false },
                    },
                  },
                },
                {
                  name: 'write_workspace_stdin',
                  description: 'Interact with or send stdin to a running DevSpace process session.',
                  inputSchema: {
                    type: 'object',
                    required: ['device_id', 'workspace_id', 'session_id'],
                    properties: {
                      device_id: { type: 'string' },
                      workspace_id: { type: 'string' },
                      session_id: { type: 'integer' },
                      chars: { type: 'string', default: '' },
                    },
                  },
                },
                {

                  name: 'get_job',
                  description: 'Query the execution result of an asynchronous Nexus job by ID.',
                  inputSchema: {
                    type: 'object',
                    required: ['job_id', 'region'],
                    properties: {
                      job_id: { type: 'string' },
                      region: { type: 'string', enum: ['eu', 'cn'] },
                    },
                  },
                },
              ],
            },
          }), {
            headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
          });
        }

        // 4. tools/call -> Dispatch to REST control plane (https://nexus-global-api.bings.app)
        if (method === 'tools/call') {
          const toolName = params.name;
          const args = params.arguments || {};
          const apiBase = (env.NEXUS_STATUS_SOURCE_URL || 'https://nexus-global-api.bings.app/api/dashboard-status')
            .replace(/\/api\/(?:status|dashboard-status)$/, '');
          const apiKey = env.NEXUS_CHATGPT_API_KEY || '';

          const apiFetch = async (endpoint, method = 'GET', body = null) => {
            const opts = {
              method,
              headers: {
                'Authorization': `Bearer ${apiKey}`,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
              },
            };
            if (body) opts.body = JSON.stringify(body);
            const resp = await fetch(`${apiBase}${endpoint}`, opts);
            const text = await resp.text();
            try {
              return JSON.parse(text);
            } catch {
              return { status: resp.status, text };
            }
          };

          try {
            let resultData;
            if (toolName === 'self_test') {
              resultData = await apiFetch('/api/self-test');
            } else if (toolName === 'list_devices') {
              resultData = await apiFetch(`/api/devices?status=${encodeURIComponent(args.status || 'approved')}`);
            } else if (toolName === 'get_device') {
              resultData = await apiFetch(`/api/devices/${encodeURIComponent(args.device_id)}`);
            } else if (toolName === 'fleet_status') {
              resultData = await apiFetch('/api/status');
            } else if (toolName === 'execute_command') {
              resultData = await apiFetch('/api/commands', 'POST', {
                device_id: args.device_id,
                command: args.command,
                timeout_ms: args.timeout_ms || 30000,
                wait_seconds: args.wait_seconds !== undefined ? args.wait_seconds : 20,
              });
            } else if (toolName === 'execute_batch') {
              resultData = await apiFetch('/api/commands/batch', 'POST', {
                jobs: args.jobs || [],
                wait_seconds: args.wait_seconds !== undefined ? args.wait_seconds : 20,
              });
            } else if (toolName === 'open_workspace') {
              resultData = await apiFetch('/api/runtime', 'POST', {
                device_id: args.device_id,
                operation: 'workspace.open',
                input: { path: args.path, mode: args.mode || 'checkout', baseRef: args.base_ref || undefined },
                wait_seconds: args.wait_seconds !== undefined ? args.wait_seconds : 20,
              });
            } else if (toolName === 'read_workspace') {
              resultData = await apiFetch('/api/runtime', 'POST', {
                device_id: args.device_id,
                operation: 'workspace.read',
                input: { workspaceId: args.workspace_id, path: args.path, offset: args.offset, limit: args.limit },
                wait_seconds: 20,
              });
            } else if (toolName === 'apply_workspace_patch') {
              resultData = await apiFetch('/api/runtime', 'POST', {
                device_id: args.device_id,
                operation: 'workspace.apply_patch',
                input: { workspaceId: args.workspace_id, patch: args.patch },
                wait_seconds: 20,
              });
            } else if (toolName === 'exec_workspace_command') {
              resultData = await apiFetch('/api/runtime', 'POST', {
                device_id: args.device_id,
                operation: 'workspace.exec',
                input: {
                  workspaceId: args.workspace_id,
                  command: args.command,
                  workingDirectory: args.working_directory || undefined,
                  tty: Boolean(args.tty),
                },
                wait_seconds: 20,
              });
            } else if (toolName === 'write_workspace_stdin') {
              resultData = await apiFetch('/api/runtime', 'POST', {
                device_id: args.device_id,
                operation: 'workspace.write_stdin',
                input: { workspaceId: args.workspace_id, sessionId: args.session_id, chars: args.chars || '' },
                wait_seconds: 20,
              });
            } else if (toolName === 'get_job') {
              resultData = await apiFetch(`/api/jobs/${encodeURIComponent(args.region)}/${encodeURIComponent(args.job_id)}`);
            } else {
              return new Response(JSON.stringify({
                jsonrpc: '2.0',
                id,
                error: { code: -32601, message: `Tool not found: ${toolName}` },
              }), {
                headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
              });
            }

            return new Response(JSON.stringify({
              jsonrpc: '2.0',
              id,
              result: {
                isError: false,
                content: [{ type: 'text', text: JSON.stringify(resultData, null, 2) }],
                structuredContent: resultData,
              },
            }), {
              headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
            });

          } catch (callErr) {
            return new Response(JSON.stringify({
              jsonrpc: '2.0',
              id,
              result: {
                isError: true,
                content: [{ type: 'text', text: `Nexus Error: ${callErr.message || callErr}` }],
              },
            }), {
              headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
            });
          }
        }

        return new Response(JSON.stringify({
          jsonrpc: '2.0',
          id,
          error: { code: -32601, message: `Method not supported: ${method}` },
        }), {
          headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
        });
      }

      return new Response('Method Not Allowed', { status: 405, headers: corsHeaders() });
    }


    // -----------------------------------------------------------------------
    // API Proxy (/api/*)
    // -----------------------------------------------------------------------
    if (path.startsWith('/api/')) {
      const upstreamBase = (env.NEXUS_STATUS_SOURCE_URL || 'https://nexus-global-api.bings.app/api/dashboard-status')
        .replace(/\/api\/(?:status|dashboard-status)$/, '');
      const upstreamUrl = `${upstreamBase}${url.pathname}${url.search}`;
      const upstreamHeaders = new Headers(request.headers);
      if (env.NEXUS_CHATGPT_API_KEY && !upstreamHeaders.has('Authorization')) {
        upstreamHeaders.set('Authorization', `Bearer ${env.NEXUS_CHATGPT_API_KEY}`);
      }
      try {
        const upstreamResp = await fetch(upstreamUrl, {
          method: request.method,
          headers: upstreamHeaders,
          body: request.body,
        });
        const respHeaders = new Headers(upstreamResp.headers);
        for (const [k, v] of Object.entries(corsHeaders())) respHeaders.set(k, v);
        return new Response(upstreamResp.body, {
          status: upstreamResp.status,
          statusText: upstreamResp.statusText,
          headers: respHeaders,
        });
      } catch (err) {
        return new Response(JSON.stringify({ error: 'api_backend_unavailable' }), {
          status: 502,
          headers: corsHeaders({ 'Content-Type': 'application/json' }),
        });
      }
    }

    // -----------------------------------------------------------------------
    // Dashboard Web Routes (/login, /logout, /status.json, /, /index.html)
    // -----------------------------------------------------------------------
    const websitePaths = new Set(['/', '/index.html', '/status.json', '/login', '/logout']);
    if (!websitePaths.has(path)) {
      return new Response('Not Found', { status: 404, headers: securityHeaders({ 'Content-Type': 'text/plain; charset=utf-8' }) });
    }

    if (path === '/login') {
      const target = safeTarget(url.searchParams.get('to') || '/');
      if (request.method === 'GET') {
        if (await hasValidSession(request, sessionSigningSecret)) return Response.redirect(new URL(target, url.origin), 302);
        return loginResponse({ target });
      }
      if (request.method === 'POST') {
        const form = await request.formData();
        const submitted = String(form.get('password') || '');
        if (!(await passwordMatches(submitted, password))) return loginResponse({ error: true, target }, 401);
        return new Response(null, {
          status: 302,
          headers: securityHeaders({ 'Location': target, 'Set-Cookie': await sessionCookie(sessionSigningSecret), 'Cache-Control': 'no-store' }),
        });
      }
      return new Response('Method Not Allowed', { status: 405, headers: { Allow: 'GET, POST' } });
    }

    if (path === '/logout') {
      return new Response(null, {
        status: 302,
        headers: securityHeaders({ 'Location': '/login', 'Set-Cookie': clearSessionCookie(), 'Cache-Control': 'no-store' }),
      });
    }

    if (!(await hasValidSession(request, sessionSigningSecret))) {
      if (path === '/status.json') {
        return new Response(JSON.stringify({ error: 'dashboard session expired' }), {
          status: 401,
          headers: securityHeaders({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }),
        });
      }
      const target = `${url.pathname}${url.search}`;
      return new Response(null, { status: 302, headers: securityHeaders({ 'Location': `/login?to=${encodeURIComponent(target)}`, 'Cache-Control': 'no-store' }) });
    }

    if (path === '/status.json') {
      if (!env.NEXUS_STATUS_SOURCE_URL || !env.NEXUS_CHATGPT_API_KEY) {
        return new Response(JSON.stringify({ error: 'live status source is not configured' }), {
          status: 503,
          headers: securityHeaders({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }),
        });
      }
      try {
        const statusHeaders = { 'Accept': 'application/json' };
        if (!env.NEXUS_STATUS_SOURCE_URL.includes('/api/dashboard-status') && env.NEXUS_CHATGPT_API_KEY) {
          statusHeaders.Authorization = `Bearer ${env.NEXUS_CHATGPT_API_KEY}`;
        }
        const upstream = await fetch(env.NEXUS_STATUS_SOURCE_URL, {
          headers: statusHeaders,
          cf: { cacheTtl: 0, cacheEverything: false },
        });
        if (!upstream.ok) throw new Error(`status source returned ${upstream.status}`);
        const payload = await upstream.json();
        const devices = Array.isArray(payload) ? payload : (payload.devices || []);
        const counts = Array.isArray(payload) ? undefined : payload.counts;
        const brokers = Array.isArray(payload) ? undefined : payload.brokers;
        const total = Array.isArray(payload) ? devices.length : payload.total;
        return new Response(JSON.stringify({ source: 'nexus-chatgpt-remote', updated_at: new Date().toISOString(), devices, counts, brokers, total }), {
          headers: securityHeaders({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Powered-By': 'Nexus v3 Remote Control' }),
        });
      } catch (error) {
        return new Response(JSON.stringify({ error: 'live status source unavailable' }), {
          status: 502,
          headers: securityHeaders({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }),
        });
      }
    }

    const routes = {
      '/': ['index.html', 'text/html; charset=utf-8'],
      '/index.html': ['index.html', 'text/html; charset=utf-8'],
    };
    const route = routes[path];
    if (!route) return new Response('Not Found', { status: 404, headers: securityHeaders({ 'Content-Type': 'text/plain; charset=utf-8' }) });
    const [r2Key, contentType] = route;
    const obj = await env.NEXUS_BUCKET.get(r2Key);
    if (!obj) return new Response(`R2 object not found: ${r2Key}`, { status: 404, headers: securityHeaders({ 'Content-Type': 'text/plain; charset=utf-8' }) });
    return new Response(await obj.arrayBuffer(), {
      headers: securityHeaders({ 'Content-Type': contentType, 'Cache-Control': 'no-store', 'X-Powered-By': 'Nexus v3 Remote Control' }),
    });
  },
};