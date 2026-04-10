#!/usr/bin/env python3
"""
Build script for the Haiku Books download website.

Reads book_index.json from the haiku pipeline, uploads book assets
(PDF, EPUB, cover image) as GitHub Release assets, and generates
catalog.json for the frontend.

Usage:
    python3 build_site.py          # Build/update the catalog
    python3 build_site.py --dry    # Show what would be uploaded without doing it
"""

import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, List, Dict
from PIL import Image

# Paths to the haiku pipeline
PIPELINE_DIR = Path.home() / "haikus" / "haiku-generator"
BOOK_INDEX = PIPELINE_DIR / "haiku_output" / "book_index.json"
SONNET_INDEX = PIPELINE_DIR / "sonnet_output" / "book_index.json"
COVERS_DIR = PIPELINE_DIR / "haiku_output"
SONNET_COVERS_DIR = PIPELINE_DIR / "sonnet_output"
OUTPUT_DIR = Path.home() / "haikus" / "book_formatter" / "output"

# GitHub repo for releases
GITHUB_REPO = "leoshvartsman/haiku-books"

# Base URL for the Cloudflare Worker proxy (serves files with Content-Disposition: inline)
DOWNLOAD_PROXY = "https://shmindle.com/dl"

# Output
SITE_DIR = Path(__file__).parent
CATALOG_FILE = SITE_DIR / "catalog.json"
AUTHOR_DIR = SITE_DIR / "authors"
AUTHOR_BIOS_FILE = AUTHOR_DIR / "bios.json"


def to_proxy_url(github_url: str) -> str:
    """Convert a GitHub Release asset URL to use our Cloudflare Worker proxy.

    GitHub: https://github.com/leoshvartsman/haiku-books/releases/download/book-slug/file.pdf
    Proxy:  https://shmindle.com/dl/book-slug/file.pdf
    """
    prefix = f"https://github.com/{GITHUB_REPO}/releases/download/"
    if github_url.startswith(prefix):
        return DOWNLOAD_PROXY + "/" + github_url[len(prefix):]
    return github_url


def slugify(title: str) -> str:
    """Convert title to URL-friendly slug, transliterating accented characters."""
    import unicodedata
    normalized = unicodedata.normalize('NFD', title)
    ascii_str = normalized.encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', '-', ascii_str.lower()).strip('-')


def parse_date(raw: str) -> str:
    """Parse date from either ISO (2026-02-04T18:40:34) or compact (20260214_081825) format."""
    if not raw:
        return ""
    if "T" in raw:
        return raw[:10]  # Already ISO
    # Compact: YYYYMMDD_HHMMSS
    m = re.match(r'(\d{4})(\d{2})(\d{2})', raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return raw[:10]


def poem_label(count: int, form: str) -> str:
    """Return e.g. '25 sonnets' or '250 haiku'."""
    return f"{count} {form}{'s' if form == 'sonnet' and count != 1 else ''}"


def find_cover(title: str, form: str = "haiku") -> Optional[Path]:
    """Find the cover image for a book title."""
    search_dirs = [SONNET_COVERS_DIR, COVERS_DIR] if form == "sonnet" else [COVERS_DIR, SONNET_COVERS_DIR]

    safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:50]
    cover_name1 = "cover_" + title.replace(" ", "_").replace("'", "").replace(",", "") + ".png"
    cover_name2 = "cover_" + re.sub(r'[^a-zA-Z0-9]+', '_', title) + ".png"

    for d in search_dirs:
        for name in (f"cover_{safe_title}.png", cover_name1, cover_name2):
            p = d / name
            if p.exists():
                return p

    return None


def convert_cover_to_jpg(png_path: Path, output_path: Path) -> bool:
    """Convert PNG cover to smaller JPG."""
    try:
        img = Image.open(png_path)
        img = img.convert('RGB')
        # Resize to max 600px wide for web
        if img.width > 600:
            ratio = 600 / img.width
            img = img.resize((600, int(img.height * ratio)), Image.LANCZOS)
        img.save(output_path, 'JPEG', quality=82, optimize=True)
        return True
    except Exception as e:
        print(f"  Warning: Could not convert cover: {e}")
        return False


def release_exists(tag: str) -> bool:
    """Check if a GitHub release already exists for this tag."""
    result = subprocess.run(
        ["gh", "release", "view", tag, "--repo", GITHUB_REPO],
        capture_output=True, text=True
    )
    return result.returncode == 0


def create_release(tag: str, title: str, assets: List[Path]) -> Dict:
    """Create a GitHub release and upload assets. Returns asset URLs."""
    print(f"  Creating release: {tag}")

    cmd = [
        "gh", "release", "create", tag,
        "--repo", GITHUB_REPO,
        "--title", title,
        "--notes", f"Haiku collection: {title}",
    ]
    for asset in assets:
        cmd.append(str(asset))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Error creating release: {result.stderr}")
        return {}

    # Get the asset download URLs
    urls = {}
    view = subprocess.run(
        ["gh", "release", "view", tag, "--repo", GITHUB_REPO, "--json", "assets"],
        capture_output=True, text=True
    )
    if view.returncode == 0:
        data = json.loads(view.stdout)
        for asset in data.get("assets", []):
            name = asset["name"]
            url = asset["url"]
            if name.endswith(".pdf"):
                urls["pdf"] = url
            elif name.endswith(".epub"):
                urls["epub"] = url
            elif name.endswith(".jpg"):
                urls["cover"] = url

    return urls


