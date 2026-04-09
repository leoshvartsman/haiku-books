#!/usr/bin/env python3
"""
rate_book.py — ELO rate all poems from a single AI book via Ollama.

Finds the raw book output file, extracts all haiku, adds any new ones to
corpus.json, then runs ELO comparisons pairing each new poem against
existing rated poems. Saves progress every CHECKPOINT_EVERY pairs so
a crash or kill doesn't lose all work.

Usage:
  python rate_book.py salt-stains-and-marble-steps
  python rate_book.py --list                          # show available books
  python rate_book.py salt-stains-and-marble-steps --model llama3.2
  python rate_book.py salt-stains-and-marble-steps --pairs-per-poem 3
"""

import argparse
import html
import json
import random
import re
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_DIR      = Path(__file__).parent
RATINGS_DIR   = REPO_DIR / "ratings"
CORPUS_PATH   = RATINGS_DIR / "corpus.json"
OUTPUT_PATH   = RATINGS_DIR / "ratings.json"
CATALOG_PATH  = REPO_DIR / "catalog.json"
HAIKU_OUTPUT  = Path("/Users/leo/haikus/haiku-generator/haiku_output")

DEFAULT_MODEL       = "llama3.1"
OLLAMA_URL          = "http://localhost:11434/api/chat"
K_FACTOR_NEW        = 32
K_FACTOR_OLD        = 16
RECENT_OPPONENT_MEMORY = 10
CHECKPOINT_EVERY    = 25   # save corpus.json every N completed pairs
DEFAULT_PAIRS_PER_POEM = 3  # how many matches to run for each new poem

# ---------------------------------------------------------------------------
# Shared judge prompt (same as rate_poems.py)
# ---------------------------------------------------------------------------

JUDGE_SYSTEM = """You are an expert haiku judge with deep knowledge of both classical Japanese haiku tradition and contemporary English-language haiku. You evaluate poems on their literary merit with precise, consistent criteria."""

JUDGE_PROMPT = """Compare these two haiku on 6 literary dimensions. Score each dimension from 1 to 5.

DIMENSIONS:
1. Image Precision — Is the image specific, concrete, and sensory? (1=abstract/generic, 5=exact and irreplaceable)
2. The Cut — Is there a productive juxtaposition or turn between two elements? (1=no tension, 5=gap is the whole meaning)
3. Economy — Is every word load-bearing? (1=padded/redundant, 5=each word irreplaceable)
4. Resonance — Does the poem linger and open outward after reading? (1=closed/exhausted, 5=continues to expand)
5. Originality — Is this a fresh perception or a familiar cliché? (1=cliché, 5=genuinely new)
6. Musicality — Does it reward being read aloud? (1=clunky, 5=sound inseparable from meaning)

POEM A:
{line1_a}
{line2_a}
{line3_a}

POEM B:
{line1_b}
{line2_b}
{line3_b}

Respond with JSON only — no other text:
{{
  "a": {{"image_precision": N, "cut": N, "economy": N, "resonance": N, "originality": N, "musicality": N}},
  "b": {{"image_precision": N, "cut": N, "economy": N, "resonance": N, "originality": N, "musicality": N}},
  "winner": "a" or "b" or "draw",
  "reasoning": "One sentence explaining the decisive difference."
}}"""


# ---------------------------------------------------------------------------
# ELO math (identical to rate_poems.py)
# ---------------------------------------------------------------------------

def expected_score(rating_a, rating_b):
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))


def k_factor(matches):
    return K_FACTOR_NEW if matches < 20 else K_FACTOR_OLD


