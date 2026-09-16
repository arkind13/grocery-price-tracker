"""v2 live search (spec §7 'live', §15 future clause). PRICES ONLY.
This module NEVER receives a worksheet handle — it cannot write."""
from __future__ import annotations

import difflib
import importlib
import re
from concurrent.futures import ThreadPoolExecutor

# §15: adding ALDI/AMAZON later = one entry here + one extractor
# mapping in _PROVIDER_FN. Nothing else may change.
LIVE_PROVIDERS = ["woolworths", "coles", "aldi"]

# provider -> "module:function" (resolved lazily per call so the
# module imports clean and tests can patch the extractor functions).
_PROVIDER_FN = {
    "woolworths": "extractors.woolworths_extractor:"
                  "fetch_woolworths_search_noauth",
    "coles": "extractors.coles_extractor:fetch_coles_search",
    "aldi": "extractors.aldi_extractor:fetch_aldi_search",
}

_RESULTS_PER_STORE = 3      # spec §7: ≤3 compact lines per store
_FETCH_PAGE_SIZE = 10       # fetch a few extra so ranking can pick

# Relevance floor (2026-09-15 bepanthen incident): Aldi's fuzzy search
# answers a brand query ("bepanthen cream") with same-category junk —
# Thickened Cream, Cream Candies, Irish Country Cream — and the old
# take-top-3 ranker relayed it as prices. A store hit now has to clear
# a floor before it can be sent: match the query's most distinctive
# non-filler word, or match every non-filler word. Dropped-but-priced
# results are counted and rendered as a "loose hits skipped" note —
# honest emptiness, never junk prices (spec IN-1: empty != junk).
_QUERY_FILLER = frozenset({
    "a", "an", "and", "any", "anywhere", "at", "cheap", "cheapest",
    "deal", "deals", "for", "from", "how", "in", "is", "live", "me",
    "much", "near", "of", "on", "or", "please", "price", "prices",
    "search", "special", "specials", "the", "vs", "with",
})
_FUZZY_TOKEN_FLOOR = 0.85   # near-miss spelling of a distinctive word
                             # (yoghurt vs yogurt) still counts


def _variants(word: str) -> set:
    out = {word}
    if word.endswith("ies") and len(word) > 4:
        out.add(word[:-3] + "y")
    if word.endswith("es") and len(word) > 3:
        out.add(word[:-2])
    if word.endswith("s") and len(word) > 2:
        out.add(word[:-1])
    return out


def _text_words(item) -> set:
    """Lowercased name+brand tokens, punctuation-stripped. Brand joins
    the text so a brand-only result ("Bepanthen | First Aid Cream")
    still qualifies for its brand query."""
    name = str(getattr(item, "raw_name", "") or "").lower()
    brand = str(getattr(item, "brand", "") or "").lower()
    return {t.rstrip(".,") for t in f"{name} {brand}".split()}


def _word_matches(word: str, text_words: set) -> bool:
    """The ranker's tolerant hit rule: singular/plural variants, or a
    length>3 prefix of a longer product token."""
    if _variants(word) & text_words:
        return True
    return len(word) > 3 and any(t.startswith(word) for t in text_words)


def _admissible(query: str, item) -> bool:
    """Relevance floor for ONE store hit (see _QUERY_FILLER note).

    Admissible when it matches EVERY non-filler query word, or the most
    distinctive (longest) non-filler word, or a ≥0.85 near-miss of that
    distinctive word. A query with no non-filler words keeps the old
    take-any-ranking behaviour.
    """
    q_words = [w for w in str(query or "").lower().split()
               if w not in _QUERY_FILLER]
    if not q_words:
        return True
    text_words = _text_words(item)
    if all(_word_matches(w, text_words) for w in q_words):
        return True
    distinctive = max(q_words, key=len)
    if len(distinctive) < 4:
        return False        # only short generic words, partial match
    if _word_matches(distinctive, text_words):
        return True
    if len(distinctive) >= 6:
        return any(
            len(t) >= 4 and
            difflib.SequenceMatcher(None, distinctive, t).ratio()
            >= _FUZZY_TOKEN_FLOOR
            for t in text_words)
    return False

# Store mentions inside the user's own phrase ("live chicken breast
# woolworths and aldi", "beef mince ww vs aldi"). Token -> provider.
# Detected mentions BOTH narrow the search to those stores AND come
# out of the item query — "chicken breast woolworths and aldi" must
# search "chicken breast", never the whole phrase (bench M1–M3
# 2026-09-13: 3-store sequential worst case ~290 s blew the 240 s
# turn budget; named-store queries now skip Coles entirely and the
# fetches run in parallel).
_STORE_TOKENS = {
    "woolworths": "woolworths", "woolworth": "woolworths",
    "woolies": "woolworths", "ww": "woolworths",
    "coles": "coles", "cole": "coles",
    "aldi": "aldi",
}
# Connectors that only glue store names together; dropped alongside
# a detected store mention ("woolworths AND aldi", "ww VS coles").
# Stripped ONLY when a store was detected — a plain query keeps
# every word ("no results" honesty for odd product names).
_STORE_CONNECTORS = {"and", "or", "vs", "versus", "at", "from",
                     "in", "both", "only", "just", "please", "+"}


def parse_store_mentions(query: str) -> tuple:
    """'chicken breast woolworths and aldi' -> (['woolworths',
    'aldi'], 'chicken breast'). No store mentioned -> ([], the
    original query stripped only of outer whitespace)."""
    text = str(query or "").strip()
    if not text:
        return [], ""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    hits = []
    for tok in tokens:
        provider = _STORE_TOKENS.get(tok)
        if provider and provider not in hits:
            hits.append(provider)
    if not hits:
        return [], text
    keep = [tok for tok in tokens
            if tok not in _STORE_TOKENS
            and tok not in _STORE_CONNECTORS]
    # keep original casing of words that weren't tokenised away
    clean = " ".join(keep)
    return [p for p in LIVE_PROVIDERS if p in hits], clean


