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

import json
import re
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

# Output
SITE_DIR = Path(__file__).parent
CATALOG_FILE = SITE_DIR / "catalog.json"


def slugify(title: str) -> str:
    """Convert title to URL-friendly slug."""
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')


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
        date = book.get("generated_at", "")[:10]  # YYYY-MM-DD

        print(f"\n[{title}] by {author}")

        # Find assets on disk
        pdf_path = OUTPUT_DIR / f"{slug}.pdf"
        epub_path = OUTPUT_DIR / f"{slug}.epub"
        cover_path = find_cover(title)

        if not pdf_path.exists() and not epub_path.exists():
            print(f"  Skipping: no PDF or EPUB found ({slug})")
            continue

        # Convert cover to JPG
        cover_jpg = None
        if cover_path:
            cover_jpg = tmp_dir / f"{slug}.jpg"
            if not convert_cover_to_jpg(cover_path, cover_jpg):
                cover_jpg = None

        if dry_run:
            print(f"  Would upload: PDF={pdf_path.exists()}, EPUB={epub_path.exists()}, Cover={cover_jpg is not None}")
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

        # Check if release already exists
        if release_exists(tag):
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

        catalog.append({
            "title": title,
            "author": author,
            "haiku_count": haiku_count,
            "date": date,
            "cover_url": urls.get("cover", ""),
            "pdf_url": urls.get("pdf", ""),
            "epub_url": urls.get("epub", ""),
        })

    # Sort by date descending
    catalog.sort(key=lambda b: b["date"], reverse=True)

    # Write catalog
    with open(CATALOG_FILE, 'w') as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 50}")
    print(f"Catalog written: {CATALOG_FILE}")
    print(f"Books in catalog: {len(catalog)}")

    # Cleanup tmp
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    if dry:
        print("DRY RUN — no uploads will be made\n")
    build_catalog(dry_run=dry)
