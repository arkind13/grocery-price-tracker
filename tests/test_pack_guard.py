"""Pack-deal guard regressions — the recurring Merjan min-buy defect.

Pinned on the REAL boards (open-fix #0, closed 2026-09-27):
  - 2026-09-11 Merjan boards: 14 pack-total-in-per-kg cells, values
    user-verified in data/test_logs/cycle-3/merjan-corrections.md
    ("2 KG LAMB MINCE $29.99" -> 15.00/kg, "5 KG BEEF CURRY $49.99"
    -> 10.00/kg, ...).
  - 2026-09-26/27 Merjan weekend board (both posts share one image,
    md5 761f9177263581ad2fec2fb3fb8089f8): the vision pass typed all
    20 weighted tiles as plain per-kg singles ("Halal Beef Curry /kg
    — $49.99/kg" posted) — the model flip-flops between runs on the
    SAME image, so the guard re-derives bundle semantics from the
    verbatim raw_text instead of trusting price_kind.
  - no-op pins: explicit per-kg captions, Fruitopia text boards,
    numbered product names ("4 STAR BEEF"), bucket deals.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from extractors.deal_text import (
    normalise_pack_deal, normalise_pack_deals, parse_fruitopia_deals,
)
from core import flyer_vision as ffv


def _tile(item, raw, price, unit="kg", kind="single", qty=None,
          bulk=None, notes=""):
    """One vision-schema deal exactly as the model classifies it."""
    return {"item": item, "raw_text": raw, "price": price,
            "unit": unit, "price_kind": kind, "multibuy_qty": qty,
            "bulk_size": bulk, "category": "butchery", "notes": notes}


# The 2026-09-27 board as the failing morning run classified it:
# every tile a plain per-kg single (bundle totals as rates).
SEP27_BAD_TILES = [
    _tile("Thigh Fillet", "2KG THIGH FILLET $21.99", 21.99),
    _tile("Beef Curry (Bone In)",
          "5KG BEEF CURRY (BONE IN) $49.99", 49.99),
    _tile("Goat Curry (Bone In)",
          "2KG GOAT CURRY (BONE IN) $29.99", 29.99),
    _tile("Chicken Breast", "5KG CHICKEN BREAST $34.99", 34.99),
    _tile("Chicken Wings", "5KG CHICKEN WINGS $19.99", 19.99),
    _tile("Chicken Drumettes", "2KG CHICKEN DRUMETTES $19.99", 19.99),
    _tile("Chicken Drumsticks",
          "5KG CHICKEN DRUMSTICKS $19.99", 19.99),
    _tile("Mid Wings", "2KG MID WINGS $17.99", 17.99),
    _tile("Chicken Tenderloins",
          "3KG CHICKEN TENDERLOINS $32.99", 32.99),
    _tile("Sausages", "2KG SAUSAGES $29.99", 29.99),
    _tile("Lamb Mince", "2KG LAMB MINCE $29.99", 29.99),
    _tile("Chicken Mince", "2KG CHICKEN MINCE $17.99", 17.99),
    _tile("BBQ Blade Steak", "2KG BBQ BLADE STEAK $33.99", 33.99),
    _tile("Lamb Grilling Chops",
          "2KG LAMB GRILLING CHOPS $33.99", 33.99),
    _tile("Lamb Ribs", "2KG LAMB RIBS $29.99", 29.99),
    _tile("Lamb Necks", "2KG LAMB NECKS $29.99", 29.99),
    _tile("Flavoured Sausages",
          "2KG FLAVOURED SAUSAGES $29.99", 29.99),
    _tile("Chicken Maryland",
          "5KG CHICKEN MARYLAND $34.99", 34.99),
]

# (deal, expected qty) — per-kg rates come out of _cell_for's single
# effective_unit_rate division; the guard only fixes the SEMANTICS.
SEP27_EXPECT_QTY = [
    ("Thigh Fillet", 2), ("Beef Curry (Bone In)", 5),
    ("Goat Curry (Bone In)", 2), ("Chicken Breast", 5),
    ("Chicken Wings", 5), ("Chicken Drumettes", 2),
    ("Chicken Drumsticks", 5), ("Mid Wings", 2),
    ("Chicken Tenderloins", 3), ("Sausages", 2),
    ("Lamb Mince", 2), ("Chicken Mince", 2), ("BBQ Blade Steak", 2),
    ("Lamb Grilling Chops", 2), ("Lamb Ribs", 2), ("Lamb Necks", 2),
    ("Flavoured Sausages", 2), ("Chicken Maryland", 5),
]


class TestGuardOnRealBoards(unittest.TestCase):
    """quantity-prefix tiles -> multibuy with the bundle total."""

    def test_sep27_board_all_weighted_tiles_become_multibuy(self):
        for (name, qty), deal in zip(SEP27_EXPECT_QTY,
                                     SEP27_BAD_TILES):
            r = normalise_pack_deal(dict(deal))
            self.assertEqual(r["price_kind"], "multibuy", name)
            self.assertEqual(r["multibuy_qty"], qty, name)
            self.assertEqual(r["unit"], "kg", name)
            self.assertEqual(r["price"], deal["price"],
                             f"{name}: bundle total must not change")

    def test_sep27_known_per_kg_rates_match_hand_corrections(self):
        """The four rates the user verified by hand on the SAME board
        family (2026-09-11 corrections doc): beef curry 10.00/kg,
        chicken wings/drumsticks 4.00/kg, thigh fillet ~11.00/kg."""
        from core.multibuy import effective_unit_rate
        rates = {}
        for deal in SEP27_BAD_TILES:
            r = normalise_pack_deal(dict(deal))
            rates[r["item"]] = effective_unit_rate(
                r["multibuy_qty"], r["price"])
        self.assertAlmostEqual(rates["Beef Curry (Bone In)"],
                               10.00, places=2)
        self.assertAlmostEqual(rates["Chicken Wings"], 4.00, places=2)
        self.assertAlmostEqual(rates["Chicken Drumsticks"], 4.00,
                               places=2)
        self.assertAlmostEqual(rates["Thigh Fillet"], 11.00, places=0)

    def test_sep11_multiline_stylised_tile(self):
        """The Sep-11 boards printed tiles across lines
        ('2 KG / LAMB MINCE / $29.99') — the prefix still matches."""
        r = normalise_pack_deal(_tile(
            "Lamb Mince", "2 KG / LAMB MINCE / $29.99", 29.99))
        self.assertEqual((r["price_kind"], r["multibuy_qty"]),
                         ("multibuy", 2))

    def test_counted_bird_bundle_2_steamer_chickens(self):
        """'2 STEAMER CHICKENS $11.99' — 2 birds for $11.99 ($6.00/ea),
        never $11.99/ea (the 2026-09-27 digest error)."""
        r = normalise_pack_deal(_tile(
            "Steamer Chickens", "2 STEAMER CHICKENS $11.99",
            11.99, unit="ea"))
        self.assertEqual(r["price_kind"], "multibuy")
        self.assertEqual(r["multibuy_qty"], 2)
        self.assertEqual(r["unit"], "ea")

    def test_whole_chicken_min_weight_is_size_spec_not_bundle(self):
        """'(MIN 1.9KG)' on a per-bird item is a bird size — the
        price stays per-ea and the weight rides notes."""
        r = normalise_pack_deal(_tile(
            "Whole Chicken", "WHOLE CHICKEN (MIN 1.9KG) $34.99",
            34.99, unit="ea"))
        self.assertEqual(r["price_kind"], "single")
        self.assertEqual(r["unit"], "ea")
        self.assertEqual(r["price"], 34.99)
        self.assertIn("min 1.9kg", r["notes"])

    def test_min_weight_on_weighted_meat_is_bundle(self):
        """'min 2kg' phrasing on a /kg deal (the vision prompt's own
        rule) — the guard agrees even when the model doesn't."""
        r = normalise_pack_deal(_tile(
            "Beef Cube", "BEEF CUBE min 2kg $25.00", 25.00))
        self.assertEqual((r["price_kind"], r["multibuy_qty"]),
                         ("multibuy", 2))

    def test_fractional_weight_becomes_bulk_pack(self):
        """1.9 is not an integer >= 2 — schema-honest bulk_pack."""
        r = normalise_pack_deal(_tile(
            "Beef Cube", "1.9KG BEEF CUBE $25.00", 25.00))
        self.assertEqual(r["price_kind"], "bulk_pack")
        self.assertEqual(r["bulk_size"], "1.9kg")
        self.assertIsNone(r["multibuy_qty"])

    def test_counted_for_form_after_name(self):
        """Sep-11 whole-chicken wording: 'WHOLE CHICKEN 5 FOR $34.99'
        -> 5 birds for $34.99."""
        r = normalise_pack_deal(_tile(
            "Whole Chicken", "WHOLE CHICKEN 5 FOR $34.99",
            34.99, unit="ea"))
        self.assertEqual((r["price_kind"], r["multibuy_qty"]),
                         ("multibuy", 5))


