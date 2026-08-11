export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';

    const authHeader = request.headers.get('Authorization');
    const user = env.AUTH_USER_V2 || env.AUTH_USER || 'admin';
    const pass = env.AUTH_PASS_V2 || env.AUTH_PASS;

    if (!pass) {
      return new Response('AUTH_PASS_V2 or AUTH_PASS is not configured', {
        status: 500,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      });
    }

    const expectedAuth = 'Basic ' + btoa(`${user}:${pass}`);
    if (!authHeader || authHeader !== expectedAuth) {
      return new Response('Unauthorized', {
        status: 401,
        headers: {
          'WWW-Authenticate': 'Basic realm="Nexus Cluster Control"',
          'Content-Type': 'text/plain; charset=utf-8',
        },
      });
    }

    if (path === '/status.json' && env.NEXUS_STATUS_SOURCE_URL && env.NEXUS_CHATGPT_API_KEY) {
      const upstream = await fetch(env.NEXUS_STATUS_SOURCE_URL, {
        headers: {
          'Authorization': `Bearer ${env.NEXUS_CHATGPT_API_KEY}`,
          'Accept': 'application/json',
        },
        cf: { cacheTtl: 0, cacheEverything: false },
      });
      if (upstream.ok) {
        const payload = await upstream.json();
        const devices = Array.isArray(payload) ? payload : (payload.devices || []);
        return new Response(JSON.stringify({
          source: 'nexus-chatgpt-remote',
          updated_at: new Date().toISOString(),
          devices,
        }), {
          headers: {
            'Content-Type': 'application/json; charset=utf-8',
            'Cache-Control': 'no-store',
            'X-Frame-Options': 'SAMEORIGIN',
            'X-Content-Type-Options': 'nosniff',
            'X-Powered-By': 'Nexus v3 Remote Control',
          },
        });
      }
    }

    const routes = {
      '/': ['index.html', 'text/html; charset=utf-8'],
      '/index.html': ['index.html', 'text/html; charset=utf-8'],
      '/README.md': ['README.md', 'text/markdown; charset=utf-8'],
      '/install.sh': ['install.sh', 'application/x-sh; charset=utf-8'],
      '/chatgpt-prompt.md': ['nexus-v3-chatgpt-remote-prompt.md', 'text/markdown; charset=utf-8'],
      '/openapi.json': ['nexus-v3-remote-control-openapi.json', 'application/json; charset=utf-8'],
      '/status.json': ['status.json', 'application/json; charset=utf-8'],
    };

    const route = routes[path];
    if (!route) {
      return new Response('Not Found', {
        status: 404,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      });
    }

    const [r2Key, contentType] = route;
    const obj = await env.NEXUS_BUCKET.get(r2Key);
    if (!obj) {
      return new Response(`R2 object not found: ${r2Key}`, {
        status: 404,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      });
    }

    return new Response(await obj.arrayBuffer(), {
      headers: {
        'Content-Type': contentType,
        'Cache-Control': 'no-cache, max-age=60',
        'X-Frame-Options': 'SAMEORIGIN',
        'X-Content-Type-Options': 'nosniff',
        'X-Powered-By': 'Nexus v3 Remote Control',
      },
    });
  },
};
