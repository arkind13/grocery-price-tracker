#!/usr/bin/env python3
"""Inspect the Fruitopia site: what content does it actually serve?"""
import re
import sys

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

r = requests.get("https://www.fruitopiamtdruitt.com.au/", timeout=30,
                 headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"})
html = r.text

imgs = re.findall(r'<img[^>]+src="([^"]+)"', html)
print(f"images: {len(imgs)}")
for i in imgs[:12]:
    print("  ", i[:130])

links = re.findall(r'href="([^"]+)"', html)
internal = [l for l in links
            if "fruitopiamtdruitt" in l or l.startswith("/")]
print(f"\ninternal links ({len(internal)}):")
for l in sorted(set(internal))[:15]:
    print("  ", l[:130])

text = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
text = re.sub(r"<style.*?</style>", " ", text, flags=re.S)
text = re.sub(r"<[^>]+>", " ", text)
text = re.sub(r"\s+", " ", text)
print("\nVISIBLE TEXT (first 1200 chars):")
print(text[:1200])
