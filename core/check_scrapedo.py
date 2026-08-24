"""Check Scrape.do response for Auth0 state extraction."""
import requests, os, re, json
from pathlib import Path
from dotenv import load_dotenv

_WORKSPACE = Path(__file__).resolve().parent.parent.parent
load_dotenv(_WORKSPACE / ".env", override=True)
key = os.getenv("SCRAPEDO_API_KEY", "")

r = requests.get("https://api.scrape.do", params={
    "token": key,
    "url": "https://www.woolworths.com.au/auth/login",
    "render": "true",
    "super": "true",
    "country": "au",
    "session": "test9b",
    "wait": "10000",
}, timeout=120)

print(f"Status: {r.status_code}")
print(f"Content length: {len(r.text)}")

# Check for Auth0 universal_login_context
ctx_present = "universal_login_context" in r.text
print(f"Universal login context: {ctx_present}")

# Check for state in various forms
state_in_url = re.findall(r"state[=:]\s*[\"']?([a-zA-Z0-9_\-]{20,})[\"']?", r.text[:20000])
print(f"State patterns: {state_in_url[:5]}")

# Check for "Oops! JavaScript" (noscript fallback)
noscript = "Oops! JavaScript" in r.text or "JavaScript has been disabled" in r.text
print(f"JavaScript disabled fallback: {noscript}")

# Check for actual login form
has_form = "<form" in r.text.lower()
has_input = "<input" in r.text.lower()
print(f"Has form: {has_form}, Has input: {has_input}")

# Check page title
title = re.search(r"<title>([^<]+)</title>", r.text)
print(f"Title: {title.group(1) if title else 'NOT FOUND'}")

# Check if Scrape.do has a header with the final URL
for k, v in r.headers.items():
    if "url" in k.lower() or "location" in k.lower() or "redirect" in k.lower():
        print(f"Header {k}: {v}")

# Save full HTML
output = Path(__file__).resolve().parent.parent / "data" / "diagnostics" / "scrapedo_auth.html"
with open(output, "w", encoding="utf-8") as f:
    f.write(r.text[:100000])
print(f"Saved: {output}")
