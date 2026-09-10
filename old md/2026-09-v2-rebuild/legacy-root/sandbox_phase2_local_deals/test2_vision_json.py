#!/usr/bin/env python3
"""Test 2 sandbox harness — Vision LLM flyer parsing with a STRICT JSON
schema that isolates single prices vs bulk/multi-buy packs.

Sandbox ONLY: test evidence for pre-arch.md, not production code.

What it proves / probes:
  1. A small flyer image is rendered with KNOWN ground-truth deals
     (synthetic, via Pillow) so the Vision LLM's accuracy is measurable.
  2. The Vision LLM must answer with ONLY JSON matching this schema:

       {"deals": [{
            "item": str,          # product name as printed
            "raw_text": str,      # the flyer line it came from
            "price": float > 0,   # the printed price
            "unit": "kg" | "ea" | "pack",
            "price_kind": "single" | "multibuy" | "bulk_pack",
            "multibuy_qty": int|null,     # >=2 when price_kind=multibuy
            "bulk_size": str|null,        # e.g. "10kg" when bulk_pack
            "notes": str
       }]}

     Isolation rules enforced by the validator (hard FAILs):
       - single        -> multibuy_qty and bulk_size MUST be null
       - multibuy      -> qty >= 2 required; effective unit rate is
                          price/qty of the SAME standard pack
       - bulk_pack     -> bulk_size required + parseable (kg/g family);
                          this price is NEVER a comparison unit
  3. Ground-truth check: every known deal must appear with the right
     price/kind; wrong kind (bulk labelled single) is a hard FAIL —
     that is the exact failure mode requirement 5 guards against.

Modes:
    --fake   Offline: feed the validator canned good AND bad responses
             (proves the validator catches every violation class).
    --live   One real Vision call via OpenRouter (OPENROUTER_API_KEY
             from the workspace-root .env; never printed). Cheap model,
             small image, max_tokens capped.

Usage:
    python test2_vision_json.py --fake
    uv run --with requests --with pillow test2_vision_json.py --live \
        [--model google/gemini-2.5-flash] [--image path/to/flyer.jpg]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMAGE_PATH = HERE / "sample_flyer.png"
RESULT_PATH = HERE / "vision_parse_result.json"

# Windows consoles default to cp1252 and crash on emoji/arrows in output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

VALID_UNITS = {"kg", "ea", "pack"}
VALID_KINDS = {"single", "multibuy", "bulk_pack"}
VALID_CATEGORIES = {"fruits", "butchery", "other"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(kg|g)\s*$", re.IGNORECASE)
# Models often echo flyer words into bulk_size ("10kg BOX", "5 kg bag").
# Production needs a normaliser: extract the first kg/g token.
SIZE_TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Synthetic flyer (ground truth)
# ---------------------------------------------------------------------------
# Lines deliberately mix every price class a butcher/produce flyer uses.
GROUND_TRUTH = [
    # (printed line, item, price, unit, kind, multibuy_qty, bulk_size)
    ("BEEF DICED          $12.99 kg", "Beef Diced",
     12.99, "kg", "single", None, None),
    ("WHOLE CHICKEN       $8.50 ea", "Whole Chicken",
     8.50, "ea", "single", None, None),
    ("CHICKEN BREAST      $14.50 kg", "Chicken Breast",
     14.50, "kg", "single", None, None),
    ("SAUSAGES 2 for $15", "Sausages",
     15.00, "pack", "multibuy", 2, None),
    ("BULK BEEF 10kg BOX  $89.90", "Bulk Beef Box",
     89.90, "pack", "bulk_pack", None, "10kg"),
    ("APPLES ROYAL GALA   $3.99 kg", "Apples Royal Gala",
     3.99, "kg", "single", None, None),
]


def make_sample_flyer(path: Path) -> None:
    """Render the ground-truth lines onto a simple flyer image."""
    from PIL import Image, ImageDraw

    width, line_h, margin = 640, 56, 24
    height = margin * 2 + line_h * (len(GROUND_TRUTH) + 2)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        # pylint: disable=used-before-assignment — fallback chain below
        font_title = None
        from PIL import ImageFont
        font_title = ImageFont.truetype("arialbd.ttf", 26)
        font = ImageFont.truetype("arial.ttf", 22)
    except Exception:  # noqa: BLE001 — any font trouble: default bitmap font
        from PIL import ImageFont
        font_title = ImageFont.load_default()
        font = ImageFont.load_default()

    y = margin
    draw.text((margin, y), "DUNYA BUTCHERY - WEEKLY SPECIALS",
              fill="black", font=font_title)
    y += line_h
    draw.text((margin, y), "PRICES VALID UNTIL 11/09/2026",
              fill="black", font=font)
    y += line_h
    for line, *_rest in GROUND_TRUTH:
        draw.text((margin, y), line, fill="black", font=font)
        y += line_h
    draw.rectangle([2, 2, width - 3, height - 3], outline="black", width=2)
    img.save(path, "PNG")


# ---------------------------------------------------------------------------
# Strict schema validation (hand-rolled: explicit rules, no extra dep)
# ---------------------------------------------------------------------------
def validate_deal(deal: object) -> list[str]:
    """Return a list of schema violations for one deal (empty = valid)."""
    errs: list[str] = []
    if not isinstance(deal, dict):
        return ["deal is not an object"]
    for field in ("item", "raw_text", "price", "unit", "price_kind"):
        if field not in deal:
            errs.append(f"missing field: {field}")
    if errs:
        return errs

    if not isinstance(deal["item"], str) or not deal["item"].strip():
        errs.append("item must be a non-empty string")
    if not isinstance(deal["raw_text"], str) or not deal["raw_text"].strip():
        errs.append("raw_text must be a non-empty string")

    price = deal["price"]
    if isinstance(price, str):
        errs.append("price must be a number, not a string")
    elif not isinstance(price, (int, float)) or isinstance(price, bool):
        errs.append("price must be numeric")
    elif price <= 0:
        errs.append(f"price must be > 0 (got {price})")

    if deal["unit"] not in VALID_UNITS:
        errs.append(f"unit '{deal['unit']}' not in {sorted(VALID_UNITS)}")
    if deal["price_kind"] not in VALID_KINDS:
        errs.append(
            f"price_kind '{deal['price_kind']}' not in {sorted(VALID_KINDS)}")
    if deal.get("category") is not None and \
            deal["category"] not in VALID_CATEGORIES:
        errs.append(
            f"category '{deal['category']}' not in {sorted(VALID_CATEGORIES)}")

    kind = deal["price_kind"]
    qty = deal.get("multibuy_qty")
    bulk = deal.get("bulk_size")
    if kind == "single":
        if qty not in (None, 0):
            errs.append(f"single deal carries multibuy_qty={qty!r}")
        if bulk not in (None, ""):
            errs.append(f"single deal carries bulk_size={bulk!r}")
    elif kind == "multibuy":
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 2:
            errs.append(f"multibuy needs integer qty >= 2 (got {qty!r})")
        if bulk not in (None, ""):
            errs.append("multibuy must not carry bulk_size")
    elif kind == "bulk_pack":
        if not isinstance(bulk, str):
            errs.append(
                f"bulk_pack needs a parseable kg/g bulk_size (got {bulk!r})")
        else:
            # Normalise: accept a size string that CONTAINS a kg/g token
            # ("10kg BOX" -> "10kg") — this is the tolerance production
            # needs; anything with no kg/g token is a hard error.
            normalized = normalize_bulk_size(bulk)
            deal["bulk_size"] = normalized
            if normalized is None:
                errs.append(
                    f"bulk_pack needs a parseable kg/g bulk_size (got {bulk!r})")
        if qty not in (None, 0):
            errs.append("bulk_pack must not carry multibuy_qty")
    return errs


def normalize_bulk_size(bulk: str) -> str | None:
    """Extract a clean size string from a model-returned bulk_size.

    "10kg BOX" -> "10kg"; "5 kg bag" -> "5kg"; bare "10kg" unchanged.
    Returns None when no kg/g token is present at all.
    """
    m = SIZE_TOKEN_RE.search(bulk)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2).lower()}"


def validate_response(payload: object) -> tuple[list[dict], list[str]]:
    """Validate the whole model payload; returns (deals, all_errors)."""
    errs: list[str] = []
    if not isinstance(payload, dict) or not isinstance(
            payload.get("deals"), list):
        return [], ["top-level object with a 'deals' array required"]
    # Board-level validity (user decision Q5: expired boards are skipped).
    valid_until = payload.get("valid_until")
    if valid_until is not None and (
            not isinstance(valid_until, str) or not DATE_RE.match(valid_until)):
        errs.append("valid_until must be null or YYYY-MM-DD")
    validity_text = payload.get("validity_text")
    if validity_text is not None and not isinstance(validity_text, str):
        errs.append("validity_text must be a string or null")
    deals: list[dict] = []
    for i, deal in enumerate(payload["deals"]):
        deal_errs = validate_deal(deal)
        for e in deal_errs:
            errs.append(f"deals[{i}]: {e}")
        if not deal_errs:
            deals.append(deal)
    return deals, errs


# ---------------------------------------------------------------------------
# Ground-truth scoring
# ---------------------------------------------------------------------------
def score_against_ground_truth(deals: list[dict]) -> tuple[list[str], int]:
    """Match returned deals to ground truth; returns (failures, hits).

    A deal matches when item words overlap case-insensitively AND the
    price is within 1 cent AND price_kind is identical. Kind mismatches
    are the critical failures (bulk labelled single would poison the
    comparison math downstream).
    """
    failures: list[str] = []
    hits = 0
    used = set()
    for line, item, price, _unit, kind, _qty, _bulk in GROUND_TRUTH:
        found = None
        for i, deal in enumerate(deals):
            if i in used:
                continue
            name_hit = deal["item"].lower().split() and any(
                w in deal["item"].lower()
                for w in item.lower().split())
            price_hit = abs(float(deal["price"]) - price) <= 0.011
            if name_hit and price_hit:
                found = i
                break
        if found is None:
            failures.append(f"MISSING: ground-truth deal not found: {line}")
            continue
        used.add(found)
        deal = deals[found]
        if deal["price_kind"] != kind:
            failures.append(
                f"KIND MISMATCH: '{item}' printed as {kind} but parsed as "
                f"{deal['price_kind']} — bulk isolation FAILED")
        else:
            hits += 1
    return failures, hits


def extract_json(text: str) -> object:
    """Robustly pull the JSON object out of a model reply.

    Strict first; on parse failure, salvage a truncated reply by
    cutting back to the last complete deal object and closing the
    array + root (finish_reason=length truncation happens in the
    field — hardening, not guessing).
    """
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        return json.loads(text)
    except ValueError:
        salvaged = _salvage_truncated_json(text)
        if salvaged is not None:
            return salvaged
        raise


def _salvage_truncated_json(text: str) -> object | None:
    """Close a JSON reply truncated inside the deals array.

    Keeps only complete deal objects (balanced braces), then closes
    "deals": [...] and the root object. Returns None when no complete
    deal survives.
    """
    if '"deals"' not in text:
        return None
    depth = 0
    last_complete = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 1:
                # closed a deal object (inside the root's deals array)
                last_complete = i
            elif depth == 0:
                last_complete = i  # whole object closed (not truncated)
    if last_complete < 0:
        return None
    head = text[:last_complete + 1]
    if not head.rstrip().endswith("}"):
        return None
    # If the root itself closed cleanly this is not a truncation case.
    try:
        return json.loads(head if head.count("{") == head.count("}")
                          else head + "]}")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
def run_fake() -> int:
    """Offline: prove the validator catches every violation class."""
    passed, failed = 0, 0
    good = {"deals": [
        {"item": "Beef Diced", "raw_text": "BEEF DICED $12.99 kg",
         "price": 12.99, "unit": "kg", "price_kind": "single",
         "multibuy_qty": None, "bulk_size": None, "notes": ""},
        {"item": "Sausages", "raw_text": "SAUSAGES 2 for $15",
         "price": 15.00, "unit": "pack", "price_kind": "multibuy",
         "multibuy_qty": 2, "bulk_size": None, "notes": ""},
        {"item": "Bulk Beef Box", "raw_text": "BULK BEEF 10kg BOX $89.90",
         "price": 89.90, "unit": "pack", "price_kind": "bulk_pack",
         "multibuy_qty": None, "bulk_size": "10kg", "notes": ""},
    ]}
    bad_variants = [
        # (label, payload, expected_error_fragment)
        ("bulk labelled single", {"deals": [
            {"item": "Bulk Beef Box", "raw_text": "x", "price": 89.90,
             "unit": "pack", "price_kind": "single",
             "multibuy_qty": None, "bulk_size": "10kg"}]},
         "single deal carries bulk_size"),
        ("bulk missing size", {"deals": [
            {"item": "Bulk Beef Box", "raw_text": "x", "price": 89.90,
             "unit": "pack", "price_kind": "bulk_pack",
             "multibuy_qty": None, "bulk_size": None}]},
         "bulk_pack needs a parseable"),
        ("multibuy qty=1", {"deals": [
            {"item": "Sausages", "raw_text": "x", "price": 15.0,
             "unit": "pack", "price_kind": "multibuy",
             "multibuy_qty": 1, "bulk_size": None}]},
         "integer qty >= 2"),
        ("price as string", {"deals": [
            {"item": "Beef Diced", "raw_text": "x", "price": "12.99",
             "unit": "kg", "price_kind": "single",
             "multibuy_qty": None, "bulk_size": None}]},
         "price must be a number"),
        ("zero price", {"deals": [
            {"item": "Beef Diced", "raw_text": "x", "price": 0,
             "unit": "kg", "price_kind": "single",
             "multibuy_qty": None, "bulk_size": None}]},
         "price must be > 0"),
        ("bad unit", {"deals": [
            {"item": "Beef Diced", "raw_text": "x", "price": 12.99,
             "unit": "litre", "price_kind": "single",
             "multibuy_qty": None, "bulk_size": None}]},
         "not in"),
    ]

    # Normaliser rescue: messy size strings with a kg/g token inside are
    # cleaned to a bare size, not rejected ("10kg BOX" -> "10kg").
    rescued_bulk = {"deals": [
        {"item": "Bulk Beef Box", "raw_text": "BULK BEEF 10kg BOX $89.90",
         "price": 89.90, "unit": "pack", "price_kind": "bulk_pack",
         "multibuy_qty": None, "bulk_size": "10kg BOX"}]}
    _deals, errs = validate_response(rescued_bulk)
    cleaned = (rescued_bulk["deals"][0]["bulk_size"]
               if not errs else None)
    if not errs and cleaned == "10kg":
        print("PASS bulk_size '10kg BOX' normalised to '10kg'")
        passed += 1
    else:
        print(f"FAIL bulk_size normalisation (errors={errs}, "
              f"cleaned={cleaned!r})")
        failed += 1

    no_size = {"deals": [
        {"item": "Mystery Box", "raw_text": "MYSTERY BOX $20",
         "price": 20.00, "unit": "pack", "price_kind": "bulk_pack",
         "multibuy_qty": None, "bulk_size": "BIG BOX"}]}
    _deals, errs = validate_response(no_size)
    if any("needs a parseable" in e for e in errs):
        print("PASS bulk_size with no kg/g token: rejected")
        passed += 1
    else:
        print(f"FAIL bulk_size 'BIG BOX' not rejected (errors={errs})")
        failed += 1

    # Prose WITH valid JSON inside is legitimately rescued by
    # extract_json — the reject-path only applies to prose with NO JSON.
    prose_ok = "Here is the JSON you asked for: " + json.dumps(good)
    rescued = extract_json(prose_ok)
    _deals, errs = validate_response(rescued)
    if not errs:
        print("PASS prose-wrapped valid JSON rescued by extract_json")
        passed += 1
    else:
        print(f"FAIL prose-wrapped valid JSON rejected: {errs}")
        failed += 1

    prose_bad = "I could not read the flyer, sorry — no prices found."
    try:
        extract_json(prose_bad)
        print("FAIL prose without JSON: extract_json did not raise")
        failed += 1
    except ValueError:
        print("PASS prose without JSON: rejected (extract_json raises)")
        passed += 1

    deals, errs = validate_response(good)
    if errs or len(deals) != 3:
        print(f"FAIL good payload rejected: {errs}")
        failed += 1
    else:
        print("PASS good payload accepted (3/3 deals)")
        passed += 1

    for label, payload, frag in bad_variants:
        if isinstance(payload, str):
            try:
                payload = extract_json(payload)
            except ValueError:
                print(f"PASS {label}: unparseable output rejected")
                passed += 1
                continue
        _deals, errs = validate_response(payload)
        caught = any(frag in e for e in errs)
        if caught:
            print(f"PASS {label}: rejected ({errs[0]})")
            passed += 1
        else:
            print(f"FAIL {label}: NOT caught (errors={errs})")
            failed += 1

    print(f"\nfake mode: {passed} passed, {failed} failed")
    return 1 if failed else 0


SCHEMA_PROMPT = """You are reading a supermarket/butcher/fruit-market
price-board or flyer photo.
Extract EVERY price line into JSON ONLY (no prose, no markdown) matching:
{"valid_until":"YYYY-MM-DD"|null,"validity_text":str|null,
 "deals":[{"item":str,"raw_text":str,"price":number,"unit":"kg"|"ea"|"pack",
"price_kind":"single"|"multibuy"|"bulk_pack","multibuy_qty":int|null,
"bulk_size":str|null,"category":"fruits"|"butchery"|"other","notes":str}]}
Rules:
- valid_until: the date the specials END as printed on the board, in
  Australian day/month/year order ("valid until 11/09/2026" ->
  "2026-09-11"). null when no date is printed. validity_text = the raw
  wording you read it from.
