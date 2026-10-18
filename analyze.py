#!/usr/bin/env python3
"""МХБ-ийн хэлцлийн шинжилгээ.

    python analyze.py daily  [YYYY-MM-DD]   # өдрийн шинжилгээ (анхдагч: сүүлийн өгөгдөлтэй өдөр)
    python analyze.py weekly [YYYY-MM-DD]   # тухайн өдөр агуулсан 7 хоногийн (Да–Ба) шинжилгээ
    python analyze.py weekly-auto           # автомат: ЗӨВХӨН Баасан гарагт энэ 7 хоногийн (Да–Ба) тайланг гаргана

Оролт : data/deals_YYYY-MM-DD.xlsx   (collect_deals.py үүсгэсэн)
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
MAX_CHARS = int(os.environ.get("MAX_CHARS", 3500))                   # тайлангийн дээд урт (Telegram-ийн хязгаар 4096)
HUGE_VALUE = float(os.environ.get("HUGE_VALUE", 1_000_000_000))      # онцгой том хэлцлийн босго (₮)
HUGE_SHARE = float(os.environ.get("HUGE_SHARE", 50))                # эсвэл компанийн өдрийн дүнгийн энэ %-аас дээш
HUGE_FLOOR = float(os.environ.get("HUGE_FLOOR", 300_000_000))       # (гэхдээ дор хаяж энэ дүнтэй)
MIN_LIQ = float(os.environ.get("MIN_LIQ", 1_000_000))                # хөрвөх чадварын өөрчлөлтөд орох доод дүн (₮)

WEEKDAYS = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]
SHORT_WD = ["Да", "Мя", "Лх", "Пү", "Ба", "Бя", "Ня"]
DISCLAIMER_SHORT = "⚠️ Хөрөнгө оруулалтын зөвлөгөө биш."
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


def flag_huge(df):
    """Онцгой том хэлцэл: нэг компанийн нэг секундэд нэгтгэсэн хэлцэл нь HUGE_VALUE-аас дээш,
    эсвэл тухайн компанийн өдрийн дүнгийн HUGE_SHARE%-аас дээш (мөн HUGE_FLOOR-оос дээш) бол онцгой."""
    if df.empty:
        return pd.Series([], dtype=bool).to_numpy()
    g = df.groupby(["sym", "dt"], sort=False)["val"].sum()
    ct = df.groupby("sym")["val"].sum().reindex(g.index.get_level_values("sym")).to_numpy()
    v = g.to_numpy()
    mask = (v >= HUGE_VALUE) | ((v >= HUGE_FLOOR) & (v / ct >= HUGE_SHARE / 100))
    return pd.MultiIndex.from_frame(df[["sym", "dt"]]).isin(g.index[mask])


def load_day(d):
    df = pd.read_excel(DATA_DIR / f"deals_{d}.xlsx", sheet_name="ALL").rename(columns=RENAME)
    df["dt"] = pd.to_datetime(df["dt"])
    df["cond"] = df["cond"].fillna("").astype(str)
    df["day"] = df["dt"].dt.strftime("%Y-%m-%d")
    df = df.sort_values(["dt", "id"]).reset_index(drop=True)
    df["huge"] = flag_huge(df)
    return df


def core_of(df):
    """Ердийн арилжаа: онцгой том хэлцлийг оруулалгүй."""
    return df[~df["huge"]].reset_index(drop=True)


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
            for sym, g in core_of(load_day(d)).groupby("sym")}


def prev_closes(before, n=5):
    """Өмнөх хаалт: сүүлийн n арилжааны өдрөөс, компани бүрийн хамгийн сүүлийн хаалт.
    Өмнөх өдөр нь арилжаагүй компани ч өмнөх мэдэгдэж буй хаалтаа авна."""
    prev = {}
    for d in reversed(before[-n:]):
        for sym, v in day_stats(d).items():
            prev.setdefault(sym, dict(v))   # хамгийн сүүлийн өдөр давамгайлна
    return prev


# ---------------------------------------------------------------- тооцоолол
def executions(df):
    """Нэг компанийн, яг ижил секундэд биелсэн хэлцлүүдийг нэг хэлцэл болгон нэгтгэнэ.
    Шалтгаан: нэг том захиалга хэд хэдэн жижиг захиалгатай таарахад олон мөр үүсдэг.
    Нэгтгэсэн үнэ = жигнэсэн дундаж (Σ үнэ×ширхэг / Σ ширхэг)."""
    e = df.groupby(["sym", "dt"], sort=False).agg(
        n=("id", "count"), qty=("qty", "sum"), val=("val", "sum"),
        pmin=("px", "min"), pmax=("px", "max"), huge=("huge", "max"),
        cond=("cond", lambda c: ", ".join(sorted({x for x in c if x})))).reset_index()
    e["px"] = e["val"] / e["qty"]
    return e


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
        e = executions(g)
        big = e.loc[e["val"].idxmax()]
        pq = g.groupby("px")["qty"].sum()
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
            "Хамгийн их арилжсан үнэ": float(pq.idxmax()),
            "Тэр үнийн ширхэгийн эзлэх (%)": float(pq.max() / vol * 100),
            "Өмнөх хаалт": pc,
            "Өмнөх VWAP": pv,
            "Өөрчлөлт (%)": (close / base - 1) * 100 if base else 0.0,
            "Өөрчлөлтийн суурь": basis,
            "VWAP өөрчлөлт (%)": (vwap / pv - 1) * 100 if pv else None,
            "Хэлбэлзэл (%)": (hi / lo - 1) * 100 if lo else 0.0,
            "Дундаж хэлцэл (ш)": vol / len(g),
            "Медиан хэлцэл (ш)": float(g["qty"].median()),
            "Хамгийн том хэлцэл (ш)": int(big["qty"]),
            "Хамгийн том хэлцлийн нэгтгэсэн тоо": int(big["n"]),
            "Хамгийн том хэлцлийн эзлэх (%)": float(big["val"]) / val * 100,
            "Том хэлцэл (тоо)": int((e["val"] >= BLOCK_VALUE).sum()),
            COL_IMPACT: ORDER_SIZE / val * 100,
        })
    out = pd.DataFrame(rows).sort_values("Эргэлт (₮)", ascending=False).reset_index(drop=True)
    if out["Өмнөх VWAP"].isna().all():  # өдрийн тайланд өмнөх VWAP хэрэггүй (хаалттай адил)
        out = out.drop(columns=["Өмнөх VWAP", "VWAP өөрчлөлт (%)"])
    return out


def definitions():
    return pd.DataFrame({"Нэр томьёо": ["Хаалт", "VWAP", "Албан ёсны хаалт", "Өөрчлөлт (%)", "Сүүлийн цаг − хаалт (%)",
                                        COL_IMPACT, "Нэгтгэсэн хэлцэл", "Хөрвөх чадварын өөрчлөлт", "Онцгой том хэлцэл"],
                         "Тодорхойлолт": [
        "Сүүлийн арилжааны өдрийн (10:00–13:00) НИЙТ хэлцлийн жигнэсэн дундаж ханш = Σ(үнэ×ширхэг) / Σ ширхэг",
        "Тайлангийн бүх хугацааны нийт арилжааны жигнэсэн дундаж ханш (өдрийн тайланд хаалттай тэнцүү)",
        "Сүүлийн 1 цагийн (12:00–13:00) хэлцлийн жигнэсэн дундаж. МХБ-ийн нийтэлдэг хаалттай харьцуулах лавлагаа",
        "Хаалтыг өмнөх арилжааны өдрийн хаалттай харьцуулсан. Өмнөх өдөр байхгүй бол эхний хэлцлийн үнэтэй",
        "Албан ёсны хаалт хаалтаас хэдэн хувиар өндөр/доогуур байна. Төгсгөлийн худалдан авалт, зарлагын хүч",
        "Жишиг захиалга нь өдрийн нийт эргэлтийн хэдэн хувь вэ. Их байх тусам хөрвөх чадвар сул",
        "Нэг компанийн, яг ижил секундэд биелсэн хэлцлүүдийг нэг хэлцэл гэж тооцсон. Нэг том захиалга хэд хэдэн "
        "жижиг захиалгатай таарахад олон мөр үүсдэг. Нэгтгэсэн үнэ = жигнэсэн дундаж, ширхэг ба дүн = нийлбэр",
        "Компанийн арилжааны дүнг өмнөх өдөртэй (7 хоногийн тайланд өдрийн дундажаар өмнөх 7 хоногтой) харьцуулсан. "
        "Нэмэгдэх нь хөрвөх чадвар сайжирсан, буурах нь муудсан гэсэн үг",
        f"Нэгтгэсэн хэлцэл нь {HUGE_VALUE / 1e9:g} тэрбум ₮-өөс дээш, эсвэл компанийн өдрийн дүнгийн {HUGE_SHARE:.0f}%-аас дээш "
        f"(мөн {HUGE_FLOOR / 1e6:g} сая ₮-өөс дээш) бол онцгой. Индекс, хаалт, хөрвөх чадвар, цаг, үсрэлтийн тооцоонд оруулаагүй "
        "(ердийн арилжаа). Оруулсан тоо нь 'Тойм (онцгой хэлцэлтэй)' хуудсанд байна"]})


def block_table(df, n=50):
    e = executions(df)
    b = e[e["val"] >= BLOCK_VALUE].sort_values("val", ascending=False).head(n)
    return b[["dt", "sym", "n", "qty", "px", "val", "cond"]].rename(columns={
        "dt": "Огноо цаг", "sym": "Symbol", "n": "Нэгтгэсэн хэлцэл (тоо)", "qty": "Ширхэг",
        "px": "Үнэ (жигнэсэн дундаж)", "val": "Дүн (₮)", "cond": "Нөхцөл"})


def biggest_by_company(df):
    """Компани бүрийн хамгийн том (нэгтгэсэн) хэлцэл ба түүний эзлэх хувь."""
    e = executions(df)
    total = df["val"].sum()
    ct = df.groupby("sym")["val"].sum()
    b = e.loc[e.groupby("sym")["val"].idxmax()].copy()
    b["mkt"] = b["val"] / total * 100
    b["co"] = [v / ct[s_] * 100 for v, s_ in zip(b["val"], b["sym"])]
    return b.sort_values("val", ascending=False).reset_index(drop=True)


def huge_table(df):
    e = executions(df)
    h = e[e["huge"]].sort_values("val", ascending=False).copy()
    tot, ct = df["val"].sum(), df.groupby("sym")["val"].sum()
    h["mkt"] = h["val"] / tot * 100
    h["co"] = [v / ct[s_] * 100 for v, s_ in zip(h["val"], h["sym"])]
    return h[["sym", "dt", "n", "qty", "px", "val", "mkt", "co", "cond"]].rename(columns={
        "sym": "Symbol", "dt": "Огноо цаг", "n": "Нэгтгэсэн хэлцэл (тоо)", "qty": "Ширхэг", "px": "Үнэ (жигнэсэн дундаж)",
        "val": "Дүн (₮)", "mkt": "Нийт арилжаанд эзлэх (%)", "co": "Компанийн дүнд эзлэх (%)", "cond": "Нөхцөл"})


def biggest_table(df):
    b = biggest_by_company(df).copy()
    b["huge"] = b["huge"].map({True: "Тийм", False: ""})
    return b[["sym", "dt", "n", "qty", "px", "pmin", "pmax", "val", "mkt", "co", "cond", "huge"]].rename(columns={
        "sym": "Symbol", "dt": "Огноо цаг", "n": "Нэгтгэсэн хэлцэл (тоо)", "qty": "Ширхэг",
        "px": "Үнэ (жигнэсэн дундаж)", "pmin": "Доод үнэ", "pmax": "Дээд үнэ", "val": "Дүн (₮)",
        "mkt": "Нийт арилжаанд эзлэх (%)", "co": "Компанийн эргэлтэд эзлэх (%)", "cond": "Нөхцөл",
        "huge": "Онцгой"})


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


def sm(x):
    if x >= 1e9:
        return f"{x / 1e9:.2f} тэрбум"
    return f"{x / 1e6:.1f} сая" if x >= 1e6 else f"{x / 1e3:.0f} мянга"


def p0(v):
    """Хувь: 10-аас бага бол 1 орон, бусад нь бүхэл тоо (0% гэж харагдахаас сэргийлнэ)."""
    return f"{v:.1f}%" if v < 10 else f"{v:,.0f}%"


def wd(day):
    return WEEKDAYS[date.fromisoformat(day).weekday()]


def basis_text(s, weekly=False):
    b = set(s["Өөрчлөлтийн суурь"])
    if b == {"өмнөх хаалт"}:
        return "өмнөх хаалттай"
    if b == {"нээлт"}:
        return "нээлтийн үнэтэй"
    return "өмнөх хаалт/нээлттэй"


def liq_rows(cur, base):
    """Хөрвөх чадварын өөрчлөлт: одоогийн арилжааны дүн өмнөхтэй харьцуулахад."""
    rows = []
    for sym, c in cur.items():
        b = base.get(sym, 0.0)
        if b <= 0 or max(c, b) < MIN_LIQ:
            continue
        rows.append((sym, b, c, c / b - 1))
    return rows


def liq_table(cur, base):
    rows = sorted(liq_rows(cur, base), key=lambda r: -r[3])
    return pd.DataFrame(rows, columns=["Symbol", "Өмнөх арилжааны дүн (₮)", "Одоогийн арилжааны дүн (₮)", "_r"]).assign(
        **{"Өөрчлөлт (%)": lambda d: d["_r"] * 100, "Дахин": lambda d: d["Одоогийн арилжааны дүн (₮)"] / d["Өмнөх арилжааны дүн (₮)"]}
    ).drop(columns="_r")


# ---- блокууд: мөр бүхий жагсаалт буцаана
def index_block(s, weekly=False, tag=""):
    w, ch = s["Эргэлт (₮)"], s["Өөрчлөлт (%)"]
    eq, vw = ch.mean(), (ch * w).sum() / w.sum()
    up, dn = int((ch > 0.05).sum()), int((ch < -0.05).sum())
    contrib = ch * w / w.sum()
    lo, hi = contrib.idxmin(), contrib.idxmax()
    L = [f"📈 МХБ-н 20{' (7 хоног)' if weekly else ''}: тэнцүү {pct(eq)} · жигнэсэн {pct(vw)} · "
         f"↑{up} ↓{dn} ={len(s) - up - dn} ({basis_text(s, weekly)}{tag})"]
    parts = []
    if contrib[lo] < 0:
        parts.append(f"татсан {s.loc[lo, 'Symbol']} {contrib[lo]:+.2f} п.п.")
    if contrib[hi] > 0:
        parts.append(f"түлхсэн {s.loc[hi, 'Symbol']} {contrib[hi]:+.2f} п.п.")
    parts.append(f"эхний 4 компани {s.head(4)['Эзлэх хувь (%)'].sum():.0f}%")
    txt = " · ".join(parts)
    L.append(txt[0].upper() + txt[1:])
    return L


def price_block(s, weekly=False, limit=None, tag=""):
    rows = s if limit is None else s.head(limit)
    if weekly:
        L = [f"💱 7 хоногийн жигнэсэн дундаж → хаалт (өөрчлөлт) · мужийн өргөн % · арилжааны дүн{tag}:"]
        L += [f"{r['Symbol']} {px(r['VWAP'])} → {px(r['Хаалт'])} ({pct(r['Өөрчлөлт (%)'])}) · {r['Хэлбэлзэл (%)']:.1f}% · {sm(r['Эргэлт (₮)'])}"
              for _, r in rows.iterrows()]
    else:
        L = [f"💱 Хаалт (өдрийн жигнэсэн дундаж ханш, өөрчлөлт) · арилжааны дүн · хэлцэл{tag}:"]
        L += [f"{r['Symbol']} {px(r['Хаалт'])} ({pct(r['Өөрчлөлт (%)'])}) · {sm(r['Эргэлт (₮)'])} · {int(r['Хэлцэл'])} хэлцэл"
              for _, r in rows.iterrows()]
    return L


def movers_block(s, k=3):
    t = s[s["Хэлцэл"] >= MIN_DEALS]
    up = t[t["Өөрчлөлт (%)"] > 0].sort_values("Өөрчлөлт (%)", ascending=False).head(k)
    dn = t[t["Өөрчлөлт (%)"] < 0].sort_values("Өөрчлөлт (%)").head(k)
    L = []
    if len(up):
        L.append("📈 Өсөлт: " + ", ".join(f"{r['Symbol']} {pct(r['Өөрчлөлт (%)'])}" for _, r in up.iterrows()))
    if len(dn):
        L.append("📉 Уналт: " + ", ".join(f"{r['Symbol']} {pct(r['Өөрчлөлт (%)'])}" for _, r in dn.iterrows()))
    return L


def close_block(s):
    t = s[s["Хэлцэл"] >= MIN_DEALS]
    col = "Сүүлийн цаг − хаалт (%)"
    weak = t[t[col] <= -CLOSE_GAP].sort_values(col).head(3)
    strong = t[t[col] >= CLOSE_GAP].sort_values(col, ascending=False).head(3)
    L = []
    if len(weak):
        L.append("🔻 Төгсгөлд суларсан (сүүлийн 1 цагийн ханш хаалтаас доор): " + ", ".join(
            f"{r['Symbol']} {pct(r[col])}" for _, r in weak.iterrows()))
    if len(strong):
        L.append("🔺 Төгсгөлд хүчирхэгжсэн (дээгүүр): " + ", ".join(
            f"{r['Symbol']} {pct(r[col])}" for _, r in strong.iterrows()))
    t2 = s[(s["Өөрчлөлт (%)"].abs() >= SINGLE_MOVE) & (s["Хамгийн том хэлцлийн эзлэх (%)"] >= SINGLE_SHARE)]
    if len(t2):
        t2 = t2.sort_values("Өөрчлөлт (%)", key=lambda x: -x.abs()).head(5)
        L.append("⚠️ Нэг хэлцлээр хөдөлсөн байж болзошгүй (арилжааны дүнгийн хэдэн % нь ганц хэлцэл): " + ", ".join(
            f"{r['Symbol']} {pct(r['Өөрчлөлт (%)'])} ({r['Хамгийн том хэлцлийн эзлэх (%)']:.0f}%)" for _, r in t2.iterrows()))
    return L


def pin_block(s, k=4):
    t = s[(s["Хэлцэл"] >= MIN_DEALS) & (s["Тэр үнийн ширхэгийн эзлэх (%)"] >= 50)]
    t = t.sort_values("Тэр үнийн ширхэгийн эзлэх (%)", ascending=False).head(k)
    if t.empty:
        return []
    return ["🎯 Нэг үнэд бэхлэгдсэн (тэр үнээр арилжсан ширхэгийн хувь): " + ", ".join(
        f"{r['Symbol']} {px(r['Хамгийн их арилжсан үнэ'])} ({r['Тэр үнийн ширхэгийн эзлэх (%)']:.0f}%)" for _, r in t.iterrows())]


def hours_block(df, with_open=True):
    h = hourly(df)
    L = ["⏱ Арилжааны дүн цагаар: " + " · ".join(
        f"{r['Цаг'][:2]}ц {r['Эзлэх хувь (%)']:.0f}%" for _, r in h.iterrows())]
    if with_open:
        total = df["val"].sum()
        day = df["day"].iloc[0]
        o10 = df[df["dt"] < pd.Timestamp(f"{day} 10:10")]["val"].sum() / total * 100
        si = df[df["cond"].str.contains("Sell Imbalance")]["val"].sum() / total * 100
        L[0] += f" | нээлтийн эхний 10 мин {o10:.0f}% (Sell Imbalance хэлцэл {si:.0f}%)"
    return L


def jumps_block(df):
    j = jump_table(df, n=100000)
    if j.empty:
        return []
    big = j.iloc[0]
    cnt = j["Symbol"].value_counts()
    return [f"⚡ Үнийн үсрэлт (дараалсан хоёр хэлцэл ≥{JUMP_PCT:g}%): {len(j)} удаа · хамгийн том {big['Symbol']} "
            f"{big['Огноо цаг']:%H:%M:%S} {big['Өөрчлөлт (%)']:+.1f}% ({px(big['Өмнөх хэлцлийн үнэ'])}→{px(big['Үнэ (₮)'])}, "
            f"{int(big['Ширхэг']):,} ш) · хамгийн олон: {cnt.index[0]} ({cnt.iloc[0]})"]


def biggest_block(df, weekly=False, limit=None):
    b = biggest_by_company(df)
    if limit:
        b = b.head(limit)
    L = ["🐋 Компани бүрийн хамгийн том хэлцэл (цаг · дүн · зах зээлд % · компанид %):"]
    for i, r in b.iterrows():
        when = f"{SHORT_WD[r['dt'].weekday()]} {r['dt']:%H:%M:%S}" if weekly else f"{r['dt']:%H:%M:%S}"
        m = f" ×{int(r['n'])}" if r["n"] > 1 else ""
        c = " SI" if "Sell Imbalance" in r["cond"] else ""
        st = " ★" if r["huge"] else ""
        L.append(f"{i + 1}. {r['sym']} {when} · {sm(r['val'])} · {r['mkt']:.2f}% · {r['co']:.0f}%{m}{c}{st}")
    L.append("×N = нэг секундэд нэг компанийн N хэлцлийг нэгтгэсэн (нэг захиалга байж болзошгүй) · SI = Sell Imbalance"
             + (" · ★ = онцгой том хэлцэл" if b["huge"].any() else ""))
    return L


def huge_block(df, weekly=False, k=4):
    e = executions(df)
    h = e[e["huge"]].sort_values("val", ascending=False)
    if h.empty:
        return []
    tot, ct = df["val"].sum(), df.groupby("sym")["val"].sum()
    L = [f"🐋 Онцгой том хэлцэл (≥{HUGE_VALUE / 1e9:g} тэрбум ₮ эсвэл компанийн дүнгийн {HUGE_SHARE:.0f}%+; доорх тооцоонд ОРООГҮЙ):"]
    for _, r in h.head(k).iterrows():
        when = f"{SHORT_WD[r['dt'].weekday()]} {r['dt']:%H:%M:%S}" if weekly else f"{r['dt']:%H:%M:%S}"
        m = f" ×{int(r['n'])}" if r["n"] > 1 else ""
        L.append(f"{r['sym']} {when} · {int(r['qty']):,} ш × {px(r['px'])} = {mn(r['val'])}{m} · "
                 f"нийт арилжааны {r['val'] / tot * 100:.1f}% · {r['sym']}-ийн {r['val'] / ct[r['sym']] * 100:.0f}%")
    if len(h) > k:
        L.append(f"… бусад {len(h) - k} онцгой хэлцэл (Excel-ийн \"Онцгой том хэлцэл\" хуудсанд)")
    return L


def liquidity_block(s, span, change=None, k=3):
    L = ["💧 Хөрвөх чадвар"]
    if change:
        cur, base, label = change
        rows = liq_rows(cur, base)
        up = sorted([r for r in rows if r[3] > 0], key=lambda r: -r[3])[:k]
        dn = sorted([r for r in rows if r[3] < 0], key=lambda r: r[3])[:k]

        def f(r):
            ratio = r[2] / r[1]
            rt = (f"{ratio:.1f}×" if ratio < 100 else f"{ratio:.0f}×") if ratio >= 2 else f"{r[3] * 100:+.0f}%"
            return f"{r[0]} {r[1] / 1e6:,.1f}→{r[2] / 1e6:,.1f} ({rt})"

        if up or dn:
            L[0] += f" (арилжааны дүн, сая ₮; {label})"
        if up:
            L.append("📈 Нэмэгдсэн: " + " · ".join(f(r) for r in up))
        if dn:
            L.append("📉 Буурсан: " + " · ".join(f(r) for r in dn))
    best = s.sort_values(COL_IMPACT).head(3)
    thin = s[s[COL_IMPACT] >= THIN_PCT].sort_values(COL_IMPACT, ascending=False).head(6)
    line = f"{ORDER_SIZE / 1e6:g} сая ₮ захиалга / {span} арилжааны дүн: сайн " + ", ".join(
        f"{r['Symbol']} {p0(r[COL_IMPACT])}" for _, r in best.iterrows())
    if len(thin):
        line += f" · сул ({THIN_PCT:.0f}%+) " + ", ".join(f"{r['Symbol']} {p0(r[COL_IMPACT])}" for _, r in thin.iterrows())
    L.append(line)
    return L


def assemble(blocks, limit=None):
    """Блокуудыг нэг текст болгоно; MAX_CHARS-аас урт бол дараах дарааллаар багасгана:
    1) p>=3 блокуудыг (ач холбогдол бага) хамгийн бага ач холбогдлоос нь хасна
    2) компанийн жагсаалтуудыг (fn) нэг нэг мөрөөр багасгана (доод хязгаар nmin)
    3) p=2 блокуудыг сүүлээс нь хасна. p<=1 блок хэзээ ч хасагдахгүй."""
    limit = limit or MAX_CHARS
    bs = [dict(b) for b in blocks]

    def lines_of(b):
        return b["fn"](b["n"]) if b.get("fn") else b["lines"]

    def render():
        return "\n\n".join("\n".join(lines_of(b)) for b in bs if lines_of(b))

    def remove(b):
        b["fn"], b["lines"] = None, []

    while len(render()) > limit:
        c3 = [b for b in bs if b["p"] >= 3 and lines_of(b)]
        if c3:
            remove(max(c3, key=lambda x: x["p"]))
            continue
        cv = [b for b in bs if b.get("fn") and b["n"] > b["nmin"]]
        if cv:
            b = max(cv, key=lambda x: len("\n".join(lines_of(x))))
            b["n"] -= 1
            continue
        c2 = [b for b in bs if b["p"] == 2 and b.get("drop", True) and lines_of(b)]
        if c2:
            remove(c2[-1])
            continue
        break
    return render()


def blk(p, lines=None, drop=True, fn=None, n=None, nmin=12):
    return {"p": p, "lines": lines or [], "drop": drop, "fn": fn, "n": n, "nmin": nmin}


def daily_text(day, df_all, core, s, liq=None, prev=None):
    total_all, total = df_all["val"].sum(), core["val"].sum()
    hg = bool(df_all["huge"].any())
    tag = "; онцгой хэлцэлгүй" if hg else ""
    head = [f"📊 МХБ {day} ({wd(day)}) · {len(df_all):,} хэлцэл · {mn(total_all)}"
            + (f" (онцгойгүй {len(core):,} хэлцэл · {mn(total)})" if hg else "") + f" · {len(s)} компани"]
    if prev:
        pday, pval, pdeals = prev
        head.append(f"Өмнөх өдөртэй ({pday[5:]}) харьцуулахад арилжааны дүн {pct((total / pval - 1) * 100)} "
                    f"({mn(pval)} → {mn(total)}), хэлцэл {pdeals:,} → {len(core):,}" + (" (онцгойгүй)" if hg else ""))
    blocks = [
        blk(0, head),
        blk(0, huge_block(df_all)),
        blk(1, index_block(s, tag=tag)),
        blk(2, fn=lambda n: price_block(s, limit=n, tag=" · онцгойгүй" if hg else ""), n=len(s), drop=False),
        blk(2, movers_block(s)),
        blk(2, close_block(s)),
        blk(3, pin_block(s)),
        blk(3, hours_block(core)),
        blk(4, jumps_block(core)),
        blk(2, fn=lambda n: biggest_block(df_all, limit=n), n=len(s), drop=False),
        blk(1, liquidity_block(s, "өдрийн", liq)),
        blk(0, [DISCLAIMER]),
    ]
    return assemble(blocks)


def weekly_text(iso_label, week, df_all, df, s, prev_avg, liq, wk):
    total_all, total = df_all["val"].sum(), df["val"].sum()
    hg = bool(df_all["huge"].any())
    tag = "; онцгой хэлцэлгүй" if hg else ""
    head = [f"📊 МХБ 7 хоног {iso_label} ({week[0][5:]} → {week[-1][5:]}) · {len(df_all):,} хэлцэл · {mn(total_all)}"
            + (f" (онцгойгүй {mn(total)})" if hg else "") + f" · {len(week)} арилжааны өдөр · {len(s)} компани"]
    if prev_avg:
        head.append(f"Өдрийн дундаж арилжааны дүн өмнөх 7 хоногоос {pct((total / len(week) / prev_avg - 1) * 100)}"
                    + (" (онцгойгүй)" if hg else ""))
    days = ["📅 Өдөр бүр (арилжааны дүн · хэлцэл · МХБ-н 20 тэнцүү/жигнэсэн өөрчлөлт" + (", онцгойгүй" if hg else "") + "):"]
    for _, r in wk["days"].iterrows():
        idx = f"{r['eq']:+.2f}% / {r['vw']:+.2f}%" if pd.notna(r["eq"]) else "—"
        extra = f" (нийт {sm(r['val_all'])})" if r["val_all"] - r["val"] > 1 else ""
        days.append(f"{r['Гараг'][:2]} {sm(r['val'])}{extra} · {int(r['deals']):,} · {idx}")
    streak = []
    if wk["n_ret"] >= 3:
        ups = wk["updays"]
        allup = [k for k in s["Symbol"] if ups.get(k, (0, 0))[1] >= 3 and ups[k][0] == ups[k][1]][:4]
        alldn = [k for k in s["Symbol"] if ups.get(k, (0, 0))[1] >= 3 and ups[k][0] == 0][:4]
        if allup:
            streak.append("📶 Бүх өдөр өссөн: " + ", ".join(allup))
        if alldn:
            streak.append("📶 Бүх өдөр унасан: " + ", ".join(alldn))
    t = s[s["Хэлцэл"] >= MIN_DEALS]
    vol = t.sort_values("Өдрийн дундаж хэлбэлзэл (%)", ascending=False)
    calm = vol.tail(3).iloc[::-1]
    volb = ["🌊 Хамгийн хэлбэлзэлтэй: " + ", ".join(f"{r['Symbol']} {r['Өдрийн дундаж хэлбэлзэл (%)']:.1f}%/өдр" for _, r in vol.head(3).iterrows()),
            "🧘 Хамгийн тайван: " + ", ".join(f"{r['Symbol']} {r['Өдрийн дундаж хэлбэлзэл (%)']:.1f}%/өдр" for _, r in calm.iterrows())]
    corr = []
    if wk["corr"] is not None:
        pairs = wk["corr"]
        pos = pairs[pairs["r"] > 0].head(2)
        neg = pairs[pairs["r"] < 0].tail(2).iloc[::-1]
        if len(pos):
            corr.append("🔗 Хамт хөдөлсөн: " + ", ".join(f"{a}–{b} {r:+.2f}" for a, b, r in pos[["a", "b", "r"]].itertuples(index=False)))
        if len(neg):
            corr.append("🔗 Эсрэг хөдөлсөн: " + ", ".join(f"{a}–{b} {r:+.2f}" for a, b, r in neg[["a", "b", "r"]].itertuples(index=False)))
    blocks = [
        blk(0, head),
        blk(0, huge_block(df_all, weekly=True)),
        blk(1, days),
        blk(1, index_block(s, weekly=True, tag=tag)),
        blk(2, fn=lambda n: price_block(s, weekly=True, limit=n, tag=" · онцгойгүй" if hg else ""), n=len(s), drop=False),
        blk(2, movers_block(s)),
        blk(2, close_block(s)),
        blk(3, streak),
        blk(2, fn=lambda n: biggest_block(df_all, weekly=True, limit=n), n=len(s), drop=False),
        blk(1, liquidity_block(s, "7 хоногийн", liq)),
        blk(4, volb),
        blk(5, corr),
        blk(4, hours_block(df, with_open=False)),
        blk(0, [DISCLAIMER]),
    ]
    return assemble(blocks)


def weekly_ctx(label, week, df_all, df, s, prev_avg, liq, wk):
    """7 хоногийн зургийг зурахад хэрэгтэй бүх өгөгдөл (render_image.py-д дамжуулна)."""
    total_all, total = float(df_all["val"].sum()), float(df["val"].sum())
    ct = df_all.groupby("sym")["val"].sum()
    e = executions(df_all)
    h = e[e["huge"]].sort_values("val", ascending=False)
    huge = [dict(sym=r.sym, when=f"{SHORT_WD[r.dt.weekday()]} {r.dt:%H:%M:%S}", qty=int(r.qty), px=float(r.px), val=float(r.val),
                 mkt=r.val / total_all * 100, co=r.val / ct[r.sym] * 100, n=int(r.n)) for r in h.itertuples()]
    days = [dict(d=r["Гараг"][:2], val=float(r["val"]), val_all=float(r["val_all"]), deals=int(r["deals"]),
                 eq=None if pd.isna(r["eq"]) else float(r["eq"]), vw=None if pd.isna(r["vw"]) else float(r["vw"]))
            for _, r in wk["days"].iterrows()]
    w_, ch = s["Эргэлт (₮)"], s["Өөрчлөлт (%)"]
    contrib = ch * w_ / w_.sum()
    lo, hi = contrib.idxmin(), contrib.idxmax()
    index = dict(eq=float(ch.mean()), vw=float((ch * w_).sum() / w_.sum()), up=int((ch > 0.05).sum()), dn=int((ch < -0.05).sum()),
                 basis=basis_text(s, True), top4=float(s.head(4)["Эзлэх хувь (%)"].sum()),
                 pull=(s.loc[lo, "Symbol"], float(contrib[lo])) if contrib[lo] < 0 else None,
                 push=(s.loc[hi, "Symbol"], float(contrib[hi])) if contrib[hi] > 0 else None)
    index["flat"] = len(s) - index["up"] - index["dn"]
    prices = [dict(sym=r["Symbol"], vwap=float(r["VWAP"]), close=float(r["Хаалт"]), chg=float(r["Өөрчлөлт (%)"]),
                   rng=float(r["Хэлбэлзэл (%)"]), val=float(r["Эргэлт (₮)"])) for _, r in s.iterrows()]
    t = s[s["Хэлцэл"] >= MIN_DEALS]
    up3 = [(r["Symbol"], float(r["Өөрчлөлт (%)"])) for _, r in t[t["Өөрчлөлт (%)"] > 0].sort_values("Өөрчлөлт (%)", ascending=False).head(3).iterrows()]
    dn3 = [(r["Symbol"], float(r["Өөрчлөлт (%)"])) for _, r in t[t["Өөрчлөлт (%)"] < 0].sort_values("Өөрчлөлт (%)").head(3).iterrows()]
    col = "Сүүлийн цаг − хаалт (%)"
    weak = [(r["Symbol"], float(r[col])) for _, r in t[t[col] <= -CLOSE_GAP].sort_values(col).head(3).iterrows()]
    strong = [(r["Symbol"], float(r[col])) for _, r in t[t[col] >= CLOSE_GAP].sort_values(col, ascending=False).head(3).iterrows()]
    t2 = s[(s["Өөрчлөлт (%)"].abs() >= SINGLE_MOVE) & (s["Хамгийн том хэлцлийн эзлэх (%)"] >= SINGLE_SHARE)]
    single = [(r["Symbol"], float(r["Өөрчлөлт (%)"]), float(r["Хамгийн том хэлцлийн эзлэх (%)"]))
              for _, r in t2.sort_values("Өөрчлөлт (%)", key=lambda x: -x.abs()).head(5).iterrows()]
    biggest = [dict(sym=r["sym"], when=f"{SHORT_WD[r['dt'].weekday()]} {r['dt']:%H:%M:%S}", val=float(r["val"]), mkt=float(r["mkt"]),
                    co=float(r["co"]), n=int(r["n"]), si="Sell Imbalance" in r["cond"], huge=bool(r["huge"]))
               for _, r in biggest_by_company(df_all).iterrows()]
    liq_up, liq_dn, liq_label = [], [], ""
    if liq:
        cur, base, liq_label = liq
        rows = liq_rows(cur, base)

        def mk(r, green):
            ratio = r[2] / r[1]
            rt = (f"{ratio:.1f}×" if ratio < 100 else f"{ratio:.0f}×") if ratio >= 2 else f"{r[3] * 100:+.0f}%"
            return (r[0], r[1] / 1e6, r[2] / 1e6, rt, GREEN_C if green else RED_C)
        GREEN_C, RED_C = (22, 160, 74), (220, 38, 38)
        liq_up = [mk(r, True) for r in sorted([r for r in rows if r[3] > 0], key=lambda r: -r[3])[:3]]
        liq_dn = [mk(r, False) for r in sorted([r for r in rows if r[3] < 0], key=lambda r: r[3])[:3]]
    impact = dict(order=ORDER_SIZE / 1e6, thin_pct=THIN_PCT,
                  best=[(r["Symbol"], float(r[COL_IMPACT])) for _, r in s.sort_values(COL_IMPACT).head(3).iterrows()],
                  thin=[(r["Symbol"], float(r[COL_IMPACT])) for _, r in s[s[COL_IMPACT] >= THIN_PCT].sort_values(COL_IMPACT, ascending=False).head(6).iterrows()])
    streak_up, streak_dn = [], []
    if wk["n_ret"] >= 3:
        ups = wk["updays"]
        streak_up = [k for k in s["Symbol"] if ups.get(k, (0, 0))[1] >= 3 and ups[k][0] == ups[k][1]][:4]
        streak_dn = [k for k in s["Symbol"] if ups.get(k, (0, 0))[1] >= 3 and ups[k][0] == 0][:4]
    vol = t.sort_values("Өдрийн дундаж хэлбэлзэл (%)", ascending=False)
    corr_pos, corr_neg = [], []
    if wk["corr"] is not None:
        pairs = wk["corr"]
        corr_pos = [(a, b, float(r)) for a, b, r in pairs[pairs["r"] > 0].head(2)[["a", "b", "r"]].itertuples(index=False)]
        corr_neg = [(a, b, float(r)) for a, b, r in pairs[pairs["r"] < 0].tail(2).iloc[::-1][["a", "b", "r"]].itertuples(index=False)]
    hrs = hourly(df)
    extras = dict(streak_up=streak_up, streak_dn=streak_dn,
                  vol=[(r["Symbol"], float(r["Өдрийн дундаж хэлбэлзэл (%)"])) for _, r in vol.head(3).iterrows()],
                  calm=[(r["Symbol"], float(r["Өдрийн дундаж хэлбэлзэл (%)"])) for _, r in vol.tail(3).iloc[::-1].iterrows()],
                  corr_pos=corr_pos, corr_neg=corr_neg,
                  hours=[(r["Цаг"][:2] + "ц", float(r["Эзлэх хувь (%)"])) for _, r in hrs.iterrows()])
    return dict(label=label, range=f"{week[0][5:]} → {week[-1][5:]}", deals=len(df_all), total_all=total_all, total_core=total,
                has_huge=bool(df_all["huge"].any()), ndays=len(week), ncomp=len(s),
                avg_change=(total / len(week) / prev_avg - 1) * 100 if prev_avg else None,
                huge_rule=f"≥{HUGE_VALUE / 1e9:g} тэрбум ₮ эсвэл компанийн дүнгийн {HUGE_SHARE:.0f}%+",
                huge=huge, days=days, index=index, prices=prices, up3=up3, dn3=dn3, weak=weak, strong=strong, single=single,
                biggest=biggest, liq_label=liq_label, liq_up=liq_up, liq_dn=liq_dn, impact=impact, extras=extras)


def weekly_caption(ctx):
    """Зурагтай хамт илгээх товч тайлбар (Telegram-ийн хязгаар 1024 тэмдэгт)."""
    ix = ctx["index"]
    L = [f"📊 МХБ 7 хоног {ctx['label']} ({ctx['range']})",
         f"{ctx['deals']:,} хэлцэл · {mn(ctx['total_all'])}" + (f" (онцгойгүй {mn(ctx['total_core'])})" if ctx["has_huge"] else ""),
         f"📈 МХБ-н 20: тэнцүү {pct(ix['eq'])} · жигнэсэн {pct(ix['vw'])} · ↑{ix['up']} ↓{ix['dn']} ={ix['flat']}"]
    if ctx["huge"]:
        L.append("🐋 Онцгой том хэлцэл: " + ", ".join(f"{h['sym']} {mn(h['val'])}" for h in ctx["huge"][:3]))
    L.append(DISCLAIMER_SHORT)
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
    df_all = load_day(day)
    if df_all.empty:
        print("Хэлцэл алга.")
        return 1
    core = core_of(df_all)
    if core.empty:
        core = df_all
    earlier = [d for d in days if d < day]
    prev = prev_closes(earlier) if earlier else None
    s = summarize(core, prev)
    liq, prev_info = None, None
    if earlier:
        pdf = core_of(load_day(earlier[-1]))
        base = pdf.groupby("sym")["val"].sum().to_dict()
        cur = core.groupby("sym")["val"].sum().to_dict()
        liq = (cur, base, "өмнөх өдрөөс")
        prev_info = (earlier[-1], float(pdf["val"].sum()), len(pdf))
    sheets = {"Тойм": s}
    if df_all["huge"].any():
        sheets["Онцгой том хэлцэл"] = huge_table(df_all)
        sheets["Тойм (онцгой хэлцэлтэй)"] = summarize(df_all, prev)
    sheets.update({
        "Цагаар": hourly(core),
        "Том хэлцэл (компаниар)": biggest_table(df_all),
        "Том хэлцэл": block_table(df_all),
        "Үнийн үсрэлт": jump_table(core),
        "Нөхцөлтэй хэлцэл": condition_table(df_all),
        "Тайлбар": definitions(),
    })
    if liq:
        sheets = {**{k: v for k, v in sheets.items() if k != "Тайлбар"},
                  "Хөрвөх чадварын өөрчлөлт": liq_table(liq[0], liq[1]), "Тайлбар": sheets["Тайлбар"]}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    save_book(REPORT_DIR / f"daily_{day}.xlsx", sheets)
    write_text(REPORT_DIR / f"daily_{day}.txt", "latest_daily.txt", daily_text(day, df_all, core, s, liq, prev_info))
    print(f"Өдрийн шинжилгээ бэлэн: {REPORT_DIR}/daily_{day}.xlsx")
    return 0


# ---------------------------------------------------------------- 7 хоног
def prev_for_week(days, monday):
    before = [d for d in days if date.fromisoformat(d) < monday]
    if not before:
        return None
    prev = prev_closes(before)                       # өмнөх хаалт (өмнөх өдрүүдийн хамгийн сүүлийнх)
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
    week = [d for d in days if monday <= date.fromisoformat(d) <= monday + timedelta(days=4)]   # Даваа–Баасан
    if not week:
        print("Тухайн 7 хоногт өгөгдөл алга.")
        return 1
    df_all = pd.concat([load_day(d) for d in week], ignore_index=True).sort_values(["dt", "id"]).reset_index(drop=True)
    df = core_of(df_all)                           # ердийн арилжаа (онцгой том хэлцэлгүй)
    if df.empty:
        df = df_all
    prev = prev_for_week(days, monday)
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

    sheets = {"Тойм": s, "Зах зээл өдрөөр": mkt, "Эргэлт өдрөөр": turn, "Өдрийн сүүлийн хэлцэл": close_tbl}
    if len(week) >= 4:  # 3+ өдрийн өгөөж байж хамаарал утга агуулна
        corr = ret.T.corr(min_periods=3).round(2).rename_axis(index="Symbol", columns=None).reset_index()
        sheets["Хамаарал"] = corr
    if df_all["huge"].any():
        sheets = {"Тойм": sheets["Тойм"], "Онцгой том хэлцэл": huge_table(df_all),
                  "Тойм (онцгой хэлцэлтэй)": summarize(df_all, prev), **{k: v for k, v in sheets.items() if k != "Тойм"}}
    sheets.update({"Том хэлцэл (компаниар)": biggest_table(df_all), "Том хэлцэл": block_table(df_all), "Үнийн үсрэлт": jump_table(df),
                   "Цагаар": hourly(df), "Нөхцөлтэй хэлцэл": condition_table(df_all), "Тайлбар": definitions()})

    iso = monday.isocalendar()
    label = f"{iso.year}-W{iso.week:02d}"
    prev_days = [d for d in days if monday - timedelta(days=7) <= date.fromisoformat(d) < monday]
    prev_avg = sum(core_of(load_day(d))["val"].sum() for d in prev_days) / len(prev_days) if prev_days else None

    # өдөр бүрийн индекс, дараалсан өсөлт/уналт, хамаарал (хаалт = өдрийн жигнэсэн дундаж ханш)
    g_val, g_qty = df.groupby(["sym", "day"])["val"].sum(), df.groupby(["sym", "day"])["qty"].sum()
    dvw, dv = (g_val / g_qty).unstack("day"), g_val.unstack("day").fillna(0.0)
    prevc = pd.Series({k: v["close"] for k, v in (prev or {}).items() if v.get("close")}, dtype=float).reindex(dvw.index)
    rch = dvw.div(dvw.ffill(axis=1).shift(1, axis=1)) - 1
    rch[dvw.columns[0]] = dvw[dvw.columns[0]] / prevc - 1
    rows_ = []
    for d_ in dvw.columns:
        c_, m_ = rch[d_], rch[d_].notna()
        w_ = dv[d_][m_]
        rows_.append({"day": d_, "eq": c_[m_].mean() * 100 if m_.any() else float("nan"),
                      "vw": (c_[m_] * w_).sum() / w_.sum() * 100 if w_.sum() > 0 else float("nan")})
    day_idx = pd.DataFrame(rows_)
    days_tbl = mkt.rename(columns={"Огноо": "day", "Хэлцэл": "deals", "Эргэлт (₮)": "val"})[["day", "Гараг", "deals", "val"]].merge(day_idx, on="day")
    days_tbl["val_all"] = days_tbl["day"].map(df_all.groupby("day")["val"].sum())
    mkt["Нийт дүн, онцгойтой (₮)"] = mkt["Огноо"].map(df_all.groupby("day")["val"].sum())
    mkt["МХБ-н 20 тэнцүү (%)"] = days_tbl["eq"].values
    mkt["МХБ-н 20 жигнэсэн (%)"] = days_tbl["vw"].values
    n_ret = int(rch.notna().any(axis=0).sum())
    updays = {k: (int((rch.loc[k] > 0).sum()), int(rch.loc[k].notna().sum())) for k in rch.index}
    corr_pairs = None
    if n_ret >= 4:  # 3 цэгээр корреляци үргэлж ±1 гарах тул 4+ өдрийн өгөөж шаардана
        cm = rch.T.corr(min_periods=4)
        cp = [(a_, b_, cm.loc[a_, b_]) for i_, a_ in enumerate(cm.index) for b_ in cm.index[i_ + 1:] if pd.notna(cm.loc[a_, b_])]
        corr_pairs = pd.DataFrame(cp, columns=["a", "b", "r"]).sort_values("r", ascending=False).reset_index(drop=True)
    wk = {"days": days_tbl, "n_ret": n_ret, "updays": updays, "corr": corr_pairs}

    liq = None
    if prev_days:
        base = pd.concat([core_of(load_day(d)) for d in prev_days]).groupby("sym")["val"].sum() / len(prev_days)
        cur = df.groupby("sym")["val"].sum() / len(week)
        liq = (cur.to_dict(), base.to_dict(), "өмнөх 7 хоногоос, өдрийн дундажаар")
    elif len(week) >= 2:  # өмнөх 7 хоногийн өгөгдөл байхгүй: сүүлийн өдрийг 7 хоногийн өмнөх өдрүүдтэй харьцуулна
        last = week[-1]
        base = df[df["day"] != last].groupby("sym")["val"].sum() / (len(week) - 1)
        cur = df[df["day"] == last].groupby("sym")["val"].sum()
        liq = (cur.to_dict(), base.to_dict(),
               f"{wd(last)[:2]} гарагийн дүн vs өмнөх өдрүүдийн дундаж")
    if liq:
        sheets = {**{k: v for k, v in sheets.items() if k != "Тайлбар"},
                  "Хөрвөх чадварын өөрчлөлт": liq_table(liq[0], liq[1]), "Тайлбар": sheets["Тайлбар"]}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    save_book(REPORT_DIR / f"weekly_{label}.xlsx", sheets)
    write_text(REPORT_DIR / f"weekly_{label}.txt", "latest_weekly.txt",
               weekly_text(label, week, df_all, df, s, prev_avg, liq, wk))
    # нэг өндөр чанартай зураг (амжилтгүй бол текст тайлан хэвээр илгээгдэнэ)
    for stale in ("latest_weekly.png", "latest_weekly_caption.txt"):
        (REPORT_DIR / stale).unlink(missing_ok=True)
    try:
        import render_image
        ctx = weekly_ctx(label, week, df_all, df, s, prev_avg, liq, wk)
        png = render_image.render_weekly(ctx, REPORT_DIR / f"weekly_{label}.png")
        shutil.copyfile(png, REPORT_DIR / "latest_weekly.png")
        (REPORT_DIR / "latest_weekly_caption.txt").write_text(weekly_caption(ctx) + "\n", encoding="utf-8")
        print(f"Зураг бэлэн: {png}")
    except Exception as exc:  # noqa: BLE001
        print("Зураг үүсгэж чадсангүй (текст тайлан хэвээр):", repr(exc))
    print(f"7 хоногийн шинжилгээ бэлэн: {REPORT_DIR}/weekly_{label}.xlsx ({len(week)} өдөр)")
    return 0


def ub_today():
    if os.environ.get("TODAY"):  # туршилтад
        return date.fromisoformat(os.environ["TODAY"])
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date()  # Улаанбаатар UTC+8


def run_weekly_auto():
    """Зөвхөн Баасан гарагт (GitHub-ийн ажил хэт саатвал Бямба, Ням) энэ 7 хоногийн
    Даваа–Баасан гарагийн арилжааны тайланг гаргана. Даваа–Пүрэв гарагт юу ч гаргахгүй.
    Бирж хэдэн өдөр ажиллаагүй ч байгаа өдрүүдээр тайлан гарна."""
    today = ub_today()
    if today.weekday() < 4:
        print("Баасан гараг биш тул 7 хоногийн тайлан гаргахгүй.")
        return 0
    monday = today - timedelta(days=today.weekday())
    end = monday + timedelta(days=4)
    if not [d for d in all_days() if monday <= date.fromisoformat(d) <= end]:
        print(f"{monday} долоо хоногт арилжааны өгөгдөл алга — тайлан гаргахгүй.")
        return 0
    return run_weekly(monday.isoformat())


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
