#!/usr/bin/env python3
"""
rate_poems.py — Run ELO rating comparisons on the haiku corpus via Ollama.

Reads ratings/corpus.json, selects pairs of poems, asks a local Ollama model
to score each on 6 literary dimensions, updates ELO ratings, and writes:
  - ratings/corpus.json  (updated ELO state)
  - ratings/ratings.json (summary for the website)

Usage:
  python rate_poems.py                  # 50 pairs (default)
  python rate_poems.py --pairs 500      # 500 pairs
  python rate_poems.py --pairs 100 --model llama3.1
"""

import argparse
import json
import math
import os
import random
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# Claude API support (only imported when needed)
def _judge_claude(prompt: str, system: str, model: str) -> str:
    """Call Anthropic Claude API and return response text."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    msg = client.messages.create(
        model=model,
        max_tokens=512,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text

RATINGS_DIR = Path(__file__).parent / "ratings"
CORPUS_PATH = RATINGS_DIR / "corpus.json"
OUTPUT_PATH = RATINGS_DIR / "ratings.json"

DEFAULT_PAIRS = 50
DEFAULT_MODEL = "llama3.1"
OLLAMA_URL = "http://localhost:11434/api/chat"
K_FACTOR_NEW = 32   # for poems with < 20 matches
K_FACTOR_OLD = 16   # for poems with >= 20 matches
RECENT_OPPONENT_MEMORY = 10  # avoid re-pairing within last N opponents

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
# ELO math
# ---------------------------------------------------------------------------

def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))


def k_factor(matches: int) -> int:
    return K_FACTOR_NEW if matches < 20 else K_FACTOR_OLD


def update_elo(poem_a: dict, poem_b: dict, winner: str) -> None:
    """Update ELO ratings in-place for a match result."""
    ea = expected_score(poem_a["elo"], poem_b["elo"])
    eb = 1.0 - ea

    if winner == "a":
        sa, sb = 1.0, 0.0
    elif winner == "b":
        sa, sb = 0.0, 1.0
    else:
        sa, sb = 0.5, 0.5

    ka = k_factor(poem_a["matches"])
    kb = k_factor(poem_b["matches"])

    poem_a["elo"] = round(poem_a["elo"] + ka * (sa - ea), 1)
    poem_b["elo"] = round(poem_b["elo"] + kb * (sb - eb), 1)

    for poem, s, opp in [(poem_a, sa, poem_b), (poem_b, sb, poem_a)]:
        poem["matches"] += 1
        if s == 1.0:
            poem["wins"] += 1
        elif s == 0.0:
            poem["losses"] += 1
        else:
            poem["draws"] += 1

        poem["recent_opponents"] = (
            [opp["id"]] + poem.get("recent_opponents", [])
        )[:RECENT_OPPONENT_MEMORY]


def update_dim_averages(poem: dict, scores: dict) -> None:
    """Update rolling dimension averages."""
    avgs = poem.setdefault("dim_averages", {
        "image_precision": None, "cut": None, "economy": None,
        "resonance": None, "originality": None, "musicality": None
    })
    n = poem["matches"]  # already incremented
    for dim, val in scores.items():
        if dim not in avgs:
            continue
        prev = avgs[dim]
        avgs[dim] = round(val if prev is None else (prev * (n - 1) + val) / n, 2)


# ---------------------------------------------------------------------------
# Pair selection
# ---------------------------------------------------------------------------

def select_pairs(poems: list[dict], n: int) -> list[tuple[dict, dict]]:
    """
    Select N pairs weighted inversely by match count so under-rated poems
    catch up to the rest of the corpus faster. Avoids recently matched opponents.
    """
    pairs = []
    attempts = 0
    max_attempts = n * 20

    # Weight: poems with fewer matches are chosen more often.
    # A poem with 0 matches gets weight (max_matches + 1); one at max gets weight 1.
    max_matches = max(p["matches"] for p in poems) if poems else 0
    weights = [max_matches - p["matches"] + 1 for p in poems]

    while len(pairs) < n and attempts < max_attempts:
        attempts += 1
        idx_a, idx_b = random.choices(range(len(poems)), weights=weights, k=2)
        if idx_a == idx_b:
            continue
        a, b = poems[idx_a], poems[idx_b]

        # Skip recently matched opponents
        if b["id"] in a.get("recent_opponents", []):
            continue

        pairs.append((a, b))

    if len(pairs) < n:
        print(f"  Warning: only found {len(pairs)} valid pairs (requested {n})")

    return pairs


# ---------------------------------------------------------------------------
# Ollama API
# ---------------------------------------------------------------------------

def parse_judge_response(text: str):
    """Extract JSON from Claude's response, tolerating minor formatting issues."""
    # Strip markdown code fences (some models wrap in ```json ... ```)
    text = re.sub(r'```(?:json)?\s*', '', text).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON block
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def validate_scores(data: dict) -> bool:
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