class TestGuardNoOps(unittest.TestCase):
    """Lines the guard must NEVER touch (regression pins)."""

    def test_explicit_per_kg_caption_untouched(self):
        """The Dunya caption deal (2026-09-13): 'per kg' marker means
        the price IS the rate, condition stays in notes."""
        deal = _tile("Beef Sirloin",
                     "Beef Sirloin - only $24.99 per kg when you buy "
                     "the whole slab!", 24.99,
                     notes="when you buy the whole slab")
        r = normalise_pack_deal(dict(deal))
        self.assertEqual(r["price_kind"], "single")
        self.assertEqual(r["price"], 24.99)

    def test_numbered_product_name_not_a_bundle(self):
        """'4 STAR BEEF' is a grade, never '4 for $30'."""
        r = normalise_pack_deal(_tile(
            "4 Star Beef", "4 STAR BEEF $30.00", 30.00, unit="ea"))
        self.assertEqual(r["price_kind"], "single")
        self.assertEqual(r["item"], "4 Star Beef")

    def test_plain_fruit_line_untouched(self):
        r = normalise_pack_deal(_tile(
            "Tomatoes", "🍅 Tomatoes – $2.99", 2.99, unit="ea"))
        self.assertEqual(r["price_kind"], "single")

    def test_already_multibuy_untouched(self):
        deal = _tile("Wings", "5KG CHICKEN WINGS $19.99", 19.99,
                     kind="multibuy", qty=5)
        r = normalise_pack_deal(dict(deal))
        self.assertEqual(r["price_kind"], "multibuy")
        self.assertEqual(r["multibuy_qty"], 5)

    def test_unit_word_item_not_count_bundle(self):
        """Item that IS a unit word ('bucket', 'pack') never starts a
        counted-bundle strip."""
        r = normalise_pack_deal(_tile(
            "Bucket", "2 BUCKET $49.99", 49.99, unit="ea"))
        self.assertEqual(r["price_kind"], "single")

    def test_fruitopia_text_board_unchanged_through_guard(self):
        """The pinned Fruitopia anniversary post parses identically
        before and after the guard (text path shares it via
        _to_vision_deal)."""
        from core.local_deals import _to_vision_deal
        text = ("📅 Saturday & Sunday, 5 & 6 September\n"
                "🍎 Apples – $2.99/kg\n"
                "🥦 Broccoli – 99¢ each\n"
                "🥛 Milk – 2 for $5.00\n")
        deals = parse_fruitopia_deals(text)
        converted = [_to_vision_deal(d, "fruits") for d in deals]
        self.assertEqual(len(converted), 3)
        self.assertEqual(converted[0]["price"], 2.99)
        self.assertEqual(converted[1]["price"], 0.99)
        self.assertEqual(converted[2]["price_kind"], "multibuy")
        self.assertEqual(converted[2]["multibuy_qty"], 2)

    def test_quantity_prefix_text_line_becomes_bundle(self):
        """A TEXT post in the Merjan layout gets the same maths."""
        from core.local_deals import _to_vision_deal
        deals = parse_fruitopia_deals(
            "2 KG THIGH FILLET – $21.99\n")
        self.assertEqual(len(deals), 1)
        r = _to_vision_deal(deals[0], "butchery")
        self.assertEqual((r["price_kind"], r["multibuy_qty"],
                          r["unit"]), ("multibuy", 2, "kg"))
        self.assertEqual(r["item"], "THIGH FILLET")


