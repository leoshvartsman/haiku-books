#!/usr/bin/env python3
"""
notify_subscribers.py — send Buttondown email when new books are published.

Run after build_site.py updates catalog.json. Reads last_notified.json to
track which books have already been emailed, sends a digest for new ones,
then updates last_notified.json.

Usage:
    ANTHROPIC_API_KEY is NOT needed here.
    BUTTONDOWN_API_KEY must be set in the environment.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

CATALOG = Path(__file__).parent / "catalog.json"
LAST_NOTIFIED = Path(__file__).parent / "last_notified.json"
BUTTONDOWN_API = "https://api.buttondown.com/v1"


def load_catalog():
    with open(CATALOG) as f:
        return json.load(f)


def load_notified():
    if LAST_NOTIFIED.exists():
        with open(LAST_NOTIFIED) as f:
            return set(json.load(f))
    return set()


def save_notified(slugs):
    with open(LAST_NOTIFIED, "w") as f:
        json.dump(sorted(slugs), f, indent=2)


def slugify(title):
    import re
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    return slug


def build_email(new_books):
    """Build HTML email body listing new books."""
    count = len(new_books)
    noun = "book" if count == 1 else "books"

    items_html = ""
    for book in new_books:
        slug = slugify(book["title"])
        cover_url = book.get("cover", "")
        pdf_url = f"https://shmindle.com/dl/book-{slug}/{slug}.pdf"
        epub_url = f"https://shmindle.com/dl/book-{slug}/{slug}.epub"
        page_url = f"https://shmindle.com/books/{slug}.html"

        cover_img = (
            f'<img src="{cover_url}" alt="Cover of {book["title"]}" '
            f'style="width:120px;height:120px;object-fit:cover;border-radius:6px;display:block;">'
            if cover_url else
            f'<div style="width:120px;height:120px;background:#e8e4df;border-radius:6px;'
            f'display:flex;align-items:center;justify-content:center;font-size:2rem;">📖</div>'
        )

        items_html += f"""
        <div style="display:flex;gap:1.5rem;align-items:flex-start;
                    margin-bottom:2rem;padding-bottom:2rem;
                    border-bottom:1px solid #ede9e4;">
          <a href="{page_url}" style="flex-shrink:0;text-decoration:none;">{cover_img}</a>
          <div>
            <div style="font-size:1.1rem;font-weight:600;margin-bottom:0.25rem;">
              <a href="{page_url}" style="color:#2c2c2c;text-decoration:none;">{book["title"]}</a>
            </div>
            <div style="color:#888;font-size:0.9rem;margin-bottom:0.75rem;">
              by {book.get("author", "Unknown")}
            </div>
            <div style="display:flex;gap:0.5rem;flex-wrap:wrap;">
              <a href="{pdf_url}" style="padding:0.35rem 0.85rem;background:#f0ebe4;
                 color:#5a4a3a;border-radius:5px;font-size:0.85rem;text-decoration:none;">PDF</a>
              <a href="{epub_url}" style="padding:0.35rem 0.85rem;background:#e8ede4;
                 color:#3a5a3a;border-radius:5px;font-size:0.85rem;text-decoration:none;">EPUB</a>
            </div>
          </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
             background:#faf8f5;color:#2c2c2c;margin:0;padding:0;">
  <div style="max-width:560px;margin:0 auto;padding:2rem 1.5rem;">

    <!-- Header -->
    <div style="text-align:center;margin-bottom:2.5rem;">
      <div style="font-size:1.8rem;font-weight:300;letter-spacing:0.08em;color:#3a3a3a;">
        Shmindle
      </div>
      <div style="color:#888;font-size:0.9rem;margin-top:0.25rem;">
        {count} new {noun} published
      </div>
    </div>

    <!-- Books -->
    {items_html}

    <!-- Footer -->
    <div style="text-align:center;color:#aaa;font-size:0.8rem;margin-top:2rem;">
      <a href="https://shmindle.com/" style="color:#888;text-decoration:none;">
        Browse all books at shmindle.com
      </a>
      <br><br>
      You're receiving this because you subscribed to new book notifications.<br>
      <a href="{{{{ unsubscribe_url }}}}" style="color:#aaa;">Unsubscribe</a>
    </div>

  </div>
</body>
</html>"""


def send_email(subject, html_body, api_key):
    import urllib.request
    payload = json.dumps({
        "subject": subject,
        "body": html_body,
        "status": "sent",
    }).encode()

    req = urllib.request.Request(
        f"{BUTTONDOWN_API}/emails",
        data=payload,
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            print(f"  Email sent: id={data.get('id')}, status={data.get('status')}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  Buttondown error {e.code}: {body}", file=sys.stderr)
        return False


def main():
    api_key = os.environ.get("BUTTONDOWN_API_KEY")
    if not api_key:
        print("BUTTONDOWN_API_KEY not set — skipping notification.")
        sys.exit(0)

    catalog = load_catalog()
    notified = load_notified()

    new_books = [b for b in catalog if slugify(b["title"]) not in notified]

    if not new_books:
        print("No new books to notify about.")
        return

    print(f"Found {len(new_books)} new book(s) to notify:")
    for b in new_books:
        print(f"  - {b['title']}")

    count = len(new_books)
    if count == 1:
        subject = f"New haiku book: {new_books[0]['title']}"
    else:
        subject = f"{count} new haiku books on Shmindle"

    html_body = build_email(new_books)
    ok = send_email(subject, html_body, api_key)

    if ok:
        # Mark all catalog books as notified (not just new_books, to catch any gaps)
        all_slugs = notified | {slugify(b["title"]) for b in catalog}
        save_notified(all_slugs)
        print(f"Updated last_notified.json ({len(all_slugs)} total slugs).")
    else:
        print("Email send failed — last_notified.json not updated.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
