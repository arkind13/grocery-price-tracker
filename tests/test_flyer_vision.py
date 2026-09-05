"""Offline tests for core/flyer_vision (spec §14.3).

Mocks core.flyer_vision._call_model (unit) and requests.post
(transport). Zero skips.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

import pytest

from core import flyer_vision as ffv


def _good_deal(item="Beef Diced", price=12.99, unit="kg",
               kind="single", qty=None, bulk=None,
               category="butchery"):
    """One schema-valid deal dict."""
    return {"item": item, "raw_text": f"{item} ${price}",
            "price": price, "unit": unit, "price_kind": kind,
            "multibuy_qty": qty, "bulk_size": bulk, "notes": "",
            "category": category}


class TestValidator(unittest.TestCase):
    """Schema validation classes (sandbox test2 11/11 port)."""

    def test_bulk_labelled_single_rejected(self):
        """single + bulk_size is the critical isolation failure."""
        deals, errs = ffv.validate_payload(
            {"deals": [_good_deal(item="Bulk Box", price=89.90,
                                  unit="pack", bulk="10kg")]})
        self.assertEqual(deals, [])
        self.assertTrue(any("single deal carries bulk_size" in e
                            for e in errs))

    def test_bulk_size_without_kg_token_rejected(self):
        """bulk_pack size with no kg/g token is a hard error."""
        _deals, errs = ffv.validate_payload(
            {"deals": [_good_deal(item="Mystery Box", price=20.0,
                                  unit="pack", kind="bulk_pack",
                                  bulk="BIG BOX")]})
        self.assertTrue(any("needs a parseable" in e for e in errs))

    def test_bulk_size_normalised_10kg_box_to_10kg(self):
        """'10kg BOX' is rescued and cleaned to '10kg'."""
        deal = _good_deal(item="Bulk Box", price=89.90, unit="pack",
                          kind="bulk_pack", bulk="10kg BOX")
        deals, errs = ffv.validate_payload({"deals": [deal]})
        self.assertEqual(errs, [])
        self.assertEqual(deal["bulk_size"], "10kg")
        self.assertEqual(len(deals), 1)

    def test_multibuy_qty_below_2_rejected(self):
        """multibuy qty=1 violates the >=2 rule."""
        _deals, errs = ffv.validate_payload(
            {"deals": [_good_deal(item="Sausages", price=15.0,
                                  unit="pack", kind="multibuy",
                                  qty=1)]})
        self.assertTrue(any("integer qty >= 2" in e for e in errs))

    def test_string_price_rejected(self):
        """price as string is rejected (would poison maths)."""
        deal = _good_deal()
        deal["price"] = "12.99"
        _deals, errs = ffv.validate_payload({"deals": [deal]})
        self.assertTrue(any("price must be a number" in e
                            for e in errs))

    def test_zero_price_rejected(self):
        """price must be > 0."""
        deal = _good_deal(price=0)
        _deals, errs = ffv.validate_payload({"deals": [deal]})
        self.assertTrue(any("price must be > 0" in e for e in errs))

    def test_bad_unit_rejected(self):
        """unit outside the enum is rejected."""
        deal = _good_deal()
        deal["unit"] = "litre"
        _deals, errs = ffv.validate_payload({"deals": [deal]})
        self.assertTrue(any("unit 'litre' not in" in e for e in errs))

    def test_date_and_category_enums_validated(self):
        """Bad valid_until and bad category both surface errors."""
        payload = {"valid_until": "11/09/2026", "validity_text": "x",
                   "deals": [_good_deal()]}
        _deals, errs = ffv.validate_payload(payload)
        self.assertTrue(any("valid_until must be null" in e
                            for e in errs))
        deal = _good_deal()
        deal["category"] = "dairy"
        _deals, errs = ffv.validate_payload({"deals": [deal]})
        self.assertTrue(any("category 'dairy' not in" in e
                            for e in errs))

    def test_clean_reply_parses_untouched(self):
        """A clean payload passes with zero errors."""
        deals, errs = ffv.validate_payload(
            {"deals": [_good_deal(), _good_deal(item="Apples",
                                                category="fruits")]})
        self.assertEqual(errs, [])
        self.assertEqual(len(deals), 2)


class TestExtractionSalvage(unittest.TestCase):
    """extract_json + salvage_truncated_json."""

    def test_prose_wrapped_json_rescued(self):
        """Prose WITH valid JSON inside is legitimately rescued."""
        good = json.dumps({"deals": [_good_deal()]})
        payload = ffv.extract_json(
            "Here is the JSON you asked for: " + good)
        deals, errs = ffv.validate_payload(payload)
        self.assertEqual(errs, [])
        self.assertEqual(len(deals), 1)

    def test_clean_prose_without_json_fails_clean(self):
        """Prose with NO JSON raises ValueError."""
        with pytest.raises(ValueError):
            ffv.extract_json(
                "I could not read the flyer — no prices found.")

    def test_truncation_salvage_keeps_complete_deals(self):
        """Reply cut mid-deal keeps every COMPLETE deal object."""
        d1 = json.dumps(_good_deal())
        d2 = json.dumps(_good_deal(item="Whole Chicken", price=8.50,
                                   unit="ea"))
        truncated = ('```json\n{"valid_until": null, "deals": ['
                     + d1 + "," + d2[:len(d2) // 2])
        # Production path: extract_json strips the (unclosed) fence,
        # brace-slices, then salvages — assert through it.
        payload = ffv.extract_json(truncated)
        deals, errs = ffv.validate_payload(payload)
        self.assertEqual(errs, [])
        self.assertEqual([d["item"] for d in deals],
                         ["Beef Diced"])

    def test_salvage_none_when_no_complete_deal(self):
        """No complete deal survives -> None."""
        self.assertIsNone(ffv.salvage_truncated_json(
            '{"valid_until": null, "deals": [{"item": "Cut"'))

    def test_zero_deals_is_valid_outcome(self):
        """Zero deals parses to an empty (valid) result."""
        mock = patch.object(
            ffv, "_call_model",
            return_value=(json.dumps({"valid_until": None,
                                      "deals": []}),
                          {"total_tokens": 10,
                           "finish_reason": "stop"}))
        with mock:
            out = ffv.parse_board_images([])
        self.assertEqual(out, {"valid_until": None,
                               "validity_text": None,
                               "deals": []})


def _fake_api_response(content):
    """Build the mocked requests.post response object."""
    resp = unittest.mock.MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content},
                     "finish_reason": "stop"}],
        "usage": {"total_tokens": 42},
    }
    return resp


class TestTransport(unittest.TestCase):
    """parse_board_images chain + transport assertions."""

    def test_finish_reason_logged(self):
        """The receipt line with finish_reason reaches stdout."""
        content = json.dumps({"deals": [_good_deal()]})
        with patch.object(
                ffv, "_call_model",
                return_value=(content, {"total_tokens": 42,
                                        "finish_reason": "stop"})):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ffv.parse_board_images([])
        out = buf.getvalue()
        self.assertIn("[vision]", out)
        self.assertIn("finish_reason=stop", out)

    def test_attempt_cap_two_per_post_fallback_counts(self):
        """Chain[0]+chain[1] fail -> cap; chain[2] never reached."""
        mock = patch.object(
            ffv, "_call_model",
            side_effect=[RuntimeError("boom"), RuntimeError("bang")])
        with mock as m:
            with pytest.raises(ffv.VisionUnavailable):
                ffv.parse_board_images([])
        self.assertEqual(m.call_count, 2)

    def test_zlm_url_gets_chat_completions_appended(self):
        """A BASE zlm_url gets /chat/completions appended."""
        content = json.dumps({"deals": []})
        env = {"zlm_url": "https://api.z.ai/api/coding/paas/v4/",
               "zlm_claw": "test-key-zlm"}
        with patch.dict(os.environ, env, clear=False), \
             patch("requests.post",
                   return_value=_fake_api_response(content)) as p:
            ffv.parse_board_images([])
        url = p.call_args.args[0]
        self.assertTrue(url.endswith("/chat/completions"))

    def test_openrouter_auth_header_present_secret_free(self):
        """openrouter route sends the Bearer header; key never logged."""
        content = json.dumps({"deals": []})
        env = {"OPENROUTER_API_KEY": "sk-test-openrouter",
               "zlm_url": "", "zlm_claw": ""}
        with patch.dict(os.environ, env, clear=False), \
             patch("requests.post",
                   return_value=_fake_api_response(content)) as p:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ffv.parse_board_images([])
        headers = p.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"],
                         "Bearer sk-test-openrouter")
        self.assertNotIn("sk-test-openrouter", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
