#!/usr/bin/env python3
"""Canonical sub-category taxonomy for Products_Master Col Q (§3, §4).

Ordered regex -> label rules, specific before generic (first match
wins). No rule match -> caller writes the literal marker NEEDS_REVIEW
(D-SC2 — never a silent guess). New clusters are one line in
_RULE_DEFS (D-SC1). Normalisation: lowercase, trim, collapse
whitespace/underscores/hyphens to single spaces.

Boundary-safe patterns: \\bbreads?\\b can NOT match "breading" or
"breadcrumbs" (the letter after "bread" is a word char, so the \\b
fails) — spec §4 mandates this.

USER REVISION 2026-09-05: misfire-prone single words carry \\b
anchors so substrings never guess wrong — "V Sugarfree" is NOT
sugar, "V Watermelon" is NOT water, "eggplant" is NOT eggs,
"pineapple" is NOT apples. Such names now fall through to
NEEDS_REVIEW and surface on the "Sub-category reviews" list, where
the user decides (ask-first policy — never write a guess).
"""
from __future__ import annotations

import re

SUBCATEGORY_HEADER = "Sub_Category"   # Col Q (0-based idx 16)
NEEDS_REVIEW = "needs review"         # literal marker (D-SC2)
CONFIDENT_THRESHOLD = 0.75            # rule hit = 1.0 >= threshold


def normalize_subcategory(s: str) -> str:
    """Lowercase, trim, collapse whitespace/_/- to single spaces.

    Args:
        s: raw sub-category text (user flag, Col Q cell, label).

    Returns:
        str: canonical form ("Shredded_Cheese" -> "shredded cheese").
    """
    text = str(s or "").strip().lower()
    text = re.sub(r"[_\-\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_SIZE_TOKEN = re.compile(
    r"^\d+(?:\.\d+)?\s*(?:kg|g|ml|l|ltr|litre|litres|pack|pk|pks|"
    r"sheet|sheets|roll|rolls|pc|pcs|piece|pieces|tub|tubs)$")
_UNITS = {"kg", "g", "ml", "l", "ltr", "litre", "litres", "pack",
          "pk", "pks", "sheet", "sheets", "roll", "rolls", "pc",
          "pcs", "piece", "pieces", "tub", "tubs"}
_BARE_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_STORE_PREFIXES = {"woolworths", "woolies", "coles", "aldi"}
_FILLER = {"original", "fresh", "large", "small", "mini", "free",
           "range", "market", "brand"}


def strip_phrase(phrase: str) -> list[str]:
    """Tokens for sub-category matching: size tokens (both glued
    "2kg" and split "2 kg"), store prefixes and filler words removed
    ("Sugar-2 kg" -> ["sugar"]; "woolworths full cream milk 3l" ->
    ["full", "cream", "milk"]). Tokens stay WHOLE — plural folding
    happens on both sides inside match_subcategory. Never empty
    (falls back to raw lowercased tokens)."""
    text = normalize_subcategory(phrase).replace("-", " ")
    out: list[str] = []
    for tok in text.split():
        if _SIZE_TOKEN.match(tok) or _BARE_NUMBER.match(tok):
            continue
        if tok in _UNITS or tok in _STORE_PREFIXES or tok in _FILLER:
            continue
        out.append(tok)
    return out or normalize_subcategory(phrase).split()


def _token_variants(token: str) -> set:
    """Singular/plural normalisation variants of one token.

    Absorbed from the retired v1 lookup engine in Round 3 — this was
    the only surviving use. "ies"->"y", trailing "es", and trailing "s"
    each produce an extra candidate variant.

    Args:
        token (str): lowercased single word.

    Returns:
        set: the token plus its plausible singular/plural forms.
    """
    variants = {token}
    if token.endswith("ies") and len(token) > 4:
        variants.add(token[:-3] + "y")
    if token.endswith("es") and len(token) > 3:
        variants.add(token[:-2])
    if token.endswith("s") and len(token) > 2:
        variants.add(token[:-1])
    return variants


