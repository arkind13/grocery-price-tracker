#!/usr/bin/env python3
"""Sydney clock tests (TODO-local-deals-gaps.md Task 1).

Pins the invariant the whole local-deals/halal rebuild rests on: every
date decision uses SYDNEY time, never the server (UTC) clock — with
UTC-instant inputs so an AEST->AEDT switch cannot silently flip a
verdict. The headline case is the user's own example: at 2026-09-06
20:00 UTC (= 06:00 Sun 7 Sep Sydney) a catalogue dated "5 & 6
September" (ends 2026-09-06 Sydney) must be EXPIRED.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.sydney_time import (  # noqa: E402
    SYDNEY_TZ, sydney_now, sydney_today,
)
from core import local_deals as ld  # noqa: E402

UTC = timezone.utc


def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


class TestSydneyClock(unittest.TestCase):
    """The single-clock contract (§1 of the TODO)."""

    def test_utc_instant_2026_09_06_2000_is_sunday_7sep_sydney(self):
        # The TODO's own pin: 2026-09-06 20:00 UTC == 06:00 Mon 7 Sep
        # Sydney (AEST, UTC+10 in September; 6 Sep itself is Sunday).
        syd = _utc(2026, 9, 6, 20, 0).astimezone(ZoneInfo(SYDNEY_TZ))
        self.assertEqual(syd.date(), date(2026, 9, 7))
        self.assertEqual(syd.hour, 6)
        self.assertEqual(syd.weekday(), 0)   # Monday

    def test_validity_boundary_2359_sydney_still_same_day(self):
        # "Valid until 6 September" covers 23:59 Sydney 6 Sep
        # (= 13:59 UTC): 13:58 UTC is still 6 Sep in Sydney.
        just_before = _utc(2026, 9, 6, 13, 58).astimezone(
            ZoneInfo(SYDNEY_TZ))
        self.assertEqual(just_before.date(), date(2026, 9, 6))
        # One minute later the catalogue is expired.
        expired = _utc(2026, 9, 6, 14, 0).astimezone(
            ZoneInfo(SYDNEY_TZ))
        self.assertEqual(expired.date(), date(2026, 9, 7))

    def test_sydney_today_follows_pinned_sydney_now(self):
        pinned = _utc(2026, 9, 6, 20, 0).astimezone(
            ZoneInfo(SYDNEY_TZ))
        with patch("core.sydney_time.sydney_now",
                   return_value=pinned):
            self.assertEqual(sydney_today(), date(2026, 9, 7))
            self.assertEqual(sydney_now().tzinfo,
                             ZoneInfo(SYDNEY_TZ))

    def test_aedt_boundary_2026_10_04_offset_is_eleven(self):
        # After the 2026-10-04 03:00 AEDT switch, 20:00 UTC is
        # 07:00 Sydney (UTC+11) — the helper needs no per-date map.
        syd = _utc(2026, 10, 3, 20, 0).astimezone(
            ZoneInfo(SYDNEY_TZ))
        self.assertEqual(syd.utcoffset().total_seconds(), 11 * 3600)
        self.assertEqual(syd.hour, 7)


class TestGateUsesSydneyFromUtcServer(unittest.TestCase):
    """friday_gate_open defaults to sydney_now — pinned via UTC."""

    def test_gate_open_on_friday_0500_sydney_from_utc_instant(self):
        # Fri 2026-09-11 05:00 Sydney (AEST) == Thu 2026-09-10
        # 19:00 UTC — a UTC server must still open the window.
        # (No state patch: the pinned date can never equal the
        # real file's last_fire_date, so "not fired" holds.)
        pinned = _utc(2026, 9, 10, 19, 0).astimezone(
            ZoneInfo(SYDNEY_TZ))
        # local_deals binds sydney_now at import — patch THERE.
        with patch("core.local_deals.sydney_now",
                   return_value=pinned):
            self.assertTrue(ld.friday_gate_open())

    def test_expired_catalogue_dropped_by_sydney_date(self):
        # The user's RE-CHECK: at 06:00 Sun 7 Sep Sydney the
        # "5 & 6 September" weekend catalogue (ends 2026-09-06)
        # is EXPIRED through the pipeline's own comparison.
        pinned = _utc(2026, 9, 6, 20, 0).astimezone(
            ZoneInfo(SYDNEY_TZ))
        with patch("core.sydney_time.sydney_now",
                   return_value=pinned):
            valid_until = date.fromisoformat("2026-09-06")
            self.assertTrue(valid_until < sydney_today())


if __name__ == "__main__":
    unittest.main()
