import fs from 'node:fs';
import assert from 'node:assert/strict';

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
  if (String(url) === env.NEXUS_STATUS_SOURCE_URL) {
    assert.equal(options.headers.Authorization, 'Bearer test-api-key');
    return new Response(JSON.stringify({
      counts: { online: 6, degraded: 0, offline: 0, unknown: 0 },
      devices: [{ device_id: 'oracle', runtime_status: 'online' }],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }
  return nativeFetch(url, options);
};

async function request(path, options = {}) {
  return worker.fetch(new Request(`https://nexus.bings.app${path}`, options), env);
}

let response = await request('/release.json');
assert.equal(response.status, 200);
assert.match(await response.text(), /test/);
response = await request('/install.sh');
assert.equal(response.status, 404);
response = await request('/README.md');
assert.equal(response.status, 404);

response = await request('/');
assert.equal(response.status, 302);
assert.equal(response.headers.get('location'), '/login?to=%2F');
response = await request('/login');
assert.equal(response.status, 200);
const loginHtml = await response.text();
assert.match(loginHtml, /name="password"/);
assert.doesNotMatch(loginHtml, /name="username"/);

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
assert.equal(response.headers.get('location'), '/');
const setCookie = response.headers.get('set-cookie');
assert.match(setCookie, /__Host-nexus_session=/);
assert.match(setCookie, /HttpOnly/);
assert.match(setCookie, /Secure/);
assert.match(setCookie, /SameSite=Strict/);
const cookie = setCookie.split(';', 1)[0];
response = await request('/', { headers: { Cookie: cookie } });
assert.equal(response.status, 200);
assert.match(await response.text(), /Nexus dashboard/);

response = await request('/status.json', { headers: { Cookie: cookie } });
assert.equal(response.status, 200);
const liveStatus = await response.json();
assert.equal(liveStatus.source, 'nexus-chatgpt-remote');
assert.equal(liveStatus.counts.online, 6);
assert.equal(liveStatus.devices[0].device_id, 'oracle');

response = await request('/logout', { headers: { Cookie: cookie } });
assert.equal(response.status, 302);
assert.equal(response.headers.get('location'), '/login');
assert.match(response.headers.get('set-cookie'), /Max-Age=0/);

console.log('Nexus single-password worker login tests passed');