class TestSchemaAdapterPassthrough(unittest.TestCase):
    """THE 2026-09-27 wiring defect: vision-schema deals were pushed
    through _to_vision_deal's TEXT branch (whose 'multibuy' key they
    never carry) — price_kind overwritten to single, multibuy_qty
    dropped, raw_text replaced by the bare item name. Correct vision
    parses STILL landed in the sheet as pack totals. Pinned here."""

    def test_vision_multibuy_deal_surives_adapter(self):
        from core.local_deals import _to_vision_deal
        deal = _tile("Thigh Fillet",
                     "2KG THIGH FILLET $21.99", 21.99,
                     kind="multibuy", qty=2)
        r = _to_vision_deal(deal, "butchery")
        self.assertEqual(r["price_kind"], "multibuy")
        self.assertEqual(r["multibuy_qty"], 2)
        self.assertEqual(r["raw_text"], "2KG THIGH FILLET $21.99")

    def test_vision_single_deal_survives_adapter(self):
        from core.local_deals import _to_vision_deal
        r = _to_vision_deal(
            _tile("Whole Chicken",
                  "WHOLE CHICKEN (MIN 1.9KG) $34.99", 34.99,
                  unit="ea"), "butchery")
        self.assertEqual(r["price_kind"], "single")
        self.assertEqual(r["unit"], "ea")
        self.assertIn("min 1.9kg", r["notes"])

    def test_cell_for_through_adapter_writes_the_rate(self):
        """The exact sheet defect: 21.99 (pack total) in the cell —
        through the fixed adapter the cell is the per-kg rate."""
        from core.local_deals import _to_vision_deal, _cell_for
        r = _to_vision_deal(
            _tile("Beef Curry (Bone In)",
                  "5KG BEEF CURRY (BONE IN) $49.99", 49.99,
                  kind="multibuy", qty=5), "butchery")
        cell, comment = _cell_for(r)
        self.assertEqual(cell, 10.0)
        self.assertEqual(comment, "multi buy 5kg for $49.99")


