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


# (pattern, label) — ORDER IS BINDING: first match wins; compounds
# BEFORE generic parents ("cheese slice" before "cheese").
_RULE_DEFS: list[tuple[str, str]] = [
    # Cross-family compounds that must outrank EVERY generic rule
    # below (e.g. "Supreme Cheese Corn Chips" -> "corn chips", not
    # "cheese") — keep these at the top.
    (r"corn\s*chips", "corn chips"),
    # --- cheese (compounds first) ---
    (r"cheese\s*slice", "cheese slice"),
    (r"shredded\s*cheese|grated\s*cheese", "shredded cheese"),
    (r"cream\s*cheese", "cream cheese"),
    (r"mozzarella", "mozzarella"),
    (r"parmesan", "parmesan"),
    (r"feta", "feta"),
    (r"cheese\s*&?\s*cracker|crackers?", "crackers"),
    (r"cheese", "cheese"),
    # --- dairy ---
    (r"greek\s*yogh?urt", "greek yoghurt"),
    (r"yogh?urt", "yoghurt"),
    (r"eggs?", "eggs"),
    (r"long\s*life\s*milk|uht", "long life milk"),
    (r"milk", "milk"),
    (r"iced\s*coffee", "iced coffee"),
    (r"coffee\s*syrup", "coffee syrup"),
    (r"coffee", "coffee"),
    # --- fruit & veg ---
    (r"spring\s*onion", "spring onion"),
    (r"onions?", "onion"),
    (r"bananas?", "bananas"),
    (r"blueberries", "blueberries"),
    (r"raspberries", "raspberries"),
    (r"strawberries", "strawberries"),
    (r"apples?", "apples"),
    (r"capsicum", "capsicum"),
    (r"cucumbers?", "cucumber"),
    (r"tomatoes?", "tomato"),
    (r"coriander|fresh\s*herbs?|herbs?", "fresh herbs"),
    (r"potatoes?", "potatoes"),
    (r"lettuce|salad\s*mix", "salad"),
    # --- bakery ---
    # \b anchors: "breading"/"breadcrumbs" must never match (§4).
    (r"\bbreads?\b", "bread"),
    (r"croissants?", "croissant"),
    (r"pancake\s*mix", "pancake mix"),
    (r"muffins?", "muffins"),
    # --- drinks ---
    (r"juice", "juice"),
    (r"mineral\s*water", "mineral water"),
    (r"spring\s*water", "spring water"),
    (r"water", "water"),
    (r"energy\s*drink", "energy drink"),
    (r"liquid\s*breakfast", "liquid breakfast"),
    (r"sports?\s*drink", "sports drink"),
    (r"soft\s*drink|soda", "soft drink"),
    # --- snacks / confectionery ---
    (r"chocolate\s*bar", "chocolate bar"),
    (r"choc\s*hazelnut|hazelnut\s*chocolate|chocolate\s*spread",
     "chocolate spread"),
    (r"chocolate", "chocolate"),
    (r"chewing\s*gum", "chewing gum"),
    (r"mints?", "mints"),
    (r"potato\s*chips|grain\s*waves|grainwaves|chips", "potato chips"),
    (r"popcorn", "popcorn"),
    (r"biscuits?|quadratini", "biscuits"),
    (r"choc\s*slice|cake\s*slice|slices?", "slices"),
    (r"loll(ie)?s|lolly", "lollies"),
    # --- freezer ---
    (r"ice\s*cream|frozen\s*dessert", "ice cream"),
    (r"frozen\s*snacks?|nuggets?|pickers|frozen\s*veg", "frozen snacks"),
    (r"frozen\s*berries", "frozen berries"),
    # --- pantry ---
    (r"sugar", "sugar"),
    (r"cereal", "cereal"),
    (r"pasta", "pasta"),
    (r"rice", "rice"),
    (r"flour", "flour"),
    (r"oil", "oil"),
    (r"sauce", "sauce"),
    (r"spread", "spread"),
    # --- household / other ---
    (r"pads?|tampon", "pads"),
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