def update_elo(poem_a, poem_b, winner):
    ea = expected_score(poem_a["elo"], poem_b["elo"])
    eb = 1.0 - ea
    sa, sb = {"a": (1.0, 0.0), "b": (0.0, 1.0)}.get(winner, (0.5, 0.5))

    ka = k_factor(poem_a["matches"])
    kb = k_factor(poem_b["matches"])

    poem_a["elo"] = round(poem_a["elo"] + ka * (sa - ea), 1)
    poem_b["elo"] = round(poem_b["elo"] + kb * (sb - eb), 1)

    for poem, s, opp in [(poem_a, sa, poem_b), (poem_b, sb, poem_a)]:
        poem["matches"] += 1
        if s == 1.0:   poem["wins"]   += 1
        elif s == 0.0: poem["losses"] += 1
        else:          poem["draws"]  += 1
        poem["recent_opponents"] = (
            [opp["id"]] + poem.get("recent_opponents", [])
        )[:RECENT_OPPONENT_MEMORY]


def update_dim_averages(poem, scores):
    avgs = poem.setdefault("dim_averages", {
        "image_precision": None, "cut": None, "economy": None,
        "resonance": None, "originality": None, "musicality": None
    })
    n = poem["matches"]
    for dim, val in scores.items():
        if dim not in avgs:
            continue
        prev = avgs[dim]
        avgs[dim] = round(val if prev is None else (prev * (n - 1) + val) / n, 2)


# ---------------------------------------------------------------------------
# Ollama API (identical to rate_poems.py)
# ---------------------------------------------------------------------------

def parse_judge_response(text):
    text = re.sub(r'```(?:json)?\s*', '', text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def validate_scores(data):
    dims = ["image_precision", "cut", "economy", "resonance", "originality", "musicality"]
    for side in ["a", "b"]:
        if side not in data:
            return False
        for dim in dims:
            val = data[side].get(dim)
            if not isinstance(val, (int, float)) or not (1 <= val <= 5):
                return False
    if data.get("winner") not in ("a", "b", "draw"):
        return False
    return True


def judge_pair(poem_a, poem_b, model):
    def pad(lines, idx):
        return lines[idx] if idx < len(lines) else ""

    prompt = JUDGE_PROMPT.format(
        line1_a=pad(poem_a["lines"], 0), line2_a=pad(poem_a["lines"], 1), line3_a=pad(poem_a["lines"], 2),
        line1_b=pad(poem_b["lines"], 0), line2_b=pad(poem_b["lines"], 1), line3_b=pad(poem_b["lines"], 2),
    )
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "format": "json",
    }).encode()

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                OLLAMA_URL, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            text = data["message"]["content"]
            result = parse_judge_response(text)
            if result and validate_scores(result):
                for side in ["a", "b"]:
                    result[side]["total"] = sum(
                        result[side][d]
                        for d in ["image_precision", "cut", "economy", "resonance", "originality", "musicality"]
                    )
                return result
            else:
                print(f"    Invalid response (attempt {attempt+1}): {text[:200]}")
        except urllib.error.URLError as e:
            print(f"    Ollama error (attempt {attempt+1}): {e}")
            print(f"    Is Ollama running? Try: ollama serve &")
            time.sleep(2)
        except Exception as e:
            print(f"    Error (attempt {attempt+1}): {e}")
            time.sleep(2)
    return None


# ---------------------------------------------------------------------------
# Ratings summary (identical to rate_poems.py)
# ---------------------------------------------------------------------------