def _provider_fn(provider: str):
    """Resolve one _PROVIDER_FN entry to its callable (lazy import)."""
    module_name, fn_name = _PROVIDER_FN[provider].split(":")
    module = importlib.import_module(module_name)
    return getattr(module, fn_name)


def _ranked(query: str, items: list, cap: int = _RESULTS_PER_STORE
            ) -> list:
    """Top-``cap`` ProductItems by tolerant relevance, order-stable.

    Score = fraction of query words present in the product name (each
    word singular/plural-folded) + a difflib ratio on the full
    lowercase strings. Stdlib only — the v1 ranker dies with
    core/lookup.py and this is its whole live-search remainder.
    """
    ql = (query or "").lower()
    q_words = set(ql.split())

    def _score(item) -> float:
        name = str(item.raw_name or "").lower()
        n_words = set(name.split())
        hit = sum(1 for w in q_words
                  if _variants(w) & {t.rstrip(".,") for t in n_words}
                  or any(t.startswith(w) and len(w) > 3
                         for t in n_words))
        coverage = hit / len(q_words) if q_words else 0.0
        ratio = difflib.SequenceMatcher(None, ql, name).ratio()
        return coverage * 2 + ratio

    return sorted(enumerate(items), key=lambda p: (-_score(p[1]), p[0]))


def _size_text(item) -> str:
    """Package size or '' (spec §7: 'name, price, pack size')."""
    return str(getattr(item, "size", "") or "").strip()


def _search_provider(provider: str, query: str) -> tuple:
    """One store's (≤3 results, skipped-junk-count):
    ([{'name','price','size'}], N).

    price = the numeric now-price; multi-buy bundle fields are
    deliberately ignored (PRICES ONLY — no deal maths in the live
    verb). Results failing the relevance floor are counted as skipped
    and never relayed (2026-09-15 bepanthen incident).
    """
    items = _provider_fn(provider)(query, page_size=_FETCH_PAGE_SIZE)
    out: list = []
    skipped = 0
    for _idx, item in _ranked(query, list(items or [])):
        price = getattr(item, "price", None)
        if not isinstance(price, (int, float)) or price <= 0:
            continue                 # no usable now-price -> not a hit
        if not _admissible(query, item):
            skipped += 1             # loose store hit — junk, not a price
            continue
        out.append({"name": str(item.raw_name or "").strip(),
                    "price": round(float(price), 2),
                    "size": _size_text(item)})
        if len(out) >= _RESULTS_PER_STORE:
            break
    return out, skipped


def live_search(query: str) -> dict:
    """{provider: [≤3 × {'name','price','size'}], 'errors': {...}}.

    The query is first stripped of any store mentions — named stores
    narrow the search to themselves (the user asked "woolworths and
    aldi", not Coles); no mention means all three (LIVE_PROVIDERS
    order). Providers fetch IN PARALLEL so the wall time is the
    slowest single store, never the sum of three sequential scrapes
    (each has its own retry ladder — worst cases stack to ~5 min
    serialised). A provider failure degrades to an errors entry —
    never an exception, never silence.
    """
    providers, clean_query = parse_store_mentions(query)
    providers = providers or list(LIVE_PROVIDERS)
    results: dict = {}
    errors: dict = {}
    with ThreadPoolExecutor(max_workers=len(providers)) as pool:
        futures = {p: pool.submit(_search_provider, p, clean_query)
                   for p in providers}
        for provider, fut in futures.items():
            try:
                hits, skipped = fut.result()
            except Exception as exc:     # noqa: BLE001 — per-store guard
                results[provider] = []
                errors[provider] = exc.__class__.__name__
            else:
                results[provider] = hits
                if skipped:
                    results.setdefault("skipped", {})[provider] = skipped
    results["errors"] = errors
    return results


def render_live(results: dict, tracked_note: str | None) -> str:
    """Styled block: per-store compact lines +, when the item is
    tracked, ONE side-note line with the sheet WW price (callers
    fetch it via v2_read.lookup_item — this module stays sheet-free).

    A store error renders a ⚠️ degradation line (never silence); an
    empty result list renders a "no results" line, or "no close
    matches (N loose store hits skipped)" when the relevance floor
    dropped priced-but-junk hits. Only the stores actually searched
    render — an excluded-by-mention store (the "woolworths and aldi"
    phrasing) is absent, never "no results".
    """
    from core.telegram_format import section_header, warn

    lines: list = []
    for provider in [p for p in LIVE_PROVIDERS if p in results]:
        lines.append(section_header(
            provider.capitalize(),
            icon="🟢" if provider == "woolworths"
            else "🔴" if provider == "coles" else "🔵"))
        hits = results.get(provider) or []
        if hits:
            for i, hit in enumerate(hits, 1):
                size = f" · {hit['size']}" if hit.get("size") else ""
                lines.append(f"  {i}. {hit['name']} — "
                             f"${hit['price']:.2f}{size}")
        elif provider in (results.get("errors") or {}):
            lines.append(warn(f"{provider.capitalize()} search "
                              f"unavailable "
                              f"({results['errors'][provider]})"))
        else:
            skipped = (results.get("skipped") or {}).get(provider, 0)
            if skipped:
                lines.append(f"  no close matches "
                             f"({skipped} loose store hits skipped)")
            else:
                lines.append("  no results")
    if tracked_note:
        lines.append(f"ℹ️ {tracked_note}")
    return "\n".join(lines)
