#!/usr/bin/env python3
"""Shopping-list session state machine (spec §4, plan Phase 2).

ONE batched-questions message per turn (D1), auto-add top live match
for untracked items (D2), price+to-do handshake with the keyword cell
left EMPTY (B2/B3), sheet-label sub-category matching (D4), and
per-invocation sheet-read budget of ONE read (two around a P write).

The CLI (repo root) is the only intended caller; core never imports
the CLI. Live search goes through the extractors directly.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.subcategory import match_subcategory, normalize_subcategory

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SESSION_PATH = DATA_DIR / "shop_session.json"
STALE_HOURS = 24

STORE_ALIASES = {"woolworths": "woolworths", "ww": "woolworths",
                 "wool": "woolworths", "w": "woolworths",
                 "coles": "coles", "c": "coles"}
VALID_STORES = {"woolworths", "coles"}


# ---------------------------------------------------------------- S2.1
def load_session(path=None) -> dict | None:
    """Load the run session; None when absent/corrupt/stale.

    A stale session (> STALE_HOURS old) is discarded and cleared —
    sheet writes already made stay (they are transactional per step).
    """
    path = Path(path) if path else SESSION_PATH
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(
            raw.get("items"), list):
        return None
    if is_stale(raw):
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return raw


def save_session(sess: dict, path=None) -> None:
    """Atomic write (tempfile + os.replace) — queue JSON pattern."""
    path = Path(path) if path else SESSION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(sess, fh, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def clear_session(path=None) -> None:
    """Remove the session file (missing_ok)."""
    path = Path(path) if path else SESSION_PATH
    try:
        path.unlink()
    except OSError:
        pass


def is_stale(sess: dict, *, now=None) -> bool:
    """True when the run started > STALE_HOURS ago."""
    try:
        started = datetime.fromisoformat(str(sess.get("run_id")))
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return now - started > timedelta(hours=STALE_HOURS)


# ---------------------------------------------------------------- S2.2
def _classify_item(item: str, rows: list[dict]) -> dict:
    """Classify ONE item against ONE sheet snapshot (plan S2.2)."""
    from core.preferences import get_preferred, PREFERRED_MARK

    sheet_labels: list[str] = []
    norm_names: dict[str, dict] = {}
    for r in rows:
        if r["subcategory"]:
            sheet_labels.append(r["subcategory"])
        norm_names.setdefault(normalize_subcategory(r["name"]), r)

    base = {"raw": item, "resolved_name": "", "row_index": None,
            "user_name": "", "store": "", "question_id": None,
            "options": [], "live_done": False, "auto_add": None,
            "subcategory": "", "note": ""}

    label = match_subcategory(item, sheet_labels)
    if label:
        members = [r for r in rows if r["subcategory"] == label]
        if not members:
            out = dict(base, stage="ask_live", subcategory=label)
            return out
        flagged = [r for r in members
                   if r["preferred"] == "P"]
        if len(flagged) > 1:  # topmost P wins (§8.3)
            flagged = [min(flagged, key=lambda r: r["row_index"])]
        if flagged:
            return dict(base, stage="priced", subcategory=label,
                        resolved_name=flagged[0]["name"],
                        row_index=flagged[0]["row_index"])
        return dict(base, stage="ask_pick", subcategory=label,
                    options=[[r["row_index"], r["name"],
                              r["item_code"]] for r in members])

    hit = norm_names.get(normalize_subcategory(item))
    if hit is not None:
        return dict(base, stage="priced", resolved_name=hit["name"],
                    row_index=hit["row_index"],
                    subcategory=hit["subcategory"] or "")
    return dict(base, stage="ask_live")


def start_run(worksheet, items: list[str]) -> dict:
    """Start a run: ONE read_qrs, classify every item, assign qids.

    Multi-P detection mirrors preferences (topmost P wins, note kept
    on the session). The halal gate for priced names is applied by the
    CLI layer exactly as _cmd_shop does today.
    """
    from core.preferences import read_qrs
    rows = read_qrs(worksheet)
    run_items = [_classify_item(i, rows) for i in items]
    qid = 1
    for it in run_items:
        if it["stage"] in ("ask_pick", "ask_live"):
            it["question_id"] = qid
            qid += 1
    return {"run_id": datetime.now(timezone.utc)
            .isoformat(timespec="seconds"),
            "items": run_items, "next_qid": qid}


# ---------------------------------------------------------------- S2.3
def build_questions(sess: dict) -> list[dict]:
    """Ordered pending questions (stable qids stored per item)."""
    out: list[dict] = []
    for it in sess["items"]:
        if it["stage"] == "ask_pick":
            out.append({"qid": it["question_id"], "kind": "pick",
                        "item": it["raw"], "options": it["options"]})
        elif it["stage"] == "ask_store":
            out.append({"qid": it["question_id"], "kind": "store",
                        "item": it["raw"], "name": it["user_name"],
                        "note": it.get("note", "")})
        elif it["stage"] == "ask_live" and not it["live_done"]:
            out.append({"qid": it["question_id"], "kind": "live",
                        "item": it["raw"]})
        elif it["stage"] == "ask_label":
            out.append({"qid": it["question_id"], "kind": "label",
                        "item": it["raw"],
                        "label": it.get("subcategory", "")})
    return out


def render_questions(questions: list[dict]) -> str:
    """EXACT template (spec §4.9) — the ONE questions message."""
    if not questions:
        return ""
    lines = [f"🛒 SHOPPING LIST — {len(questions)} question(s)"]
    for q in questions:
        n = q["qid"]
        if q["kind"] == "pick":
            opts = q["options"]
            rendered = " · ".join(
                f"{i}={name} [{code}]"
                for i, (_row, name, code) in enumerate(opts, 1))
            note = (f"{n}. {q['item']} — preferred? {rendered} "
                    f"(or type a name)")
        elif q["kind"] == "store":
            note = (f"{n}. '{q['name']}' — woolworths or coles?")
            if q.get("note"):
                note += f" ({q['note']})"
        elif q["kind"] == "live":
            note = f"{n}. {q['item']} — not tracked. Live search now? (y/n)"
        else:  # label
            note = (f"{n}. {q['item']} — new row label: "
                    f"'{q['label']}' ok? (y / type label / review)")
        lines.append(note)
    lines.append("Reply like: " + ", ".join(
        f"{q['qid']}=" + {"pick": "1", "store": "coles",
                          "live": "y", "label": "y"}[q["kind"]]
        for q in questions))
    return "\n".join(lines)


def parse_answers(text: str) -> dict[int, str]:
    """'1=2; 2=woolworths; 3=y' -> {1:'2', 2:'woolworths', 3:'y'}.

    Splits on ';' or newline; each part is '<qid>=<value>' split on
    the FIRST '='. Unknown/invalid parts are ignored by the caller
    via the applied log (here: silently skipped)."""
    out: dict[int, str] = {}
    for part in re.split(r"[;\n]+", str(text or "")):
        part = part.strip()
        if not part or "=" not in part:
            continue
        qid_raw, value = part.split("=", 1)
        qid_raw = qid_raw.strip()
        if not qid_raw.isdigit():
            continue
        if not value.strip():
            continue  # a bare "2=" is not an answer
        out[int(qid_raw)] = value.strip()
    return out


# ------------------------------------------------------------- S2.4
def _live_pair(query: str, page_size: int = 3) -> tuple[list, list,
                                                          str]:
    """Both stores ranked (thin core-side mirror of the CLI helper)."""
    from extractors.woolworths_extractor import \
        fetch_woolworths_search_noauth
    from extractors.coles_extractor import fetch_coles_search_status
    from core.lookup import rank_live_results

    ww_items: list = []
    try:
        ww_items = fetch_woolworths_search_noauth(query,
                                                  page_size=page_size)
    except Exception:
        ww_items = []
    coles_items: list = []
    coles_status = "unavailable"
    try:
        coles_items, coles_status = fetch_coles_search_status(
            query, page_size=page_size)
    except Exception:
        coles_items = []
    return (rank_live_results(query, ww_items),
            rank_live_results(query, coles_items or []),
            coles_status)


def _resolve_unit(raw_name: str, size: str) -> str:
    """Unit for a new row: live size -> name parse -> marker."""
    if size and str(size).strip():
        return str(size).strip()
    m = re.search(
        r"(\d+(?:\.\d+)?\s*(?:kg|g|ml|l|pack|pk|packs)\b)",
        raw_name, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return "unit unavailable"


def _handshake(worksheet, item: dict, query: str, store: str,
               log: list[str], alias: str = "") -> dict:
    """User-name / auto-add handshake (B2/B3, D2).

    Live-search `query` at `store`; write PRICE (+ new row when
    genuinely new); queue the to-do entry remembering the exact store
    name; the keyword column stays EMPTY until `todo done`.
    """
    from core.add_to_list import add_entry
    from core.sheets_sync import add_product_row, update_single_price

    ww_ranked, coles_ranked, status = _live_pair(query)
    ranked = ww_ranked if store == "woolworths" else coles_ranked
    if not ranked:
        # the answered store failed — fall back to the other store's
        # top result rather than dropping the item (B8: the name is
        # still the user's; the store switch is announced).
        other = coles_ranked if store == "woolworths" else ww_ranked
        if other:
            log.append(f"⚠️ {store} search unavailable — used the "
                       f"other store's top result for '{query}'.")
            ranked = other
    if not ranked:
        log.append(f"⚠️ '{query}' not found live at {store} — give "
                   f"another name or skip.")
        item["stage"] = "ask_store"
        item["user_name"] = query
        item["store"] = store
        item["note"] = f"not found live at {store}"
        return {"added": False}

    chosen = ranked[0]
    unit = _resolve_unit(chosen.raw_name,
                         getattr(chosen, "size", "") or "")
    if chosen.price and chosen.price > 0:
        res = add_product_row(
            generic_name=chosen.raw_name,
            store=store,
            price=chosen.price,
            brand=getattr(chosen, "brand", "") or "",
            size=unit,
            category=getattr(chosen, "category", "") or "",
            store_keyword="",          # B2/B3: keyword NEVER written
            alias=alias,
            is_special=bool(getattr(chosen, "is_special", False)),
            special_desc=str(getattr(chosen, "special_desc", "") or ""),
            subcategory=item.get("subcategory") or "",
        )
        created = not res.get("merged")
        row_index = res.get("row_index")
        generic = (res.get("existing_name") if res.get("merged")
                   else chosen.raw_name)
        prev_price = ""
        if res.get("merged") and row_index:
            # capture the price we are about to overwrite (undo path)
            vals = worksheet.get_all_values()
            if row_index - 1 < len(vals):
                col_i = 4 if store == "coles" else 3
                prow = vals[row_index - 1]
                prev_price = (str(prow[col_i]).strip()
                              if len(prow) > col_i else "")
        log.append(
            f"✔ {chosen.raw_name} · {store} ${chosen.price:.2f} — "
            f"{'new row ' + str(row_index) if created else 'row ' + str(row_index) + ' price updated'}")
    else:
        log.append(f"⚠️ '{query}' live price unusable ($0) — row NOT "
                   f"written; item stays open.")
        item["stage"] = "ask_store"
        item["user_name"] = query
        item["store"] = store
        return {"added": False}

    q = add_entry(store=store, keyword=chosen.raw_name,
                  generic_name=generic, size=unit)
    entry = q["entry"]
    item["auto_add"] = {"code": entry.get("code", ""),
                        "row_index": row_index,
                        "created_row": created,
                        "prev_price": prev_price}
    item["stage"] = "priced"
    item["resolved_name"] = generic
    item["row_index"] = row_index
    item["live_done"] = True
    log.append(f"Queued on the TO-DO list: '{chosen.raw_name}' "
               f"({store.capitalize()}) [{entry.get('code', '')}] — "
               f"reply 'wrong {entry.get('code', '')}' to undo.")
    return {"added": True, "code": entry.get("code", ""),
            "entry": entry}


def apply_answers(worksheet, sess: dict,
                  answers: dict[int, str]) -> tuple[dict, list[str]]:
    """Apply the user's ONE reply (plan S2.4). Returns
    (session, log_lines). ONE read_qrs refresh at the start;
    set_preferred may verify-read after its write."""
    from core.preferences import read_qrs, set_preferred

    log: list[str] = []
    by_qid = {it.get("question_id"): it for it in sess["items"]}
    for qid in sorted(answers):
        value = answers[qid]
        item = by_qid.get(qid)
        if item is None:
            log.append(f"⚠️ answer {qid} ignored — no such question.")
            continue
        kind = ("pick" if item["stage"] == "ask_pick"
                else "store" if item["stage"] == "ask_store"
                else "live" if item["stage"] == "ask_live"
                else "label" if item["stage"] == "ask_label" else "")

        if value.strip().lower() == "skip":
            item["stage"] = "skipped"
            log.append(f"– {item['raw']}: skipped.")
            continue

        if kind == "pick":
            opts = item["options"]
            code = value.strip().upper()
            picked = None
            if value.strip().isdigit() and \
                    1 <= int(value.strip()) <= len(opts):
                picked = opts[int(value.strip()) - 1]
            else:
                picked = next((o for o in opts
                               if str(o[2]).upper() == code), None)
            if picked is not None:
                res = set_preferred(worksheet, str(picked[2]))
                if res.get("wrote"):
                    item["stage"] = "priced"
                    item["resolved_name"] = picked[1]
                    item["row_index"] = picked[0]
                    log.append(f"✔ {item['raw']}: preferred set to "
                               f"{picked[1]} [{picked[2]}].")
                else:
                    log.append(f"⚠️ {item['raw']}: prefer failed "
                               f"({res.get('error')}).")
            else:
                # free text -> a specific product name; ask the store
                item["stage"] = "ask_store"
                item["user_name"] = value.strip()
                item["question_id"] = item["question_id"]
                log.append(f"? {item['raw']}: '{value.strip()}' — "
                           f"which store?")

        elif kind == "store":
            store = STORE_ALIASES.get(value.strip().lower())
            if store is None:
                log.append(f"⚠️ answer {qid} ignored — expected "
                           f"woolworths or coles.")
                continue
            item["store"] = store
            _handshake(worksheet, item, item["user_name"], store, log,
                       alias=item["user_name"])

        elif kind == "live":
            if value.strip().lower() in ("y", "yes"):
                ww_r, coles_r, _status = _live_pair(item["raw"])
                ranked = ww_r or coles_r
                store = "woolworths" if ww_r else "coles"
                if not ranked:
                    item["live_done"] = True
                    item["stage"] = "skipped"
                    log.append(f"⚠️ {item['raw']}: nothing found live "
                               f"— skipped.")
                    continue
                # D2: auto-add the top match
                _handshake_auto(worksheet, item, ranked[0], store, log)
            else:
                item["stage"] = "skipped"
                log.append(f"– {item['raw']}: skipped (no live "
                           f"search).")

        elif kind == "label":
            v = value.strip()
            if v.lower() in ("y", "yes"):
                pass  # keep matched label
            elif v.lower() == "review":
                item["subcategory"] = "needs review"
            else:
                item["subcategory"] = v
            item["stage"] = "priced" if item.get("resolved_name") \
                else "skipped"

    sess["next_qid"] = max(
        [it["question_id"] or 0 for it in sess["items"]] + [0]) + 1
    return sess, log


def _handshake_auto(worksheet, item: dict, chosen, store: str,
                    log: list[str]) -> None:
    """Auto-add path of the handshake (D2): a ranked live result."""
    from core.add_to_list import add_entry
    from core.sheets_sync import add_product_row

    unit = _resolve_unit(chosen.raw_name,
                         getattr(chosen, "size", "") or "")
    if not (chosen.price and chosen.price > 0):
        item["stage"] = "skipped"
        item["live_done"] = True
        log.append(f"⚠️ {item['raw']}: live price unusable ($0) — "
                   f"skipped.")
        return
    res = add_product_row(
        generic_name=chosen.raw_name,
        store=store,
        price=chosen.price,
        brand=getattr(chosen, "brand", "") or "",
        size=unit,
        category=getattr(chosen, "category") or "",
        store_keyword="",              # B2/B3
        alias=item["raw"],
        is_special=bool(getattr(chosen, "is_special", False)),
        special_desc=str(getattr(chosen, "special_desc", "") or ""),
        subcategory="",
    )
    created = not res.get("merged")
    row_index = res.get("row_index")
    generic = (res.get("existing_name") if res.get("merged")
               else chosen.raw_name)
    prev_price = ""
    if res.get("merged") and row_index:
        vals = worksheet.get_all_values()
        if row_index - 1 < len(vals):
            col_i = 4 if store == "coles" else 3
            prow = vals[row_index - 1]
            prev_price = (str(prow[col_i]).strip()
                          if len(prow) > col_i else "")
    q = add_entry(store=store, keyword=chosen.raw_name,
                  generic_name=generic, size=unit)
    entry = q["entry"]
    item["auto_add"] = {"code": entry.get("code", ""),
                        "row_index": row_index,
                        "created_row": created,
                        "prev_price": prev_price}
    item["stage"] = "priced"
    item["resolved_name"] = generic
    item["row_index"] = row_index
    item["live_done"] = True
    item["store"] = store
    log.append(f"✔ {item['raw']}: added '{chosen.raw_name}' · "
               f"{store} ${chosen.price:.2f} — to-do "
               f"[{entry.get('code', '')}] (reply 'wrong "
               f"{entry.get('code', '')}' to undo).")


# ---------------------------------------------------------------- S2.5
def render_final_list(worksheet, sess: dict) -> str:
    """Re-price priced items from ONE read; EXACT template (§4.9)."""
    from core.woolworths_discounts import (
        discounted_woolworths_price, is_woolworths_home_brand,
    )

    values = worksheet.get_all_values()
    lines2: list[str] = []
    todo_names: list[str] = []
    skipped: list[str] = []
    ww_total = 0.0
    coles_total = 0.0
    n = 0
    for it in sess["items"]:
        if it["stage"] == "skipped":
            skipped.append(it["raw"])
            continue
        if it["stage"] != "priced" or not it.get("row_index"):
            skipped.append(it["raw"])
            continue
        ri = it["row_index"]
        row = values[ri - 1] if ri - 1 < len(values) else []
        if not row:
            skipped.append(it["raw"])
            continue

        def _num(cell: str) -> float | None:
            try:
                v = float(str(cell).strip()
                          .replace("A$", "").replace("$", ""))
                return v if v > 0 else None
            except (ValueError, TypeError):
                return None

        name = str(row[0]).strip() if len(row) > 0 else ""
        size = str(row[2]).strip() if len(row) > 2 else ""
        brand = str(row[6]).strip() if len(row) > 6 else ""
        ww = _num(row[3]) if len(row) > 3 else None
        coles = _num(row[4]) if len(row) > 4 else None

        is_home = is_woolworths_home_brand(name, brand)
        ww_disp = ""
        if ww is not None:
            d = discounted_woolworths_price(ww, is_home)
            ww_disp = f"${d['final']:.2f}" + (" 🏠" if is_home else "")
            ww_total += d["final"]
        coles_disp = f"${coles:.2f}" if coles is not None \
            else "not tracked"
        if coles is not None:
            coles_total += coles

        base = (f"{n + 1}. {name}"
                + (f" · {size}" if size else "")
                + f" · 🟢 {ww_disp or '—'}"
                + f" · 🔴 {coles_disp}")
        if ww is not None and coles is not None and ww != coles:
            winner = "WW" if ww < coles else "Coles"
            base += f" · 🏆 {winner} −${abs(ww - coles):.2f}"
        lines2.append(base)
        n += 1

    seen_codes: set[str] = set()
    for it in sess["items"]:
        aa = it.get("auto_add") or {}
        code = aa.get("code", "")
        if code and code not in seen_codes:
            seen_codes.add(code)
            todo_names.append(f"{it['resolved_name']} [{code}]")

    out = [f"🛒 YOUR SHOPPING LIST ({n} item(s))"] + lines2
    out.append(f"📊 WW total ${ww_total:.2f} · Coles total "
               f"${coles_total:.2f}")
    out.append("📋 To-do (add on website): "
               + (" · ".join(todo_names) if todo_names else "none"))
    if skipped:
        out.append("⚠️ Skipped: " + ", ".join(skipped))
    return "\n".join(out)


# ---------------------------------------------------------------- S2.6
def undo_auto_add(worksheet, code: str) -> dict:
    """Reverse ONE auto-add by to-do code (plan S2.6)."""
    from core.add_to_list import remove_by_code

    sess = load_session()
    if sess is None:
        return {"undone": False, "detail": "no pending run"}
    code_u = str(code or "").strip().upper()
    target = None
    for it in sess["items"]:
        aa = it.get("auto_add") or {}
        if str(aa.get("code", "")).upper() == code_u:
            target = it
            break
    if target is None:
        return {"undone": False,
                "detail": f"code {code_u} is not an auto-add of this "
                          f"run"}
    aa = target["auto_add"]
    detail = ""
    if aa.get("created_row") and aa.get("row_index"):
        try:
            worksheet.delete_rows(aa["row_index"])
            detail = f"row {aa['row_index']} deleted"
        except Exception as exc:  # noqa: BLE001 — report, keep going
            return {"undone": False,
                    "detail": f"row delete failed: {exc}"}
    elif aa.get("row_index") and aa.get("prev_price") is not None:
        try:
            worksheet.update(
                values=[[aa.get("prev_price", "")]],
                range_name=f"{'D' if target.get('store') != 'coles' else 'E'}{aa['row_index']}")
            detail = f"row {aa['row_index']} price restored"
        except Exception as exc:  # noqa: BLE001
            return {"undone": False,
                    "detail": f"price restore failed: {exc}"}
    try:
        remove_by_code(code_u)
        detail += " + to-do entry removed"
    except ValueError as exc:
        detail += f" (to-do: {exc})"
    target["auto_add"] = None
    target["stage"] = "ask_live"
    target["live_done"] = False
    if target.get("question_id") is None:
        target["question_id"] = sess.get("next_qid", 1)
        sess["next_qid"] = target["question_id"] + 1
    save_session(sess)
    return {"undone": True, "detail": detail}
