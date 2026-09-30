#!/usr/bin/env python3
"""МХБ-ийн хэлцлийн шинжилгээ.

    python analyze.py daily  [YYYY-MM-DD]   # өдрийн шинжилгээ (анхдагч: сүүлийн өгөгдөлтэй өдөр)
    python analyze.py weekly [YYYY-MM-DD]   # тухайн өдөр агуулсан 7 хоногийн (Да–Ба) шинжилгээ
    python analyze.py weekly-auto           # автомат: Баасан гарагт энэ 7 хоног, бусад өдөр
                                            # өмнөх 7 хоногийн тайлан дутуу бол нөхөж гаргана

Оролт : data/deals_YYYY-MM-DD.xlsx   (collect.py үүсгэсэн)
Гаралт: reports/daily_*.xlsx|txt, reports/weekly_*.xlsx|txt, reports/latest_daily.txt, latest_weekly.txt

Үнийн тодорхойлолт:
  Хаалт            = тухайн өдрийн (10:00–13:00) НИЙТ хэлцлийн жигнэсэн дундаж ханш (Σ үнэ×ширхэг / Σ ширхэг)
  VWAP             = тайлангийн бүх хугацааны нийт арилжааны жигнэсэн дундаж (өдрийн тайланд хаалттай тэнцүү)
  Албан ёсны хаалт = сүүлийн 1 цагийн хэлцлийн жигнэсэн дундаж (МХБ-ийн нийтэлдэг), лавлагаа болгон хадгална
"""
import os
import re
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
REPORT_DIR = Path(os.environ.get("REPORT_DIR", "reports"))
CLOSE_TIME = os.environ.get("CLOSE_TIME", "13:00")                  # арилжааны төгсгөл
BLOCK_VALUE = float(os.environ.get("BLOCK_VALUE", 10_000_000))      # том хэлцлийн босго (₮)
JUMP_PCT = float(os.environ.get("JUMP_PCT", 2.0))                   # үнийн үсрэлтийн босго (%)
ORDER_SIZE = float(os.environ.get("ORDER_SIZE", 5_000_000))         # хөрвөх чадварын жишиг захиалга (₮)
THIN_PCT = float(os.environ.get("THIN_PCT", 50))                    # захиалга эргэлтийн энэ %-аас дээш бол "сул"
SINGLE_SHARE = float(os.environ.get("SINGLE_SHARE", 25))            # нэг хэлцлийн эзлэх хувийн босго (%)
SINGLE_MOVE = float(os.environ.get("SINGLE_MOVE", 2.0))             # үнийн өөрчлөлтийн босго (%)
CLOSE_GAP = float(os.environ.get("CLOSE_GAP", 1.0))                 # хаалт-VWAP зөрүүний босго (%)
MIN_DEALS = 5

WEEKDAYS = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]
DISCLAIMER = "⚠️ Энэ нь хөрөнгө оруулалтын зөвлөгөө биш, зөвхөн биелсэн хэлцлийн статистик тойм юм."
RENAME = {"Огноо цаг": "dt", "Symbol": "sym", "Үнэ (₮)": "px", "Ширхэг": "qty",
          "Дүн (₮)": "val", "Нөхцөл": "cond", "ID": "id"}
COL_IMPACT = f"{ORDER_SIZE / 1e6:g} сая ₮ захиалга / эргэлт (%)"


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


def official_close(g):
    """Хаалтын ханш: сүүлийн арилжааны өдрийн сүүлийн 1 цагийн жигнэсэн дундаж ханш.
    Сүүлийн 1 цагт хэлцэл байхгүй бол сүүлийн хэлцлийн үнийг авч, суурийг тэмдэглэнэ."""
    gd = g[g["day"] == g["day"].max()]
    end = pd.Timestamp(f"{gd['day'].iloc[0]} {CLOSE_TIME}")
    w = gd[(gd["dt"] > end - pd.Timedelta(hours=1)) & (gd["dt"] <= end)]
    if len(w) and w["qty"].sum() > 0:
        return round(w["val"].sum() / w["qty"].sum(), 2), "сүүлийн 1 цагийн жигнэсэн дундаж"
    return float(gd.sort_values(["dt", "id"])["px"].iloc[-1]), "сүүлийн хэлцэл (сүүлийн 1 цагт хэлцэлгүй)"


