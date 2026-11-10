#!/usr/bin/env python3
"""МХБ-ийн биелсэн хэлцлийг өдөр бүр татаж data/deals_YYYY-MM-DD.xlsx файлд хадгална.

Файл бүр: "ALL" хуудас (бүх компани) + компани бүрийн тусдаа хуудас.
Дахин ажиллуулбал хэлцлийн ID-аар давхардлыг арилгаж нэгтгэнэ.
"""
#!/usr/bin/env python3
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from openpyxl import Workbook, load_workbook

API = "https://api.marketinfo.mn/api/mse"
OUT_DIR = Path(os.environ.get("OUT_DIR", "data"))
SSL_CTX = ssl._create_unverified_context()

CODES = [
    "AARD", "ADB", "APU", "CUMN", "GLMT", "INV", "KHAN", "LEND", "MFC", "MNDL",
    "MSE", "QPAY", "SBM", "TDB", "TTL", "TUM", "XAC", "ERDN", "GAZR", "MFG",
]

HEADERS = ["Огноо цаг", "Symbol", "Үнэ (₮)", "Ширхэг", "Дүн (₮)", "Нөхцөл", "ID"]


def get_json(url, tries=4):
    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if i == tries - 1:
                body = e.read().decode("utf-8", errors="replace")[:300]
                print(f"HTTP алдаа ({url}): код={e.code}, хариу={body}")
                raise
            time.sleep(3 * (i + 1))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def short_sym(sym):
    t = str(sym)
    m = re.fullmatch(r"([A-Za-z]+)-O-\d+", t) or re.fullmatch(r"([A-Za-z]+)-\d+", t)
    return m.group(1) if m else t


def build_code_map():
    codes, names = {}, {}
    try:
        for t in get_json(API + "/trades"):
            if t.get("symbol") and t.get("companycode") is not None:
                codes[t["symbol"]] = t["companycode"]
    except Exception as e:
        print("trades татаж чадсангүй:", e)
    try:
        for c in get_json(API + "/companies"):
            code = c.get("companycode", c.get("code"))
            if c.get("symbol") and code is not None:
                codes.setdefault(c["symbol"], code)
            if c.get("symbol") and (c.get("name") or c.get("companyName")):
                names[c["symbol"]] = c.get("name") or c.get("companyName")
    except Exception as e:
        print("companies татаж чадсангүй:", e)
    return codes, names


def parse_dt(day, time_str):
    t = (time_str or "").strip()
    if not t or t == "null":
        t = "00:00:00"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(f"{day} {t}", fmt)
        except ValueError:
            pass
    return datetime.strptime(day, "%Y-%m-%d")


def to_row(r):
    day = str(r.get("dates", ""))[:10]
    px = float(r["mdEntryPx"])
    sz = float(r["mdEntrySize"])
    cond = r.get("tradeCondition")
    cond = "" if cond in (None, "null") else cond
    val_sz = int(sz) if sz == int(sz) else sz
    row = [parse_dt(day, r.get("mdEntryTime")), short_sym(r["symbol"]), px, val_sz, px * sz, cond, r["id"]]
    return day, row


def read_existing(path):
    if not path.exists():
        return {}
    ws = load_workbook(path, read_only=True)["ALL"]
    rows = {}
    for i, r in enumerate(ws.iter_rows(values_only=True)):
        if i == 0 or r[6] is None:
            continue
        row = list(r[:7])
        row[1] = short_sym(row[1])
        rows[r[6]] = row
    return rows


def fill(ws, rows):
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    for i, w in enumerate([20, 14, 14, 12, 16, 20, 12], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    for row in ws.iter_rows(min_row=2):
        row[0].number_format = "yyyy-mm-dd hh:mm:ss"
        row[2].number_format = "#,##0.00"
        row[3].number_format = "#,##0"
        row[4].number_format = "#,##0.00"
    ws.freeze_panes = "A2"


def write_xlsx(path, rows_by_id):
    rows = sorted(rows_by_id.values(), key=lambda r: (r[0], r[6]))
    wb = Workbook()
    ws = wb.active
    ws.title = "ALL"
    fill(ws, rows)
    by_sym = defaultdict(list)
    for r in rows:
        by_sym[r[1]].append(r)
    for sym in sorted(by_sym):
        fill(wb.create_sheet(sym[:31]), by_sym[sym])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def save_names(names, targets):
    path = OUT_DIR / "companies.json"
    try:
        cur = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        cur = {}
    for sym, _ in targets:
        if names.get(sym):
            cur[short_sym(sym)] = names[sym]
    if cur:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    code_map, names = build_code_map()
    targets, missing = [], []
    for code in CODES:
        syms = [s for s in code_map if s.startswith(code + "-O-")]
        if syms:
            for s in sorted(syms):
                targets.append((s, code_map[s]))
        else:
            missing.append(code)
    if missing:
        print("Тоон код олдсонгүй (алгасав):", ", ".join(missing))

    save_names(names, targets)

    by_day = defaultdict(dict)
    failed = []
    for sym, num in targets:
        try:
            rows = get_json(f"{API}/deals/{num}/{urllib.parse.quote(sym)}")
            for r in rows if isinstance(rows, list) else []:
                day, row = to_row(r)
                by_day[day][row[6]] = row
            print(f"{sym}: {len(rows) if isinstance(rows, list) else 0} хэлцэл")
        except Exception as e:
            failed.append(sym)
            print(f"{sym}: АЛДАА {e}")

    for day, new_rows in by_day.items():
        path = OUT_DIR / f"deals_{day}.xlsx"
        merged = read_existing(path)
        merged.update(new_rows)
        write_xlsx(path, merged)
        print(f"Хадгаллаа: {path} ({len(merged)} мөр)")

    if not by_day:
        print("Хадгалах хэлцэл олдсонгүй.")
    if not targets or failed:
        print("Амжилтгүй:", ", ".join(failed) if failed else "Компанийн жагсаалт татагдсангүй")
        return 1
    return 0


if __name__ == "__main__":
    rc = main()
    if "ipykernel" not in sys.modules:
        sys.exit(rc)
