import fs from 'node:fs';
import assert from 'node:assert/strict';

const source = fs.readFileSync(new URL('./nexus-dashboard-worker.js', import.meta.url), 'utf8');
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const { default: worker } = await import(moduleUrl);

const objects = new Map([
  ['index.html', '<html>Nexus dashboard</html>'],
  ['README.md', '# Nexus'],
]);
const env = {
  NEXUS_PASSWORD: 'correct horse battery staple',
  NEXUS_BUCKET: {
    async get(key) {
      if (!objects.has(key)) return null;
      const bytes = new TextEncoder().encode(objects.get(key));
      return { async arrayBuffer() { return bytes.buffer; } };
    },
  },
};

async function request(path, options = {}) {
  return worker.fetch(new Request(`https://nexus.bings.app${path}`, options), env);
}

let response = await request('/');
assert.equal(response.status, 302);
assert.equal(response.headers.get('location'), '/login?to=%2F');
response = await request('/login');
assert.equal(response.status, 200);
const loginHtml = await response.text();
assert.match(loginHtml, /name="password"/);
assert.doesNotMatch(loginHtml, /name="username"/);

response = await request('/login?to=%2FREADME.md', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({ password: 'wrong password' }),
});
assert.equal(response.status, 401);

response = await request('/login?to=%2FREADME.md', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({ password: env.NEXUS_PASSWORD }),
});
assert.equal(response.status, 302);
assert.equal(response.headers.get('location'), '/README.md');
const setCookie = response.headers.get('set-cookie');
assert.match(setCookie, /__Host-nexus_session=/);
assert.match(setCookie, /HttpOnly/);
assert.match(setCookie, /Secure/);
assert.match(setCookie, /SameSite=Strict/);
const cookie = setCookie.split(';', 1)[0];
response = await request('/README.md', { headers: { Cookie: cookie } });
assert.equal(response.status, 200);
assert.equal(await response.text(), '# Nexus');

response = await request('/logout', { headers: { Cookie: cookie } });
assert.equal(response.status, 302);
assert.equal(response.headers.get('location'), '/login');
assert.match(response.headers.get('set-cookie'), /Max-Age=0/);

console.log('Nexus single-password worker login tests passed');