def day_stats(d):
    """Өмнөх өдрийн суурь: хаалт = тэр өдрийн нийт хэлцлийн жигнэсэн дундаж ханш."""
    return {sym: {"close": round(g["val"].sum() / g["qty"].sum(), 2)}
            for sym, g in load_day(d).groupby("sym")}


# ---------------------------------------------------------------- тооцоолол
def summarize(df, prev=None):
    total = df["val"].sum()
    rows = []
    for sym, g in df.groupby("sym"):
        g = g.sort_values(["dt", "id"])
        vol, val = g["qty"].sum(), g["val"].sum()
        vwap = val / vol
        gd = g[g["day"] == g["day"].max()]                       # сүүлийн арилжааны өдөр
        close = round(gd["val"].sum() / gd["qty"].sum(), 2)      # хаалт = өдрийн нийт жигнэсэн дундаж
        off, obasis = official_close(g)                          # албан ёсны (сүүлийн 1 цаг)
        o, last = g["px"].iloc[0], g["px"].iloc[-1]
        hi, lo = g["px"].max(), g["px"].min()
        p = (prev or {}).get(sym, {})
        pc, pv = p.get("close"), p.get("vwap")
        base, basis = (pc, "өмнөх хаалт") if pc else (o, "нээлт")
        big = g.loc[g["val"].idxmax()]
        rows.append({
            "Symbol": sym,
            "Хэлцэл": len(g),
            "Ширхэг": int(vol),
            "Эргэлт (₮)": float(val),
            "Эзлэх хувь (%)": val / total * 100 if total else 0.0,
            "Нээлт": o,
            "Сүүлийн хэлцэл": last,
            "Хаалт": close,
            "VWAP": vwap,
            "Албан ёсны хаалт": off,
            "Албан ёсны хаалтын суурь": obasis,
            "Сүүлийн цаг − хаалт (%)": (off / close - 1) * 100,
            "Дээд": hi, "Доод": lo,
            "Өмнөх хаалт": pc,
            "Өмнөх VWAP": pv,
            "Өөрчлөлт (%)": (close / base - 1) * 100 if base else 0.0,
            "Өөрчлөлтийн суурь": basis,
            "VWAP өөрчлөлт (%)": (vwap / pv - 1) * 100 if pv else None,
            "Хэлбэлзэл (%)": (hi / lo - 1) * 100 if lo else 0.0,
            "Дундаж хэлцэл (ш)": vol / len(g),
            "Медиан хэлцэл (ш)": float(g["qty"].median()),
            "Хамгийн том хэлцэл (ш)": int(big["qty"]),
            "Хамгийн том хэлцлийн эзлэх (%)": float(big["val"]) / val * 100,
            "Том хэлцэл (тоо)": int((g["val"] >= BLOCK_VALUE).sum()),
            COL_IMPACT: ORDER_SIZE / val * 100,
        })
    out = pd.DataFrame(rows).sort_values("Эргэлт (₮)", ascending=False).reset_index(drop=True)
    if out["Өмнөх VWAP"].isna().all():  # өдрийн тайланд өмнөх VWAP хэрэггүй (хаалттай адил)
        out = out.drop(columns=["Өмнөх VWAP", "VWAP өөрчлөлт (%)"])
    return out


def definitions():
    return pd.DataFrame({"Нэр томьёо": ["Хаалт", "VWAP", "Албан ёсны хаалт", "Өөрчлөлт (%)", "Сүүлийн цаг − хаалт (%)",
                                        COL_IMPACT],
                         "Тодорхойлолт": [
        "Сүүлийн арилжааны өдрийн (10:00–13:00) НИЙТ хэлцлийн жигнэсэн дундаж ханш = Σ(үнэ×ширхэг) / Σ ширхэг",
        "Тайлангийн бүх хугацааны нийт арилжааны жигнэсэн дундаж ханш (өдрийн тайланд хаалттай тэнцүү)",
        "Сүүлийн 1 цагийн (12:00–13:00) хэлцлийн жигнэсэн дундаж. МХБ-ийн нийтэлдэг хаалттай харьцуулах лавлагаа",
        "Хаалтыг өмнөх арилжааны өдрийн хаалттай харьцуулсан. Өмнөх өдөр байхгүй бол эхний хэлцлийн үнэтэй",
        "Албан ёсны хаалт хаалтаас хэдэн хувиар өндөр/доогуур байна. Төгсгөлийн худалдан авалт, зарлагын хүч",
        "Жишиг захиалга нь өдрийн нийт эргэлтийн хэдэн хувь вэ. Их байх тусам хөрвөх чадвар сул"]})


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


