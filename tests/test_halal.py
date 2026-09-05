"""Offline tests for core/halal part 1 (spec §14.12-14.13).

Vocabulary, marker rules, scoped filters. Zero skips.
(Part 2: tier chain / LLM pipeline / P-flag rules land in S24.)
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


class TestScopeAndMarkers(unittest.TestCase):
    """§14.13: scope authority, marker detection, filters."""

    def test_scope_labels_mirror_domain_set(self):
        """HALAL_CHECK_CATEGORIES == local_deals.BUTCHERY_DOMAIN."""
        from core.local_deals import BUTCHERY_DOMAIN
        self.assertEqual(hl.HALAL_CHECK_CATEGORIES, BUTCHERY_DOMAIN)

    def test_halal_row_via_col_p(self):
        self.assertTrue(hl.is_halal_row("fresh|halal|family pack",
                                        "Beef Mince"))

    def test_halal_row_via_name(self):
        self.assertTrue(hl.is_halal_row("", "Halal Beef Mince"))
        self.assertTrue(hl.is_halal_row("", "Chicken Breast (halal)"))

    def test_manual_equals_llm_marker(self):
        """Marker origin is invisible: Col P token == name token."""
        self.assertEqual(
            hl.is_halal_row("halal", "Plain Name"),
            hl.is_halal_row("", "Halal Plain Name"))

    def test_non_marked_row_negative(self):
        self.assertFalse(hl.is_halal_row("fresh|family pack",
                                         "Beef Mince"))

    def test_filter_halal_rows(self):
        rows = [
            {"keywords": "halal", "name": "Beef Mince"},
            {"keywords": "fresh", "name": "Halal Lamb"},
            {"keywords": "fresh", "name": "Plain Chops"},
        ]
        kept = hl.filter_halal_rows(rows)
        self.assertEqual(len(kept), 2)

    def test_halal_search_suffix_idempotent(self):
        self.assertEqual(hl.halal_search_suffix("chicken breast"),
                         "halal chicken breast")
        self.assertEqual(
            hl.halal_search_suffix("halal chicken breast"),
            "halal chicken breast")


# ---------------------------------------------------------------------------
# Part 2 (S24): tier chain, LLM pipeline, P-flag rules (§14.14-14.16)
# ---------------------------------------------------------------------------
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.halal import (
    HalalResolution, HalalVerdict, backfill_halal_checks,
    check_halal_via_llm, resolve_halal_item,
)


def _verdict(verdict, confidence=0.95):
    """HalalVerdict helper."""
    return HalalVerdict(product="x", verdict=verdict,
                        confidence=confidence, evidence="e",
                        checked_at="2026-09-05", web_searched=True)


class _FakeSheet:
    """Minimal worksheet: header + Q/R/S/P rows (dict-backed)."""

    HEADER = ["Product_Name", "Size", "Keywords", "Sub_Category",
              "Item_Code", "Preferred"]

    def __init__(self, rows):
        self._rows = [list(self.HEADER)] + [list(r) for r in rows]

    def get_all_values(self):
        return [list(r) for r in self._rows]

    def update(self, *, values, range_name):
        """Single-cell write ('C2' or 'C2:C2')."""
        import re as _re
        m = _re.match(r"([A-Z]+)(\d+)(?::[A-Z]+\d+)?$", range_name)
        if m and values and isinstance(values[0], list):
            col = 0
            for ch in m.group(1):
                col = col * 26 + (ord(ch) - ord("A") + 1)
            row_i = int(m.group(2))
            self._rows[row_i - 1][col - 1] = values[0][0]
            return
        self._rows.append(list(values[0]))


class _TabSheet:
    """Local_Deals tab layout: 5 columns, no taxonomy column."""

    def __init__(self, rows):
        self._rows = [["Product", "Dunya Butchery",
                       "Merjan Brothers", "Fruitopia",
                       "Abu Salim"]] + [list(r) for r in rows]

    def get_all_values(self):
        return [list(r) for r in self._rows]


class TestTierChain(unittest.TestCase):
    """§14.15: 3-tier chain (mocked transports)."""

    def _engine(self, rows):
        from core.lookup import LookupEngine
        return LookupEngine(_FakeSheet(rows))

    def test_tier1_sheet_hit_no_live_call(self):
        """A halal sheet hit ends the chain: no LLM check, and the
        live-fill query carries NO halal prefix (chain never ran)."""
        rows = [
            ["Beef Mince", "500g", "", "beef mince", "BBB", ""],
        ]
        engine = self._engine(rows)
        with patch.object(engine, "_live_search_pair",
                          return_value=([], [], "ok")) as lsp, \
             patch("core.halal.check_halal_via_llm") as chk, \
             patch("core.lookup.LookupEngine", return_value=engine):
            res = resolve_halal_item("beef mince",
                                     worksheet=_FakeSheet(rows))
        chk.assert_not_called()
        # live-fill of the sheet result uses the PLAIN query — the
        # halal chain was never entered (tier 1 ended it).
        lsp.assert_called_once_with("beef mince")
        self.assertEqual(res.tier, 1)

    def test_tier2_live_query_carries_halal_prefix(self):
        """Chain mode live search carries the 'halal ' prefix."""
        rows = [
            ["Full Cream Milk", "3L", "", "", "", ""],
        ]
        engine = self._engine(rows)
        captured = {}

        def fake_pair(query):
            captured["q"] = query
            return [], [], "ok"

        with patch.object(engine, "_live_search_pair",
                          side_effect=fake_pair), \
             patch("core.halal.check_halal_via_llm"), \
             patch("core.lookup.LookupEngine", return_value=engine):
            resolve_halal_item("beef mince", worksheet=_FakeSheet(rows))
        self.assertTrue(captured.get("q", "").startswith("halal "))

    def test_tier2_single_confirmed_auto_adds_with_marker_and_P(self):
        """One confident halal live item -> sheet row + marker + P."""
        from core.lookup import LookupEngine, LookupResult, LookupStatus
        item = MagicMock()
        item.raw_name = "BrandX Halal Beef Mince 500g"
        item.brand = "BrandX"
        item.store = "woolworths"
        item.price = 9.5
        item.size = "500g"

        not_found = LookupResult(query="beef mince",
                                 status=LookupStatus.NOT_FOUND)
        live = LookupResult(query="beef mince",
                            status=LookupStatus.LIVE_SEARCH,
                            live_items=[item])
        engine = MagicMock()
        engine.find_product.side_effect = [not_found, live, not_found]

        with patch("core.halal.check_halal_via_llm",
                   return_value=_verdict("halal", 0.95)), \
             patch("core.lookup.LookupEngine", return_value=engine), \
             patch("core.sheets_sync.add_product_row",
                   return_value={"wrote": True,
                                 "row_index": 3}) as add, \
             patch("core.halal.query_local_butchers",
                   return_value=[]):
            res = resolve_halal_item("beef mince")
        add.assert_called_once()
        self.assertTrue(add.call_args.kwargs.get("halal_confirmed"))
        self.assertEqual(res.tier, 2)

    def test_tier2_ambiguous_returns_confirmation_list_no_write(self):
        """Two confirmed candidates -> NOTHING written, notes say so."""
        from core.lookup import LookupEngine, LookupResult, LookupStatus
        item_a, item_b = MagicMock(), MagicMock()
        for it, nm in ((item_a, "BrandA Halal Mince"),
                       (item_b, "BrandB Halal Mince")):
            it.raw_name = nm
            it.brand = nm.split()[0]
            it.store = "woolworths"
            it.price = 9.0
            it.size = "500g"
        not_found = LookupResult(query="beef mince",
                                 status=LookupStatus.NOT_FOUND)
        live = LookupResult(query="beef mince",
                            status=LookupStatus.LIVE_SEARCH,
                            live_items=[item_a, item_b])
        engine = MagicMock()
        engine.find_product.side_effect = [not_found, live]

        with patch("core.halal.check_halal_via_llm",
                   return_value=_verdict("halal", 0.95)), \
             patch("core.lookup.LookupEngine", return_value=engine), \
             patch("core.sheets_sync.add_product_row") as add:
            res = resolve_halal_item("beef mince")
        add.assert_not_called()
        self.assertTrue(any("multiple halal" in n for n in res.notes))

    def test_tier3_live_miss_reads_tab_butchery_line_format(self):
        """A live miss falls to the Local_Deals tab reader (line
        format per §12.1 rule 5 / plan §1.4.6)."""
        sheet = _FakeSheet([["Full Cream Milk", "3L", "", "", "", ""]])
        engine = self._engine(sheet._rows)
        tab = _TabSheet([
            ["Beef Diced /kg", "12.99", "", "", ""],
        ])
        with patch("core.lookup.LookupEngine", return_value=engine), \
             patch.object(engine, "_live_search_pair",
                          return_value=([], [], "ok")), \
             patch("core.sheets_client.connect_worksheet",
                   return_value=tab):
            res = resolve_halal_item("beef diced",
                                     worksheet=_FakeSheet([]))
        self.assertEqual(res.tier, 3)
        self.assertIn("Local butcher (halal)", res.butcher_line)
        self.assertIn("Beef Diced", res.butcher_line)

    def test_tier3_missing_tab_clean_unavailable_message(self):
        """No tab + no sheet + no live -> clean not-available line."""
        sheet = _FakeSheet([["Full Cream Milk", "3L", "", "", "", ""]])
        engine = self._engine(sheet._rows)
        with patch("core.lookup.LookupEngine", return_value=engine), \
             patch.object(engine, "_live_search_pair",
                          return_value=([], [], "ok")), \
             patch("core.sheets_client.connect_worksheet",
                   side_effect=RuntimeError("no sheet")):
            res = resolve_halal_item("goat leg",
                                     worksheet=_FakeSheet([]))
        self.assertIn("not available this week", res.butcher_line)

    def test_non_meat_never_enters_chain(self):
        """Non-meat queries never dispatch to resolve_halal_item."""
        from core.lookup import LookupEngine
        ws = _FakeSheet([["Full Cream Milk", "3L", "", "", "", ""]])
        with patch("core.halal.resolve_halal_item") as rh:
            engine = LookupEngine(ws)
            with patch.object(engine, "_live_search_pair",
                              return_value=([], [], "ok")):
                engine.find_product("greek yoghurt",
                                    interactive=False)
        rh.assert_not_called()

    def test_tier3_butchery_reader_domain_only(self):
        """Local_Deals reader answers ONLY BUTCHERY-domain rows —
        nuggets/prepared never answer (§8.4)."""
        tab = _TabSheet([
            ["Beef Diced /kg", "12.99", "", "", ""],
            ["Chicken Nuggets", "", "8.50", "", ""],
        ])
        with patch("core.sheets_client.connect_worksheet",
                   return_value=tab):
            from core.halal import query_local_butchers
            hits = query_local_butchers("beef diced")
            self.assertEqual(len(hits), 1)
            self.assertIn("Beef Diced", hits[0]["item"])
            self.assertEqual(query_local_butchers("chicken nuggets"),
                             [])


class TestLLMPipeline(unittest.TestCase):
    """§14.16: verdict parsing, chain order, write policy, ledger."""

    def _ledger_path(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "ledger.json"

    def test_verdict_strict_json_parse(self):
        content = json_dumps({"verdict": "halal", "confidence": 0.9,
                              "evidence": "certified",
                              "brand_line": "BrandX / HFA"})
        data = hl._parse_verdict(content)
        self.assertEqual(data["verdict"], "halal")

    def test_prose_wrapped_verdict_rescued(self):
        content = ("Sure! " + json_dumps(
            {"verdict": "non_halal", "confidence": 0.8,
             "evidence": "gelatine", "brand_line": "x"})
            + " hope that helps")
        data = hl._parse_verdict(content)
        self.assertEqual(data["verdict"], "non_halal")

    def test_model_chain_order_glm_then_gemini(self):
        """Chain order is glm-:online then gemini-:online."""
        calls = []
        with patch("core.halal._openrouter_chat",
                   side_effect=lambda model, prompt, max_tokens=700:
                   calls.append(model) or (_ for _ in ()).throw(
                       RuntimeError("down"))), \
             patch("core.halal.load_ledger", return_value={}), \
             patch("core.halal.save_ledger"):
            v = check_halal_via_llm("Beef Mince X",
                                    path=None) if False else \
                check_halal_via_llm("Beef Mince X")
        self.assertEqual(calls[0], "z-ai/glm-5.3-flash:online")
        self.assertEqual(calls[1], "google/gemini-2.5-flash:online")
        self.assertEqual(v.verdict, "uncertain")

    def test_confident_halal_writes_col_p_and_aligns_P(self):
        """Backfill: confident halal -> marker + set_preferred."""
        ws = _FakeSheet([
            ["Woolworths Beef Mince 1kg", "1kg", "", "beef mince",
             "AAA", ""],
        ])
        with patch("core.halal.check_halal_via_llm",
                   return_value=_verdict("halal", 0.95)), \
             patch("core.halal.load_ledger", return_value={}), \
             patch("core.halal.save_ledger"), \
             patch("core.preferences.set_preferred",
                   return_value={"wrote": True}) as sp:
            report = backfill_halal_checks(ws)
        self.assertEqual(report["marked"], 1)
        sp.assert_called_once()
        updated = ws.get_all_values()
        self.assertIn("halal", updated[1][2].split("|"))

    def test_non_halal_ledger_only_no_sheet_write(self):
        ws = _FakeSheet([
            ["Woolworths Beef Mince 1kg", "1kg", "", "beef mince",
             "AAA", ""],
        ])
        with patch("core.halal.check_halal_via_llm",
                   return_value=_verdict("non_halal", 0.9)), \
             patch("core.halal.load_ledger", return_value={}), \
             patch("core.halal.save_ledger"), \
             patch("core.preferences.set_preferred") as sp:
            report = backfill_halal_checks(ws)
        self.assertEqual(report["excluded"], 1)
        self.assertEqual(report["marked"], 0)
        sp.assert_not_called()
        self.assertEqual(len(ws.get_all_values()), 2)

    def test_uncertain_ledger_only(self):
        ws = _FakeSheet([
            ["Woolworths Beef Mince 1kg", "1kg", "", "beef mince",
             "AAA", ""],
        ])
        with patch("core.halal.check_halal_via_llm",
                   return_value=_verdict("uncertain", 0.2)), \
             patch("core.halal.load_ledger", return_value={}), \
             patch("core.halal.save_ledger"), \
             patch("core.preferences.set_preferred") as sp:
            report = backfill_halal_checks(ws)
        self.assertEqual(report["deferred"], 1)
        sp.assert_not_called()

    def test_ledger_cache_hit_no_second_call(self):
        """A fresh ledger verdict short-circuits the LLM call."""
        ledger_path = self._ledger_path()
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(json_dumps({
            "beef mince": {
                "verdict": "halal", "confidence": 0.95,
                "evidence": "cert", "checked_at": "2026-09-01",
                "web_searched": True, "brand_line": "",
                "product": "x"}}),
            encoding="utf-8")
        with patch.object(hl, "HALAL_LEDGER_PATH", ledger_path), \
             patch("core.halal._openrouter_chat") as chat:
            v = check_halal_via_llm("Beef Mince")
        chat.assert_not_called()
        self.assertEqual(v.verdict, "halal")

    def test_ttl_expiry_rechecks(self):
        """A stale (90-day+) verdict is re-checked."""
        ledger_path = self._ledger_path()
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(json_dumps({
            "beef mince": {
                "verdict": "halal", "confidence": 0.95,
                "evidence": "cert", "checked_at": "2026-01-01",
                "web_searched": True, "brand_line": "",
                "product": "x"}}),
            encoding="utf-8")
        with patch.object(hl, "HALAL_LEDGER_PATH", ledger_path), \
             patch("core.halal._openrouter_chat",
                   return_value=json_dumps(
                       {"verdict": "non_halal", "confidence": 0.9,
                        "evidence": "gelatine",
                        "brand_line": "x"})), \
             patch("core.halal.save_ledger"):
            v = check_halal_via_llm("Beef Mince")
        self.assertEqual(v.verdict, "non_halal")

    def test_per_run_cap_defers_remaining(self):
        """HALAL_CHECK_MAX_PER_RUN bounds the sweep; the rest defer."""
        rows = [
            [f"Beef Mince Brand{i}", "500g", "", "beef mince",
             f"B0{i}", ""] for i in range(25)
        ]
        ws = _FakeSheet(rows)
        calls = []

        def fake_check(name, brand="", force=False):
            calls.append(name)
            return _verdict("halal", 0.95)

        with patch("core.halal.check_halal_via_llm",
                   side_effect=fake_check), \
             patch("core.halal.load_ledger", return_value={}), \
             patch("core.halal.save_ledger"), \
             patch("core.preferences.set_preferred",
                   return_value={"wrote": True}), \
             patch("core.halal.mark_halal_in_sheet",
                   return_value="P2:P2"):
            report = backfill_halal_checks(ws)
        self.assertEqual(len(calls), 20)
        self.assertEqual(report["checked"], 20)

    def test_no_web_fallback_uncertain_only(self):
        """Both model attempts fail -> verdict is 'uncertain'."""
        with patch("core.halal._openrouter_chat",
                   side_effect=RuntimeError("down")), \
             patch("core.halal.load_ledger", return_value={}), \
             patch("core.halal.save_ledger"):
            v = check_halal_via_llm("Beef Mince X")
        self.assertEqual(v.verdict, "uncertain")
        self.assertFalse(v.web_searched)

    def test_yoghurt_never_reaches_llm_check(self):
        """Yoghurt is outside the auto scope -> zero LLM calls."""
        ws = _FakeSheet([
            ["Greek Yoghurt", "1kg", "", "greek yoghurt", "GHI", ""],
        ])
        with patch("core.halal.check_halal_via_llm") as chk:
            from core.halal import halal_list_gate
            gate = halal_list_gate(ws, ["Greek Yoghurt"])
        chk.assert_not_called()
        self.assertIn("Greek Yoghurt", gate["included"])

    def test_frozen_snacks_ready_meals_produce_never_reach_llm_check(
            self):
        """Frozen snacks / ready meals / produce never hit the LLM."""
        ws = _FakeSheet([
            ["Chicken Nuggets", "500g", "", "frozen snacks",
             "NUG", ""],
            ["Ready Meal Lasagna", "400g", "", "ready meals",
             "RDY", ""],
            ["Bananas", "kg", "", "bananas", "BAN", ""],
        ])
        with patch("core.halal.check_halal_via_llm") as chk:
            from core.halal import halal_list_gate
            gate = halal_list_gate(
                ws, ["Chicken Nuggets", "Ready Meal Lasagna",
                     "Bananas"])
        chk.assert_not_called()
        self.assertEqual(len(gate["included"]), 3)


def json_dumps(obj):
    """json.dumps alias so tests stay terse."""
    import json as _json
    return _json.dumps(obj)


if __name__ == "__main__":
    unittest.main()
