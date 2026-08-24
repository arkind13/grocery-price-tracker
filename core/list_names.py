"""Phase 9.0.c — Pinned saved-list name constants.

Constants derived from existing codebase conventions and confirmed against
Woolworths /apis/ui/mylists (when cookie is live). If the live mylists query
reveals different casing, update these constants here.

Used by: sheets_sync, price_comparator, recipe_resolver, and the 'map' CLI
subcommand for list-name-aware operations.

Never contains secrets.
"""
from __future__ import annotations

# Woolworths "Price Compare" list (the main price comparison list)
# Confirmed: woolworths_extractor.py:55 LIST_NAME_TARGET = "Price Compare"
WOOL_LIST_PRICE_COMPARE: str = "Price Compare"

# Woolworths "Specials" list (items on special / half-price)
# NOTE: exact casing TBD — pending live mylists verification in 9.3
WOOL_LIST_SPECIALS: str = "Specials"

# Coles "Price Comparison" list (the equivalent saved list on Coles)
# Confirmed: coles_extractor.py:384 fetch_coles_list(list_name="Price Comparison")
# NOTE: Coles uses "Price Comparison" (not "Price Compare")
COLES_LIST_PRICE_COMPARE: str = "Price Comparison"

# All three constants as a dict for iteration / probe scripts
LIST_NAMES: dict[str, str] = {
    "WOOL_LIST_PRICE_COMPARE": WOOL_LIST_PRICE_COMPARE,
    "WOOL_LIST_SPECIALS": WOOL_LIST_SPECIALS,
    "COLES_LIST_PRICE_COMPARE": COLES_LIST_PRICE_COMPARE,
}
