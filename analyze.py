#!/usr/bin/env python3
"""МХБ-ийн хэлцлийн шинжилгээ.

    python analyze.py daily  [YYYY-MM-DD]   # өдрийн шинжилгээ (анхдагч: сүүлийн өгөгдөлтэй өдөр)
    python analyze.py weekly [YYYY-MM-DD]   # тухайн өдөр агуулсан 7 хоногийн (Да–Ба) шинжилгээ

Оролт : data/deals_YYYY-MM-DD.xlsx   (collect.py үүсгэсэн)
Гаралт: reports/daily_*.xlsx|txt, reports/weekly_*.xlsx|txt, reports/latest_daily.txt, latest_weekly.txt
"""
import os
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
REPORT_DIR = Path(os.environ.get("REPORT_DIR", "reports"))
BLOCK_VALUE = float(os.environ.get("BLOCK_VALUE", 10_000_000))  # том хэлцлийн босго (₮)
JUMP_PCT = float(os.environ.get("JUMP_PCT", 2.0))               # үнийн үсрэлтийн босго (%)
MIN_DEALS = 5                                                   # өсөлт/уналтын жагсаалтад орох хамгийн бага хэлцэл

WEEKDAYS = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]
DISCLAIMER = "⚠️ Энэ нь хөрөнгө оруулалтын зөвлөгөө биш, зөвхөн биелсэн хэлцлийн статистик тойм юм."
RENAME = {"Огноо цаг": "dt", "Symbol": "sym", "Үнэ (₮)": "px", "Ширхэг": "qty",
          "Дүн (₮)": "val", "Нөхцөл": "cond", "ID": "id"}


# ---------------------------------------------------------------- өгөгдөл унших
def all_days():
    days = []
    for p in DATA_DIR.glob("deals_*.xlsx"):
        m = re.match(r"deals_(\d{4}-\d{2}-\d{2})\.xlsx$", p.name)
        if m:
            days.append(m.group(1))
    return sorted(days)


def load_day(d):
    df = pd.read_excel(DATA_DIR / f"deals_{d}.xlsx", sheet_name="ALL").rename(columns=RENAME)
    df["dt"] = pd.to_datetime(df["dt"])
    df["cond"] = df["cond"].fillna("").astype(str)
    df["day"] = df["dt"].dt.strftime("%Y-%m-%d")
    return df.sort_values(["dt", "id"]).reset_index(drop=True)


def last_prices(d):
    return load_day(d).groupby("sym")["px"].last().to_dict()


# ---------------------------------------------------------------- тооцоолол
def summarize(df, prev_close=None):
    total = df["val"].sum()
    rows = []
    for sym, g in df.groupby("sym"):
        g = g.sort_values(["dt", "id"])
        vol, val = g["qty"].sum(), g["val"].sum()
        o, c = g["px"].iloc[0], g["px"].iloc[-1]
        hi, lo = g["px"].max(), g["px"].min()
        pc = (prev_close or {}).get(sym)
        base, basis = (pc, "өмнөх хаалт") if pc else (o, "нээлт")
        rows.append({
            "Symbol": sym,
            "Хэлцэл": len(g),
            "Ширхэг": int(vol),
            "Эргэлт (₮)": float(val),
            "Эзлэх хувь (%)": val / total * 100 if total else 0.0,
            "Нээлт": o, "Хаалт": c, "Дээд": hi, "Доод": lo,
            "VWAP": val / vol if vol else 0.0,
            "Өмнөх хаалт": pc if pc else None,
            "Өөрчлөлт (%)": (c / base - 1) * 100 if base else 0.0,
            "Өөрчлөлтийн суурь": basis,
            "Хэлбэлзэл (%)": (hi / lo - 1) * 100 if lo else 0.0,
            "Дундаж хэлцэл (ш)": vol / len(g),
            "Медиан хэлцэл (ш)": float(g["qty"].median()),
            "Хамгийн том хэлцэл (ш)": int(g["qty"].max()),
            "Том хэлцэл (тоо)": int((g["val"] >= BLOCK_VALUE).sum()),
        })
    return pd.DataFrame(rows).sort_values("Эргэлт (₮)", ascending=False).reset_index(drop=True)


def block_table(df, n=50):
    b = df[df["val"] >= BLOCK_VALUE].sort_values("val", ascending=False).head(n)
    return b[["dt", "sym", "px", "qty", "val", "cond"]].rename(columns={
        "dt": "Огноо цаг", "sym": "Symbol", "px": "Үнэ (₮)", "qty": "Ширхэг", "val": "Дүн (₮)", "cond": "Нөхцөл"})


