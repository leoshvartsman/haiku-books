#!/usr/bin/env python3
"""Generate generative mark portrait for Morgan Kim."""
import os, requests
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=120.0)

OUT = Path("authors")
OUT.mkdir(exist_ok=True)

prompt = """Abstract generative mark portrait for an AI poet named Morgan Kim,
who spans Canadian prairies, South African townships, and Ethiopian highlands.

Style: a circular organic form made of fine interference patterns —
like a fingerprint, magnetic field lines, or growth rings —
radiating outward from a dense center into open space.
Monochromatic with subtle color: warm prairie gold, deep ochre, storm grey.
Clean white background. Square format.
No faces, no text, no recognizable objects.
The mark feels like a unique identity — machine-generated but organic,
precise but alive. Think: the soul of a language model made visible."""

print("Generating portrait for Morgan Kim...")
response = client.images.generate(
    model="dall-e-3",
    prompt=prompt,
    size="1024x1024",
    quality="hd",
    n=1,
)
url = response.data[0].url
img_data = requests.get(url, timeout=30).content
out = OUT / "morgan-kim.png"
out.write_bytes(img_data)
print(f"Saved: {out}")
