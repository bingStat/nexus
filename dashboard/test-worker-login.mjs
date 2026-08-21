import fs from 'node:fs';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';

const source = fs.readFileSync(new URL('./nexus-dashboard-worker.js', import.meta.url), 'utf8');
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const { default: worker } = await import(moduleUrl);

const objects = new Map([
  ['index.html', '<html>Nexus dashboard</html>'],
  ['release.json', '{\"commit\":\"test\"}'],
]);

const env = {
  NEXUS_PASSWORD: 'correct horse battery staple',
  NEXUS_STATUS_SOURCE_URL: 'https://nexus-global-api.bings.app/api/status',
  NEXUS_CHATGPT_API_KEY: 'test-api-key',
  NEXUS_MCP_BACKEND_URL: 'https://nexus-global-api.bings.app',
  NEXUS_BUCKET: {
    async get(key) {
      if (!objects.has(key)) return null;
      const bytes = new TextEncoder().encode(objects.get(key));
      return { async arrayBuffer() { return bytes.buffer; } };
    },
  },
};

const nativeFetch = globalThis.fetch;
globalThis.fetch = async (url, options = {}) => {
  const urlStr = String(url);
  if (urlStr === env.NEXUS_STATUS_SOURCE_URL) {
    assert.equal(options.headers.get?.('Authorization') || options.headers?.Authorization, 'Bearer test-api-key');
    return new Response(JSON.stringify({
      counts: { online: 6, degraded: 0, offline: 0, unknown: 0 },
      devices: [{ device_id: 'oracle', runtime_status: 'online' }],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }
  if (urlStr === 'https://nexus-global-api.bings.app/api/self-test') {
    return new Response(JSON.stringify({
      status: 'ok', service: 'nexus', version: '3.2.2',
      components: { registry: { status: 'ok' }, broker_eu: { status: 'ok' }, broker_cn: { status: 'ok' }, presence: { status: 'ok', reachable_agents: 6 } },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }
  if (urlStr === 'https://nexus-global-api.bings.app/mcp') {
    assert.equal(options.headers.get?.('Authorization') || options.headers?.Authorization, 'Bearer test-api-key');
    return new Response(JSON.stringify({
      jsonrpc: '2.0',
      result: { tools: [{ name: 'list_devices' }] }
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }
  return nativeFetch(url, options);
};

async function request(path, options = {}) {
  return worker.fetch(new Request(`https://nexus.bings.app${path}`, options), env);
}

// 1. Static and Release
let response = await request('/release.json');
assert.equal(response.status, 200);
assert.match(await response.text(), /test/);

// 2. OAuth Discovery Endpoints
response = await request('/.well-known/oauth-protected-resource');
assert.equal(response.status, 200);
const protectedMeta = await response.json();
assert.equal(protectedMeta.resource, 'https://nexus.bings.app/mcp');

response = await request('/.well-known/oauth-authorization-server');
assert.equal(response.status, 200);
const authServerMeta = await response.json();
assert.equal(authServerMeta.authorization_endpoint, 'https://nexus.bings.app/authorize');
assert.equal(authServerMeta.token_endpoint, 'https://nexus.bings.app/token');
assert.equal(authServerMeta.registration_endpoint, 'https://nexus.bings.app/register');

// 3. Dynamic Client Registration
response = await request('/register', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ client_name: 'ChatGPT MCP', redirect_uris: ['https://chatgpt.com/aip/callback'] }),
});
assert.equal(response.status, 201);
const clientInfo = await response.json();
assert.match(clientInfo.client_id, /^nexus_client_/);

// 4. OAuth Authorize GET
response = await request('/authorize?client_id=' + clientInfo.client_id + '&redirect_uri=https%3A%2F%2Fchatgpt.com%2Faip%2Fcallback&state=xyz123&response_type=code&code_challenge=E9Melhoa2OwvFrGMTJguCH5Zw_l5UG39WgpxZsOxL_4&code_challenge_method=S256');
assert.equal(response.status, 200);
const authHtml = await response.text();
assert.match(authHtml, /name="password"/);
assert.match(authHtml, /name="redirect_uri"/);
assert.match(authHtml, /name="code_challenge"/);

// 5. OAuth Authorize POST - Invalid Password
response = await request('/authorize', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    password: 'wrong-password',
    client_id: clientInfo.client_id,
    redirect_uri: 'https://chatgpt.com/aip/callback',
    state: 'xyz123',
    code_challenge: 'E9Melhoa2OwvFrGMTJguCH5Zw_l5UG39WgpxZsOxL_4',
    code_challenge_method: 'S256',
  }),
});
assert.equal(response.status, 401);
assert.match(await response.text(), /密码不正确/);

// 6. OAuth Authorize POST - Correct Password -> Code Redirect
const codeVerifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk';
const codeChallenge = crypto.createHash('sha256').update(codeVerifier).digest('base64url');

response = await request('/authorize', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    password: env.NEXUS_PASSWORD,
    client_id: clientInfo.client_id,
    redirect_uri: 'https://chatgpt.com/aip/callback',
    state: 'xyz123',
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
  }),
});
assert.equal(response.status, 302);
const redirectUrl = new URL(response.headers.get('location'));
assert.equal(redirectUrl.origin + redirectUrl.pathname, 'https://chatgpt.com/aip/callback');
assert.equal(redirectUrl.searchParams.get('state'), 'xyz123');
const code = redirectUrl.searchParams.get('code');
assert.ok(code);