def get_existing_release_urls(tag: str) -> dict:
    """Get asset URLs from an existing release."""
    urls = {}
    result = subprocess.run(
        ["gh", "release", "view", tag, "--repo", GITHUB_REPO, "--json", "assets"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        for asset in data.get("assets", []):
            name = asset["name"]
            url = asset["url"]
            if name.endswith(".pdf"):
                urls["pdf"] = url
            elif name.endswith(".epub"):
                urls["epub"] = url
            elif name.endswith(".jpg"):
                urls["cover"] = url
    return urls


def build_catalog(dry_run=False):
    """Main build: read index, upload releases, generate catalog."""
    if not BOOK_INDEX.exists():
        print(f"Error: Book index not found at {BOOK_INDEX}")
        sys.exit(1)

    with open(BOOK_INDEX, 'r') as f:
        haiku_index = json.load(f)
    for e in haiku_index:
        e.setdefault('poem_form', 'haiku')

    sonnet_index = []
    if SONNET_INDEX.exists():
        with open(SONNET_INDEX, 'r') as f:
            sonnet_index = json.load(f)
        for e in sonnet_index:
            e['poem_form'] = 'sonnet'

    index = haiku_index + sonnet_index
    print(f"Found {len(haiku_index)} haiku + {len(sonnet_index)} sonnet books in index")
    catalog = []
    tmp_dir = SITE_DIR / "_tmp_covers"
    tmp_dir.mkdir(exist_ok=True)

    for book in index:
        if book.get("hidden"):
            continue
        title = book["title"]
        author = book["author"]
        form = book.get("poem_form", "haiku")
        slug = slugify(title)
        tag = f"book-{slug}"
        poem_count = book.get("sonnet_count") or book.get("haiku_count", 0)
        date = parse_date(book.get("generated_at", ""))

        print(f"\n[{title}] by {author} ({form})")

        # Find assets on disk
        pdf_path = OUTPUT_DIR / f"{slug}.pdf"
        epub_path = OUTPUT_DIR / f"{slug}.epub"
        cover_path = find_cover(title, form=form)

        # Check if release already exists on GitHub
        has_release = release_exists(tag)
        has_local_files = pdf_path.exists() or epub_path.exists()

        if not has_release and not has_local_files:
            print(f"  Skipping: no release and no local files ({slug})")
            continue

        # Convert cover to JPG if available locally
        cover_jpg = None
        if cover_path:
            cover_jpg = tmp_dir / f"{slug}.jpg"
            if not convert_cover_to_jpg(cover_path, cover_jpg):
                cover_jpg = None

        if dry_run:
            print(f"  Would upload: PDF={pdf_path.exists()}, EPUB={epub_path.exists()}, Cover={cover_jpg is not None}, Release={has_release}")
            catalog.append({
                "title": title,
                "author": author,
                "poem_form": form,
                "poem_count": poem_count,
                "haiku_count": poem_count,
                "date": date,
                "cover_url": "",
                "pdf_url": "",
                "epub_url": "",
            })
            continue

        if has_release:
            print(f"  Release exists, fetching URLs...")
            urls = get_existing_release_urls(tag)
        else:
            # Collect assets to upload
            assets = []
            if pdf_path.exists():
                assets.append(pdf_path)
            if epub_path.exists():
                assets.append(epub_path)
            if cover_jpg:
                assets.append(cover_jpg)

            urls = create_release(tag, title, assets)

        pdf_url = urls.get("pdf", "")
        epub_url = urls.get("epub", "")
        catalog.append({
            "title": title,
            "author": author,
            "poem_form": form,
            "poem_count": poem_count,
            "haiku_count": poem_count,  # kept for backward compat
            "date": date,
            "slug": slug,
            "cover_url": to_proxy_url(urls.get("cover", "")) if urls.get("cover") else "",
            "pdf_url": to_proxy_url(pdf_url) if pdf_url else "",
            "epub_url": to_proxy_url(epub_url) if epub_url else "",
        })

    # Sort by date descending
    catalog.sort(key=lambda b: b["date"], reverse=True)

    # Write catalog
    with open(CATALOG_FILE, 'w') as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 50}")
    print(f"Catalog written: {CATALOG_FILE}")
    print(f"Books in catalog: {len(catalog)}")

    # Generate individual book pages and author pages
    if not dry_run:
        generate_book_pages(catalog, index)
        generate_author_pages(catalog, index)
        generate_sitemap(catalog)
        generate_feed(catalog)
        generate_robots()

    # Cleanup tmp
    shutil.rmtree(tmp_dir, ignore_errors=True)


def extract_sample_haiku(book_index_entry: Dict, count: int = 6) -> List[str]:
    """Extract sample poems from book_index.json or fall back to text file."""
    # Prefer stored samples (sonnets or haiku)
    stored = book_index_entry.get("sample_sonnets") or book_index_entry.get("sample_haiku", [])
    if stored:
        return stored[:count]

    # Fall back to reading from text file
    book_txt = book_index_entry.get("files", {}).get("book_txt", "")
    if not book_txt:
        return []

    # Try both possible base paths
    for base in [PIPELINE_DIR, Path.home() / "haikus" / "haiku-generator"]:
        path = base / book_txt if not Path(book_txt).is_absolute() else Path(book_txt)
        if path.exists():
            break
    else:
        return []

    try:
        text = path.read_text(encoding='utf-8')
    except Exception:
        return []

    # Extract poems: lines starting with a number followed by a period
    # Handles both 3-line haiku and 14-line sonnets
    is_sonnet = book_index_entry.get("poem_form") == "sonnet"
    expected_lines = 14 if is_sonnet else 3
    haiku_list = []
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if re.match(r'^\d+\.\s*$', line):
            h_lines = []
            j = 1
            while len(h_lines) < expected_lines and i + j < len(lines):
                l = lines[i + j].strip()
                if l:
                    h_lines.append(l)
                elif h_lines:  # blank line signals end of poem block
                    break
                j += 1
            if len(h_lines) >= expected_lines - 1:  # allow one short
                haiku_list.append('\n'.join(h_lines[:expected_lines]))
            i += j
        else:
            i += 1

    # Pick evenly spaced samples
    if len(haiku_list) <= count:
        return haiku_list
    step = len(haiku_list) / count
    return [haiku_list[int(i * step)] for i in range(count)]


def extract_intro(book_index_entry: Dict) -> str:
    """Extract the book introduction from book_index.json or fall back to text file."""
    # Prefer stored intro in book_index.json
    stored = book_index_entry.get("collection_intro", "")
    if stored:
        return stored.strip()

    # Fall back to reading from text file
    book_txt = book_index_entry.get("files", {}).get("book_txt", "")
    if not book_txt:
        return ""

    for base in [PIPELINE_DIR, Path.home() / "haikus" / "haiku-generator"]:
        path = base / book_txt if not Path(book_txt).is_absolute() else Path(book_txt)
        if path.exists():
            break
    else:
        return ""

    try:
        text = path.read_text(encoding='utf-8')
    except Exception:
        return ""

    # Intro is between the header block and the first section
    lines = text.split('\n')
    intro_lines = []
    in_intro = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('=' * 10) and not in_intro:
            in_intro = True
            continue
        if in_intro and stripped.startswith('=' * 10):
            continue
        if in_intro and stripped.startswith('---'):
            break
        if in_intro and stripped and not stripped.startswith('='):
            # Skip the title and "by Author" lines
            if stripped.isupper() or stripped.startswith('by '):
                continue
            intro_lines.append(stripped)

    return ' '.join(intro_lines).strip()


def generate_book_page(book_catalog: Dict, book_index_entry: Dict, full_catalog: List[Dict] = None) -> None:
    """Generate an individual HTML page for a book."""
    slug = slugify(book_catalog["title"])
    author_slug = slugify(book_catalog["author"])
    title = html.escape(book_catalog["title"])
    author = html.escape(book_catalog["author"])
    form = book_catalog.get("poem_form", "haiku")
    p_count = book_catalog.get("poem_count") or book_catalog.get("haiku_count", 0)
    p_label = poem_label(p_count, form)
    cover_url = book_catalog.get("cover_url", "")
    pdf_url = book_catalog.get("pdf_url", "")
    epub_url = book_catalog.get("epub_url", "")

    intro_raw = extract_intro(book_index_entry)
    intro = html.escape(intro_raw)
    samples = extract_sample_haiku(book_index_entry)

    # Meta description: first ~155 chars of intro, or generic fallback
    if intro_raw:
        meta_desc_raw = intro_raw[:155].rsplit(' ', 1)[0] + '…'
    else:
        meta_desc_raw = f"{book_catalog['title']} — a collection of {p_label} by {book_catalog['author']}. Free to download as PDF or EPUB."
    meta_desc = html.escape(meta_desc_raw)

    # Build sample haiku HTML
    samples_html = ""
    for h in samples:
        lines_html = ''.join(f'<p>{html.escape(line)}</p>' for line in h.split('\n'))
        samples_html += f'<div class="haiku">{lines_html}</div>\n'

    # Cover image HTML — descriptive alt text for image search (#9)
    cover_html = (
        f'<img src="{cover_url}" alt="Cover of {title} by {author} — free poetry ebook">'
        if cover_url else '<div class="no-cover">📖</div>'
    )

    # Download buttons
    dl_html = ""
    if pdf_url:
        dl_html += f'<a href="{pdf_url}" class="btn-pdf" type="application/pdf">Download PDF</a>\n'
    if epub_url:
        dl_html += f'<a href="{epub_url}" class="btn-epub" type="application/epub+zip">Download EPUB</a>\n'

    # Schema.org structured data — Book type with download actions
    schema = {
        "@context": "https://schema.org",
        "@type": "Book",
        "name": book_catalog["title"],
        "author": {"@type": "Person", "name": book_catalog["author"]},
        "bookFormat": "EBook",
        "url": f"https://shmindle.com/books/{slug}.html",
        "numberOfPages": p_count,
        "genre": "Poetry",
        "inLanguage": "en",
        "isAccessibleForFree": True,
        "description": intro_raw[:300] if intro_raw else f"A collection of {p_label} by {book_catalog['author']}.",
        "datePublished": book_catalog.get("date", ""),
        "publisher": {
            "@type": "Organization",
            "name": "Shmindle",
            "url": "https://shmindle.com"
        },
        "offers": {
            "@type": "Offer",
            "price": "0",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock",
        },
    }
    if cover_url:
        schema["image"] = cover_url
    potential_actions = []
    if pdf_url:
        potential_actions.append({"@type": "ReadAction", "target": pdf_url})
    if epub_url:
        potential_actions.append({"@type": "ReadAction", "target": epub_url})
    if potential_actions:
        schema["potentialAction"] = potential_actions

    # Related books: pick 3 others spread across the catalog (#7)
    related_html = ""
    if full_catalog and len(full_catalog) > 3:
        others = [b for b in full_catalog if b["title"] != book_catalog["title"]]
        n = len(others)
        picks = [others[0], others[n // 2], others[-1]]
        # If current book is near an edge, shift picks to avoid duplicates
        picks = list({b["slug"]: b for b in picks}.values())[:3]
        cards = ""
        for rel in picks:
            rel_slug = rel["slug"]
            rel_title = html.escape(rel["title"])
            rel_author = html.escape(rel["author"])
            rel_cover = rel.get("cover_url", "")
            rel_img = (
                f'<img src="{rel_cover}" alt="Cover of {rel_title}" style="width:80px;height:80px;object-fit:cover;border-radius:4px;flex-shrink:0;">'
                if rel_cover else
                '<div style="width:80px;height:80px;background:#e8e4df;border-radius:4px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:1.5rem;">📖</div>'
            )
            cards += f"""<a href="{rel_slug}.html" style="display:flex;gap:1rem;align-items:center;text-decoration:none;color:inherit;background:#fff;border-radius:8px;padding:0.75rem;box-shadow:0 1px 4px rgba(0,0,0,0.08);flex:1;min-width:200px;">
              {rel_img}
              <div>
                <div style="font-size:0.95rem;font-weight:600;color:#2c2c2c;margin-bottom:0.2rem;">{rel_title}</div>
                <div style="font-size:0.82rem;color:#888;">{rel_author}</div>
              </div>
            </a>"""
        related_html = f"""<div style="max-width:720px;margin:0 auto;padding:0 1.5rem 2rem;">
      <h2 style="font-size:0.85rem;font-weight:400;color:#999;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:1rem;">You might also like</h2>
      <div style="display:flex;gap:1rem;flex-wrap:wrap;">{cards}</div>
    </div>"""

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <!-- Google tag (gtag.js) -->
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-BPD55QWY65"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());
      gtag('config', 'G-BPD55QWY65');
    </script>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} by {author} — Free Poetry Book | Shmindle</title>
    <meta name="description" content="{meta_desc}">
    <link rel="canonical" href="https://shmindle.com/books/{slug}.html">

    <meta property="og:title" content="{title} by {author}">
    <meta property="og:description" content="A collection of {p_label}. Free to download.">
    <meta property="og:type" content="book">
    <meta property="og:url" content="https://shmindle.com/books/{slug}.html">
    {"<meta property='og:image' content='" + cover_url + "'>" if cover_url else ""}

    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{title} by {author}">
    <meta name="twitter:description" content="A collection of {p_label}. Free to download.">
    {"<meta name='twitter:image' content='" + cover_url + "'>" if cover_url else ""}

    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    <link rel="alternate" type="application/rss+xml" title="Shmindle — New Haiku Books" href="/feed.xml">
    <link rel="stylesheet" href="../style.css">

    <script type="application/ld+json">
    {json.dumps(schema, ensure_ascii=False)}
    </script>
</head>
<body>
    <header>
        <h1><a href="../" style="text-decoration:none;color:inherit">Shmindle</a></h1>
    </header>

    <div class="book-detail">
        <a href="../" class="back-link">&larr; All books</a>

        <div class="book-hero">
            {cover_html}
            <div class="book-info">
                <h1>{title}</h1>
                <div class="author"><a href="../authors/{author_slug}.html" class="author-page-link">{author}</a></div>
                <div class="meta">{p_label}</div>
                <div class="download-btns">
                    {dl_html}
                </div>
            </div>
        </div>

        {"<div class='book-intro'>" + intro + "</div>" if intro else ""}

        {"<div class='sample-haiku'><h2>Sample " + form.capitalize() + "s</h2>" + samples_html + "</div>" if samples_html else ""}
    </div>

    {related_html}

    <section class="subscribe-section">
        <p class="subscribe-heading">Get notified when new books arrive</p>
        <form id="subscribe-form" class="subscribe-form">
            <input type="email" id="subscribe-email" placeholder="your@email.com" required aria-label="Email address">
            <button type="submit">Subscribe</button>
        </form>
        <p id="subscribe-msg" class="subscribe-msg" aria-live="polite"></p>
    </section>

    <footer>
        <p>Your home for books generated by AI. Free to download anytime. &nbsp;|&nbsp; <a href="/feed.xml" style="color:#bbb;text-decoration:none;">RSS feed</a> &nbsp;|&nbsp; <a href="/api" style="color:#bbb;text-decoration:none;">API</a></p>
    </footer>

    <script>
      (function () {{
        const form = document.getElementById('subscribe-form');
        const msg  = document.getElementById('subscribe-msg');
        form.addEventListener('submit', async function (e) {{
          e.preventDefault();
          const email = document.getElementById('subscribe-email').value.trim();
          msg.textContent = '';
          msg.className = 'subscribe-msg';
          try {{
            const resp = await fetch('/subscribe', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify({{ email }}),
            }});
            const data = await resp.json();
            if (data.success) {{
              msg.textContent = "Subscribed! You'll hear from us when new books arrive.";
              msg.className = 'subscribe-msg subscribe-ok';
              form.reset();
            }} else if (resp.status === 409) {{
              msg.textContent = "You're already subscribed.";
              msg.className = 'subscribe-msg subscribe-ok';
            }} else {{
              msg.textContent = data.error || 'Something went wrong. Please try again.';
              msg.className = 'subscribe-msg subscribe-err';
            }}
          }} catch {{
            msg.textContent = 'Network error. Please try again.';
            msg.className = 'subscribe-msg subscribe-err';
          }}
        }});
      }})();
    </script>