# ---------------------------------------------------------------- тайлангийн текст (Telegram)
def mn(x):
    if x >= 1e9:
        return f"{x / 1e9:,.2f} тэрбум ₮"
    if x >= 1e6:
        return f"{x / 1e6:,.1f} сая ₮"
    return f"{x:,.0f} ₮"


def pct(x):
    return f"{x:+.2f}%"


def px(x):
    return f"{x:,.0f}" if x >= 1000 else f"{x:,.2f}".rstrip("0").rstrip(".")


def wd(day):
    return WEEKDAYS[date.fromisoformat(day).weekday()]


def basis_text(s, weekly=False):
    b = set(s["Өөрчлөлтийн суурь"])
    if b == {"өмнөх хаалт"}:
        return "өмнөх 7 хоногийн хаалттай" if weekly else "өмнөх өдрийн хаалттай"
    if b == {"нээлт"}:
        return "7 хоногийн нээлттэй" if weekly else "нээлтийн үнэтэй"
    return "өмнөх хаалт эсвэл нээлттэй"


def index_lines(s, weekly=False):
    w, ch = s["Эргэлт (₮)"], s["Өөрчлөлт (%)"]
    eq, vw = ch.mean(), (ch * w).sum() / w.sum()
    up, dn = int((ch > 0.05).sum()), int((ch < -0.05).sum())
    contrib = ch * w / w.sum()
    L = ["📈 МХБ-н 20 (индекс)",
         f"Тэнцүү жинтэй {pct(eq)} · эргэлтээр жигнэсэн {pct(vw)} ({basis_text(s, weekly)})",
         f"Өссөн {up} · Унасан {dn} · Хэвээр {len(s) - up - dn}"]
    lo, hi = contrib.idxmin(), contrib.idxmax()
    parts = []
    if contrib[lo] < 0:
        parts.append(f"хамгийн их татсан {s.loc[lo, 'Symbol']} ({contrib[lo]:+.2f} п.п.)")
    if contrib[hi] > 0:
        parts.append(f"хамгийн их түлхсэн {s.loc[hi, 'Symbol']} ({contrib[hi]:+.2f} п.п.)")
    if parts:
        L.append("Индексийг " + ", ".join(parts))
    if abs(vw - eq) >= 0.5:
        L.append("Хоёр индексийн зөрүү их: хөдөлгөөн эргэлт ихтэй цөөн хувьцаанаас хамаарсан.")
    return L


def vwap_lines(s, title, k=5, weekly=False):
    L = [title]
    for _, r in s.head(k).iterrows():
        if weekly:
            L.append(f"• {r['Symbol']}: 7 хоногийн VWAP {px(r['VWAP'])} ₮ · хаалт {px(r['Хаалт'])} ₮ "
                     f"({pct(r['Өөрчлөлт (%)'])}) · {mn(r['Эргэлт (₮)'])}")
        else:
            L.append(f"• {r['Symbol']}: {px(r['Хаалт'])} ₮ ({pct(r['Өөрчлөлт (%)'])}) · {mn(r['Эргэлт (₮)'])}")
    return L


def close_lines(s):
    t = s[s["Хэлцэл"] >= MIN_DEALS]
    weak = t[t["Сүүлийн цаг − хаалт (%)"] <= -CLOSE_GAP].sort_values("Сүүлийн цаг − хаалт (%)").head(3)
    strong = t[t["Сүүлийн цаг − хаалт (%)"] >= CLOSE_GAP].sort_values("Сүүлийн цаг − хаалт (%)", ascending=False).head(3)
    L = []
    if len(weak):
        L.append("🔻 Төгсгөлд суларсан (сүүлийн 1 цагийн ханш хаалтаас доор): " + ", ".join(
            f"{r['Symbol']} {pct(r['Сүүлийн цаг − хаалт (%)'])}" for _, r in weak.iterrows()))
    if len(strong):
        L.append("🔺 Төгсгөлд хүчирхэгжсэн (сүүлийн 1 цагийн ханш хаалтаас дээгүүр): " + ", ".join(
            f"{r['Symbol']} {pct(r['Сүүлийн цаг − хаалт (%)'])}" for _, r in strong.iterrows()))
    return L


