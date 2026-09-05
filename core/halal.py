"""Halal rules: vocabulary, Col P marker, LLM live check, 3-tier
resolution chain, butcher tier-3 reader (spec §12)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

HALAL_MARKER = "halal"          # positive-only token in Col P
HALAL_CHECK_CATEGORIES = {      # §4.5 / §12.3 labels (exact mirror)
    "beef mince", "chicken mince", "chicken breast", "chicken thigh",
    "chicken drumstick", "chicken wings", "whole chicken", "beef diced",
    "lamb & mutton", "goat", "veal", "processed meats",
}
HALAL_CHECK_MODEL_CHAIN = [     # M7-validated ids (plan §1.1)
    {"model": "z-ai/glm-5.3-flash:online",       "route": "openrouter"},
    {"model": "google/gemini-2.5-flash:online",  "route": "openrouter"},
]
HALAL_CHECK_MAX_PER_RUN = 20
HALAL_CHECK_TTL_DAYS = 90
HALAL_LEDGER_PATH = (Path(__file__).resolve().parent.parent
                     / "data" / "halal_status.json")
HALAL_WRITE_CONFIDENCE = 0.8    # >= writes Col P (D-H9)

MEAT_PROTEIN_WORDS = frozenset({
    "meat", "beef", "chicken", "lamb", "mutton", "goat", "veal"})
MEAT_CUT_WORDS = frozenset({
    "mince", "minced", "breast", "thigh", "drumstick", "drumsticks",
    "wing", "wings", "diced", "cubes", "chops", "cutlets", "roast",
    "kebab", "skewer", "sausage", "sausages", "frankfurt",
    "frankfurts", "leg", "steak", "shoulder", "brisket", "rib",
    "ribs", "loin", "shanks", "shank"})
MEAT_CUT_PHRASES = ("whole bird",)
PREPARED_EXCLUSIONS = (
    re.compile(r"\bchicken\s+salt\b"),
    re.compile(r"\bchicken\s+(?:noodles?|soup)\b"),
    re.compile(r"\bbeef\s+stock\b"),
    re.compile(r"\b(?:chicken|beef)\s+flavou?red\b"),
    re.compile(r"\bflavou?red\b[^.]{0,30}\b(?:chicken|beef)\b"),
)


def is_meat_term(query: str) -> bool:
    """Query layer (§12.2): raw meat terms only; prepared-food
    exclusions WIN ("chicken salt" is not a meat term).

    Word-boundary tokenisation (lowercase alphanumerics). A term is a
    meat term when a protein word co-occurs with a cut word / whole
    bird phrase / protein alone as a head noun ("lamb"), and NO
    prepared-food exclusion matches.

    Args:
        query: raw user query.

    Returns:
        True when the query targets raw meat/poultry.
    """
    text = (query or "").lower()
    if any(rx.search(text) for rx in PREPARED_EXCLUSIONS):
        return False
    if any(phrase in text for phrase in MEAT_CUT_PHRASES):
        return True
    words = set(re.findall(r"[a-z0-9]+", text))
    if not words & MEAT_PROTEIN_WORDS:
        return False
    if words & MEAT_CUT_WORDS:
        return True
    # Bare protein head noun ("lamb", "goat") with no other food words
    return words <= MEAT_PROTEIN_WORDS


def is_auto_halal_scope(subcategory_label: str) -> bool:
    """Row/sub-category authority for the AUTOMATIC machinery.

    Args:
        subcategory_label: Col Q label (already normalised).

    Returns:
        True when rows in this sub-category are auto-checked.
    """
    return (subcategory_label or "").strip() in HALAL_CHECK_CATEGORIES


def is_halal_row(col_p_aliases: str, name: str = "") -> bool:
    """HALAL_MARKER in the Col P alias list OR literal 'halal' word
    in the name. Manual and LLM-verified markers are EQUAL.

    Args:
        col_p_aliases: pipe-separated Col P aliases (may be blank).
        name: Col A product name.

    Returns:
        True when the row is halal-marked by either origin.
    """
    aliases = [a.strip().lower()
               for a in str(col_p_aliases or "").split("|")
               if a.strip()]
    if HALAL_MARKER in aliases:
        return True
    return bool(re.search(r"\bhalal\b", (name or "").lower()))


def halal_search_suffix(query: str) -> str:
    """'chicken breast' -> 'halal chicken breast' (tier-2 live query);
    idempotent when 'halal' is already present.

    Args:
        query: raw meat query.

    Returns:
        The query with the 'halal ' prefix (once).
    """
    text = (query or "").strip()
    if re.search(r"\bhalal\b", text.lower()):
        return text
    return f"halal {text}"


def filter_halal_rows(rows) -> list:
    """Keep rows where is_halal_row(col_p, name) is True.

    Args:
        rows: dicts with 'keywords' (Col P) and 'name' fields, or
            gspread-style row lists — dict form is expected.

    Returns:
        The halal-marked subset.
    """
    return [r for r in rows
            if is_halal_row(r.get("keywords", ""), r.get("name", ""))]


def _ledger_key(name: str, brand: str = "", item_code: str = "") -> str:
    """item_code when known, else normalised brand+name.

    Args:
        name: product name.
        brand: brand line (may be blank).
        item_code: permanent row id when known.

    Returns:
        Stable ledger dictionary key.
    """
    if item_code:
        return f"code:{item_code.strip().upper()}"
    text = " ".join(f"{brand} {name}".lower().split())
    return re.sub(r"[^a-z0-9 ]", "", text)


def load_ledger(path=None) -> dict:
    """Load the halal verdict ledger; corrupt/missing -> {}.

    Args:
        path: override the default HALAL_LEDGER_PATH (tests).

    Returns:
        {ledger_key: HalalVerdict-shaped dict}.
    """
    ledger_path = path or HALAL_LEDGER_PATH
    try:
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_ledger(ledger: dict, path=None) -> None:
    """Atomic ledger write (tmp file + os.replace).

    Args:
        ledger: the full ledger mapping.
        path: override the default HALAL_LEDGER_PATH (tests).
    """
    ledger_path = path or HALAL_LEDGER_PATH
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ledger, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, ledger_path)


def _openrouter_chat(model: str, prompt: str,
                     max_tokens: int = 700) -> str:
    """One OpenRouter chat call (transport hook — tests monkeypatch
    this). Uses OPENROUTER_API_KEY; the ':online' suffix enables web
    search (M7). One-line fallback documented in plan §1.1: strip the
    suffix and send plugins [{"id": "web", "max_results": 5}].
    Raises RuntimeError (secret-free) on failure.
    """
    import requests

    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set in .env")
    url = "https://openrouter.ai/api/v1/chat/completions"
    body = {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    try:
        resp = requests.post(
            url, headers={"Authorization": f"Bearer {key}",
                          "Content-Type": "application/json"},
            json=body, timeout=90)
    except requests.RequestException as exc:
        raise RuntimeError(
            f"openrouter transport failed: "
            f"{exc.__class__.__name__}") from exc
    if resp.status_code != 200:
        text = resp.text[:300].replace(key, "***MASKED***")
        raise RuntimeError(
            f"openrouter HTTP {resp.status_code}: {text}")
    try:
        return resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        raise RuntimeError(
            f"openrouter reply shape unexpected "
            f"({exc.__class__.__name__})") from exc


HALAL_CHECK_PROMPT = """You are checking whether an Australian retail
food product is halal. Product: {name}. Brand: {brand}. Country:
Australia. Use web-search evidence: halal certifier logos, official
brand statements, ingredient concerns (gelatine, alcohol, non-halal
slaughter). If web evidence is missing or conflicting, answer
"uncertain" - never guess. Answer STRICT JSON only:
{{"verdict": "halal"|"non_halal"|"uncertain", "confidence": 0.0-1.0,
 "evidence": "one line", "brand_line": "brand/certifier summary"}}"""


def _parse_verdict(content: str) -> dict:
    """Extract the strict-JSON verdict object from a model reply.

    Fence strip -> brace slice -> strict parse. Raises ValueError
    when no JSON object survives.
    """
    text = (content or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text,
                      re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            text = text[start:end + 1]
    data = json.loads(text)
    if not isinstance(data, dict) or "verdict" not in data:
        raise ValueError("verdict object required")
    return data


def check_halal_via_llm(name: str, brand: str = "",
                        force: bool = False) -> HalalVerdict:
    """Ledger-first LLM halal check (§12.5).

    1. Ledger hit younger than HALAL_CHECK_TTL_DAYS -> cached
       verdict, NO call (force ignores TTL).
    2. HALAL_CHECK_MODEL_CHAIN, attempt cap 2, strict-JSON prompt.
       Prose-wrapped JSON rescued; a no-web failure may only yield
       'uncertain'.
    3. ALL verdicts (incl. negatives) written to the ledger;
       secret-free logging. Errors -> 'uncertain' (never raises).

    Args:
        name: product name (Col A).
        brand: brand line (may be blank).
        force: re-check even when a fresh verdict exists.

    Returns:
        HalalVerdict (always).
    """
    ledger = load_ledger()
    key = _ledger_key(name, brand)
    if not force and key in ledger:
        cached = ledger[key]
        try:
            checked = date.fromisoformat(
                str(cached.get("checked_at", ""))[:10])
            if date.today() - checked < \
                    timedelta(days=HALAL_CHECK_TTL_DAYS):
                return HalalVerdict(**{**cached, "product": name})
        except ValueError:
            pass
    prompt = HALAL_CHECK_PROMPT.format(
        name=name, brand=brand or "unspecified")
    verdict = None
    last_err = ""
    for entry in HALAL_CHECK_MODEL_CHAIN[:2]:   # attempt cap 2
        try:
            content = _openrouter_chat(entry["model"], prompt)
            data = _parse_verdict(content)
            verdict = HalalVerdict(
                product=name,
                verdict=str(data.get("verdict", "uncertain")),
                confidence=float(data.get("confidence") or 0.0),
                evidence=str(data.get("evidence", ""))[:300],
                checked_at=date.today().isoformat(),
                web_searched=True,
                brand_line=str(data.get("brand_line", ""))[:200],
            )
            break
        except (RuntimeError, ValueError) as exc:
            last_err = exc.__class__.__name__
            continue
    if verdict is None:
        verdict = HalalVerdict(
            product=name, verdict="uncertain", confidence=0.0,
            evidence=f"check failed: {last_err}",
            checked_at=date.today().isoformat(),
            web_searched=False, brand_line=brand)
    ledger[key] = {
        "verdict": verdict.verdict,
        "confidence": verdict.confidence,
        "evidence": verdict.evidence,
        "checked_at": verdict.checked_at,
        "web_searched": verdict.web_searched,
        "brand_line": verdict.brand_line,
        "product": name,
    }
    save_ledger(ledger)
    print(f"[halal] {name}: {verdict.verdict} "
          f"(confidence {verdict.confidence:.2f})")
    return verdict


def mark_halal_in_sheet(worksheet, row_index: int) -> str:
    """Append HALAL_MARKER to Col P via the existing
    sheets_sync._append_alias path (POSITIVE verdicts only).

    Args:
        worksheet: Products_Master worksheet handle.
        row_index: 1-based sheet row of the product.

    Returns:
        The range written ("" when nothing needed / write failed).
    """
    try:
        values = worksheet.get_all_values()
        if not values or row_index > len(values):
            return ""
        from core.sheets_sync import _append_alias
        return _append_alias(worksheet, values[0], row_index,
                             HALAL_MARKER) or ""
    except Exception as exc:  # noqa: BLE001 — marker write is
        # best-effort; the verdict stays in the ledger either way.
        print(f"[halal] marker write skipped: "
              f"{exc.__class__.__name__}")
        return ""


@dataclass
class HalalVerdict:
    """One LLM halal verdict (ledger + in-memory form)."""
    product: str
    verdict: str            # "halal" | "non_halal" | "uncertain"
    confidence: float
    evidence: str
    checked_at: str
    web_searched: bool
    brand_line: str = ""


@dataclass
class HalalResolution:
    """3-tier resolution result (§12.1 rule 5, plan §1.3)."""
    tier: int                      # 1 sheet, 2 live+LLM, 3 butchery, 0 none
    result: object = None          # LookupResult (tiers 1/2)
    butcher_line: str = ""         # display-only (D-H5)
    notes: list = field(default_factory=list)

    def to_lookup_result(self):
        """LookupResult view for the CLI relay.

        Tiers 1/2 -> the inner result verbatim; tier 3/0 -> None
        (the caller renders butcher_line / the unavailable message).
        """
        return self.result


def query_local_butchers(term: str) -> list[dict]:
    """Tier 3: read the Local_Deals tab, BUTCHERY-domain rows only.

    The tab carries no taxonomy column, so each row's Col A name is
    classified via core.subcategory and kept only when the label is
    in BUTCHERY_DOMAIN — nuggets/patties/schnitzels never answer
    (§8.4). Rows match when token_set_ratio >= 0.5 or the query
    tokens are contained. Missing/empty tab -> []. Butcheries are
    assumed halal (D-H6).

    Args:
        term: raw meat query.

    Returns:
        [{store, item, price_text}] matches (display-ready).
    """
    from core.local_deals import BUTCHERY_DOMAIN
    from core.name_matcher import similarity_tokens, token_set_ratio
    from core.subcategory import classify_subcategory
    words = set(re.findall(r"[a-z0-9]+", (term or "").lower()))
    prepared = {"nugget", "nuggets", "patty", "patties", "schnitzel",
                "crumbed", "salt", "stock", "flavoured", "flavored"}
    if words & prepared:
        return []
    try:
        from core.sheets_client import connect_worksheet
        worksheet = connect_worksheet("Local_Deals")
        values = worksheet.get_all_values()
    except Exception:  # noqa: BLE001 — missing tab / no creds -> []
        return []
    if len(values) < 2:
        return []
    query_tokens = similarity_tokens(term)
    matches: list[dict] = []
    for row in values[1:]:
        if not row or not str(row[0]).strip():
            continue
        name = str(row[0]).strip()
        label, _conf = classify_subcategory(name)
        if label not in BUTCHERY_DOMAIN:
            continue
        ratio = token_set_ratio(term, name)
        containment = bool(query_tokens) and query_tokens.issubset(
            similarity_tokens(name))
        if ratio >= 0.5 or containment:
            price_text = next(
                (str(cell).strip() for cell in row[1:]
                 if str(cell).strip() not in ("", "0")), "")
            matches.append({"store": "", "item": name,
                            "price_text": price_text})
    return matches


def resolve_halal_item(query: str, worksheet=None) -> HalalResolution:
    """The 3-tier chain orchestrator (§12.1 rule 5, plan §1.4.9).

    Tier 1: halal-SCOPED sheet stages via LookupEngine.find_product(
    query, interactive=False, _halal_chain=True) — halal-visible rows
    only; a sheet hit ends the chain with NO live call. Tier 2: the
    chain-mode live stage already carries the 'halal ' prefix; each
    top live candidate is LLM-verified. Exactly ONE confirmed (verdict
    halal AND confidence >= HALAL_WRITE_CONFIDENCE) ->
    add_product_row(..., alias=query, halal_confirmed=True) (D-H2
    auto-add) -> re-resolve and return the new sheet row. Multiple
    confirmed -> CANDIDATES list, NOTHING written. None confirmed ->
    tier 3. Non-meat queries never enter (caller guarantees).

    Args:
        query: raw meat term.
        worksheet: optional Products_Master handle for auto-add.

    Returns:
        HalalResolution (never raises to the caller).
    """
    from core.lookup import LookupEngine, LookupStatus

    def _sheet_hit(result) -> bool:
        return result is not None and (
            getattr(result, "row_index", None) is not None
            or getattr(result, "status", None) in (
                LookupStatus.EXACT_SHEET, LookupStatus.KEYWORD_ALIAS,
                LookupStatus.SHEET_AND_LIVE))

    engine = LookupEngine(worksheet) if worksheet is not None \
        else LookupEngine()
    tier1 = engine.find_product(query, interactive=False,
                                _halal_chain=True)
    if _sheet_hit(tier1):
        return HalalResolution(tier=1, result=tier1)

    live = engine.find_product(query, interactive=False,
                               _halal_chain=True)
    live_items = list(getattr(live, "live_items", None) or [])
    confirmed = []
    for item in live_items[:3]:
        verdict = check_halal_via_llm(
            getattr(item, "raw_name", "") or str(item),
            brand=getattr(item, "brand", "") or "")
        if verdict.verdict == "halal" and \
                verdict.confidence >= HALAL_WRITE_CONFIDENCE:
            confirmed.append(item)
    if len(confirmed) == 1:
        from core.sheets_sync import add_product_row
        item = confirmed[0]
        result = add_product_row(
            getattr(item, "raw_name", "") or str(item),
            getattr(item, "store", "") or "",
            getattr(item, "price", 0.0) or 0.0,
            brand=getattr(item, "brand", "") or "",
            size=getattr(item, "size", "") or "unit unavailable",
            alias=query, allow_duplicate=False,
            halal_confirmed=True, worksheet=worksheet)
        if isinstance(result, dict) and result.get("wrote"):
            tier1b = engine.find_product(query, interactive=False,
                                         _halal_chain=True)
            if _sheet_hit(tier1b):
                return HalalResolution(tier=2, result=tier1b, notes=[
                    "auto-added halal row (D-H2)"])
        return HalalResolution(tier=2, result=live, notes=[
            "halal candidate confirmed; sheet add did not complete"])
    if len(confirmed) > 1:
        return HalalResolution(tier=2, result=live, notes=[
            "multiple halal candidates — confirm manually"])

    butchers = query_local_butchers(query)
    if butchers:
        b = butchers[0]
        price_part = f" — {b['price_text']}" if b["price_text"] else ""
        line = (f"🔪 Local butcher (halal): {b['item']}"
                f"{price_part} (this week's board)")
        return HalalResolution(tier=3, butcher_line=line)
    return HalalResolution(tier=0, butcher_line=(
        f"no halal source found for '{query}' — "
        f"not available this week"))


def backfill_halal_checks(worksheet, dry_run: bool = False,
                          limit: int | None = None,
                          force: bool = False) -> dict:
    """Sweep AUTO-SCOPE rows with unknown/stale ledger status through
    the LLM check (<= limit or HALAL_CHECK_MAX_PER_RUN; resumes on
    later runs). Confident halal -> mark_halal_in_sheet +
    set_preferred(code) (rule 6 alignment, single writer). Non-halal
    / uncertain -> ledger ONLY. --dry-run reports, writes nothing.

    Args:
        worksheet: Products_Master handle.
        dry_run: report without writing anything.
        limit: optional per-run cap override.
        force: ignore ledger TTL.

    Returns:
        {checked, marked, excluded, deferred, notes}.
    """
    from core.preferences import read_qrs, set_preferred

    rows = read_qrs(worksheet)
    ledger = load_ledger()
    report = {"checked": 0, "marked": 0, "excluded": 0,
              "deferred": 0, "notes": []}
    cap = limit if limit is not None else HALAL_CHECK_MAX_PER_RUN
    for row in rows:
        if report["checked"] >= cap:
            break
        if not is_auto_halal_scope(row.get("subcategory", "")):
            continue
        if is_halal_row(row.get("keywords", ""), row["name"]):
            continue   # already marked — manual or LLM, equal
        key = _ledger_key(row["name"],
                          item_code=row.get("item_code", ""))
        cached = ledger.get(key)
        fresh = False
        if cached and not force:
            try:
                checked = date.fromisoformat(
                    str(cached.get("checked_at", ""))[:10])
                fresh = date.today() - checked < timedelta(
                    days=HALAL_CHECK_TTL_DAYS)
            except ValueError:
                fresh = False
        if cached and fresh:
            continue   # ledger current — nothing to do this sweep
        report["checked"] += 1
        verdict = check_halal_via_llm(
            row["name"], force=force) if not (cached and fresh) \
            else None
        verdict = verdict or HalalVerdict(
            product=row["name"],
            verdict=str(cached.get("verdict", "uncertain")),
            confidence=float(cached.get("confidence", 0.0)),
            evidence=str(cached.get("evidence", "")),
            checked_at=str(cached.get("checked_at", "")),
            web_searched=bool(cached.get("web_searched")))
        if verdict.verdict == "halal" and \
                verdict.confidence >= HALAL_WRITE_CONFIDENCE:
            if dry_run:
                report["notes"].append(
                    f"[dry-run] would mark: {row['name']}")
                continue
            range_written = mark_halal_in_sheet(
                worksheet, row["row_index"])
            if range_written:
                report["marked"] += 1
            if row.get("item_code"):
                try:
                    set_preferred(worksheet, row["item_code"])
                except Exception as exc:  # noqa: BLE001 — P align
                    # is best-effort; marker already written.
                    report["notes"].append(
                        f"P-align skipped for {row['name']}: "
                        f"{exc.__class__.__name__}")
        elif verdict.verdict == "non_halal":
            report["excluded"] += 1
        else:
            report["deferred"] += 1
    return report


def halal_list_gate(worksheet, names: list[str],
                    explicit: list[str] | None = None) -> dict:
    """Shopping-list halal gate for shop/optimize (§12.4 wiring).

    For each resolved Col A name: read its row's Q + Col P (+ name).
    - Non-marked row in an AUTO-SCOPE sub-category -> EXCLUDED
      ('excluded (non-halal — database only)') — including
      explicitly-typed full names (D-H4: the exclusion note stays
      visible).
    - UNKNOWN-status auto-scope row -> on-demand check (bounded by
      the per-run cap): halal >= 0.8 -> marked + included;
      non_halal -> excluded; uncertain or impossible -> EXCLUDED
      ('halal unverified — check pending' / '... verify manually')
      — fail-safe, never silently in a list.
    - Marked row in ANY sub-category -> included (generic marker
      rule — manual marking honored, §12.1 rule 6).
    - Everything else -> included unchanged.

    Args:
        worksheet: Products_Master handle.
        names: resolved Col A names on the shopping list.
        explicit: names the user typed verbatim (informational).

    Returns:
        {included, excluded: [(name, note)], checked, notes}.
    """
    from core.preferences import read_qrs

    explicit = explicit or set()
    rows = read_qrs(worksheet)
    by_name = {r["name"].strip().lower(): r for r in rows
               if r.get("name")}
    result: dict = {"included": [], "excluded": [], "checked": 0,
                    "notes": []}
    ledger = load_ledger()
    for name in names:
        row = by_name.get((name or "").strip().lower())
        if row is None:
            result["included"].append(name)
            continue
        marked = is_halal_row(row.get("keywords", ""), row["name"])
        if marked:
            result["included"].append(name)
            continue
        if not is_auto_halal_scope(row.get("subcategory", "")):
            result["included"].append(name)
            continue
        key = _ledger_key(row["name"],
                          item_code=row.get("item_code", ""))
        cached = ledger.get(key)
        if cached is None:
            if result["checked"] < HALAL_CHECK_MAX_PER_RUN:
                result["checked"] += 1
                verdict = check_halal_via_llm(row["name"])
                if verdict.verdict == "halal" and \
                        verdict.confidence >= HALAL_WRITE_CONFIDENCE:
                    mark_halal_in_sheet(worksheet,
                                        row["row_index"])
                    result["included"].append(name)
                    continue
                if verdict.verdict == "non_halal":
                    result["excluded"].append(
                        (name, "excluded (non-halal — database "
                               "only)"))
                    continue
                result["excluded"].append(
                    (name, "halal unverified — check pending"))
                continue
            result["excluded"].append(
                (name, "halal unverified — verify manually"))
            continue
        if cached.get("verdict") == "non_halal":
            note = "excluded (non-halal — database only)"
            if name in explicit:
                note += " (explicitly typed)"
            result["excluded"].append((name, note))
        else:
            result["excluded"].append(
                (name, "halal unverified — verify manually"))
    return result