def match_subcategory(phrase: str, sheet_labels: list[str]) -> str:
    """Best sheet label for a shopping-list phrase, or "".

    Deterministic: (1) exact normalized equality; (2) label whose
    token set (singular/plural folded) is a subset of the phrase
    tokens, or the phrase tokens a subset of the label tokens —
    longest label wins, then most matched tokens, then alphabetical.
    Only whole tokens count ("mini cucumber" phrase matches label
    "cucumber" via subset; "cucumber mini" also tries the joined
    form). Sheet labels ONLY (D4 — the sheet is the truth)."""

    def variants(tokens: set[str]) -> set[str]:
        out: set[str] = set()
        for tok in tokens:
            out |= _token_variants(tok)
        return out

    want = set(strip_phrase(phrase))
    if not want:
        return ""
    # raw-token reorder: "cucumber mini" and "mini cucumber" share a
    # token set — a label whose tokens equal the RAW phrase tokens
    # wins immediately (word-order independence).
    raw_tokens = set(normalize_subcategory(phrase).split())
    want_var = variants(want)
    best: tuple[int, int, str, str] | None = None
    # exact-token-set first, then longest label, then most matched
    for raw in sheet_labels:
        norm = normalize_subcategory(raw)
        if not norm:
            continue
        if norm == normalize_subcategory(phrase):
            return raw
        if raw_tokens and set(norm.split()) == raw_tokens:
            return raw
        lab_tokens = set(norm.split())
        if not lab_tokens:
            continue
        lab_var = variants(lab_tokens)
        exact = 1 if lab_var == want_var else 0
        if lab_var <= want_var or want_var <= lab_var:
            matched = len(lab_tokens) if lab_var <= want_var \
                else len(want)
        elif not exact:
            continue
        else:
            matched = 0
        key = (-exact, -len(norm), -matched, norm, raw)
        if best is None or key < best:
            best = key
    return best[3] if best else ""


