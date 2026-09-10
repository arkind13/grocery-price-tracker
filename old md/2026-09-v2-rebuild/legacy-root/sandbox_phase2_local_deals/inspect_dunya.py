#!/usr/bin/env python3
"""Inspect dunyabutchery.com.au — can we build a normal-price catalogue?"""
import re
import sys

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://www.dunyabutchery.com.au/"
# Diagnostic probe: the site's TLS chain fails verification from this
# sandbox (missing intermediate or incomplete bundle). verify=False is
        # ONLY for this inspection; production must use a proper chain
# (requests+certifi, or route through Scrape.do which terminates TLS).
resp = requests.get(BASE, timeout=30, verify=False, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
html = resp.text
print(f"status: {resp.status_code}  bytes: {len(html)}")

title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
print(f"title: {(title.group(1).strip() if title else '?')[:120]}")

# platform fingerprint
for mark in ("shopify", "woocommerce", "wix", "squarespace", "google sites",
             "wp-content", "cdn.shopify"):
    if mark in html.lower():
        print(f"platform hint: {mark}")

imgs = re.findall(r'<img[^>]+src="([^"]+)"', html)
print(f"\nimages: {len(imgs)}")
for i in imgs[:10]:
    print("  ", i[:130])

links = re.findall(r'href="([^"]+)"', html)
keep = [l for l in links
        if re.search(r"product|shop|collect|category|menu|order|page", l, re.I)]
print(f"\ninteresting links ({len(keep)}):")
for l in sorted(set(keep))[:25]:
    print("  ", l[:140])

prices = re.findall(r"\$\s?\d+(?:\.\d{1,2})?", html)
print(f"\nprice mentions: {len(prices)}  samples: {prices[:15]}")

text = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
text = re.sub(r"<style.*?</style>", " ", text, flags=re.S)
text = re.sub(r"<[^>]+>", " ", text)
text = re.sub(r"\s+", " ", text)
print(f"\nVISIBLE TEXT (first 1500 chars):")
print(text[:1500])