def jump_table(df, n=100):
    d = df.sort_values(["sym", "dt", "id"]).copy()
    d["prev"] = d.groupby(["sym", "day"])["px"].shift(1)
    d["chg"] = (d["px"] / d["prev"] - 1) * 100
    j = d[d["chg"].abs() >= JUMP_PCT].copy()
    j["_a"] = j["chg"].abs()
    j = j.sort_values("_a", ascending=False).head(n)
    return j[["dt", "sym", "prev", "px", "chg", "qty"]].rename(columns={
        "dt": "Огноо цаг", "sym": "Symbol", "prev": "Өмнөх хэлцлийн үнэ", "px": "Үнэ (₮)",
        "chg": "Өөрчлөлт (%)", "qty": "Ширхэг"})


def hourly(df):
    h = df.assign(h=df["dt"].dt.hour).groupby("h").agg(
        deals=("id", "count"), qty=("qty", "sum"), val=("val", "sum")).reset_index()
    h["Цаг"] = h["h"].map(lambda x: f"{x:02d}:00–{x:02d}:59")
    h["Эзлэх хувь (%)"] = h["val"] / h["val"].sum() * 100
    return h[["Цаг", "deals", "qty", "val", "Эзлэх хувь (%)"]].rename(columns={
        "deals": "Хэлцэл", "qty": "Ширхэг", "val": "Эргэлт (₮)"})


def condition_table(df):
    c = df[df["cond"] != ""]
    return c[["dt", "sym", "px", "qty", "val", "cond"]].rename(columns={
        "dt": "Огноо цаг", "sym": "Symbol", "px": "Үнэ (₮)", "qty": "Ширхэг", "val": "Дүн (₮)", "cond": "Нөхцөл"})


# ---------------------------------------------------------------- Excel
def save_book(path, sheets):
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            name = name[:31]
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            for cell in ws[1]:
                cell.font = Font(bold=True)
            for i, col in enumerate(df.columns, start=1):
                letter = get_column_letter(i)
                series = df[col]
                if pd.api.types.is_datetime64_any_dtype(series):
                    fmt, width = "yyyy-mm-dd hh:mm:ss", 20
                elif pd.api.types.is_float_dtype(series):
                    fmt = "#,##0.00"
                    width = max([len(str(col))] + [len(f"{v:,.2f}") for v in series.head(200)]) + 2
                elif pd.api.types.is_integer_dtype(series):
                    fmt = "#,##0"
                    width = max([len(str(col))] + [len(f"{v:,}") for v in series.head(200)]) + 2
                else:
                    fmt = None
                    width = max([len(str(col))] + [len(str(v)) for v in series.head(200)]) + 2
                ws.column_dimensions[letter].width = min(max(width, 8), 30)
                if fmt:
                    for cell in ws[letter][1:]:
                        cell.number_format = fmt


# ---------------------------------------------------------------- текст (Facebook-д илгээх)
def mn(x):
    if x >= 1e9:
        return f"{x / 1e9:,.2f} тэрбум ₮"
    if x >= 1e6:
        return f"{x / 1e6:,.1f} сая ₮"
    return f"{x:,.0f} ₮"


def pct(x):
    return f"{x:+.2f}%"


def px(x):
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def wd(day):
    return WEEKDAYS[date.fromisoformat(day).weekday()]


def movers(s, k=3):
    t = s[s["Хэлцэл"] >= MIN_DEALS]
    up = t[t["Өөрчлөлт (%)"] > 0].sort_values("Өөрчлөлт (%)", ascending=False).head(k)
    dn = t[t["Өөрчлөлт (%)"] < 0].sort_values("Өөрчлөлт (%)").head(k)
    return up, dn


def biggest_trade_line(df):
    r = df.loc[df["val"].idxmax()]
    return f"{r['sym']} — {int(r['qty']):,} ш × {px(r['px'])} ₮ = {mn(r['val'])} ({r['dt']:%H:%M:%S})"