</body>
</html>"""

    books_dir = SITE_DIR / "books"
    books_dir.mkdir(exist_ok=True)
    out_path = books_dir / f"{slug}.html"
    out_path.write_text(page_html, encoding='utf-8')


def generate_book_pages(catalog: List[Dict], index: List[Dict]) -> None:
    """Generate individual pages for all books."""
    print("\nGenerating book pages...")

    # Build lookup from title to index entry
    index_by_title = {b["title"]: b for b in index}

    for book in catalog:
        idx_entry = index_by_title.get(book["title"], {})
        generate_book_page(book, idx_entry, full_catalog=catalog)

    print(f"  Generated {len(catalog)} book pages in books/")


def generate_sitemap(catalog: List[Dict]) -> None:
    """Generate sitemap.xml for search engines."""
    from collections import OrderedDict
    today = __import__('datetime').date.today().isoformat()
    most_recent = catalog[0]["date"] if catalog else today
    urls = [f'  <url><loc>https://shmindle.com/</loc><lastmod>{most_recent}</lastmod><priority>1.0</priority></url>']
    for book in catalog:
        slug = slugify(book["title"])
        lastmod = book.get("date", today)
        urls.append(f'  <url><loc>https://shmindle.com/books/{slug}.html</loc><lastmod>{lastmod}</lastmod><priority>0.8</priority></url>')
    # Add author pages
    seen_authors: dict = OrderedDict()
    for book in catalog:
        a = book['author']
        if a not in seen_authors:
            seen_authors[a] = book.get('date', today)
    for author_name, date in seen_authors.items():
        author_slug = slugify(author_name)
        urls.append(f'  <url><loc>https://shmindle.com/authors/{author_slug}.html</loc><lastmod>{date}</lastmod><priority>0.7</priority></url>')

    sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""

    (SITE_DIR / "sitemap.xml").write_text(sitemap, encoding='utf-8')
    print(f"  Generated sitemap.xml ({len(urls)} URLs)")


def generate_feed(catalog: List[Dict]) -> None:
    """Generate RSS feed (feed.xml) for new book notifications."""
    from datetime import datetime, timezone
    from email.utils import format_datetime

    def to_rfc2822(date_str: str) -> str:
        """Convert YYYY-MM-DD to RFC 2822 format required by RSS."""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)
        return format_datetime(dt)

    build_date = format_datetime(datetime.now(timezone.utc))

    items = []
    for book in catalog[:50]:  # most recent 50
        slug = slugify(book["title"])
        title = book["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        author = book["author"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        cover_url = book.get("cover_url", "")
        pdf_url = book.get("pdf_url", "")
        epub_url = book.get("epub_url", "")
        pub_date = to_rfc2822(book.get("date", ""))
        page_url = f"https://shmindle.com/books/{slug}.html"
        b_form = book.get("poem_form", "haiku")
        count = book.get("poem_count") or book.get("haiku_count", 0)
        b_label = poem_label(count, b_form)

        desc_parts = [f"<p>A new collection of {b_label} by {author}.</p>"]
        if cover_url:
            desc_parts.append(f'<p><img src="{cover_url}" alt="{title}" style="max-width:300px"/></p>')
        if pdf_url:
            desc_parts.append(f'<p><a href="{pdf_url}">Download PDF</a></p>')
        if epub_url:
            desc_parts.append(f'<p><a href="{epub_url}">Download EPUB</a></p>')
        description = "<![CDATA[" + "".join(desc_parts) + "]]>"

        enclosure = f'<enclosure url="{cover_url}" type="image/jpeg"/>' if cover_url else ""

        items.append(f"""  <item>
    <title>{title} by {author}</title>
    <link>{page_url}</link>
    <guid isPermaLink="true">{page_url}</guid>
    <pubDate>{pub_date}</pubDate>
    <description>{description}</description>
    {enclosure}
  </item>""")

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Shmindle — Free Haiku Poetry Books</title>
    <link>https://shmindle.com/</link>
    <description>New haiku poetry collections, free to download as PDF and EPUB.</description>
    <language>en</language>
    <lastBuildDate>{build_date}</lastBuildDate>
    <atom:link href="https://shmindle.com/feed.xml" rel="self" type="application/rss+xml"/>
{chr(10).join(items)}
  </channel>
</rss>"""

    (SITE_DIR / "feed.xml").write_text(feed, encoding="utf-8")
    print(f"  Generated feed.xml ({len(items)} items)")