// 7. OAuth Token Exchange (POST /token) with PKCE
response = await request('/token', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: 'https://chatgpt.com/aip/callback',
    client_id: clientInfo.client_id,
    code_verifier: codeVerifier,
  }),
});
assert.equal(response.status, 200);
const tokenResp = await response.json();
assert.equal(tokenResp.token_type, 'Bearer');
assert.ok(tokenResp.access_token.startsWith('nxt_'));
assert.ok(tokenResp.refresh_token.startsWith('nxr_'));
const accessToken = tokenResp.access_token;
const refreshToken = tokenResp.refresh_token;

// OAuth tokens are machine-signed and must survive dashboard-password rotation.
const originalPassword = env.NEXUS_PASSWORD;
env.NEXUS_PASSWORD = 'rotated dashboard password';
let rotatedAuth = await request('/mcp', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ jsonrpc: '2.0', method: 'tools/list', id: 77 }),
});
assert.equal(rotatedAuth.status, 200);

// 8. OAuth Refresh Token Exchange
response = await request('/token', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    grant_type: 'refresh_token',
    refresh_token: refreshToken,
  }),
});
assert.equal(response.status, 200);
const refreshedResp = await response.json();
assert.ok(refreshedResp.access_token.startsWith('nxt_'));
env.NEXUS_PASSWORD = originalPassword;

// 9. MCP Request with Invalid Token -> 401
response = await request('/mcp', {
  headers: { 'Authorization': 'Bearer bad_token' }
});
assert.equal(response.status, 401);

// 10. MCP Request with Valid OAuth Access Token -> Proxied
response = await request('/mcp', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${accessToken}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ jsonrpc: '2.0', method: 'tools/list', id: 1 }),
});
assert.equal(response.status, 200);
const mcpJson = await response.json();
assert.equal(mcpJson.result.tools.length, 12);
assert.equal(mcpJson.result.tools[0].name, 'self_test');
assert.ok(mcpJson.result.tools.some((tool) => tool.name === 'execute_command'));

// 10b. MCP self_test dispatches to the canonical REST control plane
response = await request('/mcp', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${accessToken}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ jsonrpc: '2.0', method: 'tools/call', id: 10, params: { name: 'self_test', arguments: {} } }),
});
assert.equal(response.status, 200);
const selfTestRpc = await response.json();
assert.equal(selfTestRpc.result.isError, false);
assert.equal(selfTestRpc.result.structuredContent.status, 'ok');

// 11. MCP Request with Direct API Key -> Proxied
response = await request('/mcp', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${env.NEXUS_CHATGPT_API_KEY}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ jsonrpc: '2.0', method: 'tools/list', id: 2 }),
});
assert.equal(response.status, 200);

// 12. Dashboard Login & Cookie Tests
response = await request('/');
assert.equal(response.status, 302);
assert.equal(response.headers.get('location'), '/login?to=%2F');

response = await request('/login');
assert.equal(response.status, 200);
const loginPageHtml = await response.text();
assert.match(loginPageHtml, /name="password"/);

response = await request('/login?to=%2F', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({ password: 'wrong password' }),
});
assert.equal(response.status, 401);

response = await request('/login?to=%2F', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({ password: env.NEXUS_PASSWORD }),
});
assert.equal(response.status, 302);
const cookie = response.headers.get('set-cookie').split(';', 1)[0];

response = await request('/', { headers: { Cookie: cookie } });
assert.equal(response.status, 200);
assert.match(await response.text(), /Nexus dashboard/);

response = await request('/status.json', { headers: { Cookie: cookie } });
assert.equal(response.status, 200);
const liveStatus = await response.json();
assert.equal(liveStatus.source, 'nexus-chatgpt-remote');
assert.equal(liveStatus.counts.online, 6);

response = await request('/logout', { headers: { Cookie: cookie } });
assert.equal(response.status, 302);
assert.equal(response.headers.get('location'), '/login');

console.log('ALL Nexus Dashboard Worker + OAuth 2.0 + MCP Proxy tests PASSED!');