def daily_text(day, df, s, hrs):
    total = df["val"].sum()
    basis = "өмнөх арилжааны өдрийн хаалттай" if (s["Өөрчлөлтийн суурь"] == "өмнөх хаалт").any() else "нээлтийн үнэтэй"
    L = [f"📊 МХБ арилжааны тойм — {day} ({wd(day)})",
         f"Нийт {len(df):,} хэлцэл · {mn(total)} · {len(s)} компани арилжигдлаа", ""]
    L.append("🔝 Эргэлтээр тэргүүлсэн:")
    for i, r in s.head(3).iterrows():
        L.append(f"{i + 1}. {r['Symbol']} — {mn(r['Эргэлт (₮)'])} · хаалт {px(r['Хаалт'])} ₮ ({pct(r['Өөрчлөлт (%)'])})")
    up, dn = movers(s)
    if len(up):
        L += ["", f"📈 Өсөлт ({basis} харьцуулсан):"]
        L += [f"• {r['Symbol']} {pct(r['Өөрчлөлт (%)'])} → {px(r['Хаалт'])} ₮" for _, r in up.iterrows()]
    if len(dn):
        L += ["", "📉 Уналт:"]
        L += [f"• {r['Symbol']} {pct(r['Өөрчлөлт (%)'])} → {px(r['Хаалт'])} ₮" for _, r in dn.iterrows()]
    act = s.sort_values("Хэлцэл", ascending=False).iloc[0]
    peak = hrs.sort_values("Эргэлт (₮)", ascending=False).iloc[0]
    top4 = s.head(4)["Эзлэх хувь (%)"].sum()
    L += ["", f"🔁 Хамгийн олон хэлцэл: {act['Symbol']} ({int(act['Хэлцэл'])})",
          f"🐋 Хамгийн том хэлцэл: {biggest_trade_line(df)}",
          f"⏱ Хамгийн идэвхтэй цаг: {peak['Цаг']} ({peak['Эзлэх хувь (%)']:.0f}%)",
          f"🎯 Эргэлтийн төвлөрөл: эхний 4 компани {top4:.0f}%",
          "", DISCLAIMER]
    return "\n".join(L)


def weekly_text(iso_label, week, df, s, mkt, prev_avg):
    total = df["val"].sum()
    L = [f"📊 МХБ 7 хоногийн тойм — {iso_label} ({week[0]} → {week[-1]})",
         f"Нийт {len(df):,} хэлцэл · {mn(total)} · {len(week)} арилжааны өдөр · {len(s)} компани"]
    if prev_avg:
        L.append(f"Өдрийн дундаж эргэлт өмнөх 7 хоногоос {pct((total / len(week) / prev_avg - 1) * 100)}")
    L += ["", "📅 Өдрөөр: " + " · ".join(f"{r['Гараг']} {mn(r['Эргэлт (₮)'])}" for _, r in mkt.iterrows()), ""]
    L.append("🔝 Эргэлтээр тэргүүлсэн:")
    for i, r in s.head(5).iterrows():
        L.append(f"{i + 1}. {r['Symbol']} — {mn(r['Эргэлт (₮)'])} · хаалт {px(r['Хаалт'])} ₮ ({pct(r['Өөрчлөлт (%)'])})")
    up, dn = movers(s)
    basis = "өмнөх 7 хоногийн хаалттай" if (s["Өөрчлөлтийн суурь"] == "өмнөх хаалт").any() else "7 хоногийн нээлттэй"
    if len(up):
        L += ["", f"📈 Өсөлт ({basis} харьцуулсан):"]
        L += [f"• {r['Symbol']} {pct(r['Өөрчлөлт (%)'])} → {px(r['Хаалт'])} ₮" for _, r in up.iterrows()]
    if len(dn):
        L += ["", "📉 Уналт:"]
        L += [f"• {r['Symbol']} {pct(r['Өөрчлөлт (%)'])} → {px(r['Хаалт'])} ₮" for _, r in dn.iterrows()]
    vol = s[s["Хэлцэл"] >= MIN_DEALS].sort_values("Өдрийн дундаж хэлбэлзэл (%)", ascending=False).head(3)
    act = s.sort_values("Хэлцэл", ascending=False).iloc[0]
    top4 = s.head(4)["Эзлэх хувь (%)"].sum()
    L += ["", "🌊 Хамгийн хэлбэлзэлтэй: " + ", ".join(
        f"{r['Symbol']} ({r['Өдрийн дундаж хэлбэлзэл (%)']:.1f}%/өдөр)" for _, r in vol.iterrows()),
          f"🔁 Хамгийн олон хэлцэл: {act['Symbol']} ({int(act['Хэлцэл']):,})",
          f"🐋 Хамгийн том хэлцэл: {biggest_trade_line(df)}",
          f"🎯 Эргэлтийн төвлөрөл: эхний 4 компани {top4:.0f}%",
          "", DISCLAIMER]
    return "\n".join(L)


def write_text(path, latest_name, text):
    path.write_text(text + "\n", encoding="utf-8")
    shutil.copyfile(path, REPORT_DIR / latest_name)


