// Nexus Dashboard Worker â€” serves R2 static HTML for nexus.bings.app
// Also serves nexus_system_prompt.md and nexus_openapi.json from R2

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Basic Authentication
    const authHeader = request.headers.get('Authorization');
    const user = env.AUTH_USER || 'admin';
    const pass = env.AUTH_PASS || 'nexus2026';
    const expectedAuth = 'Basic ' + btoa(user + ':' + pass);
    
    if (!authHeader || authHeader !== expectedAuth) {
      return new Response('Unauthorized', {
        status: 401,
        headers: {
          'WWW-Authenticate': 'Basic realm="Nexus Cluster Control, please log in"',
          'Content-Type': 'text/plain',
        },
      });
    }

    // Route: serve specific static files from R2
    let r2Key;
    let contentType;

    if (path === '/' || path === '/index.html' || path === '') {
      r2Key = 'index.html';
      contentType = 'text/html; charset=utf-8';
    } else if (path === '/nexus_system_prompt.md') {
      r2Key = 'nexus_system_prompt.md';
      contentType = 'text/markdown; charset=utf-8';
    } else if (path === '/nexus_openapi.json' || path === '/openapi.json') {
      r2Key = 'nexus_openapi.json';
      contentType = 'application/json; charset=utf-8';
    } else if (path === '/readme' || path === '/README.md') {
      r2Key = 'README.md';
      contentType = 'text/markdown; charset=utf-8';
    } else if (path === '/install_v2.sh') {
      r2Key = 'install_v2.sh';
      contentType = 'application/x-sh; charset=utf-8';
    } else {
      return new Response('Not Found', { status: 404 });
    }

    try {
      const obj = await env.NEXUS_BUCKET.get(r2Key);
      if (!obj) {
        return new Response('File not found in R2', { status: 404 });
      }

      const body = await obj.arrayBuffer();
      return new Response(body, {
        headers: {
          'Content-Type': contentType,
          'Cache-Control': 'no-cache, max-age=60',
          'X-Frame-Options': 'SAMEORIGIN',
          'X-Powered-By': 'Nexus Cluster Control v4',
        },
      });
    } catch (e) {
      return new Response(`Worker error: ${e.message}`, { status: 500 });
    }
  },
};

