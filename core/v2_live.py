"""v2 live search (spec §7 'live', §15 future clause). PRICES ONLY.
This module NEVER receives a worksheet handle — it cannot write."""
from __future__ import annotations

import difflib
import importlib

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

    def _variants(word: str) -> set:
        out = {word}
        if word.endswith("ies") and len(word) > 4:
            out.add(word[:-3] + "y")
        if word.endswith("es") and len(word) > 3:
            out.add(word[:-2])
        if word.endswith("s") and len(word) > 2:
            out.add(word[:-1])
        return out

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


def _search_provider(provider: str, query: str) -> list:
    """One store's ≤3 results: [{'name','price','size'}].

    price = the numeric now-price; multi-buy bundle fields are
    deliberately ignored (PRICES ONLY — no deal maths in the live
    verb).
    """
    items = _provider_fn(provider)(query, page_size=_FETCH_PAGE_SIZE)
    out: list = []
    for _idx, item in _ranked(query, list(items or [])):
        price = getattr(item, "price", None)
        if not isinstance(price, (int, float)) or price <= 0:
            continue                 # no usable now-price -> not a hit
        out.append({"name": str(item.raw_name or "").strip(),
                    "price": round(float(price), 2),
                    "size": _size_text(item)})
        if len(out) >= _RESULTS_PER_STORE:
            break
    return out


def live_search(query: str) -> dict:
    """{provider: [≤3 × {'name','price','size'}], 'errors': {...}}.

    Woolworths: extractors.woolworths_extractor no-auth search.
    Coles: extractors.coles_extractor Scrape.do credit-guarded search
    (existing chain, unchanged). Providers run in LIVE_PROVIDERS
    order; a provider failure degrades to an errors entry — never an
    exception, never silence.
    """
    results: dict = {}
    errors: dict = {}
    for provider in LIVE_PROVIDERS:      # §15 iteration order
        try:
            results[provider] = _search_provider(provider, query)
        except Exception as exc:         # noqa: BLE001 — per-store guard
            results[provider] = []
            errors[provider] = exc.__class__.__name__
    results["errors"] = errors
    return results


def render_live(results: dict, tracked_note: str | None) -> str:
    """Styled block: per-store compact lines +, when the item is
    tracked, ONE side-note line with the sheet WW price (callers
    fetch it via v2_read.lookup_item — this module stays sheet-free).

    A store error renders a ⚠️ degradation line (never silence); an
    empty result list renders a "no results" line.
    """
    from core.telegram_format import section_header, warn

    lines: list = []
    for provider in LIVE_PROVIDERS:
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
            lines.append("  no results")
    if tracked_note:
        lines.append(f"ℹ️ {tracked_note}")
    return "\n".join(lines)