def single_lines(s):
    t = s[(s["Өөрчлөлт (%)"].abs() >= SINGLE_MOVE) & (s["Хамгийн том хэлцлийн эзлэх (%)"] >= SINGLE_SHARE)]
    if t.empty:
        return []
    L = ["⚠️ Нэг хэлцлээр хөдөлсөн байж болзошгүй (найдвартай дохио биш):"]
    for _, r in t.sort_values("Өөрчлөлт (%)", key=lambda x: -x.abs()).iterrows():
        L.append(f"• {r['Symbol']} {pct(r['Өөрчлөлт (%)'])} — эргэлтийн {r['Хамгийн том хэлцлийн эзлэх (%)']:.0f}% нь "
                 f"ганц хэлцэл ({int(r['Хамгийн том хэлцэл (ш)']):,} ш), нийт {int(r['Хэлцэл'])} хэлцэл")
    return L


def liquidity_lines(s, span="өдрийн"):
    best = s.sort_values(COL_IMPACT).head(3)
    thin = s[s[COL_IMPACT] >= THIN_PCT].sort_values(COL_IMPACT, ascending=False).head(6)
    L = [f"💧 Хөрвөх чадвар ({ORDER_SIZE / 1e6:g} сая ₮-ийн захиалга {span} эргэлтийн хэдэн хувь вэ)",
         "Хамгийн сайн: " + ", ".join(f"{r['Symbol']} {r[COL_IMPACT]:.1f}%" for _, r in best.iterrows())]
    if len(thin):
        L.append(f"Сул ({THIN_PCT:.0f}%+): " + ", ".join(f"{r['Symbol']} {r[COL_IMPACT]:.0f}%" for _, r in thin.iterrows()))
    return L


def daily_text(day, df, s):
    total = df["val"].sum()
    top4 = s.head(4)["Эзлэх хувь (%)"].sum()
    L = [f"📊 МХБ арилжааны тойм — {day} ({wd(day)})",
         f"Нийт {len(df):,} хэлцэл · {mn(total)} · {len(s)} компани · эхний 4 компани {top4:.0f}%", ""]
    L += index_lines(s) + [""]
    L += vwap_lines(s, "💱 Хаалт — өдрийн нийт хэлцлийн жигнэсэн дундаж ханш") + [""]
    for block in (close_lines(s), single_lines(s), liquidity_lines(s)):
        if block:
            L += block + [""]
    L.append(DISCLAIMER)
    return "\n".join(L)


