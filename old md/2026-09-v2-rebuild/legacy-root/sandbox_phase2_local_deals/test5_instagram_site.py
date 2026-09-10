#!/usr/bin/env python3
"""Test 5 — Instagram access (Merjan) + Fruitopia website catalogue.

Two questions from the user (2026-09-05):
  1. Can we read the Instagram pages (e.g. @merjanbrothers) the same
     way as Facebook, so FB + IG can be cross-checked and deduped?
  2. Can we scrape the shop website (fruitopiamtdruitt.com.au is the
     one real site among the four) to build a normal-price catalogue?

Instagram is probed through the same Scrape.do chain (render=true,
AU exit). The website is probed with a PLAIN request first (small
business sites rarely block); Scrape.do only if blocked.
No keys are ever printed.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PRICE_RE = re.compile(r"\$\s?\d+(?:\.\d{1,2})?")


def load_env() -> None:
    for parent in [HERE, *HERE.parents]:
        if (parent / ".env").exists():
            with open(parent / ".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        os.environ.setdefault(k.strip(), v.strip("\"' "))
            return
    raise SystemExit(".env not found")


def scrapedo_get(url: str, timeout_s: float = 90.0) -> tuple[int, str]:
    """Rendered fetch through Scrape.do."""
    token = os.getenv("SCRAPEDO_API_KEY", "")
    if not token:
        raise SystemExit("SCRAPEDO_API_KEY missing")
    resp = requests.get(
        "https://api.scrape.do",
        params={"token": token, "url": url, "render": "true",
                "geoCode": "au"},
        timeout=timeout_s)
    return resp.status_code, resp.text or ""


def probe_instagram(handle: str) -> dict:
    """Can we see an IG profile's posts and captions logged out?"""
    url = f"https://www.instagram.com/{handle}/"
    result: dict = {"channel": "instagram", "url": url}
    status, html = scrapedo_get(url)
    result["http_status"] = status
    low = html.lower()
    result["login_wall"] = any(m in low for m in (
        "login", "sign up to see", "log in to instagram"))
    # captions often survive in meta tags / JSON blobs
    og = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
                   html)
    result["og_description"] = (og.group(1)[:300] if og else None)
    captions = re.findall(r'"edge_media_to_caption":\s*'
                          r'{"edges":\[{"node":{"text":"(.*?)"}', html)
    result["captions_found"] = len(captions)
    result["caption_samples"] = [
        c.encode().decode("unicode_escape", errors="replace")[:200]
        for c in captions[:5]]
    result["image_count"] = len(re.findall(
        r"https://scontent[^\"'\\s]+?\.(?:jpg|webp)", html))
    result["price_mentions"] = len(PRICE_RE.findall(html))
    result["ok"] = (status == 200
                    and (result["captions_found"] > 0
                         or result["price_mentions"] > 3))
    return result


def probe_website(url: str) -> dict:
    """Can we read the shop site's product/price info with a plain fetch?"""
    result: dict = {"channel": "website", "url": url}
    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 Chrome/126.0 Safari/537.36")})
    except requests.RequestException as exc:
        result["error"] = f"{exc.__class__.__name__}"
        return result
    result["http_status"] = resp.status_code
    html = resp.text or ""
    result["bytes"] = len(html)
    result["title"] = (re.search(r"<title[^>]*>(.*?)</title>", html,
                                 re.IGNORECASE | re.DOTALL) or [None, ""])[1][:120]
    # price-looking text anywhere on the page
    prices = PRICE_RE.findall(html)
    result["price_mentions"] = len(prices)
    result["price_samples"] = prices[:10]
    # product-ish links/pages to walk later
    links = re.findall(r'href="(/[^"]*(?:product|shop|item|menu)[^"]*)"',
                       html, re.IGNORECASE)
    result["product_links"] = sorted(set(links))[:15]
    result["ok"] = resp.status_code == 200 and len(prices) > 0
    return result


def main() -> int:
    load_env()
    out: list[dict] = []

    ig = probe_instagram("merjanbrothers")
    out.append(ig)
    print("--- Instagram: @merjanbrothers ---")
    print(json.dumps({k: v for k, v in ig.items() if k != "caption_samples"},
                     indent=2, ensure_ascii=False))
    for c in ig["caption_samples"]:
        print(f"  caption: {c}")

    print("\n--- Website: Fruitopia Mt Druitt ---")
    site = probe_website("https://www.fruitopiamtdruitt.com.au/")
    out.append(site)
    print(json.dumps(site, indent=2, ensure_ascii=False))

    (HERE / "instagram_site_findings.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