def build_ratings_json(poems):
    ai_poems    = [p for p in poems if p["source"] == "ai"]
    human_poems = [p for p in poems if p["source"] == "human"]

    def avg_elo(group):
        return round(sum(p["elo"] for p in group) / len(group), 1) if group else 1500

    total_matches = sum(p["matches"] for p in poems) // 2
    ai_wins    = sum(p["wins"]  for p in ai_poems)
    human_wins = sum(p["wins"]  for p in human_poems)
    draws      = sum(p["draws"] for p in poems) // 2

    top_ai    = sorted(ai_poems,    key=lambda p: p["elo"], reverse=True)[:10]
    top_human = sorted(human_poems, key=lambda p: p["elo"], reverse=True)[:10]
    leaderboard = sorted(poems, key=lambda p: p["elo"], reverse=True)

    def slim(p, extra=False):
        base = {"id": p["id"], "lines": p["lines"], "author": p["author"],
                "collection": p["collection"], "elo": p["elo"],
                "matches": p["matches"], "wins": p["wins"]}
        if extra:
            base.update({
                "source": p["source"], "losses": p["losses"], "draws": p["draws"],
                "dim_averages": p.get("dim_averages", {}),
                "last_reasoning": p.get("last_reasoning"),
                "translator": p.get("translator"),
            })
        return base

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_matches": total_matches,
        "summary": {
            "ai_count": len(ai_poems), "human_count": len(human_poems),
            "ai_avg_elo": avg_elo(ai_poems), "human_avg_elo": avg_elo(human_poems),
            "ai_wins": ai_wins, "human_wins": human_wins, "draws": draws,
        },
        "top_ai":    [slim(p) for p in top_ai],
        "top_human": [slim(p) for p in top_human],
        "poems":     [slim(p, extra=True) for p in leaderboard],
    }


# ---------------------------------------------------------------------------
# Book discovery
# ---------------------------------------------------------------------------

def load_catalog():
    return json.load(CATALOG_PATH.open())


def find_output_file(slug, catalog):
    """Return Path to the raw haiku output file for the given book slug."""
    entry = next((b for b in catalog if b["slug"] == slug), None)
    if not entry:
        return None, None

    if not HAIKU_OUTPUT.exists():
        return None, entry

    title  = entry["title"].lower()
    author = entry["author"].lower()

    # Title match — search only the first 500 chars (header) to avoid false matches
    # in poem bodies (poetic phrases like "dust motes dancing" can appear anywhere)
    for f in sorted(HAIKU_OUTPUT.glob("book_*.txt")):
        header = f.read_text(errors="replace")[:500].lower()
        if title in header:
            return f, entry

    # Fallback: match by author (only works if author is unique in catalog)
    author_books = [b for b in catalog if b["author"].lower() == author]
    if len(author_books) == 1:
        for f in sorted(HAIKU_OUTPUT.glob("book_*.txt")):
            header = f.read_text(errors="replace")[:500].lower()
            if author in header:
                return f, entry

    return None, entry


def list_available_books(catalog):
    """Print all books, whether their output file exists, and ELO rating status."""
    rated_ids = set()
    if CORPUS_PATH.exists():
        corpus = json.load(CORPUS_PATH.open())
        rated_ids = {p["id"] for p in corpus}

    print(f"{'SLUG':<45} {'TITLE':<35} {'RATED':<8} FILE")
    print("-" * 110)
    for entry in catalog:
        slug = entry["slug"]
        f, _ = find_output_file(slug, catalog)
        file_status = f.name if f else "NO OUTPUT FILE"
        is_rated = "yes" if any(pid.startswith(f"ai-{slug}-full-") for pid in rated_ids) else "no"
        print(f"{slug:<45} {entry['title']:<35} {is_rated:<8} {file_status}")


# ---------------------------------------------------------------------------
# Haiku parsing
# ---------------------------------------------------------------------------

def parse_haiku_from_file(path):
    """Extract all numbered haiku from a raw output file. Returns list of 3-line tuples."""
    text = path.read_text()
    # Numbered haiku: "N.\nline1\nline2\nline3"
    blocks = re.findall(r'^\d+\.\n(.+)\n(.+)\n(.+)', text, re.MULTILINE)
    result = []
    for (l1, l2, l3) in blocks:
        lines = [
            html.unescape(l1.strip()),
            html.unescape(l2.strip()),
            html.unescape(l3.strip()),
        ]
        if all(lines):
            result.append(lines)
    return result


def make_poem_id(slug, idx):
    return f"ai-{slug}-full-{idx}"


