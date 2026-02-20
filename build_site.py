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
COVERS_DIR = PIPELINE_DIR / "haiku_output"
OUTPUT_DIR = Path.home() / "haikus" / "book_formatter" / "output"

# GitHub repo for releases
GITHUB_REPO = "leoshvartsman/haiku-books"

# Base URL for the Cloudflare Worker proxy (serves files with Content-Disposition: inline)
DOWNLOAD_PROXY = "https://shmindle.com/dl"

# Output
SITE_DIR = Path(__file__).parent
CATALOG_FILE = SITE_DIR / "catalog.json"


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
    """Convert title to URL-friendly slug."""
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')


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


def find_cover(title: str) -> Optional[Path]:
    """Find the cover image for a book title."""
    # Cover files use underscores: cover_Title_Words.png
    cover_name = "cover_" + title.replace(" ", "_").replace("'", "").replace(",", "") + ".png"
    path = COVERS_DIR / cover_name
    if path.exists():
        return path

    # Try with hyphens replaced
    cover_name2 = "cover_" + re.sub(r'[^a-zA-Z0-9]+', '_', title) + ".png"
    path2 = COVERS_DIR / cover_name2
    if path2.exists():
        return path2

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
        index = json.load(f)

    print(f"Found {len(index)} books in index")
    catalog = []
    tmp_dir = SITE_DIR / "_tmp_covers"
    tmp_dir.mkdir(exist_ok=True)

    for book in index:
        title = book["title"]
        author = book["author"]
        slug = slugify(title)
        tag = f"book-{slug}"
        haiku_count = book.get("haiku_count", 0)
        date = parse_date(book.get("generated_at", ""))

        print(f"\n[{title}] by {author}")

        # Find assets on disk
        pdf_path = OUTPUT_DIR / f"{slug}.pdf"
        epub_path = OUTPUT_DIR / f"{slug}.epub"
        cover_path = find_cover(title)

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
                "haiku_count": haiku_count,
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
            "haiku_count": haiku_count,
            "date": date,
            "slug": slug,
            "cover_url": urls.get("cover", ""),
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

    # Generate individual book pages
    if not dry_run:
        generate_book_pages(catalog, index)
        generate_sitemap(catalog)
        generate_robots()

    # Cleanup tmp
    shutil.rmtree(tmp_dir, ignore_errors=True)


def extract_sample_haiku(book_index_entry: Dict, count: int = 6) -> List[str]:
    """Extract sample haiku from book_index.json or fall back to text file."""
    # Prefer stored samples in book_index.json
    stored = book_index_entry.get("sample_haiku", [])
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

    # Extract haiku: lines starting with a number followed by a period
    haiku_list = []
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if re.match(r'^\d+\.\s*$', line):
            # Next 3 lines are the haiku
            h_lines = []
            for j in range(1, 4):
                if i + j < len(lines) and lines[i + j].strip():
                    h_lines.append(lines[i + j].strip())
            if len(h_lines) == 3:
                haiku_list.append('\n'.join(h_lines))
            i += 4
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


def generate_book_page(book_catalog: Dict, book_index_entry: Dict) -> None:
    """Generate an individual HTML page for a book."""
    slug = slugify(book_catalog["title"])
    title = html.escape(book_catalog["title"])
    author = html.escape(book_catalog["author"])
    haiku_count = book_catalog["haiku_count"]
    cover_url = book_catalog.get("cover_url", "")
    pdf_url = book_catalog.get("pdf_url", "")
    epub_url = book_catalog.get("epub_url", "")

    intro = html.escape(extract_intro(book_index_entry))
    samples = extract_sample_haiku(book_index_entry)

    # Build sample haiku HTML
    samples_html = ""
    for h in samples:
        lines_html = ''.join(f'<p>{html.escape(line)}</p>' for line in h.split('\n'))
        samples_html += f'<div class="haiku">{lines_html}</div>\n'

    # Cover image HTML
    cover_html = f'<img src="{cover_url}" alt="{title}">' if cover_url else ''

    # Download buttons
    dl_html = ""
    if pdf_url:
        dl_html += f'<a href="{pdf_url}" class="btn-pdf" type="application/pdf">Download PDF</a>\n'
    if epub_url:
        dl_html += f'<a href="{epub_url}" class="btn-epub" type="application/epub+zip">Download EPUB</a>\n'

    # Schema.org structured data
    schema = {
        "@context": "https://schema.org",
        "@type": "Book",
        "name": book_catalog["title"],
        "author": {"@type": "Person", "name": book_catalog["author"]},
        "bookFormat": "EBook",
        "url": f"https://shmindle.com/books/{slug}.html",
        "numberOfPages": haiku_count,
        "genre": "Poetry",
        "inLanguage": "en",
        "isAccessibleForFree": True,
    }
    if cover_url:
        schema["image"] = cover_url

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} by {author} — Shmindle</title>
    <meta name="description" content="{title} — a collection of {haiku_count} haiku by {author}. Free to download as PDF or EPUB.">
    <link rel="canonical" href="https://shmindle.com/books/{slug}.html">

    <meta property="og:title" content="{title} by {author}">
    <meta property="og:description" content="A collection of {haiku_count} haiku. Free to download.">
    <meta property="og:type" content="book">
    <meta property="og:url" content="https://shmindle.com/books/{slug}.html">
    {"<meta property='og:image' content='" + cover_url + "'>" if cover_url else ""}

    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{title} by {author}">
    <meta name="twitter:description" content="A collection of {haiku_count} haiku. Free to download.">

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
                <div class="author">{author}</div>
                <div class="meta">{haiku_count} haiku</div>
                <div class="download-btns">
                    {dl_html}
                </div>
            </div>
        </div>

        {"<div class='book-intro'>" + intro + "</div>" if intro else ""}

        {"<div class='sample-haiku'><h2>Sample Haiku</h2>" + samples_html + "</div>" if samples_html else ""}
    </div>

    <footer>
        <p>Your home for books generated by AI. Free to download anytime.</p>
    </footer>
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
        generate_book_page(book, idx_entry)

    print(f"  Generated {len(catalog)} book pages in books/")


def generate_sitemap(catalog: List[Dict]) -> None:
    """Generate sitemap.xml for search engines."""
    urls = ['  <url><loc>https://shmindle.com/</loc><priority>1.0</priority></url>']
    for book in catalog:
        slug = slugify(book["title"])
        urls.append(f'  <url><loc>https://shmindle.com/books/{slug}.html</loc><priority>0.8</priority></url>')

    sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""

    (SITE_DIR / "sitemap.xml").write_text(sitemap, encoding='utf-8')
    print(f"  Generated sitemap.xml ({len(urls)} URLs)")


def generate_robots() -> None:
    """Generate robots.txt."""
    robots = """User-agent: *
Allow: /
Sitemap: https://shmindle.com/sitemap.xml
"""
    (SITE_DIR / "robots.txt").write_text(robots, encoding='utf-8')
    print("  Generated robots.txt")


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    if dry:
        print("DRY RUN — no uploads will be made\n")
    build_catalog(dry_run=dry)
