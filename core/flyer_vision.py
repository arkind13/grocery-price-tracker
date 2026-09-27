"""Vision LLM flyer parsing: schema v2 validation + salvage (§6.3).

One call per POST (all of that post's images attached). Model chain
zlm-glm → or-glm → or-gemini with a hard 2-attempt cap per post.
MAX_TOKENS >= 2200 is REQUIRED (truncation observed at 1200).
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

MODEL_CHAIN = [
    {"label": "zlm-glm",   "model": "glm-5.3-flash",
     "route": "zlm"},                        # zlm_url + zlm_claw
    {"label": "or-glm",    "model": "z-ai/glm-5.3-flash",
     "route": "openrouter"},
    {"label": "or-gemini", "model": "google/gemini-2.5-flash",
     "route": "openrouter"},
]
MAX_TOKENS = 4500
MAX_ATTEMPTS_PER_POST = 2

VALID_UNITS = {"kg", "ea", "pack"}
VALID_KINDS = {"single", "multibuy", "bulk_pack"}
VALID_CATEGORIES = {"fruits", "butchery", "other"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SIZE_TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g)\b", re.IGNORECASE)


class VisionUnavailable(Exception):
    """All vision attempts for one post failed (§5 cap)."""


SCHEMA_V2_PROMPT = """You are reading a supermarket/butcher/fruit-market
price-board or flyer photo.
Extract EVERY price line into JSON ONLY (no prose, no markdown) matching:
{"valid_until":"YYYY-MM-DD"|null,"validity_text":str|null,
 "deals":[{"item":str,"raw_text":str,"price":number,"unit":"kg"|"ea"|"pack",
"price_kind":"single"|"multibuy"|"bulk_pack","multibuy_qty":int|null,
"bulk_size":str|null,"category":"fruits"|"butchery"|"other","notes":str,
"valid_until":"YYYY-MM-DD"|null}]}
Rules:
- valid_until: the date the specials END as printed on the board, in
  Australian day/month/year order ("valid until 11/09/2026" ->
  "2026-09-11"). null when no date is printed. validity_text = the raw
  wording you read it from.
