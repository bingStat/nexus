const SESSION_COOKIE = '__Host-nexus_session';
const SESSION_TTL_SECONDS = 7 * 24 * 60 * 60;

function securityHeaders(extra = {}) {
  return {
    'X-Frame-Options': 'SAMEORIGIN',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    ...extra,
  };
}

function safeTarget(raw) {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//')) return '/';
  return raw;
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

async function signSession(secret, expires) {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  return new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`nexus:${expires}`)));
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

function loginHtml({ error = false, target = '/' } = {}) {
  const safe = safeTarget(target);
  const action = `/login?to=${encodeURIComponent(safe)}`;
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nexus Login</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#070b14;color:#eef4ff;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.card{width:min(360px,calc(100vw - 32px));padding:30px 28px 26px;border:1px solid #23304a;border-radius:16px;background:#0d1422;box-shadow:0 18px 60px #0008}.brand{display:flex;align-items:center;gap:12px;margin-bottom:24px}.icon{width:40px;height:40px;border-radius:11px;display:grid;place-items:center;background:linear-gradient(135deg,#4f8eff,#a855f7);font-size:20px;box-shadow:0 0 24px #4f8eff55}.title{font-size:18px;font-weight:800;letter-spacing:.18em}.sub{font-size:12px;color:#8192b1;margin-top:3px}label{display:block;font-size:12px;color:#9aabc7;margin-bottom:8px}input{width:100%;height:44px;border:1px solid #2a3957;border-radius:9px;background:#080d17;color:#fff;padding:0 12px;font-size:15px;outline:none}input:focus{border-color:#4f8eff;box-shadow:0 0 0 3px #4f8eff22}button{width:100%;height:42px;margin-top:14px;border:0;border-radius:9px;background:#4f8eff;color:white;font-weight:700;cursor:pointer}.error{margin:0 0 12px;color:#ff718c;font-size:12px}.foot{margin-top:18px;text-align:center;color:#667794;font-size:11px}</style></head>
<body><main class="card"><div class="brand"><div class="icon">⚡</div><div><div class="title">NEXUS</div><div class="sub">v3 Remote Control Plane</div></div></div>${error ? '<p class="error">密码不正确，请重试。</p>' : ''}<form method="post" action="${action}"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" autofocus required><button type="submit">登录</button></form><div class="foot">Password managed by Bitwarden Password Manager</div></main></body></html>`;
}

function loginResponse(options = {}, status = 200) {
  return new Response(loginHtml(options), {
    status,
    headers: securityHeaders({
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
      'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
      'X-Frame-Options': 'DENY',
    }),
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';
    const password = env.NEXUS_PASSWORD;
    if (!password) return new Response('NEXUS_PASSWORD is not configured', { status: 500 });

    if (path === '/login') {
      const target = safeTarget(url.searchParams.get('to') || '/');
      if (request.method === 'GET') {
        if (await hasValidSession(request, password)) return Response.redirect(new URL(target, url.origin), 302);
        return loginResponse({ target });
      }
      if (request.method === 'POST') {
        const form = await request.formData();
        const submitted = String(form.get('password') || '');
        if (!(await passwordMatches(submitted, password))) return loginResponse({ error: true, target }, 401);
        return new Response(null, {
          status: 302,
          headers: securityHeaders({ 'Location': target, 'Set-Cookie': await sessionCookie(password), 'Cache-Control': 'no-store' }),
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

    if (!(await hasValidSession(request, password))) {
      const target = `${url.pathname}${url.search}`;
      return new Response(null, { status: 302, headers: securityHeaders({ 'Location': `/login?to=${encodeURIComponent(target)}`, 'Cache-Control': 'no-store' }) });
    }

    if (path === '/status.json' && env.NEXUS_STATUS_SOURCE_URL && env.NEXUS_CHATGPT_API_KEY) {
      const upstream = await fetch(env.NEXUS_STATUS_SOURCE_URL, {
        headers: { 'Authorization': `Bearer ${env.NEXUS_CHATGPT_API_KEY}`, 'Accept': 'application/json' },
        cf: { cacheTtl: 0, cacheEverything: false },
      });
      if (upstream.ok) {
        const payload = await upstream.json();
        const devices = Array.isArray(payload) ? payload : (payload.devices || []);
        return new Response(JSON.stringify({ source: 'nexus-chatgpt-remote', updated_at: new Date().toISOString(), devices }), {
          headers: securityHeaders({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Powered-By': 'Nexus v3 Remote Control' }),
        });
      }
    }

    const routes = {
      '/': ['index.html', 'text/html; charset=utf-8'],
      '/index.html': ['index.html', 'text/html; charset=utf-8'],
      '/README.md': ['README.md', 'text/markdown; charset=utf-8'],
      '/install.sh': ['install.sh', 'application/x-sh; charset=utf-8'],
      '/install.ps1': ['install.ps1', 'text/plain; charset=utf-8'],
      '/chatgpt-prompt.md': ['nexus-v3-chatgpt-remote-prompt.md', 'text/markdown; charset=utf-8'],
      '/openapi.json': ['nexus-v3-remote-control-openapi.json', 'application/json; charset=utf-8'],
      '/release.json': ['release.json', 'application/json; charset=utf-8'],
      '/status.json': ['status.json', 'application/json; charset=utf-8'],
    };
    const route = routes[path];
    if (!route) return new Response('Not Found', { status: 404, headers: securityHeaders({ 'Content-Type': 'text/plain; charset=utf-8' }) });
    const [r2Key, contentType] = route;
    const obj = await env.NEXUS_BUCKET.get(r2Key);
    if (!obj) return new Response(`R2 object not found: ${r2Key}`, { status: 404, headers: securityHeaders({ 'Content-Type': 'text/plain; charset=utf-8' }) });
    return new Response(await obj.arrayBuffer(), {
      headers: securityHeaders({ 'Content-Type': contentType, 'Cache-Control': 'no-cache, max-age=60', 'X-Powered-By': 'Nexus v3 Remote Control' }),
    });
  },
};