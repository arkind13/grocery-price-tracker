"""Sydney clock — the ONE place all local-deals + halal date logic
gets Sydney time from (TODO-local-deals-gaps.md Task 1).

Facts the design locks in:
- The VPS runs UTC; a bare ``datetime.now()`` there is UTC wall time.
- Sydney is AEST (UTC+10) and becomes AEDT (UTC+11) on Sun 4 Oct 2026
  — zoneinfo resolves the offset by date, so DST needs no special
  cases anywhere else.
- "Valid until 6 September" means through 23:59 Sydney on 6 Sep
  (= 13:59 UTC that day): every date comparison must therefore use
  ``sydney_today()`` / ``sydney_now()``, never the server clock.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

SYDNEY_TZ = "Australia/Sydney"


def sydney_now() -> datetime:
    """Current Sydney time as a tz-aware datetime.

    Returns:
        datetime: aware value in Australia/Sydney (AEST or AEDT as
        the date dictates).
    """
    return datetime.now(ZoneInfo(SYDNEY_TZ))


def sydney_today() -> date:
    """Current Sydney date (not the server's UTC date).

    Returns:
        date: today in Sydney.
    """
    return sydney_now().date()
