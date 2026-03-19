export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Handle /subscribe POST (Buttondown signup proxy)
    if (path === '/subscribe') {
      return handleSubscribe(request, env);
    }

    // Handle /submit POST (user book submission)
    if (path === '/submit') {
      return handleSubmit(request, env);
    }

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

    // Set correct Content-Type so Safari/iOS knows how to handle the file
    if (path.endsWith('.epub')) {
      headers.set('Content-Type', 'application/epub+zip');
    } else if (path.endsWith('.pdf')) {
      headers.set('Content-Type', 'application/pdf');
    }

    return new Response(resp.body, {
      status: resp.status,
      headers,
    });
  },
};

async function handleSubmit(request, env) {
  const corsHeaders = {
    'Access-Control-Allow-Origin': 'https://shmindle.com',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };

  if (request.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders });
  }

  if (request.method !== 'POST') {
    return new Response('Method not allowed', { status: 405 });
  }

  let title, author, theme;
  try {
    const body = await request.json();
    title = String(body.title || '').trim().slice(0, 100);
    author = String(body.author || '').trim().slice(0, 100);
    theme = String(body.theme || '').trim().slice(0, 300);
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid request body' }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  if (!title) {
    return new Response(JSON.stringify({ error: 'Book title is required' }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  if (!author) {
    return new Response(JSON.stringify({ error: 'Author name is required' }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  const resp = await fetch(
    'https://api.github.com/repos/leoshvartsman/haikus/actions/workflows/generate-books.yml/dispatches',
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${env.GITHUB_PAT}`,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
        'User-Agent': 'shmindle-worker',
      },
      body: JSON.stringify({
        ref: 'main',
        inputs: {
          submit_title: title,
          submit_author: author,
          submit_theme: theme,
        },
      }),
    }
  );

  // GitHub returns 204 No Content on success
  if (resp.status === 204) {
    return new Response(JSON.stringify({ success: true }), {
      status: 200,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  const data = await resp.json().catch(() => ({}));
  const errMsg = data.message || 'Failed to queue submission';
  return new Response(JSON.stringify({ error: errMsg }), {
    status: 500,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' },
  });
}

async function handleSubscribe(request, env) {
  const corsHeaders = {
    'Access-Control-Allow-Origin': 'https://shmindle.com',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };

  // CORS preflight
  if (request.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders });
  }

  if (request.method !== 'POST') {
    return new Response('Method not allowed', { status: 405 });
  }

  let email;
  try {
    const body = await request.json();
    email = body.email;
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid request body' }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  if (!email || !email.includes('@')) {
    return new Response(JSON.stringify({ error: 'Valid email required' }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  const resp = await fetch('https://api.buttondown.com/v1/subscribers', {
    method: 'POST',
    headers: {
      'Authorization': `Token ${env.BUTTONDOWN_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email_address: email }),
  });

  if (resp.status === 201) {
    return new Response(JSON.stringify({ success: true }), {
      status: 200,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  // Already subscribed (409) or validation error
  const data = await resp.json().catch(() => ({}));
  const errMsg = data.email?.[0] || data.detail || 'Subscription failed';
  return new Response(JSON.stringify({ error: errMsg }), {
    status: resp.status === 409 ? 409 : 400,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' },
  });
}
