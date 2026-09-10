#!/usr/bin/env python3
"""Offline check of the truncated-JSON salvage path in test2."""
import importlib.util
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

spec = importlib.util.spec_from_file_location(
    "t2", Path(__file__).parent / "test2_vision_json.py")
t2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t2)

# A reply truncated mid-way through the second deal (finish_reason=length).
truncated = json.dumps({
    "valid_until": "2026-09-11",
    "deals": [
        {"item": "A", "raw_text": "x", "price": 1.0, "unit": "kg",
         "price_kind": "single", "multibuy_qty": None, "bulk_size": None,
         "category": "fruits", "notes": ""},
        {"item": "B", "raw_text": "y", "price": 2.0, "unit": "kg",
         "price_kind": "single", "multibuy_qty": None, "bulk_size": None,
         "category": "fruits", "notes": ""},
    ],
})[:420]  # cut mid-JSON, after deal 1 is complete but inside deal 2
payload = t2.extract_json(truncated)
deals, errs = t2.validate_response(payload)
assert len(deals) >= 1, f"expected salvaged deals, got {len(deals)}"
assert errs == [], f"unexpected schema errors: {errs}"
print(f"PASS truncation salvage: parsed to valid JSON with "
      f"{len(deals)} complete deals, valid_until={payload.get('valid_until')!r}")

# A clean reply must parse untouched (no salvage needed).
clean = json.dumps({"valid_until": None, "deals": [
    {"item": "A", "raw_text": "x", "price": 1.0, "unit": "kg",
     "price_kind": "single", "multibuy_qty": None, "bulk_size": None,
     "category": "butchery", "notes": ""}]})
deals, errs = t2.validate_response(t2.extract_json(clean))
assert len(deals) == 1 and errs == []
print("PASS clean reply parses untouched")

# Prose without any JSON must still raise.
try:
    t2.extract_json("totally no json here")
    print("FAIL: should have raised")
    sys.exit(1)
except ValueError:
    print("PASS prose without JSON still raises")