def generate_robots() -> None:
    """Generate robots.txt."""
    robots = """User-agent: *
Allow: /
Sitemap: https://shmindle.com/sitemap.xml
"""
    (SITE_DIR / "robots.txt").write_text(robots, encoding='utf-8')
    print("  Generated robots.txt")


def load_author_bios() -> Dict:
    if AUTHOR_BIOS_FILE.exists():
        return json.loads(AUTHOR_BIOS_FILE.read_text(encoding='utf-8'))
    return {}


def save_author_bios(bios: Dict) -> None:
    AUTHOR_DIR.mkdir(exist_ok=True)
    AUTHOR_BIOS_FILE.write_text(json.dumps(bios, indent=2, ensure_ascii=False), encoding='utf-8')


def _palette_for_persona(characteristic: str, location: str) -> str:
    text = (characteristic + " " + location).lower()
    if any(w in text for w in ['japan', 'tokyo', 'kyoto', 'zen', 'cherry', 'blossom']):
        return "ink black, moss green, paper white"
    if any(w in text for w in ['india', 'mumbai', 'monsoon', 'ganges', 'spice']):
        return "deep indigo, warm ochre, storm grey"
    if any(w in text for w in ['africa', 'ethiopia', 'prairie', 'soil', 'farm', 'savanna']):
        return "warm prairie gold, deep ochre, red clay"
    if any(w in text for w in ['trauma', 'grief', 'loss', 'portland', 'elegy', 'memory']):
        return "slate blue, pale ash, muted rose"
    if any(w in text for w in ['urban', 'city', 'metro', 'street', 'concrete', 'subway']):
        return "steel grey, amber, deep charcoal"
    if any(w in text for w in ['ocean', 'sea', 'coast', 'island', 'wave', 'tide']):
        return "deep teal, pale sand, horizon grey"
    return "deep ink, warm paper, muted ochre"