- "single": a normal per-kg or per-item price.
- "multibuy": a minimum-purchase deal on the SAME standard unit —
  "N for $X" counted items AND "Nkg for $X" weighted meat alike ->
  multibuy_qty=N, price=X (the bundle total). The unit is the unit
  the deal is priced in: "kg" when the quantity is a WEIGHT ("3kg for
  $32.99", "min 2kg") or the board prices that meat per kg; "ea" for
  counted items. NEVER report a weighted deal as bulk_pack and never
  report its per-unit/per-kg rate as price — price is ALWAYS the
  bundle total.
- QUANTITY-PREFIX TILES (the Merjan weekend layout): the minimum
  purchase is printed BEFORE the item name — "2KG THIGH FILLET
  $21.99" means $21.99 buys the whole 2kg (so multibuy_qty=2,
  price=21.99, unit kg — NEVER a $21.99/kg single). Same for
  "2 STEAMER CHICKENS $11.99" (multibuy_qty=2, unit ea). A weight in
  parentheses AFTER a per-item product ("WHOLE CHICKEN (MIN 1.9KG)
  $34.99") is a SIZE spec -> single/ea with "min 1.9kg" in notes.
  Copy the quantity into raw_text VERBATIM — downstream code re-checks
  every tile's arithmetic from raw_text.
- "bulk_pack": ONLY a PHYSICAL pack product (a sealed box/bag/tray
  you buy as one article, e.g. "10kg box", "5kg bag") -> bulk_size =
  the pack size string; NEVER report "Nkg for $X" deal wording as
  bulk_pack.
- A deal line may carry its OWN end date printed next to it
  (item-level date, e.g. "Lamb $12.99/kg til 14/09") -> that deal's
  "valid_until" = "YYYY-MM-DD"; null when the line has no own date.
- "category": fruits for produce, butchery for meat/chicken/smallgoods,
  anything else -> other.
Output only the JSON object."""


def _validate_deal(deal: object) -> list[str]:
    """Return a list of schema violations for one deal (empty = valid).

    Ported verbatim from sandbox test2_vision_json.py (the 11/11
    reference). Mutates bulk_pack deals in place: bulk_size is
    normalised ("10kg BOX" -> "10kg") when a kg/g token exists.
    """
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
    if not isinstance(deal["raw_text"], str) or \
            not deal["raw_text"].strip():
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
            f"price_kind '{deal['price_kind']}' not in "
            f"{sorted(VALID_KINDS)}")
    if deal.get("category") is not None and \
            deal["category"] not in VALID_CATEGORIES:
        errs.append(
            f"category '{deal['category']}' not in "
            f"{sorted(VALID_CATEGORIES)}")

    kind = deal["price_kind"]
    qty = deal.get("multibuy_qty")
    bulk = deal.get("bulk_size")
    # S6 (user directive 2026-09-11): a deal line may carry its own
    # item-level end date — optional "YYYY-MM-DD" or null/absent.
    deal_until = deal.get("valid_until")
    if deal_until is not None \
            and (not isinstance(deal_until, str)
                 or not DATE_RE.match(deal_until)):
        errs.append(
            f"deal-level valid_until must be null or YYYY-MM-DD "
            f"(got {deal_until!r})")
    if kind == "single":
        if qty not in (None, 0):
            errs.append(f"single deal carries multibuy_qty={qty!r}")
        if bulk not in (None, ""):
            errs.append(f"single deal carries bulk_size={bulk!r}")
    elif kind == "multibuy":
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 2:
            errs.append(
                f"multibuy needs integer qty >= 2 (got {qty!r})")
        if bulk not in (None, ""):
            errs.append("multibuy must not carry bulk_size")
    elif kind == "bulk_pack":
        if not isinstance(bulk, str):
            errs.append(
                f"bulk_pack needs a parseable kg/g bulk_size "
                f"(got {bulk!r})")
        else:
            # Normalise: accept a size string that CONTAINS a kg/g
            # token ("10kg BOX" -> "10kg") — the tolerance production
            # needs; anything with no kg/g token is a pack WORD, not
            # a droppable deal: downgrade to single/ea with the word
            # in notes (2026-09-27: the Povi Masima 'bucket' $49.99
            # line was silently LOST to the old hard error).
            normalised = normalise_bulk_size(bulk)
            if normalised is None:
                deal["price_kind"] = "single"
                deal["bulk_size"] = None
                deal["multibuy_qty"] = None
                if deal.get("unit") not in VALID_UNITS:
                    deal["unit"] = "ea"
                word = bulk.strip()
                deal["notes"] = (f"{deal['notes']} · {word}"
                                 if str(deal.get("notes") or "").strip()
                                 else word)
            else:
                deal["bulk_size"] = normalised
        if qty not in (None, 0) and deal.get("price_kind") == "bulk_pack":
            errs.append("bulk_pack must not carry multibuy_qty")
    return errs


def normalise_bulk_size(raw: str) -> str | None:
    """Extract a clean size string from a model-returned bulk_size.

    "10kg BOX" -> "10kg"; "5 kg bag" -> "5kg"; bare "10kg" unchanged.
    Returns None when no kg/g token is present at all.
    """
    m = SIZE_TOKEN_RE.search(raw)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2).lower()}"


def validate_payload(data: object) -> tuple[list[dict], list[str]]:
    """Validate the whole model payload; returns (deals, all_errors).

    Ported from sandbox validate_response with the binding name.
    Invalid deals are dropped from the returned list; their errors
    carry the deals[i] index prefix.
    """
    errs: list[str] = []
    if not isinstance(data, dict) or not isinstance(
            data.get("deals"), list):
        return [], ["top-level object with a 'deals' array required"]
    # Board-level validity (expired boards are skipped downstream).
    valid_until = data.get("valid_until")
    if valid_until is not None and (
            not isinstance(valid_until, str)
            or not DATE_RE.match(valid_until)):
        errs.append("valid_until must be null or YYYY-MM-DD")
    validity_text = data.get("validity_text")
    if validity_text is not None and \
            not isinstance(validity_text, str):
        errs.append("validity_text must be a string or null")
    deals: list[dict] = []
    for i, deal in enumerate(data["deals"]):
        deal_errs = _validate_deal(deal)
        for e in deal_errs:
            errs.append(f"deals[{i}]: {e}")
        if not deal_errs:
            deals.append(deal)
    return deals, errs


def salvage_truncated_json(text: str) -> str | None:
    """Repair a reply truncated inside the deals array.

    Cuts back to the last COMPLETE deal object (balanced braces,
    string-aware), closes "deals" + root, returns the repaired JSON
    STRING (caller parses). None when no complete deal survives.
    Mirrors sandbox test_salvage.py (offline-tested).
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
    # Return the repaired STRING; the caller json.loads it.
    return head if head.count("{") == head.count("}") else head + "]}"


def extract_json(text: str) -> object:
    """Robustly pull the JSON object out of a model reply.

    Strict first; on parse failure, salvage a truncated reply by
    cutting back to the last complete deal object and closing the
    array + root (finish_reason=length truncation happens in the
    field — hardening, not guessing). Raises ValueError when the
    reply contains no recoverable JSON.
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
        salvaged = salvage_truncated_json(text)
        if salvaged is not None:
            return json.loads(salvaged)
        raise


ZAI_KEY_VARS = ("zlm_claw", "ZLM_CLAW")
ZAI_URL_VARS = ("zlm_url", "ZLM_URL")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _chat_url_and_key(route: str) -> tuple[str, str]:
    """Resolve (url, key) for a route.

    zlm: BASE url + append /chat/completions when missing (Coding-Plan
    gotcha). openrouter: fixed url. Raises RuntimeError (secret-free)
    when the key env is missing.
    """
    if route == "zlm":
        key = next((os.getenv(v) for v in ZAI_KEY_VARS if os.getenv(v)),
                   None)
        url = next((os.getenv(v) for v in ZAI_URL_VARS if os.getenv(v)),
                   "")
        if not key or not url:
            raise RuntimeError(
                "zlm route needs zlm_url + zlm_claw in .env")
        if not url.rstrip("/").endswith("/chat/completions"):
            url = url.rstrip("/") + "/chat/completions"
        return url, key
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set in .env")
    return OPENROUTER_URL, key


def _call_model(entry: dict, prompt: str, files: list[Path]) -> tuple:
    """One vision call with all images attached (multipart content).

    Returns (content_str, usage_dict). Raises RuntimeError on HTTP
    error (body masked, secret-free) - caller moves to the next
    chain entry.
    """
    import requests
    url, key = _chat_url_and_key(entry["route"])
    content: list[dict] = [{"type": "text", "text": prompt}]
    for f in files:
        b64 = base64.b64encode(f.read_bytes()).decode()
        content.append({"type": "image_url",
                        "image_url": {"url":
                                      f"data:image/jpeg;base64,{b64}"}})
    body = {"model": entry["model"], "max_tokens": MAX_TOKENS,
            "temperature": 0,
            "messages": [{"role": "user", "content": content}]}
    resp = requests.post(url, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"},
        json=body, timeout=120)
    if resp.status_code != 200:
        text = resp.text[:300].replace(key, "***MASKED***")
        raise RuntimeError(f"HTTP {resp.status_code}: {text}")
    data = resp.json()
    usage = dict(data.get("usage") or {})
    usage["finish_reason"] = (data.get("choices") or [{}])[0].get(
        "finish_reason")
    return (data["choices"][0]["message"]["content"], usage)


def parse_board_images(files: list[Path]) -> dict:
    """ONE vision call per POST with all its images (EC1-tested).

    MODEL_CHAIN order under the hard MAX_ATTEMPTS_PER_POST=2 cap
    (fallback counts as attempt 2 - D-LD2). finish_reason logged per
    call (secret-free). Zero deals is a VALID outcome (model
    variance) - returns {"valid_until": None, "deals": []}.
    Raises VisionUnavailable after the cap.

    Since 2026-09-27 every payload goes through TWO post-model gates
    (the Merjan pack-deal incidents): the deterministic pack-guard
    (extractors.deal_text.normalise_pack_deals re-derives bundle
    semantics from raw_text — the model flip-flops between runs on
    the same image, so code owns the arithmetic) and verify_board_parse
    (a second, independent look at the image auditing each parsed
    deal; its corrections ride the deal as review_flag).
    """
    attempts = 0
    last_err = ""
    for entry in MODEL_CHAIN:
        if attempts >= MAX_ATTEMPTS_PER_POST:
            break
        attempts += 1
        try:
            content, usage = _call_model(entry, SCHEMA_V2_PROMPT, files)
            print(f"[vision] {entry['label']} finish_reason="
                  f"{usage.get('finish_reason')} "
                  f"tokens={usage.get('total_tokens')}")
            payload = extract_json(content)
            deals, errs = validate_payload(payload)
            for e in errs:
                print(f"[vision] schema: {e}")
            from extractors.deal_text import normalise_pack_deals
            normalise_pack_deals(deals)
            if deals:
                verify_board_parse(files, deals)
            _log_payload(payload, deals)
            return {"valid_until": payload.get("valid_until"),
                    "validity_text": payload.get("validity_text"),
                    "deals": deals}
        except RuntimeError as exc:
            last_err = str(exc)
            continue
        except ValueError:
            last_err = "reply was not JSON"
            continue
    raise VisionUnavailable(
        f"vision failed after {attempts} attempt(s): {last_err}")


def _log_payload(payload: object, deals: list) -> None:
    """Persist the RAW model payload + the post-guard deals for every
    board (data/diagnostics/vision_payloads/, newest 50 kept). The
    2026-09-27 re-pollution was diagnosable only by guessing because
    nothing recorded what the model actually returned; now every
    incident has its evidence on disk."""
    try:
        import time
        from pathlib import Path as _P
        folder = (_P(__file__).resolve().parent.parent
                  / "data" / "diagnostics" / "vision_payloads")
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out = {"at": stamp,
               "model_payload": payload,
               "post_guard_deals": deals}
        (folder / f"{stamp}_{id(deals) & 0xffff:x}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1,
                       default=str), encoding="utf-8")
        old = sorted(folder.glob("*.json"))
        for stale in old[:-50]:
            stale.unlink(missing_ok=True)
    except Exception:   # noqa: BLE001 — logging must never break parse
        pass


TRANSCRIBE_PROMPT = """Transcribe EVERY price line printed on this
price-board photo, in reading order (top-to-bottom, left-to-right),
EXACTLY as printed — including every leading number, "KG", "MIN",
"FOR", unit word and price. Do NOT interpret, convert, normalise or
reorder anything; if a line starts with a number ("2 KG THIGH FILLET
$21.99") copy that number too. Output JSON only:
{"lines": ["2 KG THIGH FILLET $21.99", ...]}"""


def _line_matches_deal(line: str, deal: dict) -> bool:
    """A re-transcribed line belongs to a deal when the price digits
    appear in it AND an item-name word overlaps (plural-folded)."""
    if not isinstance(line, str) or not line.strip():
        return False
    price = deal.get("price")
    if isinstance(price, (int, float)):
        if (f"{price:.2f}" not in line
                and f"{price:g}" not in line):
            return False
    name_tokens = {w.lower().rstrip("s") for w in
                   str(deal.get("item") or "").split() if len(w) > 2}
    line_tokens = {w.lower().rstrip("s")
                   for w in line.split()}
    return bool(name_tokens & line_tokens)


def _qty_in(text: str) -> str | None:
    """The quantity token a line carries ('2', '5', '1.9') or None."""
    from extractors.deal_text import (
        _QTY_KG_PREFIX_RE, _QTY_COUNT_PREFIX_RE, _MIN_WEIGHT_RE,
        _KG_FOR_PRICE_RE, _COUNT_FOR_PRICE_RE,
    )
    for rx in (_QTY_KG_PREFIX_RE, _KG_FOR_PRICE_RE, _MIN_WEIGHT_RE,
               _QTY_COUNT_PREFIX_RE, _COUNT_FOR_PRICE_RE):
        m = rx.search(text or "")
        if m:
            return m.group(1)
    return None


def verify_board_parse(files: list[Path], deals: list[dict]) -> list:
    """Second independent READ before anything posts (user directive
    2026-09-27: 'let the model research this before posting — this is
    so much false information').

    The first pass sometimes DROPS the printed quantity from raw_text
    entirely (observed live 2026-09-27: 'THIGH FILLET $21.99' for a
    '2 KG THIGH FILLET $21.99' tile — and the classify step flips
    single/multibuy between runs on the same image). So this pass
    asks the model only what models are reliable at — COPYING: a pure
    re-transcription of every price line. CODE then decides: for each
    single deal whose re-read line carries a quantity, the pack-guard
    conversion is applied from the re-read text; a multibuy deal
    whose re-read quantity disagrees is flagged ⚠. Never raises and
    never blocks: raw_text-anchored guard fixes have already applied.
    """
    try:
        content, usage = _call_model(MODEL_CHAIN[0], TRANSCRIBE_PROMPT,
                                     files)
        print(f"[vision-verify] {MODEL_CHAIN[0]['label']} "
              f"finish_reason={usage.get('finish_reason')} "
              f"tokens={usage.get('total_tokens')}")
        lines = (extract_json(content) or {}).get("lines") or []
        from extractors.deal_text import normalise_pack_deal
        used: set = set()
        for d in deals:
            match = None
            for i, line in enumerate(lines):
                if i in used:
                    continue
                if _line_matches_deal(line, d):
                    match = (i, line)
                    break
            if match is None:
                continue
            used.add(match[0])
            line = match[1]
            kind = d.get("price_kind")
            if kind == "single":
                probe = dict(d)
                probe["raw_text"] = line
                normalise_pack_deal(probe)
                if probe["price_kind"] != "single":
                    # the re-read found a quantity the parse dropped —
                    # bundle maths win, transparently
                    for k in ("price_kind", "multibuy_qty",
                              "bulk_size", "unit", "item", "notes"):
                        if k in probe:
                            d[k] = probe[k]
                    d["raw_text"] = line
                    d["review_flag"] = f"re-read: {line.strip()[:60]}"
            elif kind == "multibuy":
                rq = _qty_in(line)
                dq = str(d.get("multibuy_qty") or "")
                if rq is not None and rq != dq:
                    d["review_flag"] = (
                        f"check qty — board reads {line.strip()[:60]}")
    except Exception as exc:   # noqa: BLE001 — verification is additive
        print(f"[vision-verify] unavailable ({exc.__class__.__name__})"
              f" — pack-guard values stand")
    return deals