# (pattern, label) — ORDER IS BINDING: first match wins; compounds
# BEFORE generic parents ("cheese slice" before "cheese").
# \b anchors on single words (2026-09-05): substrings must never
# guess wrong — "sugarfree"/"watermelon"/"eggplant"/"pineapple" fall
# through to needs review instead of a confident misfire.
#
# SLIM-DOWN 2026-09-07 (plan S1.3): labels with no live sheet row AND
# not referenced by core/halal.py (HALAL_CHECK_CATEGORIES) or
# core/local_deals.py (PRODUCE_SUBCATEGORIES) were removed — 33 dead
# rules deleted (chicken schnitzel kept with the meat family;
# corn chips kept: active sheet label + top-of-list cross-family
# guard). Deleted: cheese slice, cream cheese, mozzarella, parmesan,
# feta, cheese, yoghurt, long life milk, iced coffee, coffee syrup,
# coffee, croissant, muffins, mineral water, spring water, energy
# drink, liquid breakfast, sports drink, soft drink, chocolate bar,
# chewing gum, potato chips, popcorn, biscuits, slices, lollies,
# frozen snacks, frozen berries, cereal, flour, oil, spread. New rows
# in those families now classify to "needs review" (ask-first, B4).
_RULE_DEFS: list[tuple[str, str]] = [
    # Cross-family compounds that must outrank EVERY generic rule
    # below (e.g. "Supreme Cheese Corn Chips" -> "corn chips", not
    # "cheese") — keep these at the top.
    (r"corn\s*chips", "corn chips"),
    # --- meat & poultry (halal + comparison domains depend on
    #     these labels — spec §12.3; single words carry \b) ---
    (r"beef\s*mince|minced\s*beef", "beef mince"),
    (r"chicken\s*mince|minced\s*chicken", "chicken mince"),
    (r"chicken\s*breast", "chicken breast"),
    (r"chicken\s*thigh", "chicken thigh"),
    (r"chicken\s*drumsticks?", "chicken drumstick"),
    (r"chicken\s*wings?", "chicken wings"),
    (r"whole\s*chicken|chicken\s*whole", "whole chicken"),
    (r"\bbeef\s*diced|diced\s*beef\b", "beef diced"),
    (r"\blamb\b|\bmutton\b", "lamb & mutton"),
    (r"\bgoat\b", "goat"),
    (r"\bveal\b", "veal"),
    (r"sausages?|kebab|skewer", "processed meats"),
    (r"schnitzel|crumbed\s*chicken|chicken\s*schnitzel",
     "chicken schnitzel"),
    # --- cheese (compounds first; base "cheese" removed 2026-09-07 —
    #     sheet carries the active cheese labels) ---
    (r"shredded\s*cheese|grated\s*cheese", "shredded cheese"),
    (r"cheese\s*&?\s*cracker|\bcrackers?\b", "crackers"),
    # --- dairy ---
    (r"greek\s*yogh?urt", "greek yoghurt"),
    (r"\beggs?\b", "eggs"),
    (r"\bmilk\b", "milk"),
    # --- drinks (sheet-active labels only) ---
    (r"\bjuice\b", "juice"),
    (r"\bwater\b", "water"),
    (r"choc\s*hazelnut|hazelnut\s*chocolate|chocolate\s*spread",
     "chocolate spread"),
    (r"\bchocolate\b", "chocolate"),
    (r"\bmints?\b", "mints"),
    # --- fruit & veg (produce labels protected by
    #     core/local_deals.py::PRODUCE_SUBCATEGORIES) ---
    (r"spring\s*onion", "spring onion"),
    (r"\bonions?\b", "onion"),
    (r"\bbananas?\b", "bananas"),
    (r"blueberries", "blueberries"),
    (r"raspberries", "raspberries"),
    (r"strawberries", "strawberries"),
    (r"\bapples?\b", "apples"),
    (r"capsicum", "capsicum"),
    (r"\bcucumbers?\b", "cucumber"),
    (r"\btomatoes?\b", "tomato"),
    (r"coriander|fresh\s*herbs?|\bherbs?\b", "fresh herbs"),
    (r"\bpotatoes?\b", "potatoes"),
    (r"\blettuce\b|salad\s*mix", "salad"),
    # --- bakery ---
    # \b anchors: "breading"/"breadcrumbs" must never match (§4).
    (r"\bbreads?\b", "bread"),
    (r"pancake\s*mix", "pancake mix"),
    # --- pantry ---
    (r"\bsugars?\b", "sugar"),
    (r"\bpasta\b", "pasta"),
    (r"\brice\b", "rice"),
    (r"\bsauces?\b", "sauce"),
    (r"ice\s*cream|frozen\s*dessert", "ice cream"),
    # --- household / other ---
    (r"\bpads?\b|\btampons?\b", "pads"),
    (r"hand\s*warmers?", "hand warmers"),
]

SUBCATEGORY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(p), label) for p, label in _RULE_DEFS
]


def classify_subcategory(
    name: str, category_hint: str = ""
) -> tuple[str, float]:
    """Classify a product name into a sub-category label.

    Args:
        name: product name (Col A style).
        category_hint: coarse Col B category — accepted for future
            use; NEVER rescues a non-match (D-SC2).

    Returns:
        (label, confidence): ("", 0.0) when no rule matches — the
        CALLER then writes NEEDS_REVIEW. A rule hit returns
        (label, 1.0).
    """
    text = normalize_subcategory(name)
    if not text:
        return ("", 0.0)
    for pattern, label in SUBCATEGORY_RULES:
        if pattern.search(text):
            return (label, 1.0)
    return ("", 0.0)


def all_labels() -> list[str]:
    """Distinct labels in rule order (deduped) — for `subcategories`.

    Returns:
        list[str]: labels in precedence order.
    """
    seen: set = set()
    out: list[str] = []
    for _pattern, label in SUBCATEGORY_RULES:
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out
