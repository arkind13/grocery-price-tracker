# LEGACY AUDIT — grocery-price-tracker Scripts

Generated: 2026-08-22 | Subtask 0.3

---

## Column Index Map (Products_Master tab, 0-based)

| Col | Letter | Header | Usage |
|-----|--------|--------|-------|
| 0 | A | Product_Name | Generic product name (primary key) |
| 1 | B | Category | e.g. Dairy, Meat, Bakery |
| 2 | C | Size | e.g. 1L, 500g |
| 3 | D | Woolworths_Price | Updated by local_sync |
| 4 | E | Coles_Price | Updated by local_sync |
| 5 | F | Aldi_Price | Updated by local_sync |
| 6 | G | Brand_Type | Store brand or name brand |
| 7 | H | Last_Updated | Timestamp of last price update |
| 8 | I | Search_Keyword_Woolworths | Exact store name for Woolworths matching |
| 9 | J | Search_Keyword_Coles | Exact store name for Coles matching |
| 10 | K | Search_Keyword_Aldi | Exact store name for Aldi matching |
| 11 | L | Aldi Refresh | Timestamp for Aldi-specific refresh |

---

## Matching Strategy (per user directive)

**No fuzzy matching.** The sheet stores exact store-listed product names in columns
I/J/K. Matching is done by exact string comparison against these stored keywords.
This replaces the rapidfuzz token_set_ratio approach previously attempted.

---

## name_importer.py

| Aspect | Detail |
|--------|--------|
| Purpose | Maps new product names from Word docs to Google Sheet rows |
| Interactive? | YES — uses input() prompts for NEW/SKIP/LINK decisions |
| Docx parsing | extract_names_from_docx(): finds lines followed by price pattern |
| UI noise filter | 20+ ignore terms (toggle, search, footer, etc.) |
| Auth method | Hardcoded path: credentials/service_account.json |
| Store keyword cols | Woolworths=col 9, Coles=col 10, Aldi=col 11 (1-based) |
| Reusable parts | docx name extraction logic, ignore list, col mapping |
| Obsolete parts | input() prompts — must become headless; hardcoded creds path |

## local_sync.py

| Aspect | Detail |
|--------|--------|
| Purpose | Batch sync prices from Word docs to Google Sheets |
| Interactive? | NO — fully automated |
| Matching | rapidfuzz token_set_ratio, threshold >= 95 (TO BE REPLACED with exact) |
| Batch update | Single sheet.update() call for all rows |
| Price extraction | clean_price(): regex for $XX.XX or A$XX.XX |
| Docx parsing | extract_from_docx(): name->price cache from paragraphs |
| Auth method | Hardcoded path: credentials/service_account.json |
| Reusable parts | clean_price(), extract_from_docx(), batch update logic |
| Obsolete parts | Hardcoded credentials path, fuzzy matching approach |

## Woolworths_Historical.py

| Aspect | Detail |
|--------|--------|
| Purpose | Parse Woolworths product names into structured CSV |
| Interactive? | NO |
| Size extraction | Regex: (\d+\.?\d*\s?(?:kg|g|l|ml|pk|pack|ea|units|oz)) |
| Brand detection | Checks known brands list, falls back to first word |
| Category logic | Keyword matching: Dairy, Fruit & Veg, Bakery, Meat |
| Output | woolworths_master_comparison.csv |
| Reusable parts | parse_product_details() — brand/size/category extraction |
| Obsolete parts | Hardcoded input file name, no integration with Sheets |