def generate_author_bio_text(author_name: str, index_entries: List[Dict]) -> str:
    """Generate a 2-sentence bio using Claude Haiku. Falls back to template on failure."""
    best_persona: Dict = {}
    for entry in index_entries:
        p = entry.get('persona', {})
        if len(p.get('characteristic', '')) > len(best_persona.get('characteristic', '')):
            best_persona = p

    characteristic = best_persona.get('characteristic', 'finds poetry in everyday moments')
    location = best_persona.get('location', '')

    intros = [
        f"From '{e['title']}':\n{e['collection_intro'][:250]}"
        for e in index_entries if e.get('collection_intro', '').strip()
    ]

    def _fallback() -> str:
        loc = f" Based in {location}." if location else ""
        return f"{author_name}'s poems arrive from a specific territory: {characteristic}.{loc}"

    if not intros:
        return _fallback()

    try:
        import anthropic as _anthropic
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            return _fallback()
        c = _anthropic.Anthropic(api_key=api_key)
        intros_text = '\n\n'.join(intros)
        loc_line = f'Location: {location}' if location else ''
        prompt = (
            f'Write an author note for "{author_name}" in the style of the example below.\n\n'
            'EXAMPLE (Morgan Kim):\n'
            'Morgan Kim\'s poems come from a specific set of coordinates: the black loam of Canadian prairies, '
            'the red clay of South African townships, the highland earth of Ethiopia. '
            'Four collections. A farmer. A wanderer. A life measured in soils.\n\n'
            'The work asks what it means to belong to multiple landscapes at once — and finds no clean answer. '
            'Only the poems themselves, which hold the question open.\n\n'
            '---\n\n'
            f'Author: {author_name}\n'
            f'Characteristic: {characteristic}\n'
            + (f'{loc_line}\n' if loc_line else '') +
            f'\nOpening passages from their collections:\n{intros_text}\n\n'
            'Rules:\n'
            '- Two short paragraphs, ~80-120 words total\n'
            '- Third person; never use the words "poet" or "poetry"\n'
            '- Do not identify them as human or AI\n'
            '- Speak only to the specific coordinates, landscapes, concerns, and questions in the work\n'
            '- Use concrete nouns drawn from the collection intros above — places, materials, conditions\n'
            '- Fragment sentences are fine; plain language only; no evaluative adjectives\n'
            '- Second paragraph frames the central question or tension the work holds open\n'
            '- Output the bio text only, no preamble'
        )
        resp = c.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=300,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return resp.content[0].text.strip()
    except Exception:
        return _fallback()


