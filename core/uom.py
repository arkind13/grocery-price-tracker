#!/usr/bin/env python3
"""Unit-of-measure (UOM) size parsing + comparability gate — pure stdlib.

Implements spec B1: before two live-searched products may be compared,
their package sizes must be parseable, belong to the same measurement
family (weight/volume/length/count), and sit within 20% of each other.
This is the guard against the hand-tool-set class of wrong-pair
comparisons (e.g. "3 Piece Garden Tool Set" vs "Seasol 1.2L").

Design rules (spec §3.2):
    - Parsing is tolerant and total: anything unparseable -> ``None``.
    - Families NEVER cross: 1.2 L vs 500 g is a family mismatch, not a
      numeric comparison.
    - Missing size on either side is NOT_COMPARABLE (``missing_size``).
    - Exactly 20% apart passes; 20.1% fails.

No per-unit price math happens here (or anywhere downstream) — this
module only decides whether two package sizes are comparable.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Measurement families (spec §4.1) — canonical units: "g" | "mL" | "m" | "ea"
# ---------------------------------------------------------------------------
FAMILY_WEIGHT = "weight"
FAMILY_VOLUME = "volume"
FAMILY_LENGTH = "length"
FAMILY_COUNT = "count"

# Canonical unit per family (normalised form exposed on ParsedSize).
_CANONICAL_UNIT = {
    FAMILY_WEIGHT: "g",
    FAMILY_VOLUME: "mL",
    FAMILY_LENGTH: "m",
    FAMILY_COUNT: "ea",
}

# Unit -> (family, factor-to-canonical-value). Longer unit tokens first so
# alternation is greedy-correct ("ml" before "m"/"l", "kg" before "g").
_UNITS: dict[str, tuple[str, float]] = {
    "mg": (FAMILY_WEIGHT, 0.001),
    "kg": (FAMILY_WEIGHT, 1000.0),
    "g": (FAMILY_WEIGHT, 1.0),
    "ml": (FAMILY_VOLUME, 1.0),
    "l": (FAMILY_VOLUME, 1000.0),
    "mm": (FAMILY_LENGTH, 0.001),
    "cm": (FAMILY_LENGTH, 0.01),
    "m": (FAMILY_LENGTH, 1.0),
    "each": (FAMILY_COUNT, 1.0),
}

_UNIT_PATTERN = "|".join(re.escape(u) for u in _UNITS)

# Single-size strings: "600mL", "1.2kg", "25L", "10 m", "1 each"
_SINGLE_RE = re.compile(
    rf"^\s*(\d+(?:\.\d+)?)\s*({_UNIT_PATTERN})\s*$", re.IGNORECASE)

# Multipack strings: "6 x 170g", "6x170g", "2 X 1L"
_MULTIPACK_RE = re.compile(
    rf"^\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*({_UNIT_PATTERN})\s*$",
    re.IGNORECASE)

# Tolerance band: |a - b| / min(a, b) <= 0.20 (exactly 20% passes).
TOLERANCE = 0.20

# Float-equality slack for the COMPARABLE_SAME verdict (absorbs 0.5 vs 50cm
# style round-trips where both normalise to the identical double).
_SAME_EPSILON = 1e-9


class Verdict(str, Enum):
    """Comparison verdict strings mandated by the spec (§3.2 enum)."""

    COMPARABLE_SAME = "comparable_same"
    COMPARABLE_TOLERANT = "comparable_tolerant"
    NOT_COMPARABLE = "not_comparable"


@dataclass(frozen=True)
class ParsedSize:
    """A parsed package size normalised to its family's canonical unit.

    Attributes:
        value: Numeric value in the canonical unit (grams, mL, m, or count).
        unit: Canonical unit string ("g" | "mL" | "m" | "ea").
        family: Measurement family constant (FAMILY_*).
    """

    value: float
    unit: str
    family: str


@dataclass(frozen=True)
class SizeComparison:
    """Result of comparing two package sizes.

    Attributes:
        verdict: COMPARABLE_SAME / COMPARABLE_TOLERANT / NOT_COMPARABLE.
        reason: "" when comparable; otherwise "family_mismatch",
            "beyond_20pct", or "missing_size".
    """

    verdict: Verdict
    reason: str = ""


def parse_size(text) -> ParsedSize | None:
    """Parse a package-size string into a normalised ParsedSize.

    Handles (case-insensitive, whitespace-tolerant):
        - weight  ``mg|g|kg``      -> grams   (kg x1000, mg /1000)
        - volume  ``mL|L``         -> mL      (L x1000)
        - length  ``mm|cm|m``      -> metres  (cm /100, mm /1000)
        - count   ``N each``       -> count   (value N)
        - decimal values           ("1.2kg", "0.75L")
        - multipacks               ("6 x 170g" -> 1020 g, "2 X 1L" -> 2000 mL)

    Args:
        text: Raw size string (e.g. a store listing's size field).

    Returns:
        ParsedSize with the normalised value + canonical unit, or None
        when the input is None / empty / not a size string.
    """
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if not candidate:
        return None

    multipack = _MULTIPACK_RE.match(candidate)
    if multipack:
        count = float(multipack.group(1))
        inner_value = float(multipack.group(2))
        unit = multipack.group(3).lower()
        family, factor = _UNITS[unit]
        return ParsedSize(
            value=count * inner_value * factor,
            unit=_CANONICAL_UNIT[family],
            family=family,
        )

    single = _SINGLE_RE.match(candidate)
    if single:
        value = float(single.group(1))
        unit = single.group(2).lower()
        family, factor = _UNITS[unit]
        return ParsedSize(
            value=value * factor,
            unit=_CANONICAL_UNIT[family],
            family=family,
        )

    return None


def size_families_match(a: ParsedSize | None, b: ParsedSize | None) -> bool:
    """Whether two parsed sizes belong to the same measurement family.

    Families never cross: weight vs volume is always False even though a
    naive numeric compare is possible.

    Args:
        a: First parsed size (or None).
        b: Second parsed size (or None).

    Returns:
        bool: True only when both are non-None and share a family.
    """
    if a is None or b is None:
        return False
    return a.family == b.family


def within_20pct(a: float, b: float) -> bool:
    """Whether two normalised values sit within the 20% tolerance band.

    Args:
        a: First normalised value.
        b: Second normalised value.

    Returns:
        bool: True when |a - b| / min(a, b) <= 0.20. Exactly 20% passes;
        20.1% fails. Values with min <= 0 never pass (avoids divide-by-zero).
    """
    low = min(a, b)
    if low <= 0:
        return False
    return abs(a - b) / low <= TOLERANCE


def compare_sizes(a: ParsedSize | None, b: ParsedSize | None) -> SizeComparison:
    """Compare two parsed sizes and return the UOM gate verdict.

    Order of rules (spec §3.2):
        1. Either side missing  -> NOT_COMPARABLE / "missing_size"
        2. Family mismatch      -> NOT_COMPARABLE / "family_mismatch"
        3. Equal value          -> COMPARABLE_SAME
        4. Within 20%           -> COMPARABLE_TOLERANT
        5. Otherwise            -> NOT_COMPARABLE / "beyond_20pct"

    Args:
        a: First parsed size (or None).
        b: Second parsed size (or None).

    Returns:
        SizeComparison with the verdict and machine-readable reason.
    """
    if a is None or b is None:
        return SizeComparison(Verdict.NOT_COMPARABLE, "missing_size")
    if not size_families_match(a, b):
        return SizeComparison(Verdict.NOT_COMPARABLE, "family_mismatch")
    if abs(a.value - b.value) <= _SAME_EPSILON * max(a.value, b.value, 1.0):
        return SizeComparison(Verdict.COMPARABLE_SAME, "")
    if within_20pct(a.value, b.value):
        return SizeComparison(Verdict.COMPARABLE_TOLERANT, "")
    return SizeComparison(Verdict.NOT_COMPARABLE, "beyond_20pct")