class TestCellAndDigestIntegration(unittest.TestCase):
    """The corrected deal flows through the REAL cell writer and the
    REAL digest renderer (the exact posted line changes)."""

    def test_cell_for_corrected_thigh_fillet(self):
        from core.local_deals import _cell_for
        r = normalise_pack_deal(dict(SEP27_BAD_TILES[0]))
        cell, comment = _cell_for(r)
        self.assertEqual(cell, 10.99)    # 21.99 / 2 — NOT 21.99
        self.assertEqual(comment,
                         "multi buy 2kg for $21.99")

    def test_digest_line_shows_min_order_terms(self):
        from core.local_deals import _digest_items, _to_vision_deal
        converted = normalise_pack_deals(
            [_to_vision_deal(d, "butchery")
             for d in parse_fruitopia_deals(
                 "2 KG THIGH FILLET – $21.99\n")])
        items = _digest_items(converted)
        self.assertEqual(items[0]["price_text"], "$10.99/kg")
        self.assertEqual(items[0]["terms"], "2kg for $21.99")
        self.assertAlmostEqual(items[0]["per_kg"], 10.99)

    def test_digest_render_window_line(self):
        from core.local_deals import _render_window_digest
        msg = _render_window_digest(
            [{"shop": "Merjan Brothers Quality Meats",
              "shop_label": "Merjan",
              "posts": [{"code": "MER2709260507",
                         "file": "fb:122191227128942477",
                         "items": [
                             {"name": "Halal Thigh Fillet /kg",
                              "price_text": "$11.00/kg",
                              "terms": "2kg for $21.99",
                              "per_kg": 11.0},
                             {"name": "Halal Beef Curry /kg",
                              "price_text": "$10.00/kg",
                              "terms": "5kg for $49.99",
                              "per_kg": 10.0}]}]}],
            [], "test window")
        self.assertIn(
            "• Halal Thigh Fillet /kg — $11.00/kg "
            "(min order 2kg for $21.99)", msg[0])
        self.assertIn(
            "• Halal Beef Curry /kg — $10.00/kg "
            "(min order 5kg for $49.99)", msg[0])
        self.assertIn("2 with min-order deals", msg[0])

    def test_digest_review_flag_renders(self):
        from core.local_deals import _render_window_digest
        msg = _render_window_digest(
            [{"shop": "Merjan", "shop_label": "Merjan",
              "posts": [{"code": "M", "items": [
                  {"name": "X /kg", "price_text": "$5.00/kg",
                   "review_flag": "verify: tile says 3kg"}]}]}],
            [], "t")
        self.assertIn("⚠ verify: tile says 3kg", msg[0])

    def test_size_spec_renders_without_min_order_wrapper(self):
        from core.local_deals import _digest_items
        r = normalise_pack_deal(_tile(
            "Whole Chicken", "WHOLE CHICKEN (MIN 1.9KG) $34.99",
            34.99, unit="ea"))
        items = _digest_items([r])
        self.assertEqual(items[0]["price_text"], "$34.99/ea")
        self.assertEqual(items[0]["terms"], "min 1.9kg")


