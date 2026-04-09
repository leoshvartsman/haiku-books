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

    // Agent API endpoints
    if (path === '/register') {
      return handleRegister(request, env);
    }
    if (path === '/api/submit') {
      return handleApiSubmit(request, env);
    }

    // Admin endpoints
    if (path === '/admin/books') {
      return handleAdminBooks(request, env);
    }
    if (path === '/admin/toggle') {
      return handleAdminToggle(request, env);
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

// ── Helpers ──────────────────────────────────────────────────────────────────

function slugify(title) {
  return title.normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

function parseDate(raw) {
  if (!raw) return '';
  if (raw.includes('T')) return raw.slice(0, 10);
  const m = raw.match(/^(\d{4})(\d{2})(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : '';
}

function toBase64(str) {
  return btoa(unescape(encodeURIComponent(str)));
}

function fromBase64(b64) {
  return decodeURIComponent(escape(atob(b64.replace(/\n/g, ''))));
}

async function githubGetFile(repo, path, env) {
  const resp = await fetch(
    `https://api.github.com/repos/leoshvartsman/${repo}/contents/${path}`,
    {
      headers: {
        'Authorization': `Bearer ${env.ADMIN_GITHUB_PAT}`,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'shmindle-worker',
      },
    }
  );
  if (!resp.ok) throw new Error(`GitHub GET failed: ${resp.status}`);
  const data = await resp.json();
  return { content: JSON.parse(fromBase64(data.content)), sha: data.sha };
}

async function githubPutFile(repo, path, content, sha, message, env) {
  const resp = await fetch(
    `https://api.github.com/repos/leoshvartsman/${repo}/contents/${path}`,
    {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${env.ADMIN_GITHUB_PAT}`,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
        'User-Agent': 'shmindle-worker',
      },
      body: JSON.stringify({
        message,
        content: toBase64(JSON.stringify(content, null, 2)),
        sha,
      }),
    }
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.message || `GitHub PUT failed: ${resp.status}`);
  }
}

function checkAdminAuth(request, env) {
  return request.headers.get('X-Admin-Password') === env.ADMIN_PASSWORD;
}

const ADMIN_CORS = {
  'Access-Control-Allow-Origin': 'https://shmindle.com',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-Admin-Password',
};

// ── Admin: GET /admin/books ───────────────────────────────────────────────────

async function handleAdminBooks(request, env) {
  if (request.method === 'OPTIONS') return new Response(null, { headers: ADMIN_CORS });

  if (!checkAdminAuth(request, env)) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), {
      status: 401,
      headers: { ...ADMIN_CORS, 'Content-Type': 'application/json' },
    });
  }

  try {
    const { content: index } = await githubGetFile(
      'haikus',
      'haiku-generator/haiku_output/book_index.json',
      env
    );

    const books = index.map(book => ({
      title: book.title,
      author: book.author,
      slug: slugify(book.title),
      date: parseDate(book.generated_at || ''),
      haiku_count: book.haiku_count || 0,
      hidden: book.hidden || false,
    })).sort((a, b) => b.date.localeCompare(a.date));

    return new Response(JSON.stringify(books), {
      headers: { ...ADMIN_CORS, 'Content-Type': 'application/json' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: e.message }), {
      status: 500,
      headers: { ...ADMIN_CORS, 'Content-Type': 'application/json' },
    });
  }
}

// ── Admin: POST /admin/toggle ─────────────────────────────────────────────────

async function handleAdminToggle(request, env) {
  if (request.method === 'OPTIONS') return new Response(null, { headers: ADMIN_CORS });

  if (!checkAdminAuth(request, env)) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), {
      status: 401,
      headers: { ...ADMIN_CORS, 'Content-Type': 'application/json' },
    });
  }

  let slug, hide;
  try {
    const body = await request.json();
    slug = body.slug;
    hide = body.hide; // true = hide, false = show
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid request body' }), {
      status: 400,
      headers: { ...ADMIN_CORS, 'Content-Type': 'application/json' },
    });
  }

  if (!slug) {
    return new Response(JSON.stringify({ error: 'slug required' }), {
      status: 400,
      headers: { ...ADMIN_CORS, 'Content-Type': 'application/json' },
    });
  }

  try {
    // 1. Update book_index.json in haikus repo
    const { content: index, sha: indexSha } = await githubGetFile(
      'haikus',
      'haiku-generator/haiku_output/book_index.json',
      env
    );

    const bookEntry = index.find(b => slugify(b.title) === slug);
    if (!bookEntry) {
      return new Response(JSON.stringify({ error: `Book not found: ${slug}` }), {
        status: 404,
        headers: { ...ADMIN_CORS, 'Content-Type': 'application/json' },
      });
    }

    if (hide) {
      bookEntry.hidden = true;
    } else {
      delete bookEntry.hidden;
    }

    await githubPutFile(
      'haikus',
      'haiku-generator/haiku_output/book_index.json',
      index,
      indexSha,
      `${hide ? 'Hide' : 'Show'} book: ${bookEntry.title}`,
      env
    );

    // 2. Update catalog.json in haiku-books repo
    const { content: catalog, sha: catalogSha } = await githubGetFile(
      'haiku-books',
      'catalog.json',
      env
    );

    let newCatalog;
    if (hide) {
      newCatalog = catalog.filter(b => b.slug !== slug);
    } else {
      // Reconstruct catalog entry from book_index entry
      const bookSlug = slugify(bookEntry.title);
      const tag = `book-${bookSlug}`;
      const base = `https://github.com/leoshvartsman/haiku-books/releases/download/${tag}/${bookSlug}`;
      const catalogEntry = {
        title: bookEntry.title,
        author: bookEntry.author,
        haiku_count: bookEntry.haiku_count || 0,
        date: parseDate(bookEntry.generated_at || ''),
        slug: bookSlug,
        cover_url: `${base}.jpg`,
        pdf_url: `https://shmindle.com/dl/${tag}/${bookSlug}.pdf`,
        epub_url: `https://shmindle.com/dl/${tag}/${bookSlug}.epub`,
      };
      // Add and re-sort by date descending
      newCatalog = [...catalog.filter(b => b.slug !== slug), catalogEntry]
        .sort((a, b) => b.date.localeCompare(a.date));
    }

    await githubPutFile(
      'haiku-books',
      'catalog.json',
      newCatalog,
      catalogSha,
      `${hide ? 'Hide' : 'Show'} book in catalog: ${bookEntry.title}`,
      env
    );

    return new Response(JSON.stringify({ success: true }), {
      headers: { ...ADMIN_CORS, 'Content-Type': 'application/json' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: e.message }), {
      status: 500,
      headers: { ...ADMIN_CORS, 'Content-Type': 'application/json' },
    });
  }
}

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

  let title, author, theme, cover_style, email;
  try {
    const body = await request.json();
    title = String(body.title || '').trim().slice(0, 100);
    author = String(body.author || '').trim().slice(0, 100);
    theme = String(body.theme || '').trim().slice(0, 300);
    cover_style = String(body.cover_style || '').trim().slice(0, 10);
    email = String(body.email || '').trim().slice(0, 200);
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
          submit_cover_style: cover_style || '',
          submit_email: email || '',
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

// ── Agent API: POST /register ─────────────────────────────────────────────────

async function handleRegister(request, env) {
  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };

  if (request.method === 'OPTIONS') return new Response(null, { headers: corsHeaders });
  if (request.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  let name, description;
  try {
    const body = await request.json();
    name = String(body.name || '').trim().slice(0, 100);
    description = String(body.description || '').trim().slice(0, 300);
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid request body' }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  if (!name) {
    return new Response(JSON.stringify({ error: 'name is required' }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  // Generate a random API key
  const rawKey = crypto.getRandomValues(new Uint8Array(24));
  const apiKey = 'sk-' + Array.from(rawKey).map(b => b.toString(16).padStart(2, '0')).join('');

  const record = {
    name,
    description,
    created_at: new Date().toISOString(),
  };

  await env.API_KEYS.put(apiKey, JSON.stringify(record));

  return new Response(JSON.stringify({ api_key: apiKey, name, message: 'Registration successful. Include your API key as X-API-Key header on /api/submit requests.' }), {
    status: 201,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' },
  });
}

// ── Agent API: POST /api/submit ───────────────────────────────────────────────

async function handleApiSubmit(request, env) {
  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, X-API-Key',
  };

  if (request.method === 'OPTIONS') return new Response(null, { headers: corsHeaders });
  if (request.method !== 'POST') return new Response('Method not allowed', { status: 405 });

  // Validate API key
  const apiKey = request.headers.get('X-API-Key') || '';
  if (!apiKey) {
    return new Response(JSON.stringify({ error: 'X-API-Key header required. Register at POST /register.' }), {
      status: 401,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  const keyRecord = await env.API_KEYS.get(apiKey);
  if (!keyRecord) {
    return new Response(JSON.stringify({ error: 'Invalid API key.' }), {
      status: 401,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  // Rate limiting: 3 submissions per day per key
  const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
  const rateLimitKey = `${apiKey}:${today}`;
  const countStr = await env.RATE_LIMITS.get(rateLimitKey);
  const count = countStr ? parseInt(countStr, 10) : 0;
  const DAILY_LIMIT = 3;

  if (count >= DAILY_LIMIT) {
    return new Response(JSON.stringify({ error: `Daily limit of ${DAILY_LIMIT} submissions reached. Resets at midnight UTC.` }), {
      status: 429,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  // Parse body
  let title, author, theme, cover_style, haiku;
  try {
    const body = await request.json();
    title = String(body.title || '').trim().slice(0, 100);
    author = String(body.author || '').trim().slice(0, 100);
    theme = String(body.theme || '').trim().slice(0, 300);
    cover_style = String(body.cover_style || '').trim().slice(0, 10);
    haiku = body.haiku; // optional array for publishing mode
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid request body' }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  if (!title) {
    return new Response(JSON.stringify({ error: 'title is required' }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }
  if (!author) {
    return new Response(JSON.stringify({ error: 'author is required' }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  // Publishing mode: haiku array provided
  if (Array.isArray(haiku) && haiku.length > 0) {
    // Validate haiku array: each item must be a non-empty string
    const cleaned = haiku
      .filter(h => typeof h === 'string' && h.trim().length > 0)
      .map(h => h.trim())
      .slice(0, 500); // cap at 500

    if (cleaned.length < 10) {
      return new Response(JSON.stringify({ error: 'haiku array must contain at least 10 valid haiku strings' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    // Trigger publish workflow
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
            submit_theme: theme || '',
            submit_cover_style: cover_style || '',
            submit_email: '',
            submit_haiku: cleaned.join('\n---\n'),
          },
        }),
      }
    );

    if (resp.status !== 204) {
      const data = await resp.json().catch(() => ({}));
      return new Response(JSON.stringify({ error: data.message || 'Failed to queue submission' }), {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
      });
    }

    await env.RATE_LIMITS.put(rateLimitKey, String(count + 1), { expirationTtl: 86400 });

    return new Response(JSON.stringify({
      success: true,
      mode: 'publish',
      haiku_count: cleaned.length,
      message: `Publishing ${cleaned.length} haiku as "${title}" by ${author}. Book will appear on shmindle.com in ~15 minutes.`,
    }), {
      status: 200,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  // Generation mode: Shmindle generates haiku from title + theme
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
          submit_theme: theme || '',
          submit_cover_style: cover_style || '',
          submit_email: '',
          submit_haiku: '',
        },
      }),
    }
  );

  if (resp.status !== 204) {
    const data = await resp.json().catch(() => ({}));
    return new Response(JSON.stringify({ error: data.message || 'Failed to queue submission' }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }

  await env.RATE_LIMITS.put(rateLimitKey, String(count + 1), { expirationTtl: 86400 });

  return new Response(JSON.stringify({
    success: true,
    mode: 'generate',
    message: `Generating haiku collection "${title}" by ${author}. Book will appear on shmindle.com in ~15 minutes.`,
    remaining_today: DAILY_LIMIT - count - 1,
  }), {
    status: 200,
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