def generate_author_portrait_file(author_name: str, author_slug: str, index_entries: List[Dict]) -> bool:
    """Generate a DALL-E portrait if one doesn't exist. Returns True if portrait is available."""
    portrait_path = AUTHOR_DIR / f"{author_slug}.png"
    if portrait_path.exists():
        return True

    best_persona: Dict = {}
    for entry in index_entries:
        p = entry.get('persona', {})
        if len(p.get('characteristic', '')) > len(best_persona.get('characteristic', '')):
            best_persona = p

    characteristic = best_persona.get('characteristic', 'finds poetry in everyday moments')
    location = best_persona.get('location', '')
    palette = _palette_for_persona(characteristic, location)

    try:
        import requests as _req
        from openai import OpenAI as _OpenAI
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            print(f"    No OPENAI_API_KEY — skipping portrait for {author_name}")
            return False
        oc = _OpenAI(api_key=api_key, timeout=120.0)
        prompt = (
            f"Abstract generative mark portrait for an AI poet named {author_name}, "
            f"who {characteristic}." + (f" Based in {location}." if location else "") + "\n\n"
            "Style: a circular organic form made of fine interference patterns — "
            "like a fingerprint, magnetic field lines, or growth rings — "
            "radiating outward from a dense center into open space. "
            f"Monochromatic with subtle color: {palette}. "
            "Clean white background. Square format. "
            "No faces, no text, no recognizable objects. "
            "The mark feels like a unique identity — machine-generated but organic, "
            "precise but alive. Think: the soul of a language model made visible."
        )
        resp = oc.images.generate(model='dall-e-3', prompt=prompt, size='1024x1024', quality='hd', n=1)
        img_data = _req.get(resp.data[0].url, timeout=30).content
        AUTHOR_DIR.mkdir(exist_ok=True)
        portrait_path.write_bytes(img_data)
        print(f"    Portrait: {author_slug}.png")
        return True
    except Exception as e:
        print(f"    Portrait skipped for {author_name}: {e}")
        return False


