import sys, json
sys.path.insert(0, r"C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker")
from core.sheets_client import connect_worksheet
from core.sheets_sync import add_product_row
from core import add_to_list as q

ws = connect_worksheet()
r = add_product_row("ZZTEST T4 Mechanism Product 250g", "woolworths", 5.00,
                    size="250g", alias="zztest t4", worksheet=ws)
print("ADD_ROW:", json.dumps(r, default=str)[:300])
vals = ws.col_values(1)
idx = next((i for i, v in enumerate(vals, start=1) if v.strip() == "ZZTEST T4 Mechanism Product 250g"), None)
print("ROW_INDEX:", idx)
e1 = q.add_entry("woolworths", "ZZTEST Woolworths Keyword 250g", "ZZTEST T4 Mechanism Product 250g")
e2 = q.add_entry("coles", "ZZTEST Coles Keyword 250g", "ZZTEST T4 Mechanism Product 250g")
print("TODO_CODES:", e1.get("code"), e2.get("code"), "| QUEUE_COUNT:", len(q.load_pending()))