def make_poem_entry(poem_id, lines, author, collection):
    return {
        "id":         poem_id,
        "lines":      lines,
        "source":     "ai",
        "author":     author,
        "collection": collection,
        "elo":        1500,
        "matches":    0,
        "wins":       0,
        "losses":     0,
        "draws":      0,
    }


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def save(poems):
    CORPUS_PATH.write_text(json.dumps(poems, indent=2, ensure_ascii=False))
    ratings = build_ratings_json(poems)
    OUTPUT_PATH.write_text(json.dumps(ratings, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def find_unrated_book(catalog):
    """Return (output_file, entry) for the first book with no full poems in the corpus."""
    if not CORPUS_PATH.exists():
        return None, None
    corpus = json.load(CORPUS_PATH.open())
    rated_ids = {p["id"] for p in corpus}

    for entry in catalog:
        slug = entry["slug"]
        output_file, _ = find_output_file(slug, catalog)
        if not output_file:
            continue  # no source file available
        # Check if any full poems from this book are already in the corpus
        if not any(pid.startswith(f"ai-{slug}-full-") for pid in rated_ids):
            return output_file, entry

    return None, None


def main():
    parser = argparse.ArgumentParser(description="ELO rate all poems from one AI book")
    parser.add_argument("slug", nargs="?", help="Book slug (e.g. salt-stains-and-marble-steps). Omit to auto-select next unrated book.")
    parser.add_argument("--list",           action="store_true", help="List available books")
    parser.add_argument("--model",          default=DEFAULT_MODEL, help="Ollama model")
    parser.add_argument("--pairs-per-poem", type=int, default=DEFAULT_PAIRS_PER_POEM,
                        help="Number of ELO matches to run per new poem (default 3)")
    args = parser.parse_args()

    catalog = load_catalog()

    if args.list:
        list_available_books(catalog)
        return

    if not args.slug:
        # Auto-select the next unrated book
        output_file, entry = find_unrated_book(catalog)
        if not entry:
            raise SystemExit("All available books have already been rated. Run --list to see status.")
        print(f"Auto-selected next unrated book: {entry['title']} by {entry['author']}")
    else:
        # --- find the specified book ---
        output_file, entry = find_output_file(args.slug, catalog)
        if not entry:
            raise SystemExit(f"No book with slug '{args.slug}' found in catalog.json")
        if not output_file:
            raise SystemExit(
                f"No raw output file found for '{args.slug}'.\n"
                f"Expected a file in {HAIKU_OUTPUT} matching title '{entry['title']}' or author '{entry['author']}'"
            )

    slug = entry["slug"]  # use entry slug, not args.slug (args.slug may be None in auto-select)

    print(f"Book:   {entry['title']} by {entry['author']}")
    print(f"File:   {output_file.name}")

    # --- parse all haiku from the file ---
    all_lines = parse_haiku_from_file(output_file)
    if not all_lines:
        raise SystemExit(f"No haiku found in {output_file}")
    print(f"Haiku in file: {len(all_lines)}")

    # --- load corpus ---
    if not CORPUS_PATH.exists():
        raise SystemExit(f"Corpus not found: {CORPUS_PATH}\nRun: python build_corpus.py")
    poems = json.load(CORPUS_PATH.open())
    existing_ids = {p["id"] for p in poems}

    # --- add new poems ---
    new_poems = []
    for idx, lines in enumerate(all_lines, 1):
        poem_id = make_poem_id(slug, idx)
        if poem_id not in existing_ids:
            poem = make_poem_entry(poem_id, lines, entry["author"], entry["title"])
            poems.append(poem)
            new_poems.append(poem)

    print(f"New poems added to corpus: {len(new_poems)}")
    print(f"Already in corpus:         {len(all_lines) - len(new_poems)}")

    if not new_poems:
        print("Nothing to rate — all poems from this book are already in the corpus.")
        return

    # Build list of opponent candidates (all rated poems from the broader corpus)
    def opponent_pool(exclude_id):
        return [p for p in poems if p["id"] != exclude_id and p["matches"] > 0]

    total_pairs = len(new_poems) * args.pairs_per_poem
    print(f"\nRunning {args.pairs_per_poem} matches × {len(new_poems)} poems = {total_pairs} comparisons")
    print(f"Model: {args.model} (local Ollama)")
    print(f"Checkpointing every {CHECKPOINT_EVERY} matches\n")

    completed = 0
    errors    = 0

    # Go through each new poem front to back, run pairs_per_poem matches each
    for poem_idx, new_poem in enumerate(new_poems, 1):
        lines_preview = " / ".join(new_poem["lines"])
        print(f"\n── Poem {poem_idx}/{len(new_poems)}: {lines_preview[:60]}")

        pool = opponent_pool(new_poem["id"])
        if not pool:
            print("  No rated opponents yet — skipping (re-run after more poems are rated)")
            continue

        # Pick opponents — prefer ones not recently matched, weight toward close ELO
        opponents_used = set(new_poem.get("recent_opponents", []))
        available = [p for p in pool if p["id"] not in opponents_used] or pool
        # Weight toward close ELO
        weights = [1.0 / (1.0 + abs(p["elo"] - new_poem["elo"]) / 200) for p in available]
        total_w = sum(weights)
        weights = [w / total_w for w in weights]

        chosen = []
        remaining = list(range(len(available)))
        for _ in range(min(args.pairs_per_poem, len(available))):
            if not remaining:
                break
            r = random.random()
            cumulative = 0.0
            picked = remaining[-1]
            for i in remaining:
                cumulative += weights[i]
                if r <= cumulative:
                    picked = i
                    break
            chosen.append(available[picked])
            remaining.remove(picked)

        for match_num, opponent in enumerate(chosen, 1):
            # Randomly assign A/B to avoid position bias
            if random.random() < 0.5:
                poem_a, poem_b, new_is = new_poem, opponent, "a"
            else:
                poem_a, poem_b, new_is = opponent, new_poem, "b"

            label_a = poem_a["lines"][0][:30]
            label_b = poem_b["lines"][0][:30]
            print(f"  [{match_num}/{args.pairs_per_poem}] {label_a} vs {label_b}")

            result = judge_pair(poem_a, poem_b, args.model)

            if result is None:
                print("    SKIP (no valid response)")
                errors += 1
                continue

            winner   = result["winner"]
            reasoning = result.get("reasoning", "")

            update_elo(poem_a, poem_b, winner)
            update_dim_averages(poem_a, result["a"])
            update_dim_averages(poem_b, result["b"])
            poem_a["last_reasoning"] = reasoning
            poem_b["last_reasoning"] = reasoning

            label = {"a": "A wins", "b": "B wins"}.get(winner, "Draw")
            print(f"    {label} | A:{result['a']['total']}/30  B:{result['b']['total']}/30")
            print(f"    New poem ELO → {new_poem['elo']}")
            print(f"    \"{reasoning}\"")

            completed += 1

            # Checkpoint
            if completed % CHECKPOINT_EVERY == 0:
                save(poems)
                print(f"\n  ✓ Checkpoint saved ({completed}/{total_pairs} matches)\n")
                subprocess.run([
                    "osascript", "-e",
                    f'display notification "Checkpoint {completed}/{total_pairs} matches saved." with title "rate_book.py" sound name "Glass"'
                ])

    # Final save
    save(poems)

    ai_poems    = [p for p in poems if p["source"] == "ai"]
    human_poems = [p for p in poems if p["source"] == "human"]
    ai_avg    = round(sum(p["elo"] for p in ai_poems)    / len(ai_poems),    1) if ai_poems    else 0
    human_avg = round(sum(p["elo"] for p in human_poems) / len(human_poems), 1) if human_poems else 0

    print(f"\n{'='*60}")
    print(f"Done: {completed} matches, {errors} errors")
    print(f"Corpus: {len(poems)} poems total")
    print(f"AI avg ELO: {ai_avg}  |  Human avg ELO: {human_avg}")
    print(f"Corpus saved → {CORPUS_PATH}")
    print(f"Ratings saved → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
