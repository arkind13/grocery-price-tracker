"""Tests for core.halal (v2 slim surface — spec §5/§13).

The v2 rebuild keeps exactly: the meat-term query gate and the
butchery domain set. The tier-2 LLM chain, ledger IO, marker
writers, and the shopping-list gate are DELETED (their tests went
with them).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core import halal as hl


class TestMeatTerms(unittest.TestCase):
    """§14.12: meat-term query layer boundaries."""

    def test_meat_terms_positive(self):
        for term in ("beef mince", "chicken breast", "lamb chops",
                     "mutton", "goat leg", "meat", "whole bird",
                     "chicken drumsticks", "veal cutlets"):
            self.assertTrue(hl.is_meat_term(term), term)

    def test_prepared_food_excluded(self):
        for term in ("chicken salt", "chicken noodles",
                     "chicken soup", "beef stock",
                     "chicken flavoured chips",
                     "beef flavored noodles"):
            self.assertFalse(hl.is_meat_term(term), term)

    def test_word_boundaries_veal_frankfurt(self):
        """'Veal Frankfurt' IS a meat term; 'Reveal' is NOT."""
        self.assertTrue(hl.is_meat_term("Veal Frankfurt"))
        self.assertFalse(hl.is_meat_term("Reveal"))
        self.assertFalse(hl.is_meat_term("Uncovered"))

    def test_non_meat_queries(self):
        for term in ("tomato", "greek yoghurt", "paper towels", ""):
            self.assertFalse(hl.is_meat_term(term), term)


class TestButcheryDomain(unittest.TestCase):
    """The domain set survives — core.local_deals gates with it and
    the migration used it as the butchery sub-category authority."""

    def test_domain_set_contents(self):
        for label in ("beef mince", "chicken breast", "lamb & mutton",
                      "whole chicken", "processed meats"):
            self.assertIn(label, hl.HALAL_CHECK_CATEGORIES)

    def test_local_deals_domain_is_the_same_set(self):
        """local_deals.BUTCHERY_DOMAIN IS HALAL_CHECK_CATEGORIES —
        one domain authority, no drift."""
        from core.local_deals import BUTCHERY_DOMAIN
        self.assertIs(BUTCHERY_DOMAIN, hl.HALAL_CHECK_CATEGORIES)

    def test_tier2_chain_is_gone(self):
        """§13: the LLM chain symbols must not exist any more."""
        for gone in ("HALAL_CHECK_MODEL_CHAIN", "check_halal_via_llm",
                     "resolve_halal_item", "load_ledger", "save_ledger",
                     "halal_list_gate", "backfill_halal_checks",
                     "mark_halal_in_sheet", "is_halal_row",
                     "HALAL_LEDGER_PATH"):
            self.assertFalse(hasattr(hl, gone), gone)


if __name__ == "__main__":
    unittest.main()
