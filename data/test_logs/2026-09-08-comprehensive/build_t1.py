import json
d = json.load(open("sheet_dump.json", encoding="utf-8"))
names = [r["name"] for r in d]
print("total", len(names))
# 10 batches x 25 sheet items = 250 items through compare --mode sheet
batches = []
n = 0
for b in range(10):
    chunk = names[b*25:(b+1)*25]
    if not chunk: break
    n += len(chunk)
    batches.append({"id": f"T1.C{b+1:02d}", "label": f"compare sheet-mode batch {b+1} ({len(chunk)} sheet items)",
                    "args": ["compare", "--items", ", ".join(chunk), "--mode", "sheet"]})
json.dump(batches, open("batch_t1_compare.json", "w", encoding="utf-8"), indent=1)
print("batched", n)
# variants
variants = [
 {"id":"T1.V01","label":"compare single item (sheet)","args":["compare","--items",names[0]]},
 {"id":"T1.V02","label":"compare multi 6 items auto mode","args":["compare","--items",", ".join(names[30:36])]},
 {"id":"T1.V03","label":"compare --no-team-discount (raw prices)","args":["compare","--items",names[0],"--no-team-discount"]},
 {"id":"T1.V04","label":"compare --extra-discount 10","args":["compare","--items",names[0],"--extra-discount","10"]},
 {"id":"T1.V05","label":"compare --team-discount explicit","args":["compare","--items",names[0],"--team-discount"]},
 {"id":"T1.V06","label":"compare not-on-sheet item (live fallback expected)","args":["compare","--items","Duracell AAA batteries 8 pack"]},
 {"id":"T1.V07","label":"compare junk/nonsense item","args":["compare","--items","xyzzy plugh quantum banana 999"]},
 {"id":"T1.V08","label":"compare empty items","args":["compare","--items",""]},
 {"id":"T1.V09","label":"compare multi-buy priced sheet item","args":["compare","--items",", ".join([r["name"] for r in d if "multi-buy" in (r["special_m"]+r["special_n"]).lower()][:3]) or names[0]]},
 {"id":"T1.V10","label":"compare halal meat query","args":["compare","--items","chicken breast"]},
 {"id":"T1.V11","label":"compare misspelled known item","args":["compare","--items","milkk"]},
 {"id":"T1.V12","label":"compare items with quotes/commas stress","args":["compare","--items",'O\'Brien "premium" milk, egg']},
]
json.dump(variants, open("batch_t1_variants.json", "w", encoding="utf-8"), indent=1)
# other analysis commands
analysis = [
 {"id":"T1.A01","label":"specials all","args":["specials"]},
 {"id":"T1.A02","label":"specials woolworths","args":["specials","--store","woolworths"]},
 {"id":"T1.A03","label":"specials coles","args":["specials","--store","coles"]},
 {"id":"T1.A04","label":"rewards","args":["rewards"]},
 {"id":"T1.A05","label":"subcategories","args":["subcategories"]},
 {"id":"T1.A06","label":"analyze savings","args":["analyze","--query","savings"]},
 {"id":"T1.A07","label":"analyze home-brands","args":["analyze","--query","home-brands"]},
 {"id":"T1.A08","label":"analyze categories","args":["analyze","--query","categories"]},
 {"id":"T1.A09","label":"recipe French toast","args":["recipe","--name","French toast","--ingredients","bread, eggs, milk, sugar"]},
 {"id":"T1.A10","label":"optimize sheet-priced 6 items","args":["optimize","--items",", ".join(names[40:46])]},
 {"id":"T1.A11","label":"optimize refuse <5 items","args":["optimize","--items","milk, bread"]},
 {"id":"T1.A12","label":"optimize --min-saving 50 (force split view)","args":["optimize","--items",", ".join(names[50:55]),"--min-saving","50"]},
 {"id":"T1.A13","label":"optimize --confirm none (no writes)","args":["optimize","--items",", ".join(names[60:65]),"--confirm","none"]},
 {"id":"T1.A14","label":"lists","args":["lists"]},
 {"id":"T1.A15","label":"lists --full","args":["lists","--full"]},
 {"id":"T1.A16","label":"no-price","args":["no-price"]},
 {"id":"T1.A17","label":"missed-pricing show","args":["missed-pricing"]},
 {"id":"T1.A18","label":"unmapped","args":["unmapped"]},
 {"id":"T1.A19","label":"todo show","args":["todo","show"]},
 {"id":"T1.A20","label":"searched-items retired notice","args":["searched-items"]},
]
json.dump(analysis, open("batch_t1_analysis.json", "w", encoding="utf-8"), indent=1)
print("variants+analysis written")