- "single": a normal per-kg or per-item price.
- "multibuy": "N for $X" on the SAME standard pack -> multibuy_qty=N,
  price=X (the bundle total).
- "bulk_pack": a BULK/tier pack (e.g. "10kg box", "5kg bag") -> bulk_size
  = the pack size string; NEVER report it as single.
- "category": fruits for produce, butchery for meat/chicken/smallgoods,
  anything else -> other.
Output only the JSON object."""


# ---------------------------------------------------------------------------
# Providers (Q9: deepseek-v4-flash via OpenRouter first; GLM via the
# user's OWN zlm endpoint — the .env variables zlm_url + zlm_claw are
# the correct ones (user correction 2026-09-05), NOT the generic
# Z.ai endpoint).
# ---------------------------------------------------------------------------
ZAI_URL = "https://api.z.ai/api/paas/v4/chat/completions"
ZAI_KEY_VARS = ("zlm_claw", "ZLM_CLAW")
ZAI_URL_VARS = ("zlm_url", "ZLM_URL")


def call_vision(provider: str, model: str, prompt: str,
                img_bytes: bytes, max_tokens: int = 1200) -> tuple[str, dict]:
    """One vision call; returns (content, usage). Never prints keys."""
    import requests

    if provider == "zai":
        key = next((os.getenv(v) for v in ZAI_KEY_VARS if os.getenv(v)), None)
        if not key:
            raise RuntimeError(
                "no ZLM key found — looked for: " + ", ".join(ZAI_KEY_VARS))
        # The user's .env carries the exact BASE endpoint (zlm_url,
        # e.g. https://api.z.ai/api/coding/paas/v4/); the OpenAI-
        # compatible path appends chat/completions when missing.
        url = next((os.getenv(v) for v in ZAI_URL_VARS if os.getenv(v)),
                   ZAI_URL)
        if not url.rstrip("/").endswith("chat/completions"):
            url = url.rstrip("/") + "/chat/completions"
        print(f"[zlm] endpoint: {url}")  # URL is not a secret; key never is
        headers = {"Authorization": f"Bearer {key}",
                   "Content-Type": "application/json"}
    else:  # openrouter
        key = os.getenv("OPENROUTER_API_KEY", "")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY not found")
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}",
                   "Content-Type": "application/json"}

    b64 = base64.b64encode(img_bytes).decode()
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
    }
    resp = requests.post(url, headers=headers, json=body, timeout=120)
    if resp.status_code != 200:
        text = resp.text[:300]
        # Mask the key if the provider ever echoes it back.
        for secret in (key,):
            if secret:
                text = text.replace(secret, "***MASKED***")
        raise RuntimeError(
            f"HTTP {resp.status_code} from {url}: {text}")
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    usage["finish_reason"] = data["choices"][0].get("finish_reason")
    return content, usage


def _load_env() -> None:
    """Walk up from this file to the workspace root and load .env into
    os.environ (first .env found wins; values are never printed)."""
    for parent in [HERE, *HERE.parents]:
        if (parent / ".env").exists():
            try:
                with open(parent / ".env", "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, _, v = line.partition("=")
                            os.environ.setdefault(k.strip(), v.strip("\"' "))
            except OSError as exc:
                print(f"[warn] could not read .env: "
                      f"{exc.__class__.__name__}")
            return


def run_live(provider: str, model: str, image_path: Path | None) -> int:
    """One real Vision call; ground-truth scored (synthetic image only)."""
    _load_env()

    if image_path is not None:
        img_bytes = image_path.read_bytes()
        img_name = image_path.name
    else:
        if not IMAGE_PATH.exists():
            make_sample_flyer(IMAGE_PATH)
            print(f"generated synthetic flyer: {IMAGE_PATH.name}")
        img_bytes = IMAGE_PATH.read_bytes()
        img_name = IMAGE_PATH.name

    try:
        content, usage = call_vision(provider, model, SCHEMA_PROMPT,
                                     img_bytes, max_tokens=2200)
    except RuntimeError as exc:
        print(f"FAIL vision call: {exc}")
        return 2

    try:
        payload = extract_json(content)
    except ValueError as exc:
        print(f"FAIL model reply is not JSON: {exc}\n---\n{content[:400]}")
        return 1

    deals, errs = validate_response(payload)
    failures, hits = (score_against_ground_truth(deals)
                      if image_path is None else ([], 0))

    out = {
        "provider": provider, "model": model, "image": img_name,
        "usage": usage, "schema_errors": errs,
        "valid_until": payload.get("valid_until") if isinstance(payload, dict) else None,
        "validity_text": payload.get("validity_text") if isinstance(payload, dict) else None,
        "deals": deals, "ground_truth_failures": failures,
        "ground_truth_hits": f"{hits}/{len(GROUND_TRUTH)}",
    }
    RESULT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                           "utf-8")

    print(f"model: {provider}/{model}  tokens: {usage}")
    if out["valid_until"] or out["validity_text"]:
        print(f"validity: {out['valid_until']!r} "
              f"(from {out['validity_text']!r})")
    print(f"schema errors: {len(errs)}")
    for e in errs:
        print(f"  - {e}")
    print(f"deals parsed: {len(deals)}")
    for d in deals:
        print(f"  {d['item']!r:24} ${d['price']:>7} {d['unit']:>4} "
              f"[{d['price_kind']}]" +
              (f" qty={d['multibuy_qty']}" if d.get("multibuy_qty") else "") +
              (f" size={d['bulk_size']}" if d.get("bulk_size") else "") +
              (f" ({d.get('category')})" if d.get("category") else ""))
    for f in failures:
        print(f"  ✗ {f}")
    if image_path is None:
        print(f"ground truth: {hits}/{len(GROUND_TRUTH)} matched")
    return 1 if (errs or failures) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["fake", "live"])
    parser.add_argument("--provider", default="openrouter",
                        choices=["openrouter", "zai"],
                        help="vision API provider (default openrouter)")
    parser.add_argument("--model", default="google/gemini-2.5-flash",
                        help="vision model id")
    parser.add_argument("--image", type=Path, default=None,
                        help="real flyer image instead of the synthetic one")
    args = parser.parse_args()
    return run_fake() if args.mode == "fake" else run_live(
        args.provider, args.model, args.image)


if __name__ == "__main__":
    sys.exit(main())
