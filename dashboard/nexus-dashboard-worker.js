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
    const expectedSig = base64url(await hmacSign(secret, `token:${dataB64}`));
    if (sig !== expectedSig) return false;
    const json = new TextDecoder().decode(fromBase64url(dataB64));
    const payload = JSON.parse(json);
    if (!payload.exp || Math.floor(Date.now() / 1000) > payload.exp) return false;
    return true;
  } catch {
    return false;
  }
}

async function verifyRefreshToken(token, secret) {
  if (!token || !token.startsWith('nxr_')) return null;
  const raw = token.slice(4);
  const parts = raw.split('.');
  if (parts.length !== 2) return null;
  const [dataB64, sig] = parts;
  try {
    const expectedSig = base64url(await hmacSign(secret, `ref:${dataB64}`));
    if (sig !== expectedSig) return null;
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
<title>Nexus Login</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#070b14;color:#eef4ff;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.card{width:min(380px,calc(100vw - 32px));padding:32px 28px 26px;border:1px solid #23304a;border-radius:16px;background:#0d1422;box-shadow:0 18px 60px #0008}.brand{display:flex;align-items:center;gap:12px;margin-bottom:24px}.icon{width:40px;height:40px;border-radius:11px;display:grid;place-items:center;background:linear-gradient(135deg,#4f8eff,#a855f7);font-size:20px;box-shadow:0 0 24px #4f8eff55}.title{font-size:18px;font-weight:800;letter-spacing:.18em}.sub{font-size:12px;color:#8192b1;margin-top:3px}label{display:block;font-size:12px;color:#9aabc7;margin-bottom:8px}input{width:100%;height:44px;border:1px solid #2a3957;border-radius:9px;background:#080d17;color:#fff;padding:0 12px;font-size:15px;outline:none}input:focus{border-color:#4f8eff;box-shadow:0 0 0 3px #4f8eff22}button{width:100%;height:42px;margin-top:14px;border:0;border-radius:9px;background:#4f8eff;color:white;font-weight:700;cursor:pointer;font-size:14px}button:hover{background:#3b7ce8}.error{margin:0 0 12px;color:#ff718c;font-size:12px}.foot{margin-top:18px;text-align:center;color:#667794;font-size:11px}</style></head>
<body><main class="card"><div class="brand"><div class="icon">⚡</div><div><div class="title">NEXUS</div><div class="sub">v3 Remote Control Plane</div></div></div>${error ? '<p class="error">密码不正确，请重试。</p>' : ''}<form method="post" action="${action}"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" autofocus required><button type="submit">登录</button></form><div class="foot">Password managed by Bitwarden Password Manager</div></main></body></html>`;
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
<title>授权 Nexus MCP 连接</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#070b14;color:#eef4ff;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.card{width:min(440px,calc(100vw - 32px));padding:32px 28px;border:1px solid #23304a;border-radius:18px;background:#0d1422;box-shadow:0 24px 80px rgba(0,0,0,.6)}.brand{display:flex;align-items:center;gap:12px;margin-bottom:20px}.icon{width:44px;height:44px;border-radius:12px;display:grid;place-items:center;background:linear-gradient(135deg,#38bdf8,#818cf8);font-size:22px;box-shadow:0 0 24px #38bdf855}.title{font-size:18px;font-weight:800;letter-spacing:.15em}.sub{font-size:12px;color:#8192b1;margin-top:2px}h2{font-size:16px;margin:0 0 12px;color:#f1f5f9}.scope-box{background:#080d17;border:1px solid #1e293b;border-radius:10px;padding:12px 14px;margin-bottom:18px;font-size:13px;color:#94a3b8;line-height:1.5}.scope-box strong{color:#38bdf8;display:block;margin-bottom:4px}label{display:block;font-size:12px;color:#9aabc7;margin-bottom:8px}input[type="password"]{width:100%;height:44px;border:1px solid #2a3957;border-radius:9px;background:#080d17;color:#fff;padding:0 12px;font-size:15px;outline:none}input[type="password"]:focus{border-color:#38bdf8;box-shadow:0 0 0 3px #38bdf822}button{width:100%;height:44px;margin-top:16px;border:0;border-radius:9px;background:#38bdf8;color:#020617;font-weight:700;font-size:14px;cursor:pointer}button:hover{background:#0ea5e9}.error{margin:0 0 12px;color:#ff718c;font-size:12px;background:#7f1d1d33;padding:8px 12px;border-radius:6px;border:1px solid #ff718c44}.foot{margin-top:18px;text-align:center;color:#64748b;font-size:11px}</style></head>
<body><main class="card"><div class="brand"><div class="icon">⚡</div><div><div class="title">NEXUS</div><div class="sub">Distributed Fleet & DevSpace MCP</div></div></div>
<h2>授权连接</h2>
<div class="scope-box">
  <strong>${clientName} 请求访问：</strong>
  ${scopeDesc}
</div>
${error ? '<p class="error">密码不正确，请重新输入 Nexus 主密码。</p>' : ''}
<form method="post" action="/authorize">
  ${hiddenFields}
  <label for="password">输入 Nexus 密码以批准连接</label>
  <input id="password" name="password" type="password" autocomplete="current-password" autofocus required>
  <button type="submit">批准并授权</button>
</form>
<div class="foot">密码由 Bitwarden 管理 · 单点认证访问全部设备</div>
</main></body></html>`;
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

        const accessToken = await createAccessToken(password, authPayload.client_id);
        const refreshToken = await createRefreshToken(password, authPayload.client_id);

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
        const refreshPayload = await verifyRefreshToken(refreshToken, password);
        if (!refreshPayload) {
          return new Response(JSON.stringify({ error: 'invalid_grant', error_description: 'Refresh token is invalid or expired' }), {
            status: 400,
            headers: corsHeaders({ 'Content-Type': 'application/json; charset=utf-8' }),
          });
        }
        const accessToken = await createAccessToken(password, refreshPayload.sub);
        const newRefreshToken = await createRefreshToken(password, refreshPayload.sub);
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
          name: 'Nexus v3 Control Plane',
          version: '3.1.0',
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
              serverInfo: { name: 'Nexus v3 Control Plane', version: '3.1.0' },
              capabilities: { tools: { listChanged: false } },
              instructions: 'Nexus is a distributed DevSpace and multi-device fleet control plane. Target devices explicitly (oracle, thinkcenter, victus, victus-wsl, vsc, n1, ax3600).',
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
          const apiBase = (env.NEXUS_STATUS_SOURCE_URL || 'https://nexus-global-api.bings.app/api/status')
            .replace(/\/api\/status$/, '');
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
            if (!resp.ok) {
              const text = await resp.text();
              throw new Error(`API HTTP ${resp.status}: ${text}`);
            }
            return resp.json();
          };

          try {
            let resultData = null;
            if (toolName === 'list_devices') {
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
                content: [{ type: 'text', text: JSON.stringify(resultData, null, 2) }],
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
      const upstreamBase = (env.NEXUS_STATUS_SOURCE_URL || 'https://nexus-global-api.bings.app/api/status')
        .replace(/\/api\/status$/, '');
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

    if (path === '/status.json') {
      if (!env.NEXUS_STATUS_SOURCE_URL || !env.NEXUS_CHATGPT_API_KEY) {
        return new Response(JSON.stringify({ error: 'live status source is not configured' }), {
          status: 503,
          headers: securityHeaders({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }),
        });
      }
      try {
        const upstream = await fetch(env.NEXUS_STATUS_SOURCE_URL, {
          headers: { 'Authorization': `Bearer ${env.NEXUS_CHATGPT_API_KEY}`, 'Accept': 'application/json' },
          cf: { cacheTtl: 0, cacheEverything: false },
        });
        if (!upstream.ok) throw new Error(`status source returned ${upstream.status}`);
        const payload = await upstream.json();
        const devices = Array.isArray(payload) ? payload : (payload.devices || []);
        const counts = Array.isArray(payload) ? undefined : payload.counts;
        return new Response(JSON.stringify({ source: 'nexus-chatgpt-remote', updated_at: new Date().toISOString(), devices, counts }), {
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
      headers: securityHeaders({ 'Content-Type': contentType, 'Cache-Control': 'no-cache, max-age=60', 'X-Powered-By': 'Nexus v3 Remote Control' }),
    });
  },
};