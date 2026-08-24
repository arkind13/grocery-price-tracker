#!/usr/bin/env python3
"""Offline document parser for Word (.docx) and plain-text grocery lists.

Modernises the docx/text parsing logic from ``name_importer.py`` into a
clean, reusable module. Supports:
  - ``.docx`` files (via ``python-docx``)
  - ``.txt`` files
  - ``.json`` structured dumps

All parsers return a list of ``ProductItem`` dataclasses.

Usage:
    from extractors.doc_parser import parse_docx_cache, parse_text_dump

    # Parse a Word doc
    items = parse_docx_cache("Woolworths.docx", store="woolworths")

    # Parse a text dump
    items = parse_text_dump("coles_export.txt", store="coles")
"""

import json
import os
import re
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_TRACKER_DIR = os.path.abspath(os.path.join(_HERE, ".."))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
for p in (_TRACKER_DIR, _REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from extractors.models import ProductItem

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# UI noise / ignore terms (expanded from name_importer.py)
IGNORE_TERMS = [
    "total", "estimated", "footer", "value of done", "special buys",
    "toggle", "search", "hi, ", "delivery to", "sort by", "view cart",
    "items available", "you'll save up to", "more from",
    "products value", "you'll collect", "pts", "back to top",
    "my account", "specials only", "categorise", "price compare",
    "add all to cart", "sign in", "register", "password", "email",
    "checkout", "continue shopping", "your list", "create list",
    "list name", "delete", "share", "print list",
    "unit price", "each", "per kg", "per l", "per 1",
    "you pay", "you save", "was ", "save ", "bonus ",
    "everyday rewards", "flybuys", "subtotal",
    "ends ", "add to cart", "personal care", "explore our brands",
]

DOCX_SEARCH_PATHS = {
    "woolworths": "Woolworths.docx",
    "coles": "Coles.docx",
    "aldi": "Aldi.docx",
}

STORE_ALIASES = {
    "woolworths": ("woolworths", "ww", "woolies"),
    "coles": ("coles"),
    "aldi": ("aldi"),
}


# ---------------------------------------------------------------------------
# Price extraction
# ---------------------------------------------------------------------------
def _clean_price(text: str) -> Optional[float]:
    """Extract a numeric price from a string like ``$4.50`` or ``A$4.50``.

    Args:
        text: Raw string potentially containing a price.

    Returns:
        float price, or None.
    """
    if not text:
        return None
    match = re.search(r"(?:A\$|\$)\s*(\d+\.?\d*)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _is_price_line(text: str) -> bool:
    """Check if a line is predominantly a price (no product name).

    Args:
        text: Line text.

    Returns:
        True if the line matches price-only pattern.
    """
    return bool(re.match(r"^(?:A\$|\$)\s*\d+\.?\d*", text.strip()))


def _is_ignore_line(text: str) -> bool:
    """Check if a line should be ignored (UI noise, footer, etc.).

    Uses word-boundary matching for terms shorter than 5 characters
    to prevent false positives (e.g. ``"edit"`` matching ``"Edition"``).

    Args:
        text: Line text.

    Returns:
        True if the line matches known ignore terms.
    """
    lower = text.lower().strip()
    for term in IGNORE_TERMS:
        if len(term) < 5:
            # Use word-boundary matching for short terms
            if re.search(r"\b" + re.escape(term) + r"\b", lower):
                return True
        else:
            if term in lower:
                return True
    return False


# ---------------------------------------------------------------------------
# Size / brand / category extraction (from Woolworths_Historical.py)
# ---------------------------------------------------------------------------
def _extract_size(name: str) -> str:
    """Extract product size from a name string.

    Examples: ``"1L"``, ``"500g"``, ``"2kg"``, ``"6pk"``.

    Args:
        name: Product name.

    Returns:
        Size string, or empty string if none found.
    """
    match = re.search(
        r"(\d+\.?\d*\s*(?:kg|g|l|ml|pk|pack|ea|units|oz|litre|litres))",
        name,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _detect_category(name: str) -> str:
    """Infer product category from name keywords.

    Args:
        name: Product name.

    Returns:
        Category string (e.g. ``"Dairy"``, ``"Meat"``), or ``""``.
    """
    lower = name.lower()
    if any(w in lower for w in ("milk", "cheese", "yoghurt", "yogurt", "butter", "cream", "egg")):
        return "Dairy"
    if any(w in lower for w in ("mince", "chicken", "beef", "pork", "steak", "sausage", "bacon", "ham", "turkey")):
        return "Meat"
    if any(w in lower for w in ("bread", "roll", "bagel", "muffin", "croissant", "tortilla", "wrap")):
        return "Bakery"
    if any(w in lower for w in ("apple", "banana", "orange", "grape", "lettuce", "tomato", "onion", "potato", "broccoli")):
        return "Fruit & Veg"
    if any(w in lower for w in ("rice", "pasta", "noodle", "spaghetti", "lasagne")):
        return "Pantry"
    if any(w in lower for w in ("soap", "shampoo", "cleaner", "detergent", "tissue", "paper")):
        return "Household"
    if any(w in lower for w in ("chips", "chocolate", "lollies", "candy", "biscuit", "cookie")):
        return "Snacks"
    return ""


def _detect_brand(name: str) -> str:
    """Detect product brand from name.

    Args:
        name: Product name.

    Returns:
        Brand name or ``""``.
    """
    known_brands = [
        "Oatly", "Bega", "Devondale", "Paul's", "Dairy Farmers",
        "Mainland", "Tatura", "Liddells", "Zooper Dooper", "Poppa",
        "Kleenex", "Sunny Queen", "Tip Top", "Helga's", "Abbott's",
        "McDonald's", "Moccona", "Nescafe", "Dilmah", "Twinings",
        "Coca-Cola", "Pepsi", "Sprite", "Fanta", "Mount Franklin",
        "Schweppes", "Barista", "Bonnie", "Campbell's", "Heinz",
        "Leggo's", "Dolmio", "San Remo", "Barilla", "Vetta",
        "White Wings", "McKenzie's", "Woolworths", "Coles",
    ]
    for brand in known_brands:
        if brand.lower() in name.lower():
            return brand
    return ""


# ---------------------------------------------------------------------------
# Docx parser
# ---------------------------------------------------------------------------
def parse_docx(
    file_path: str, store: str = ""
) -> list[ProductItem]:
    """Parse product names and prices from a Word (.docx) grocery list.

    Uses the same strategy as ``name_importer.py``: a line is a product
    name if the next line contains a price. This accounts for the
    typical two-line layout of saved lists.

    Args:
        file_path: Path to the ``.docx`` file.
        store: Store identifier (``"woolworths"``, ``"coles"``, ``"aldi"``).

    Returns:
        list of ``ProductItem`` instances.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    try:
        from docx import Document
    except ImportError:
        print(
            "[doc_parser] python-docx not installed. "
            "Install with: pip install python-docx",
            file=sys.stderr,
        )
        return []

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    doc = Document(file_path)
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    items = []
    seen = set()

    for i in range(len(lines) - 1):
        current_line = lines[i]
        next_line = lines[i + 1]

        # Check if the NEXT line contains a price
        price = _clean_price(next_line)

        if price is not None and len(current_line) > 3 and "$" not in current_line:
            if _is_ignore_line(current_line):
                continue

            name = current_line.strip()
            name_lower = name.lower()

            if name_lower in seen:
                continue
            seen.add(name_lower)

            items.append(
                ProductItem(
                    store=store,
                    raw_name=name,
                    price=price,
                    category=_detect_category(name),
                    size=_extract_size(name),
                    brand=_detect_brand(name),
                )
            )

    return items


def parse_docx_cache(store: str = "") -> list[ProductItem]:
    """Parse the cached docx file for a given store from the project directory.

    Looks for ``Woolworths.docx``, ``Coles.docx``, or ``Aldi.docx`` in
    the ``grocery-price-tracker/`` directory.

    Args:
        store: Store identifier (``"woolworths"``, ``"coles"``, ``"aldi"``).

    Returns:
        list of ``ProductItem`` instances. Empty if file not found.
    """
    store = store.lower().strip()
    filename = DOCX_SEARCH_PATHS.get(store)
    if not filename:
        print(
            f"[doc_parser] Unknown store '{store}'. "
            f"Supported: {', '.join(DOCX_SEARCH_PATHS.keys())}",
            file=sys.stderr,
        )
        return []

    # Search in grocery-price-tracker/ directory
    tracker_dir = _TRACKER_DIR
    file_path = os.path.join(tracker_dir, filename)

    # Also search in current working directory
    if not os.path.isfile(file_path):
        file_path = os.path.join(os.getcwd(), filename)

    if not os.path.isfile(file_path):
        print(
            f"[doc_parser] No docx found for '{store}' at: {file_path}",
            file=sys.stderr,
        )
        return []

    try:
        return parse_docx(file_path, store=store)
    except FileNotFoundError as exc:
        print(f"[doc_parser] {exc}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Plain-text parser
# ---------------------------------------------------------------------------
def parse_text_dump(
    text: str, store: str = "", source_name: str = "text"
) -> list[ProductItem]:
    """Parse a plain-text grocery list with ``Name\\n$Price`` format.

    Each product name should be on its own line, immediately followed
    by a line containing its price. Also supports ``Name - $Price``
    single-line format.

    Args:
        text: Raw text content of the grocery list.
        store: Store identifier.
        source_name: Name of the source for error messages.

    Returns:
        list of ``ProductItem`` instances.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    items = []
    seen = set()

    # Try single-line format first: "Product Name - $4.50" or "Product Name $4.50"
    for line in lines:
        match = re.match(
            r"(.+?)\s*(?:-|–)\s*(?:\$)(\d+\.?\d*)",
            line,
        )
        if not match:
            match = re.match(
                r"(.+?)\s{2,}(?:\$)(\d+\.?\d*)",
                line,
            )
        if match:
            name = match.group(1).strip()
            price_str = match.group(2)
            if _is_ignore_line(name):
                continue
            try:
                price = float(price_str)
            except ValueError:
                continue
            name_lower = name.lower()
            if name_lower not in seen:
                seen.add(name_lower)
                items.append(
                    ProductItem(
                        store=store,
                        raw_name=name,
                        price=price,
                        category=_detect_category(name),
                        size=_extract_size(name),
                        brand=_detect_brand(name),
                    )
                )

    # Fall back to two-line format if no single-line matches
    if not items:
        for i in range(len(lines) - 1):
            price = _clean_price(lines[i + 1])
            if price is not None and "$" not in lines[i] and len(lines[i]) > 3:
                name = lines[i]
                if _is_ignore_line(name):
                    continue
                name_lower = name.lower()
                if name_lower not in seen:
                    seen.add(name_lower)
                    items.append(
                        ProductItem(
                            store=store,
                            raw_name=name,
                            price=price,
                            category=_detect_category(name),
                            size=_extract_size(name),
                            brand=_detect_brand(name),
                        )
                    )

    return items


def parse_text_file(
    file_path: str, store: str = ""
) -> list[ProductItem]:
    """Read and parse a text file containing a grocery list.

    Args:
        file_path: Path to the ``.txt`` file.
        store: Store identifier.

    Returns:
        list of ``ProductItem`` instances.
    """
    if not os.path.isfile(file_path):
        print(f"[doc_parser] File not found: {file_path}", file=sys.stderr)
        return []

    with open(file_path, "r", encoding="utf-8-sig") as f:
        text = f.read()

    return parse_text_dump(text, store=store, source_name=os.path.basename(file_path))


# ---------------------------------------------------------------------------
# JSON structured parser
# ---------------------------------------------------------------------------
def parse_json_dump(
    file_path: str, store: str = ""
) -> list[ProductItem]:
    """Parse a JSON file containing product data.

    Expected format: list of dicts with keys ``name`` (or ``raw_name``),
    ``price``, and optional ``is_special``, ``special_desc``, etc.

    Args:
        file_path: Path to the ``.json`` file.
        store: Store identifier.

    Returns:
        list of ``ProductItem`` instances.
    """
    if not os.path.isfile(file_path):
        print(f"[doc_parser] File not found: {file_path}", file=sys.stderr)
        return []

    with open(file_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            print(f"[doc_parser] Invalid JSON: {exc}", file=sys.stderr)
            return []

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        print(f"[doc_parser] Expected list or dict, got {type(data).__name__}", file=sys.stderr)
        return []

    items = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        raw_name = entry.get("name") or entry.get("raw_name") or entry.get("product_name") or ""
        if not raw_name:
            continue

        price = entry.get("price", 0.0)
        try:
            price = float(price)
        except (ValueError, TypeError):
            price = 0.0

        items.append(
            ProductItem(
                store=store or entry.get("store", ""),
                raw_name=raw_name,
                price=price,
                is_special=bool(entry.get("is_special", False)),
                special_desc=entry.get("special_desc", ""),
                rewards_points=str(entry.get("rewards_points", "")),
                unit_price=entry.get("unit_price", ""),
                category=entry.get("category", ""),
                size=entry.get("size", ""),
                brand=entry.get("brand", ""),
            )
        )

    return items


# ---------------------------------------------------------------------------
# Auto-detect and parse
# ---------------------------------------------------------------------------
def auto_parse(file_path: str, store: str = "") -> list[ProductItem]:
    """Auto-detect file type and parse accordingly.

    Supports ``.docx``, ``.txt``, and ``.json`` files.

    Args:
        file_path: Path to the grocery list file.
        store: Store identifier (optional).

    Returns:
        list of ``ProductItem`` instances.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        return parse_docx(file_path, store=store)
    elif ext == ".json":
        return parse_json_dump(file_path, store=store)
    else:
        return parse_text_file(file_path, store=store)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Doc Parser Self-Test ===\n")

    # Test with Woolworths docx
    print("1. Parsing Woolworths.docx...")
    try:
        items = parse_docx_cache("woolworths")
        print(f"   Found {len(items)} items")
        for item in items[:5]:
            print(f"   - {item.raw_name}: ${item.price:.2f}")
    except Exception as exc:
        print(f"   Error: {exc}")

    # Test with text
    print("\n2. Parsing sample text...")
    sample = "Oatly Barista Milk 1L\n$4.50\nBega Cheese Block 500g\n$7.00\n"
    items = parse_text_dump(sample, store="woolworths")
    print(f"   Found {len(items)} items")
    for item in items:
        print(f"   - {item.raw_name}: ${item.price:.2f}")

    print("\n=== Done ===")
