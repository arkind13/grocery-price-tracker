#!/usr/bin/env python3
"""Halal rules v2 — meat-term vocabulary + the butchery domain set.

Slimmed in the v2 rebuild (Round 3, spec §5/§13): the marker IS the
name prefix (Q12 — a row is halal iff its name contains 'halal'), and
the tier-2 LLM live-verification chain, its verdict-cache IO, and the
shopping-list gate are DELETED. What survives is exactly what the v2
surface needs: the meat-term gate (v2_read lookups) and the butchery
domain labels (core.local_deals domain gating).
"""
from __future__ import annotations

import re

HALAL_CHECK_CATEGORIES = {      # the butchery domain labels (§12.3)
    "beef mince", "chicken mince", "chicken breast", "chicken thigh",
    "chicken drumstick", "chicken wings", "whole chicken", "beef diced",
    "lamb & mutton", "goat", "veal", "processed meats",
}

MEAT_PROTEIN_WORDS = frozenset({
    "meat", "beef", "chicken", "lamb", "mutton", "goat", "veal"})
MEAT_CUT_WORDS = frozenset({
    "mince", "minced", "breast", "thigh", "thighs", "drumstick",
    "drumsticks", "wing", "wings", "diced", "cube", "cubes", "chops",
    "chop", "cutlets", "cutlet", "roast", "kebab", "kebabs", "skewer",
    "skewers", "sausage", "sausages", "frankfurt", "frankfurts",
    "leg", "steak", "shoulder", "brisket", "rib", "ribs", "loin",
    "shanks", "shank", "neck", "necks", "curry", "stirfry", "sliced",
    "fillet", "fillets", "backstrap", "topside", "tender", "tenders",
    "strip", "strips", "maryland", "marylands", "burger", "burgers",
    "blade", "pieces", "piece", "bits", "bits"})
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
    # Plural-fold for the cut check ("necks" -> "neck", "thighs" ->
    # "thigh") — the local butchery vocabulary uses both forms.
    if any(w in MEAT_CUT_WORDS or (w.endswith("s") and w[:-1] in
                                   MEAT_CUT_WORDS)
           for w in words):
        return True
    # Bare protein head noun ("lamb", "goat") with no other food words
    return words <= MEAT_PROTEIN_WORDS
