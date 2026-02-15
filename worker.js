export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Only handle /dl/* routes
    if (!path.startsWith('/dl/')) {
      return fetch(request);
    }

    // Path format: /dl/book-slug/filename.pdf
    const ghUrl = 'https://github.com/leoshvartsman/haiku-books/releases/download' + path.slice(3);

    const resp = await fetch(ghUrl, { redirect: 'follow' });

    if (!resp.ok) {
      return new Response('File not found', { status: 404 });
    }

    const headers = new Headers(resp.headers);
    headers.set('Content-Disposition', 'inline');
    headers.set('Access-Control-Allow-Origin', '*');

    return new Response(resp.body, {
      status: resp.status,
      headers,
    });
  },
};