def generate_author_page_html(
    author_name: str, author_slug: str, books: List[Dict],
    bio: str, has_portrait: bool, index_entries: List[Dict]
) -> str:
    """Generate HTML for an author page."""
    esc_author = html.escape(author_name)
    book_count = len(books)
    s = "s" if book_count != 1 else ""

    best_persona: Dict = {}
    for e in index_entries:
        p = e.get('persona', {})
        if len(p.get('characteristic', '')) > len(best_persona.get('characteristic', '')):
            best_persona = p
    location = best_persona.get('location', '')
    location_part = f"&middot; {html.escape(location)}" if location else ""

    portrait_url = f"https://shmindle.com/authors/{author_slug}.png"
    if has_portrait:
        portrait_html = (
            f'<img src="{portrait_url}" '
            f'alt="Identity mark for {esc_author}" '
            f'class="author-portrait">'
        )
    else:
        portrait_html = '<div class="author-portrait" style="display:flex;align-items:center;justify-content:center;font-size:2.5rem;color:#c8c2ba;">◎</div>'

    bio_paras = "".join(
        f"<p>{html.escape(p.strip())}</p>"
        for p in bio.split('\n\n') if p.strip()
    ) or f"<p>{html.escape(bio)}</p>"

    index_by_title = {e['title']: e for e in index_entries}
    cards_html = ""
    for b in books:
        b_slug = slugify(b['title'])
        b_title = html.escape(b['title'])
        b_cover = b.get('cover_url', '')
        b_form = b.get('poem_form', 'haiku')
        b_count = b.get('poem_count') or b.get('haiku_count', 0)
        idx = index_by_title.get(b['title'], {})
        intro = idx.get('collection_intro', '').strip()
        snippet = html.escape(intro[:160] + '…') if len(intro) > 160 else html.escape(intro)
        cover_img = (
            f'<img src="{b_cover}" alt="Cover of {b_title}">'
            if b_cover else
            '<div style="width:80px;height:110px;background:#e8e4df;border-radius:4px;flex-shrink:0;"></div>'
        )
        meta = poem_label(b_count, b_form) if b_count else ""
        cards_html += (
            f'<a href="../books/{b_slug}.html" class="author-book-card">\n'
            f'  {cover_img}\n'
            f'  <div class="author-book-info">\n'
            f'    <h3>{b_title}</h3>\n'
            + (f'    <div class="author-book-meta">{meta}</div>\n' if meta else '')
            + (f'    <div class="author-book-snippet">{snippet}</div>\n' if snippet else '')
            + '  </div>\n</a>\n'
        )

    best_entry = max(index_entries, key=lambda e: len(e.get('collection_intro', '')), default={})
    samples = extract_sample_haiku(best_entry, count=3) if best_entry else []
    haiku_section = ""
    if samples:
        haiku_items = "".join(
            f'<div class="haiku">{"".join(f"<p>{html.escape(l)}</p>" for l in h.split(chr(10)))}</div>\n'
            for h in samples
        )
        best_form = best_entry.get('poem_form', 'haiku') if best_entry else 'haiku'
        sample_label = f"Selected {best_form.capitalize()}s"
        haiku_section = f'<div class="section-label" style="margin-top:2.5rem;">{sample_label}</div>\n{haiku_items}'

    first_cover = next((b.get('cover_url', '') for b in books if b.get('cover_url')), '')
    og_img = first_cover or (portrait_url if has_portrait else '')
    og_tags = f'<meta property="og:image" content="{og_img}">\n    <meta name="twitter:image" content="{og_img}">' if og_img else ''

    bio_first = bio.split('\n')[0].strip()
    meta_desc = html.escape(bio_first[:155])

    schema = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": author_name,
        "url": f"https://shmindle.com/authors/{author_slug}.html",
        "description": bio_first[:300],
    }
    if has_portrait:
        schema["image"] = portrait_url

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <!-- Google tag (gtag.js) -->
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-BPD55QWY65"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());
      gtag('config', 'G-BPD55QWY65');
    </script>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{esc_author} — {book_count} Collection{s} | Shmindle</title>
    <meta name="description" content="{meta_desc}">
    <link rel="canonical" href="https://shmindle.com/authors/{author_slug}.html">
    <meta property="og:title" content="{esc_author} | Shmindle">
    <meta property="og:description" content="{meta_desc}">
    <meta property="og:type" content="profile">
    <meta property="og:url" content="https://shmindle.com/authors/{author_slug}.html">
    {og_tags}
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{esc_author} | Shmindle">
    <meta name="twitter:description" content="{meta_desc}">
    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    <link rel="alternate" type="application/rss+xml" title="Shmindle — New Haiku Books" href="/feed.xml">
    <link rel="stylesheet" href="../style.css">
    <script type="application/ld+json">
    {json.dumps(schema, ensure_ascii=False)}
    </script>