def judge_pair(poem_a: dict, poem_b: dict, model: str):
    """Compare two haiku via Claude API or Ollama. Returns parsed result or None on failure."""
    def pad(lines, idx):
        return lines[idx] if idx < len(lines) else ""

    prompt = JUDGE_PROMPT.format(
        line1_a=pad(poem_a["lines"], 0),
        line2_a=pad(poem_a["lines"], 1),
        line3_a=pad(poem_a["lines"], 2),
        line1_b=pad(poem_b["lines"], 0),
        line2_b=pad(poem_b["lines"], 1),
        line3_b=pad(poem_b["lines"], 2),
    )

    use_claude = model.startswith("claude-")

    for attempt in range(3):
        try:
            if use_claude:
                text = _judge_claude(prompt, JUDGE_SYSTEM, model)
            else:
                payload = json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": JUDGE_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "format": "json",
                }).encode()
                req = urllib.request.Request(
                    OLLAMA_URL,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
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
            print(f"    Ollama connection error (attempt {attempt+1}): {e}")
            print(f"    Is Ollama running? Try: ollama serve &")
            time.sleep(2)
        except Exception as e:
            print(f"    Error (attempt {attempt+1}): {e}")
            time.sleep(2)

    return None


# ---------------------------------------------------------------------------
# Ratings summary for website
# ---------------------------------------------------------------------------

def build_ratings_json(poems: list[dict]) -> dict:
    ai_poems = [p for p in poems if p["source"] == "ai"]
    human_poems = [p for p in poems if p["source"] == "human"]

    def avg_elo(group):
        return round(sum(p["elo"] for p in group) / len(group), 1) if group else 1500

    total_matches = sum(p["matches"] for p in poems) // 2  # each match counted twice

    # Head-to-head: count matches between AI and human
    ai_wins = sum(p["wins"] for p in ai_poems)
    human_wins = sum(p["wins"] for p in human_poems)
    draws = sum(p["draws"] for p in poems) // 2

    # Top 10 per source
    top_ai = sorted(ai_poems, key=lambda p: p["elo"], reverse=True)[:10]
    top_human = sorted(human_poems, key=lambda p: p["elo"], reverse=True)[:10]

    # All poems for leaderboard (sorted by ELO)
    leaderboard = sorted(poems, key=lambda p: p["elo"], reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_matches": total_matches,
        "summary": {
            "ai_count": len(ai_poems),
            "human_count": len(human_poems),
            "ai_avg_elo": avg_elo(ai_poems),
            "human_avg_elo": avg_elo(human_poems),
            "ai_wins": ai_wins,
            "human_wins": human_wins,
            "draws": draws,
        },
        "top_ai": [
            {"id": p["id"], "lines": p["lines"], "author": p["author"],
             "collection": p["collection"], "elo": p["elo"],
             "matches": p["matches"], "wins": p["wins"]}
            for p in top_ai
        ],
        "top_human": [
            {"id": p["id"], "lines": p["lines"], "author": p["author"],
             "collection": p["collection"], "elo": p["elo"],
             "matches": p["matches"], "wins": p["wins"]}
            for p in top_human
        ],
        "poems": [
            {
                "id": p["id"],
                "lines": p["lines"],
                "source": p["source"],
                "author": p["author"],
                "collection": p["collection"],
                "translator": p.get("translator"),
                "elo": p["elo"],
                "matches": p["matches"],
                "wins": p["wins"],
                "losses": p["losses"],
                "draws": p["draws"],
                "dim_averages": p.get("dim_averages", {}),
                "last_reasoning": p.get("last_reasoning"),
            }
            for p in leaderboard
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run haiku ELO rating comparisons via Ollama")
    parser.add_argument("--pairs", type=int, default=DEFAULT_PAIRS, help="Number of pairs to compare")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model to use")
    args = parser.parse_args()

    if not CORPUS_PATH.exists():
        raise SystemExit(f"Corpus not found: {CORPUS_PATH}\nRun: python build_corpus.py")

    poems = json.loads(CORPUS_PATH.read_text())

    print(f"Corpus: {len(poems)} poems ({sum(1 for p in poems if p['source']=='human')} human, "
          f"{sum(1 for p in poems if p['source']=='ai')} AI)")
    print(f"Running {args.pairs} comparisons with {args.model} (local Ollama)...\n")

    pairs = select_pairs(poems, args.pairs)

    wins_a = wins_b = draws = errors = 0

    for i, (poem_a, poem_b) in enumerate(pairs, 1):
        print(f"[{i}/{len(pairs)}] {poem_a['id'][:40]} vs {poem_b['id'][:40]}")

        result = judge_pair(poem_a, poem_b, args.model)

        if result is None:
            print("  SKIP (no valid response)")
            errors += 1
            continue

        winner = result["winner"]
        reasoning = result.get("reasoning", "")

        # Update ELO
        update_elo(poem_a, poem_b, winner)
        update_dim_averages(poem_a, result["a"])
        update_dim_averages(poem_b, result["b"])

        poem_a["last_reasoning"] = reasoning
        poem_b["last_reasoning"] = reasoning

        if winner == "a":
            wins_a += 1
            label = "A wins"
        elif winner == "b":
            wins_b += 1
            label = "B wins"
        else:
            draws += 1
            label = "Draw"

        print(f"  {label} | A:{result['a']['total']}/30  B:{result['b']['total']}/30")
        print(f"  ELO: {poem_a['id'][:25]} → {poem_a['elo']}  |  {poem_b['id'][:25]} → {poem_b['elo']}")
        print(f"  \"{reasoning}\"")

    print(f"\nDone: {len(pairs)-errors} matches, {errors} errors")
    print(f"A wins: {wins_a}  B wins: {wins_b}  Draws: {draws}")

    # Write updated corpus
    CORPUS_PATH.write_text(json.dumps(poems, indent=2, ensure_ascii=False))
    print(f"Corpus saved → {CORPUS_PATH}")

    # Write ratings summary for website
    ratings = build_ratings_json(poems)
    OUTPUT_PATH.write_text(json.dumps(ratings, indent=2, ensure_ascii=False))
    print(f"Ratings saved → {OUTPUT_PATH}")

    ai_avg = ratings["summary"]["ai_avg_elo"]
    human_avg = ratings["summary"]["human_avg_elo"]
    print(f"\nCurrent ELO — AI avg: {ai_avg}  |  Human avg: {human_avg}")


if __name__ == "__main__":
    main()