class TestBucketDowngrade(unittest.TestCase):
    """bulk_size without a weight ('bucket') used to DROP the deal
    (the 2026-09-27 Povi Masima $49.99 line vanished). Now it
    downgrades to single/ea with the word in notes."""

    def test_bucket_bulk_pack_downgraded_not_dropped(self):
        deal = _tile("Povi Masima", "POVI MASIMA BUCKET $49.99",
                     49.99, unit="ea", kind="bulk_pack",
                     bulk="bucket")
        deals, errs = ffv.validate_payload({"deals": [deal]})
        self.assertEqual(len(deals), 1)
        self.assertEqual(deal["price_kind"], "single")
        self.assertEqual(deal["unit"], "ea")
        self.assertEqual(deal["notes"], "bucket")
        self.assertFalse(any("needs a parseable" in e for e in errs))

    def test_kg_bulk_pack_still_normalised(self):
        deal = _tile("Box", "10KG BOX $89.90", 89.90, kind="bulk_pack",
                     bulk="10kg BOX")
        deals, errs = ffv.validate_payload({"deals": [deal]})
        self.assertEqual(deal["bulk_size"], "10kg")
        self.assertEqual(deal["price_kind"], "bulk_pack")


def _fake_model_reply(payload_deals, lines=None):
    """(first_call, verify_call) model contents for the pipeline."""
    first = json_dumps({"valid_until": None, "deals": payload_deals})
    verify = json_dumps({"lines": lines or []})
    return first, verify


def json_dumps(obj):
    import json as _json
    return _json.dumps(obj, ensure_ascii=False)