def weekly_text(iso_label, week, df, s, mkt, prev_avg):
    total = df["val"].sum()
    top4 = s.head(4)["Эзлэх хувь (%)"].sum()
    L = [f"📊 МХБ 7 хоногийн тойм — {iso_label} ({week[0]} → {week[-1]})",
         f"Нийт {len(df):,} хэлцэл · {mn(total)} · {len(week)} арилжааны өдөр · {len(s)} компани · эхний 4 компани {top4:.0f}%"]
    if prev_avg:
        L.append(f"Өдрийн дундаж эргэлт өмнөх 7 хоногоос {pct((total / len(week) / prev_avg - 1) * 100)}")
    L += ["📅 Өдрөөр: " + " · ".join(f"{r['Гараг']} {mn(r['Эргэлт (₮)'])}" for _, r in mkt.iterrows()), ""]
    L += index_lines(s, weekly=True) + [""]
    L += vwap_lines(s, "💱 7 хоногийн жигнэсэн дундаж ханш ба хаалт (сүүлийн өдрийн жигнэсэн дундаж)", weekly=True) + [""]
    for block in (close_lines(s), single_lines(s), liquidity_lines(s, "7 хоногийн")):
        if block:
            L += block + [""]
    vol = s[s["Хэлцэл"] >= MIN_DEALS].sort_values("Өдрийн дундаж хэлбэлзэл (%)", ascending=False).head(3)
    if len(vol):
        L.append("🌊 Хамгийн хэлбэлзэлтэй: " + ", ".join(
            f"{r['Symbol']} ({r['Өдрийн дундаж хэлбэлзэл (%)']:.1f}%/өдөр)" for _, r in vol.iterrows()))
        L.append("")
    L.append(DISCLAIMER)
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
    s = summarize(df, day_stats(earlier[-1]) if earlier else None)
    sheets = {
        "Тойм": s,
        "Цагаар": hourly(df),
        "Том хэлцэл": block_table(df),
        "Үнийн үсрэлт": jump_table(df),
        "Нөхцөлтэй хэлцэл": condition_table(df),
        "Тайлбар": definitions(),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    save_book(REPORT_DIR / f"daily_{day}.xlsx", sheets)
    write_text(REPORT_DIR / f"daily_{day}.txt", "latest_daily.txt", daily_text(day, df, s))
    print(f"Өдрийн шинжилгээ бэлэн: {REPORT_DIR}/daily_{day}.xlsx")
    return 0


# ---------------------------------------------------------------- 7 хоног
def prev_for_week(days, monday):
    before = [d for d in days if date.fromisoformat(d) < monday]
    if not before:
        return None
    prev = day_stats(before[-1])                     # өмнөх хаалт: өмнөх арилжааны өдрийнх
    pw = [d for d in before if date.fromisoformat(d) >= monday - timedelta(days=7)]
    if pw:                                           # өмнөх VWAP: өмнөх 7 хоногийн нийт арилжаанаас
        pdf = pd.concat([load_day(d) for d in pw], ignore_index=True)
        for sym, g in pdf.groupby("sym"):
            prev.setdefault(sym, {})["vwap"] = g["val"].sum() / g["qty"].sum()
    return prev


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
    s = summarize(df, prev_for_week(days, monday))

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

    sheets = {"Тойм": s, "Зах зээл өдрөөр": mkt, "Эргэлт өдрөөр": turn, "Өдрийн сүүлийн хэлцэл": close_tbl}
    if len(week) >= 4:  # 3+ өдрийн өгөөж байж хамаарал утга агуулна
        corr = ret.T.corr(min_periods=3).round(2).rename_axis(index="Symbol", columns=None).reset_index()
        sheets["Хамаарал"] = corr
    sheets.update({"Том хэлцэл": block_table(df), "Үнийн үсрэлт": jump_table(df),
                   "Цагаар": hourly(df), "Нөхцөлтэй хэлцэл": condition_table(df), "Тайлбар": definitions()})

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


def ub_today():
    if os.environ.get("TODAY"):  # туршилтад
        return date.fromisoformat(os.environ["TODAY"])
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date()  # Улаанбаатар UTC+8


def week_path(monday):
    iso = monday.isocalendar()
    return REPORT_DIR / f"weekly_{iso.year}-W{iso.week:02d}.xlsx"


def run_weekly_auto():
    """Баасан гарагт энэ 7 хоногийг гаргана. Бусад өдөр өмнөх 7 хоногийн тайлан
    хараахан гараагүй бол (жишээ нь Баасан гарагийн ажил алдагдсан) нөхөж гаргана.
    Бирж хэдэн өдөр ажиллаагүй ч байгаа өдрүүдээр тайлан гарна."""
    today = ub_today()
    monday = today - timedelta(days=today.weekday())
    if today.weekday() == 4:
        target = monday
    else:
        target = monday - timedelta(days=7)
        if week_path(target).exists():
            print("Өмнөх 7 хоногийн тайлан гарсан тул алгасав.")
            return 0
    end = target + timedelta(days=6)
    if not [d for d in all_days() if target <= date.fromisoformat(d) <= end]:
        print(f"{target} долоо хоногт арилжааны өгөгдөл алга — тайлан гаргахгүй.")
        return 0
    return run_weekly(target.isoformat())


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if mode == "daily":
        sys.exit(run_daily(arg))
    if mode == "weekly":
        sys.exit(run_weekly(arg))
    if mode == "weekly-auto":
        sys.exit(run_weekly_auto())
    print(__doc__)
    sys.exit(2)