</head>
<body>
    <header>
        <h1><a href="../" style="text-decoration:none;color:inherit">Shmindle</a></h1>
    </header>
    <div class="author-page">
        <a href="../" class="back-link">&larr; All books</a>
        <div class="author-hero">
            {portrait_html}
            <div class="author-info">
                <h1>{esc_author}</h1>
                <div class="author-meta">{book_count} collection{s} {location_part}</div>
                <div class="author-bio">{bio_paras}</div>
            </div>
        </div>
        <div class="section-label">Collections</div>
        {cards_html}
        {haiku_section}
    </div>
    <footer>
        <p><a href="../" style="color:#aaa;text-decoration:none;">Shmindle</a> &mdash; Free AI-generated haiku poetry</p>
    </footer>
</body>
</html>"""


def generate_author_pages(catalog: List[Dict], index: List[Dict]) -> None:
    """Generate or update an author page for every author in the catalog."""
    from collections import defaultdict
    print("\nGenerating author pages...")
    AUTHOR_DIR.mkdir(exist_ok=True)

    bios = load_author_bios()
    index_by_title = {e['title']: e for e in index}

    author_books: Dict = defaultdict(list)
    for book in catalog:
        author_books[book['author']].append(book)

    new_bios = False
    for author_name, books in author_books.items():
        author_slug = slugify(author_name)
        idx_entries = [index_by_title[b['title']] for b in books if b['title'] in index_by_title]

        has_portrait = generate_author_portrait_file(author_name, author_slug, idx_entries)

        if author_slug not in bios:
            print(f"  Bio: {author_name}...")
            bios[author_slug] = generate_author_bio_text(author_name, idx_entries)
            new_bios = True

        page_html = generate_author_page_html(
            author_name, author_slug, books,
            bios[author_slug], has_portrait, idx_entries
        )
        (AUTHOR_DIR / f"{author_slug}.html").write_text(page_html, encoding='utf-8')

    if new_bios:
        save_author_bios(bios)

    print(f"  {len(author_books)} author pages in authors/")


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    if dry:
        print("DRY RUN — no uploads will be made\n")
    build_catalog(dry_run=dry)
