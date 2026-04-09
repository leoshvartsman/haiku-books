#!/usr/bin/env python3
"""
Generate author pages for all authors with 2+ books.

Run from haiku-books/:
    python3 gen_author_pages.py           # multi-book authors only (default)
    python3 gen_author_pages.py --all     # all 146 authors
    python3 gen_author_pages.py --dry     # show who would be processed, no API calls

Skips authors whose portrait already exists (won't re-charge DALL-E).
Skips authors whose bio already exists in bios.json.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Run from haiku-books dir
import os
os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path.home() / "haikus" / "haiku-generator" / ".env")

# Import helpers from build_site
from build_site import (
    AUTHOR_DIR,
    AUTHOR_BIOS_FILE,
    BOOK_INDEX,
    load_author_bios,
    save_author_bios,
    generate_author_portrait_file,
    generate_author_bio_text,
    generate_author_page_html,
    slugify,
)

CATALOG_FILE = Path(__file__).parent / "catalog.json"


def main():
    dry = "--dry" in sys.argv
    all_authors = "--all" in sys.argv

    catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    index = json.loads(BOOK_INDEX.read_text(encoding="utf-8"))
    index_by_title = {e["title"]: e for e in index}

    # Count books per author
    author_counts = Counter(b["author"] for b in catalog)

    # Build author -> books mapping
    author_books = defaultdict(list)
    for book in catalog:
        author_books[book["author"]].append(book)

    # Filter to multi-book authors unless --all
    if all_authors:
        targets = list(author_books.keys())
        label = "all"
    else:
        targets = [a for a, c in author_counts.items() if c >= 2]
        label = "multi-book"

    targets.sort(key=lambda a: -author_counts[a])  # most books first

    print(f"\nGenerating author pages — {label} authors ({len(targets)} total)")
    if dry:
        print("DRY RUN — no API calls or files written\n")

    bios = load_author_bios()
    new_bios = False
    portraits_generated = 0
    bios_generated = 0
    pages_written = 0

    for i, author_name in enumerate(targets, 1):
        author_slug = slugify(author_name)
        books = author_books[author_name]
        idx_entries = [index_by_title[b["title"]] for b in books if b["title"] in index_by_title]

        portrait_exists = (AUTHOR_DIR / f"{author_slug}.png").exists()
        bio_exists = author_slug in bios

        status_parts = []
        if portrait_exists:
            status_parts.append("portrait✓")
        if bio_exists:
            status_parts.append("bio✓")
        status = f"  [{i}/{len(targets)}] {author_name} ({len(books)} books) {' '.join(status_parts)}"
        print(status)

        if dry:
            if not portrait_exists:
                print(f"    would generate portrait (~$0.12)")
            if not bio_exists:
                print(f"    would generate bio (Haiku)")
            continue

        # Portrait (skips if file exists)
        has_portrait = generate_author_portrait_file(author_name, author_slug, idx_entries)
        if has_portrait and not portrait_exists:
            portraits_generated += 1

        # Bio (skips if already in bios.json)
        if author_slug not in bios:
            print(f"    Generating bio...")
            bios[author_slug] = generate_author_bio_text(author_name, idx_entries)
            new_bios = True
            bios_generated += 1

        # HTML page (always regenerated)
        page_html = generate_author_page_html(
            author_name, author_slug, books,
            bios[author_slug], has_portrait, idx_entries,
        )
        out_path = AUTHOR_DIR / f"{author_slug}.html"
        AUTHOR_DIR.mkdir(exist_ok=True)
        out_path.write_text(page_html, encoding="utf-8")
        pages_written += 1

        # Save bios periodically so crashes don't lose work
        if new_bios and bios_generated % 5 == 0:
            save_author_bios(bios)
            print(f"    (bios.json checkpoint saved)")

    if not dry:
        if new_bios:
            save_author_bios(bios)

        print(f"\nDone.")
        print(f"  Portraits generated : {portraits_generated}")
        print(f"  Bios generated      : {bios_generated}")
        print(f"  Pages written       : {pages_written}")
        print(f"\nNext: git add authors/ && git commit && git push")
    else:
        need_portrait = sum(
            1 for a in targets
            if not (AUTHOR_DIR / f"{slugify(a)}.png").exists()
        )
        need_bio = sum(
            1 for a in targets
            if slugify(a) not in bios
        )
        print(f"\nDry run summary:")
        print(f"  Authors to process  : {len(targets)}")
        print(f"  Portraits needed    : {need_portrait} (~${need_portrait * 0.12:.2f})")
        print(f"  Bios needed         : {need_bio}")


if __name__ == "__main__":
    main()