class TestPipelineEndToEnd(unittest.TestCase):
    """The full parse_board_images chain with the model MOCKED to the
    REAL failure shapes observed live on 2026-09-27: the classify
    step flips single/multibuy between runs AND sometimes drops the
    printed quantity from raw_text altogether. The pipeline (guard +
    temperature-0 transcription re-read) must come out correct for
    every observed shape."""

    def _run(self, first_deals, lines):
        import core.flyer_vision as ffv2
        from pathlib import Path
        first, verify = _fake_model_reply(first_deals, lines)

        def fake_call(entry, prompt, files):
            assert isinstance(files, list) and files
            assert entry is ffv2.MODEL_CHAIN[0] or True
            return ((first if "Transcribe EVERY price line"
                     not in prompt else verify),
                    {"total_tokens": 100, "finish_reason": "stop"})

        with patch.object(ffv2, "_call_model", side_effect=fake_call),                 patch.object(ffv2, "_log_payload"):
            payload = ffv2.parse_board_images([Path("x.jpg")])
        return payload

    def test_qty_in_raw_text_guard_fixes_without_reliance_on_verify(self):
        """Run-shape A: raw_text carries the tile text but the
        classify step typed single — the guard alone fixes it."""
        payload = self._run(
            [dict(d) for d in SEP27_BAD_TILES[:3]],
            lines=["2KG THIGH FILLET $21.99",
                   "5KG BEEF CURRY (BONE IN) $49.99",
                   "2KG GOAT CURRY (BONE IN) $29.99"])
        for d, (name, qty) in zip(payload["deals"],
                                  SEP27_EXPECT_QTY[:3]):
            self.assertEqual(d["price_kind"], "multibuy", name)
            self.assertEqual(d["multibuy_qty"], qty, name)
            self.assertFalse(d.get("review_flag"), name)

    def test_qty_dropped_from_raw_text_re_read_recovers(self):
        """Run-shape B (the live VPS failure): raw_text LOST the
        quantity and the deal reads single — the transcription
        re-read finds it, the guard maths applies, the line is
        flagged transparently."""
        stripped = [
            _tile("Thigh Fillet", "THIGH FILLET $21.99", 21.99),
            _tile("Beef Curry (Bone In)",
                  "BEEF CURRY (BONE IN) $49.99", 49.99),
        ]
        payload = self._run(
            stripped,
            lines=["2 KG THIGH FILLET $21.99",
                   "5 KG BEEF CURRY (BONE IN) $49.99"])
        deals = payload["deals"]
        self.assertEqual(deals[0]["price_kind"], "multibuy")
        self.assertEqual(deals[0]["multibuy_qty"], 2)
        self.assertEqual(deals[1]["multibuy_qty"], 5)
        self.assertIn("re-read: 2 KG THIGH FILLET",
                      deals[0]["review_flag"])

    def test_multibuy_qty_disagreement_flagged(self):
        """Already-multibuy deal whose re-read quantity differs is
        flagged for the user, never silently changed."""
        deal = _tile("Thigh Fillet", "3KG THIGH FILLET $21.99",
                     21.99, kind="multibuy", qty=3)
        payload = self._run(
            [deal], lines=["2KG THIGH FILLET $21.99"])
        d = payload["deals"][0]
        self.assertEqual(d["multibuy_qty"], 3)   # unchanged
        self.assertIn("check qty", d["review_flag"])

    def test_verifier_failure_never_blocks(self):
        """Verifier down (network/JSON) — the guarded values post."""
        import core.flyer_vision as ffv2
        from pathlib import Path
        bad = [dict(SEP27_BAD_TILES[0])]
        first, _ = _fake_model_reply(bad)

        def fake_call(entry, prompt, files):
            if "Transcribe EVERY price line" in prompt:
                raise RuntimeError("HTTP 500: ***MASKED***")
            return first, {"total_tokens": 1,
                           "finish_reason": "stop"}

        with patch.object(ffv2, "_call_model", side_effect=fake_call),                 patch.object(ffv2, "_log_payload"):
            payload = ffv2.parse_board_images([Path("x.jpg")])
        self.assertEqual(payload["deals"][0]["multibuy_qty"], 2)


if __name__ == "__main__":
    unittest.main()