# ---------------------------------------------------------------- өдөр
def run_daily(arg=None):
    days = all_days()
    if not days:
        print("data/ хавтсанд өгөгдөл алга.")
        return 1
    day = arg or days[-1]
    if day not in days:
        print(f"{day} өдрийн файл олдсонгүй.")
        return 1
    df = load_day(day)
    if df.empty:
        print("Хэлцэл алга.")
        return 1
    earlier = [d for d in days if d < day]
    prev = last_prices(earlier[-1]) if earlier else None
    s = summarize(df, prev)
    hrs = hourly(df)
    sheets = {
        "Тойм": s,
        "Цагаар": hrs,
        "Том хэлцэл": block_table(df),
        "Үнийн үсрэлт": jump_table(df),
        "Нөхцөлтэй хэлцэл": condition_table(df),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    save_book(REPORT_DIR / f"daily_{day}.xlsx", sheets)
    write_text(REPORT_DIR / f"daily_{day}.txt", "latest_daily.txt", daily_text(day, df, s, hrs))
    print(f"Өдрийн шинжилгээ бэлэн: {REPORT_DIR}/daily_{day}.xlsx")
    return 0


# ---------------------------------------------------------------- 7 хоног
def run_weekly(arg=None):
    days = all_days()
    if not days:
        print("data/ хавтсанд өгөгдөл алга.")
        return 1
    ref = date.fromisoformat(arg or days[-1])
    monday = ref - timedelta(days=ref.weekday())
    week = [d for d in days if monday <= date.fromisoformat(d) <= monday + timedelta(days=6)]
    if not week:
        print("Тухайн 7 хоногт өгөгдөл алга.")
        return 1
    df = pd.concat([load_day(d) for d in week], ignore_index=True).sort_values(["dt", "id"]).reset_index(drop=True)

    before = [d for d in days if date.fromisoformat(d) < monday]
    prev = last_prices(before[-1]) if before else None
    s = summarize(df, prev)

    grp = df.groupby(["sym", "day"])
    dclose = grp["px"].last().unstack("day")
    dval = grp["val"].sum().unstack("day").fillna(0.0)
    rng = grp["px"].agg(["max", "min"])
    rng["r"] = (rng["max"] / rng["min"] - 1) * 100
    ffilled = dclose.ffill(axis=1)
    ret = (ffilled / ffilled.shift(1, axis=1) - 1) * 100

    s["Арилжсан өдөр"] = s["Symbol"].map(dclose.notna().sum(axis=1)).astype(int)
    s["Өдрийн дундаж эргэлт (₮)"] = s["Эргэлт (₮)"] / len(week)
    s["Өдрийн дундаж хэлбэлзэл (%)"] = s["Symbol"].map(rng.groupby("sym")["r"].mean())
    s["Өдрийн өгөөжийн σ (%)"] = s["Symbol"].map(ret.std(axis=1))
    s["Хамгийн идэвхтэй өдөр"] = s["Symbol"].map(dval.idxmax(axis=1)).map(wd)

    mkt = df.groupby("day").agg(deals=("id", "count"), qty=("qty", "sum"), val=("val", "sum")).reset_index()
    mkt["Гараг"] = mkt["day"].map(wd)
    mkt["Өмнөх өдрөөс (%)"] = (mkt["val"] / mkt["val"].shift(1) - 1) * 100
    mkt = mkt.rename(columns={"day": "Огноо", "deals": "Хэлцэл", "qty": "Ширхэг", "val": "Эргэлт (₮)"})[
        ["Огноо", "Гараг", "Хэлцэл", "Ширхэг", "Эргэлт (₮)", "Өмнөх өдрөөс (%)"]]

    turn = dval.copy()
    turn["Нийт"] = turn.sum(axis=1)
    turn = turn.sort_values("Нийт", ascending=False).rename_axis(index="Symbol", columns=None).reset_index()
    close_tbl = dclose.rename_axis(index="Symbol", columns=None).reset_index()

    sheets = {"Тойм": s, "Зах зээл өдрөөр": mkt, "Эргэлт өдрөөр": turn, "Өдрийн хаалт": close_tbl}
    if len(week) >= 4:  # 3+ өдрийн өгөөж байж хамаарал утга агуулна
        corr = ret.T.corr(min_periods=3).round(2).rename_axis(index="Symbol", columns=None).reset_index()
        sheets["Хамаарал"] = corr
    sheets.update({"Том хэлцэл": block_table(df), "Үнийн үсрэлт": jump_table(df),
                   "Цагаар": hourly(df), "Нөхцөлтэй хэлцэл": condition_table(df)})

    iso = monday.isocalendar()
    label = f"{iso.year}-W{iso.week:02d}"
    prev_days = [d for d in days if monday - timedelta(days=7) <= date.fromisoformat(d) < monday]
    prev_avg = sum(load_day(d)["val"].sum() for d in prev_days) / len(prev_days) if prev_days else None

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    save_book(REPORT_DIR / f"weekly_{label}.xlsx", sheets)
    write_text(REPORT_DIR / f"weekly_{label}.txt", "latest_weekly.txt",
               weekly_text(label, week, df, s, mkt, prev_avg))
    print(f"7 хоногийн шинжилгээ бэлэн: {REPORT_DIR}/weekly_{label}.xlsx ({len(week)} өдөр)")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if mode == "daily":
        sys.exit(run_daily(arg))
    if mode == "weekly":
        sys.exit(run_weekly(arg))
    print(__doc__)
    sys.exit(2)
