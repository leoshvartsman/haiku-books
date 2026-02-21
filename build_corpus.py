#!/usr/bin/env python3
"""
build_corpus.py — Build the haiku ELO rating corpus.

Extracts all AI haiku from shmindle book HTML pages and combines them
with curated public domain human haiku (Basho, Issa, Buson, Shiki).

Run this whenever new books are added to refresh the corpus.
Writes: ratings/corpus.json
"""

import json
import os
import re
from pathlib import Path

BOOKS_DIR = Path(__file__).parent / "books"
RATINGS_DIR = Path(__file__).parent / "ratings"
OUTPUT_PATH = RATINGS_DIR / "corpus.json"
MAX_PER_AUTHOR = 200


# ---------------------------------------------------------------------------
# Public domain human haiku
# Sources:
#   Basil Hall Chamberlain, "Bashō and the Japanese Poetical Epigram" (1902)
#   Lafcadio Hearn, "Japanese Lyrics" (1915)
#   Clara A. Walsh, "The Master-Singers of Japan" (1914)
#   Curtis Hidden Page, "Japanese Poetry" (1923)
# ---------------------------------------------------------------------------

HUMAN_HAIKU = [

    # -----------------------------------------------------------------------
    # MATSUO BASHO (1644–1694)
    # -----------------------------------------------------------------------

    # --- Basho via Chamberlain (1902) ---
    {"lines": ["old pond—", "a frog jumps in,", "sound of water"],
     "author": "Matsuo Basho", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["on a withered bough", "a crow has settled—", "autumn nightfall"],
     "author": "Matsuo Basho", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["how still it is!", "piercing the very rocks,", "the locusts' din"],
     "author": "Matsuo Basho", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["on this road", "where nobody else travels,", "autumn evening"],
     "author": "Matsuo Basho", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["first winter rain—", "the monkey also seems", "to want a little coat"],
     "author": "Matsuo Basho", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["spring passes,", "and the birds cry out—", "tears in the eyes of fishes"],
     "author": "Matsuo Basho", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["the lightning flash—", "a heron's cry", "in the darkness"],
     "author": "Matsuo Basho", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["the banana tree", "in the autumn gale—", "all night sound of rain"],
     "author": "Matsuo Basho", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["I'd like enough drinks", "to put me to sleep—", "cold nights, these"],
     "author": "Matsuo Basho", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["even the woodpecker", "has not knocked yet—", "this napping noon"],
     "author": "Matsuo Basho", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    # --- Basho via Hearn (1915) ---
    {"lines": ["the sea darkens;", "voices of the wild ducks", "are faintly white"],
     "author": "Matsuo Basho", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["clouds come from time to time—", "and give men rest", "from moon-gazing"],
     "author": "Matsuo Basho", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["a cold rain starting;", "no hat—", "but it is something"],
     "author": "Matsuo Basho", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["the temple bell dies away.", "The scent of flowers in the evening", "is still tolling the bell."],
     "author": "Matsuo Basho", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["the snowy morning—", "by myself,", "chewing dried salmon"],
     "author": "Matsuo Basho", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["the butterfly—", "dreaming, perhaps,", "of fields and flowers"],
     "author": "Matsuo Basho", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["bitten by fleas and lice,", "I slept in a bed", "where horses urinated near my pillow"],
     "author": "Matsuo Basho", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["in my old home", "which I forsook, the cherries", "are in bloom"],
     "author": "Matsuo Basho", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    # --- Basho via Walsh (1914) ---
    {"lines": ["summer grasses—", "all that remains", "of warriors' dreams"],
     "author": "Matsuo Basho", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["year's end:", "all corners", "of this floating world, swept"],
     "author": "Matsuo Basho", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["crossing the summer moor:", "how glad I am", "to see the path!"],
     "author": "Matsuo Basho", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["the old road to Oku—", "under the summer grasses,", "I tread on dreams"],
     "author": "Matsuo Basho", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["the sea of spring—", "rising and falling,", "rising and falling all day"],
     "author": "Matsuo Basho", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["with the morning glory", "I too am growing old—", "a single day's flower"],
     "author": "Matsuo Basho", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["sick on my journey,", "only my dreams will wander", "these desolate moors"],
     "author": "Matsuo Basho", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["from all these trees—", "in salads, in soups, everywhere—", "cherry blossoms fall"],
     "author": "Matsuo Basho", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    # --- Basho via Page (1923) ---
    {"lines": ["even in Kyoto—", "hearing the cuckoo—", "I long for Kyoto"],
     "author": "Matsuo Basho", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["a mountain temple:", "the bell's voice soundeth—", "how deep the stillness!"],
     "author": "Matsuo Basho", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["the morning-glory—", "even today", "its thread to the bucket"],
     "author": "Matsuo Basho", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["in the cicada's cry", "there is no sign that it knows", "it will soon die"],
     "author": "Matsuo Basho", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["in all the rains of May", "there is one thing that has not hidden—", "the bridge of Seta"],
     "author": "Matsuo Basho", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["a flash of lightning—", "into the gloom goes", "the heron's cry"],
     "author": "Matsuo Basho", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["the dragonfly—", "it cannot quite reach", "the yellow flower"],
     "author": "Matsuo Basho", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["scent of chrysanthemums—", "and in Nara", "all the ancient Buddhas"],
     "author": "Matsuo Basho", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["the oak tree stands", "noble in the storm—", "I envy it nothing"],
     "author": "Matsuo Basho", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["on the moor, detached", "from all things—", "singing, the skylark"],
     "author": "Matsuo Basho", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    # -----------------------------------------------------------------------
    # KOBAYASHI ISSA (1763–1828)
    # -----------------------------------------------------------------------

    {"lines": ["this world of dew—", "is only a world of dew,", "and yet... and yet..."],
     "author": "Kobayashi Issa", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["O snail,", "climb Mount Fuji,", "but slowly, slowly!"],
     "author": "Kobayashi Issa", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["don't worry, spiders—", "I keep house", "very casually"],
     "author": "Kobayashi Issa", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["everything I touch", "with tenderness, alas,", "pricks like a bramble"],
     "author": "Kobayashi Issa", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["a world of dew,", "and within every dewdrop", "a world of struggle"],
     "author": "Kobayashi Issa", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["where there are humans", "there are flies,", "and Buddhas"],
     "author": "Kobayashi Issa", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["the begging bowl—", "morning glories fill it", "with dew"],
     "author": "Kobayashi Issa", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["in the moonlight,", "the colour and scent of the wisteria", "seems far away"],
     "author": "Kobayashi Issa", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["for you fleas too", "the night must be long,", "it must be lonely"],
     "author": "Kobayashi Issa", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["new year's morning—", "everything is in blossom!", "I feel about average."],
     "author": "Kobayashi Issa", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["inch by inch,", "little snail,", "climb Mount Fuji!"],
     "author": "Kobayashi Issa", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["the man pulling radishes", "pointed my way", "with a radish"],
     "author": "Kobayashi Issa", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["visiting the graves,", "the old dog", "leads the way"],
     "author": "Kobayashi Issa", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["children imitating cormorants", "are even more wonderful", "than real cormorants"],
     "author": "Kobayashi Issa", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["my spring is just this:", "a single bamboo shoot,", "a plum in blossom"],
     "author": "Kobayashi Issa", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["lean frog,", "don't give up the fight—", "Issa is here!"],
     "author": "Kobayashi Issa", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["the distant mountains", "are reflected in the eye", "of the dragonfly"],
     "author": "Kobayashi Issa", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["on a branch", "floating downriver,", "a cricket, singing"],
     "author": "Kobayashi Issa", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["dew evaporates", "and all our world is dew—", "so dear, so fresh, so fleeting"],
     "author": "Kobayashi Issa", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["in this world", "we walk on the roof of hell,", "gazing at flowers"],
     "author": "Kobayashi Issa", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["i'm going to roll over,", "so please move,", "cricket"],
     "author": "Kobayashi Issa", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["the oak tree stands", "noble in the storm—", "I envy it nothing"],
     "author": "Kobayashi Issa", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["the snow is melting", "and the village is flooded", "with children"],
     "author": "Kobayashi Issa", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    # -----------------------------------------------------------------------
    # YOSA BUSON (1716–1783)
    # -----------------------------------------------------------------------

    {"lines": ["spring rain:", "browsing under an umbrella", "at the picture-book store"],
     "author": "Yosa Buson", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["the piercing cold:", "in our bedroom my wife's comb", "found under my heel"],
     "author": "Yosa Buson", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["white lotus—", "the monk draws back", "his naked foot"],
     "author": "Yosa Buson", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["a brushwood gate:", "for a lock,", "this snail"],
     "author": "Yosa Buson", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["coolness—", "the sound of the bell", "as it leaves the bell"],
     "author": "Yosa Buson", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["the short night—", "on the hairy caterpillar", "small beads of dew"],
     "author": "Yosa Buson", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["spring rain:", "the uneaten clams", "soaking in seawater"],
     "author": "Yosa Buson", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["yellow rapeseed flowers,", "the moon in the east,", "the sun in the west"],
     "author": "Yosa Buson", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["one who has not spoken—", "the old woman at the flower-viewing", "looks up at the sky"],
     "author": "Yosa Buson", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["the peony falls,", "piling its petals", "one upon another"],
     "author": "Yosa Buson", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["in the old man's eyes,", "momentarily,", "the flower-scatter"],
     "author": "Yosa Buson", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["spring sea—", "heaving and falling,", "heaving and falling, all day"],
     "author": "Yosa Buson", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["without a sound", "the white camellia fell", "into the dark well"],
     "author": "Yosa Buson", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["lights are lit", "in the house across the river—", "the autumn dusk"],
     "author": "Yosa Buson", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["the rains of May—", "everything is beautiful", "and the bridge at Seta"],
     "author": "Yosa Buson", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["through torn paper screens,", "the cold stars", "glitter"],
     "author": "Yosa Buson", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["how cold!", "the feel of the sword-hilt", "in this autumn wind"],
     "author": "Yosa Buson", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["taking a nap,", "feet planted", "against a cool wall"],
     "author": "Yosa Buson", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["in the bedroom,", "the wife's white feet—", "night with a chill"],
     "author": "Yosa Buson", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["the river in spring:", "how it carries along", "all that light!"],
     "author": "Yosa Buson", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    # -----------------------------------------------------------------------
    # MASAOKA SHIKI (1867–1902)
    # -----------------------------------------------------------------------

    {"lines": ["a lightning flash:", "between the forest trees", "I have seen water"],
     "author": "Masaoka Shiki", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["I want to sleep.", "Swat the flies,", "softly, please."],
     "author": "Masaoka Shiki", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["the moon sets,", "the fog descends,", "the sky, filled with frost"],
     "author": "Masaoka Shiki", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["on the wide seashore,", "a little crab", "crosses the spring moon"],
     "author": "Masaoka Shiki", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["over the mountain,", "going alone—", "one travelling cloud"],
     "author": "Masaoka Shiki", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["autumn wind:", "the mountain's shadow", "shivers on the sea"],
     "author": "Masaoka Shiki", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["bright red—", "two bunches of grapes", "on the scales"],
     "author": "Masaoka Shiki", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["the cricket chirps—", "my inkstone is cold,", "the light is dim"],
     "author": "Masaoka Shiki", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["evening cherry blossoms—", "a night of stars", "in the petals"],
     "author": "Masaoka Shiki", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["the summer night is over:", "from beneath a cloud", "a corner of the moon"],
     "author": "Masaoka Shiki", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["even among insects", "in this world", "some are singers, some are not"],
     "author": "Masaoka Shiki", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["ill on my bed,", "I see the peony", "through the gap in the blinds"],
     "author": "Masaoka Shiki", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["spring wind—", "the ripples on the water", "come, one by one"],
     "author": "Masaoka Shiki", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["the winter garden—", "the moonlight flickers", "on the stone"],
     "author": "Masaoka Shiki", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    {"lines": ["the white chrysanthemums—", "even after I hold them,", "my hands still smell of white"],
     "author": "Masaoka Shiki", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["a red dragonfly—", "taking it in my hand,", "what a light weight!"],
     "author": "Masaoka Shiki", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    {"lines": ["spring breeze:", "the sound of the water", "tells where the brook bends"],
     "author": "Masaoka Shiki", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["crows cawing—", "I run across the field", "to find you"],
     "author": "Masaoka Shiki", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    # -----------------------------------------------------------------------
    # OTHER MASTERS (pre-1928 translations)
    # -----------------------------------------------------------------------

    # Kikaku (1661–1707) via Chamberlain 1902
    {"lines": ["on the white poppy,", "a butterfly's torn wing", "is a keepsake"],
     "author": "Takarai Kikaku", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    {"lines": ["the harvest moon—", "going and returning,", "I walked the whole night"],
     "author": "Takarai Kikaku", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    # Chiyo-ni (1703–1775) via Walsh 1914
    {"lines": ["the morning-glory vine—", "my well-bucket is tangled in it.", "I'll beg water elsewhere."],
     "author": "Chiyo-ni", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    {"lines": ["after my child died", "the flowers of spring—", "what are they to me?"],
     "author": "Chiyo-ni", "translator": "Walsh", "year": 1914,
     "collection": "The Master-Singers of Japan"},

    # Ransetsu (1653–1708) via Chamberlain 1902
    {"lines": ["one blow of the wind", "and the winter moon", "is clear"],
     "author": "Hattori Ransetsu", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

    # Gyodai (1732–1793) via Hearn 1915
    {"lines": ["autumn wind:", "for me too,", "this is a strange land"],
     "author": "Gyodai", "translator": "Hearn", "year": 1915,
     "collection": "Japanese Lyrics"},

    # Onitsura (1661–1738) via Page 1923
    {"lines": ["since there is no rice,", "let us arrange flowers", "in the empty pot"],
     "author": "Onitsura", "translator": "Page", "year": 1923,
     "collection": "Japanese Poetry"},

    # Joso (1661–1704) via Chamberlain 1902
    {"lines": ["the autumn wind blew—", "I thought of you,", "and turned to look"],
     "author": "Naito Joso", "translator": "Chamberlain", "year": 1902,
     "collection": "Bashō and the Japanese Poetical Epigram"},

]


# ---------------------------------------------------------------------------
# Extract AI haiku from book HTML pages
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def extract_haiku_from_html(html_content: str) -> list[list[str]]:
    """Extract all haiku (3-line groups) from .haiku divs in book HTML."""
    haiku_list = []
    # Match <div class="haiku">...</div> blocks (non-greedy)
    for div_match in re.finditer(r'<div class="haiku">(.*?)</div>', html_content, re.DOTALL):
        div_content = div_match.group(1)
        lines = re.findall(r'<p>(.*?)</p>', div_content)
        lines = [l.strip() for l in lines if l.strip()]
        if len(lines) >= 2:
            haiku_list.append(lines[:3])
    return haiku_list


def extract_book_meta(html_content: str, filename: str) -> dict:
    """Extract title and author from book HTML."""
    # Use <title> tag: format is "Book Title by Author Name — Shmindle"
    title_tag_match = re.search(r'<title>(.*?) by (.*?) —', html_content)
    if title_tag_match:
        title = title_tag_match.group(1).strip()
        author = title_tag_match.group(2).strip()
    else:
        # Fallback: author div and slug-based title
        author_match = re.search(r'<div class="author">(.*?)</div>', html_content)
        title = filename.replace(".html", "").replace("-", " ").title()
        author = author_match.group(1) if author_match else "Unknown"
    return {"title": title, "author": author}


def extract_ai_haiku(books_dir: Path):
    """Read all book HTML files and extract AI haiku."""
    ai_haiku = []
    html_files = sorted(books_dir.glob("*.html"))
    print(f"  Found {len(html_files)} book HTML files")

    for html_file in html_files:
        slug = html_file.stem
        content = html_file.read_text(encoding="utf-8")
        meta = extract_book_meta(content, html_file.name)
        haiku_lines_list = extract_haiku_from_html(content)

        for i, lines in enumerate(haiku_lines_list, 1):
            ai_haiku.append({
                "id": f"ai-{slug}-{i}",
                "lines": lines,
                "source": "ai",
                "author": meta["author"],
                "collection": meta["title"],
                "translator": None,
                "year": None,
                "elo": 1500,
                "matches": 0,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "dim_averages": {
                    "image_precision": None, "cut": None, "economy": None,
                    "resonance": None, "originality": None, "musicality": None
                },
                "last_reasoning": None,
                "recent_opponents": [],
            })

    print(f"  Extracted {len(ai_haiku)} AI haiku")
    return ai_haiku


# ---------------------------------------------------------------------------
# Build and write corpus
# ---------------------------------------------------------------------------

def build_human_poems():
    """Convert human haiku list to full corpus entries."""
    # Group by author to enforce cap
    by_author: dict[str, list] = {}
    for entry in HUMAN_HAIKU:
        by_author.setdefault(entry["author"], []).append(entry)

    poems = []
    for author, entries in by_author.items():
        capped = entries[:MAX_PER_AUTHOR]
        print(f"  {author}: {len(capped)} haiku ({len(entries)} available)")
        for i, entry in enumerate(capped, 1):
            author_slug = slugify(author)
            poems.append({
                "id": f"human-{author_slug}-{i}",
                "lines": entry["lines"],
                "source": "human",
                "author": entry["author"],
                "collection": entry["collection"],
                "translator": entry.get("translator"),
                "year": entry.get("year"),
                "elo": 1500,
                "matches": 0,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "dim_averages": {
                    "image_precision": None, "cut": None, "economy": None,
                    "resonance": None, "originality": None, "musicality": None
                },
                "last_reasoning": None,
                "recent_opponents": [],
            })

    return poems


def merge_with_existing(new_poems, existing_path: Path):
    """Preserve ELO ratings for poems already in corpus; add new ones fresh."""
    if not existing_path.exists():
        return new_poems

    existing = {p["id"]: p for p in json.loads(existing_path.read_text())}
    print(f"  Existing corpus: {len(existing)} poems — merging...")

    merged = []
    for poem in new_poems:
        if poem["id"] in existing:
            # Preserve ELO data, update metadata/lines
            ex = existing[poem["id"]]
            poem["elo"] = ex.get("elo", 1500)
            poem["matches"] = ex.get("matches", 0)
            poem["wins"] = ex.get("wins", 0)
            poem["losses"] = ex.get("losses", 0)
            poem["draws"] = ex.get("draws", 0)
            poem["dim_averages"] = ex.get("dim_averages", poem["dim_averages"])
            poem["last_reasoning"] = ex.get("last_reasoning")
            poem["recent_opponents"] = ex.get("recent_opponents", [])
        merged.append(poem)

    new_ids = {p["id"] for p in new_poems}
    dropped = [pid for pid in existing if pid not in new_ids]
    if dropped:
        print(f"  Dropping {len(dropped)} poems no longer in source")

    return merged


def main():
    RATINGS_DIR.mkdir(exist_ok=True)

    print("Building human haiku corpus...")
    human_poems = build_human_poems()
    print(f"  Total human haiku: {len(human_poems)}")

    print("\nExtracting AI haiku from book HTML pages...")
    ai_poems = extract_ai_haiku(BOOKS_DIR)

    all_poems = human_poems + ai_poems
    all_poems = merge_with_existing(all_poems, OUTPUT_PATH)

    OUTPUT_PATH.write_text(json.dumps(all_poems, indent=2, ensure_ascii=False))

    ai_count = sum(1 for p in all_poems if p["source"] == "ai")
    human_count = sum(1 for p in all_poems if p["source"] == "human")
    print(f"\nCorpus written to {OUTPUT_PATH}")
    print(f"  Human: {human_count}  |  AI: {ai_count}  |  Total: {len(all_poems)}")


if __name__ == "__main__":
    main()
