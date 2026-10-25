#!/usr/bin/env python3
"""Нэмэлт инфографикууд.

    python extras.py spotlight     # Долоо хоногийн компани (Баасан гарагт)
    python extras.py term          # Арилжааны нэр томьёо (Лхагва гарагт, сүүлийн 5 арилжааны өдрийн жишээгээр)
    python extras.py news          # Мэдээ ба зах зээлийн хариу (Баасан гарагт)
    python extras.py news-collect  # api/news/get-ээс мэдээ татаж data/news.json-д нэмнэ (өдөр бүр)
    python extras.py alltime       # Бүх цаг үеийн хаалтын ханш (data/history/*.csv-ээс)
    python extras.py monthly|quarterly|yearly   # Сар, улирал, жилийн ханшийн хөдөлгөөн (%) — өнгөт хүснэгт (ASOF=YYYY-MM-DD)
    python extras.py periods-auto  # Сүүлд дууссан сар (мөн улирал, жил)-ын хүснэгтийг гаргана

Гаралт (reports/): <төрөл>_<долоо хоног>.png, latest_<төрөл>.png, latest_<төрөл>.txt (нөөц текст),
latest_<төрөл>_caption.txt (зургийн тайлбар). Илгээхийг send_telegram.py хийнэ.
"""
import json
import math
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import analyze as A
import render_extra as RX
from render_image import AMBER, BLUE, GREEN, RED

POS, NEG = (61, 220, 132), (255, 120, 120)          # харанхуй дэвсгэр дээрх өнгө
NEWS_API = os.environ.get("NEWS_API", "http://api.marketinfo.mn/api/news/get/")
SP_COOLDOWN = 3                                      # сүүлийн хэдэн долоо хоногт онцолсон компанийг дахин сонгохгүй


# ------------------------------------------------------------------ нийтлэг
def iso_label(d):
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def load_names():
    p = A.DATA_DIR / "companies.json"
    try:
        return {A.canon(k): v for k, v in json.loads(p.read_text(encoding="utf-8")).items()} if p.exists() else {}
    except ValueError:
        return {}


def week_days():
    days = A.all_days()
    ref = date.fromisoformat(os.environ.get("WEEK_OF") or days[-1])      # WEEK_OF=YYYY-MM-DD: тухайн өдрийг агуулсан 7 хоног (туршилт, гараар дахин гаргах)
    monday = ref - timedelta(days=ref.weekday())
    week = [d for d in days if monday <= date.fromisoformat(d) <= monday + timedelta(days=4)]
    return days, monday, week


def load_window(dlist, days):
    df_all = pd.concat([A.load_day(d) for d in dlist], ignore_index=True).sort_values(["dt", "id"]).reset_index(drop=True)
    core = A.core_of(df_all)
    before = [d for d in days if d < dlist[0]]
    prev = A.prev_closes(before) if before else None
    return df_all, (core if not core.empty else df_all), prev


def clear_latest(kind):
    for suf in (".png", ".txt", "_caption.txt"):
        (A.REPORT_DIR / f"latest_{kind}{suf}").unlink(missing_ok=True)


def save_outputs(kind, label, png_writer, caption, text):
    import shutil
    A.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    png = A.REPORT_DIR / f"{kind}_{label}.png"
    png_writer(png)
    shutil.copyfile(png, A.REPORT_DIR / f"latest_{kind}.png")
    (A.REPORT_DIR / f"latest_{kind}_caption.txt").write_text(caption + "\n", encoding="utf-8")
    (A.REPORT_DIR / f"latest_{kind}.txt").write_text(text + "\n", encoding="utf-8")
    print(f"Зураг бэлэн: {png}")


def zs(x):
    sd = x.std()
    return (x - x.mean()) / sd if sd and sd > 0 else x * 0


def bin5(dt):
    return int(min(35, max(0, (dt.hour * 60 + dt.minute - 600) // 5)))


def day_path(g):
    """Нэг өдрийн 36 ширхэг 5 минутын сүүлийн хэлцлийн үнэ (хоосон хэсгийг өмнөхөөр дүүргэнэ)."""
    s = g.sort_values(["dt", "id"]).assign(b=lambda x: x["dt"].map(bin5)).groupby("b")["px"].last().reindex(range(36))
    return s.ffill().bfill().tolist()


# ================================================================== ДОЛОО ХОНОГИЙН КОМПАНИ
def build_spotlight():
    days, monday, week = week_days()
    df_all, df, prev = load_window(week, days)
    s = A.summarize(df, A.prev_for_week(days, monday)).set_index("Symbol", drop=False)
    prev_days = [d for d in days if monday - timedelta(days=7) <= date.fromisoformat(d) < monday]
    base, cur = None, df.groupby("sym")["val"].sum() / len(week)
    if prev_days:
        base = pd.concat([A.core_of(A.load_day(d)) for d in prev_days]).groupby("sym")["val"].sum() / len(prev_days)
    elif len(week) >= 2:
        last = week[-1]
        base = df[df["day"] != last].groupby("sym")["val"].sum() / (len(week) - 1)
        cur = df[df["day"] == last].groupby("sym")["val"].sum()

    hist_path = A.REPORT_DIR / "spotlight_history.json"
    hist = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else []
    label = iso_label(monday)
    recent = [h["sym"] for h in hist if h["week"] != label][-SP_COOLDOWN:]

    chg = s["Өөрчлөлт (%)"]
    act, ratio = pd.Series(0.0, index=s.index), {}
    if base is not None:
        for sym in s.index:
            b, c_ = base.get(sym, 0.0), cur.get(sym, 0.0)
            if b > 0 and c_ > 0:
                ratio[sym] = c_ / b
                act[sym] = abs(math.log(c_ / b))
    huge_syms = set(df_all[df_all["huge"]]["sym"])
    conc = s["Хамгийн том хэлцлийн эзлэх (%)"] / 100 + pd.Series({k: 0.5 if k in huge_syms else 0.0 for k in s.index})
    zm, za, zc = zs(chg.abs()), zs(act), 0.5 * zs(conc)
    score = zm + za + zc
    cand = score[(s["Хэлцэл"] >= 20) & ~s.index.isin(recent)]
    if cand.empty:
        cand = score[s["Хэлцэл"] >= 5]
    sym = cand.idxmax()

    names = load_names()
    name = names.get(sym, "")
    row = s.loc[sym]
    g_all, g = df_all[df_all["sym"] == sym], df[df["sym"] == sym]
    wl = [A.wd(d)[:2] for d in week]

    # үнийн зам
    pts, breaks, last_px = [], [], None
    for d in week:
        breaks.append(len(pts))
        gd = g[g["day"] == d]
        if gd.empty:
            path = [last_px if last_px is not None else float(row["Нээлт"])] * 36
        else:
            path = day_path(gd)
            if last_px is not None and gd.sort_values("dt")["dt"].iloc[0].hour * 60 + gd.sort_values("dt")["dt"].iloc[0].minute > 600:
                first_b = bin5(gd.sort_values("dt")["dt"].iloc[0])
                path[:first_b] = [last_px] * first_b
        pts += path
        last_px = pts[-1]
    # онцлох хэлцлүүд (онцгой хэлцэл ч орно)
    ex = A.executions(g_all)
    total_all_sym = float(g_all["val"].sum())
    markers = []
    for r in ex.nlargest(3, "val").itertuples():
        k = week.index(r.dt.strftime("%Y-%m-%d"))
        markers.append(dict(i=breaks[k] + bin5(r.dt), price=float(r.px), val=float(r.val),
                            text=f"{A.SHORT_WD[r.dt.weekday()]} {r.dt:%H:%M} · {A.sm(r.val)}" + (" ★" if r.huge else "")))
    # өдөр бүр
    dayvals, days_tbl, pc = [], [], (prev or {}).get(sym, {}).get("close") if prev is None else None
    pc = A.prev_closes([d for d in days if d < week[0]]).get(sym, {}).get("close") if [d for d in days if d < week[0]] else None
    for d in week:
        gd, ga = g[g["day"] == d], g_all[g_all["day"] == d]
        core_v, huge_v = float(gd["val"].sum()), float(ga[ga["huge"]]["val"].sum())
        dayvals.append(dict(d=A.wd(d)[:2], core=core_v, huge=huge_v))
        if gd.empty:
            continue
        close = round(gd["val"].sum() / gd["qty"].sum(), 2)
        days_tbl.append(dict(d=A.wd(d)[:2], close=close, chg=None if pc is None else (close / pc - 1) * 100,
                             val=core_v, deals=len(gd), rng=(gd["px"].max() / gd["px"].min() - 1) * 100))
        pc = close

    # шалтгаан
    rank_abs = int((chg.abs() > abs(chg[sym])).sum()) + 1
    n_c = len(s)
    reasons = [(f"7 хоногийн өөрчлөлт {chg[sym]:+.2f}% — 20 дотор хөдөлгөөнөөр {rank_abs}-р", GREEN if chg[sym] > 0 else RED)]
    if sym in ratio:
        r_ = ratio[sym]
        txt = f"Арилжааны дүн өмнөх үеийн дундажаас {r_:.1f} дахин" if r_ >= 1.5 else f"Арилжааны дүн өмнөх үеийн дундажаас {(r_ - 1) * 100:+.0f}%"
        reasons.append((txt, BLUE if r_ >= 1 else AMBER))
    top_share = float(row["Хамгийн том хэлцлийн эзлэх (%)"])
    if sym in huge_syms:
        reasons.append(("Онцгой том хэлцэл гарсан (индексийн тооцоонд ороогүй)", AMBER))
    elif top_share >= 20:
        reasons.append((f"7 хоногийн дүнгийн {top_share:.0f}% нь ганц хэлцэл", AMBER))
    reasons = reasons[:3]

    # онцлох үйл явдал
    events = []
    if len(ex):
        b = ex.loc[ex["val"].idxmax()]
        mg = f", {int(b['n'])} хэлцэл нэгтгэсэн" if b["n"] > 1 else ""
        events.append((f"{A.SHORT_WD[b['dt'].weekday()]} {b['dt']:%H:%M:%S}",
                       f"Хамгийн том хэлцэл {A.mn(b['val'])} ({int(b['qty']):,} ш × {A.px(b['px'])}{mg}) — 7 хоногийн дүнгийн {b['val'] / total_all_sym * 100:.0f}%"))
    jt = A.jump_table(g, n=1000)
    if len(jt):
        j = jt.iloc[0]
        events.append((f"{A.SHORT_WD[j['Огноо цаг'].weekday()]} {j['Огноо цаг']:%H:%M:%S}",
                       f"Үнийн үсрэлт {j['Өөрчлөлт (%)']:+.1f}% ({A.px(j['Өмнөх хэлцлийн үнэ'])}→{A.px(j['Үнэ (₮)'])}, {int(j['Ширхэг']):,} ш)"))
    if days_tbl:
        wide = max(days_tbl, key=lambda x: x["rng"])
        events.append((wide["d"], f"Хамгийн их хэлбэлзсэн өдөр: муж {wide['rng']:.1f}%"))
        chgs = [x for x in days_tbl if x["chg"] is not None]
        if chgs:
            hi_, lo_ = max(chgs, key=lambda x: x["chg"]), min(chgs, key=lambda x: x["chg"])
            events.append((hi_["d"], f"Хамгийн хүчтэй өдөр {hi_['chg']:+.2f}%" + (f" · хамгийн сул {lo_['d']} {lo_['chg']:+.2f}%" if lo_ is not hi_ else "")))
    si = g_all[g_all["cond"].str.contains("Sell Imbalance")]
    if len(si):
        events.append(("Нээлт", f"Sell Imbalance нөхцөлтэй хэлцэл {len(si)} (нээлтийн арилжаа {si['day'].nunique()} өдөр)"))
    events = events[:5]

    # индекстэй харьцуулалт
    w_ = s["Эргэлт (₮)"]
    eq, vw = chg.mean(), (chg * w_).sum() / w_.sum()
    rank_chg = int((chg > chg[sym]).sum()) + 1
    rank_val = int((w_ > w_[sym]).sum()) + 1
    col = lambda v: GREEN if v > 0 else RED if v < 0 else None
    facts = [("Компани", f"{chg[sym]:+.2f}%", col(chg[sym]), "7 хоногийн өөрчлөлт"),
             ("МХБ-н 20 (тэнцүү)", f"{eq:+.2f}%", col(eq), f"зөрүү {chg[sym] - eq:+.2f} п.п."),
             ("Өөрчлөлтөөр", f"{rank_chg}-р / {n_c}", None, "өсөлтөөр эрэмбэлбэл"),
             ("Арилжааны дүнгээр", f"{rank_val}-р / {n_c}", None, "ердийн арилжаагаар"),
             ("Хөрвөх чадвар", f"{row[A.COL_IMPACT]:.1f}%", None, f"{A.ORDER_SIZE / 1e6:g} сая ₮ захиалга / 7 хоногийн дүн"),
             ("Хамгийн их арилжсан үнэ", A.px(row["Хамгийн их арилжсан үнэ"]), None, f"ширхэгийн {row['Тэр үнийн ширхэгийн эзлэх (%)']:.0f}%")]
    big_text = (f"{A.SHORT_WD[b['dt'].weekday()]} {b['dt']:%H:%M:%S} · {int(b['qty']):,} ш × {A.px(b['px'])} = {A.mn(b['val'])}"
                f"{' (' + str(int(b['n'])) + ' хэлцэл нэгтгэсэн)' if b['n'] > 1 else ''} · компанийн 7 хоногийн дүнгийн {b['val'] / total_all_sym * 100:.0f}%") if len(ex) else "—"

    turn = float(row["Эргэлт (₮)"])
    ctx = dict(sym=sym, name=name, range=f"{week[0][5:]} → {week[-1][5:]}",
               kpis=[(f"{chg[sym]:+.2f}%", "7 хоногийн өөрчлөлт", POS if chg[sym] >= 0 else NEG),
                     (A.px(row["Хаалт"]), "хаалт (сүүлийн өдрийн жигнэсэн дундаж)", None),
                     (A.px(row["VWAP"]), "7 хоногийн жигнэсэн дундаж", None),
                     (A.mn(turn), "арилжааны дүн (онцгойгүй)", None),
                     (f"{int(row['Хэлцэл']):,}", "хэлцэл", None)],
               pts=pts, breaks=breaks, day_labels=wl, vwap=float(row["VWAP"]), markers=markers, dayvals=dayvals,
               ref_avg=float(base.get(sym)) if base is not None and base.get(sym) else None,
               ref_label="өмнөх үеийн дундаж", days=days_tbl, reasons=reasons, events=events,
               compare=dict(), facts=facts, big_text=big_text)

    hist = [h for h in hist if h["week"] != label] + [{"week": label, "sym": sym}]
    caption = "\n".join([f"⭐ Долоо хоногийн компани: {sym}{' — ' + name if name else ''} ({ctx['range']})",
                         f"7 хоногийн өөрчлөлт {chg[sym]:+.2f}% · арилжааны дүн {A.mn(turn)}"] + [f"• {t}" for t, _ in reasons] + [A.DISCLAIMER_SHORT])
    text = caption + "\n\nОнцлох үйл явдал:\n" + "\n".join(f"{w} — {t}" for w, t in events)
    return label, ctx, caption, text, (hist_path, hist)


def cmd_spotlight():
    clear_latest("spotlight")
    label, ctx, caption, text, (hp, hist) = build_spotlight()
    save_outputs("spotlight", label, lambda p: RX.render_spotlight(ctx, p), caption, text)
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_text(json.dumps(hist[-30:], ensure_ascii=False), encoding="utf-8")
    print("Онцолсон компани:", ctx["sym"])


# ================================================================== НЭР ТОМЬЁО
def daily_index(df, prev):
    """Өдөр бүрийн МХБ-н 20 (тэнцүү, жигнэсэн) өөрчлөлт: хаалт = өдрийн жигнэсэн дундаж."""
    gv, gq = df.groupby(["sym", "day"])["val"].sum(), df.groupby(["sym", "day"])["qty"].sum()
    dvw, dv = (gv / gq).unstack("day"), gv.unstack("day").fillna(0.0)
    prevc = pd.Series({k: v["close"] for k, v in (prev or {}).items() if v.get("close")}, dtype=float).reindex(dvw.index)
    rch = dvw.div(dvw.ffill(axis=1).shift(1, axis=1)) - 1
    rch[dvw.columns[0]] = dvw[dvw.columns[0]] / prevc - 1
    out = []
    for d in dvw.columns:
        c_, m_ = rch[d], rch[d].notna()
        w_ = dv[d][m_]
        out.append(dict(day=d, eq=c_[m_].mean() * 100 if m_.any() else None,
                        vw=(c_[m_] * w_).sum() / w_.sum() * 100 if w_.sum() > 0 else None))
    return out


def tiles_color(v):
    return None if v is None else (POS if v >= 0 else NEG)


def t_vwap(W):
    best = None
    for (sym, day), g in W["df"].groupby(["sym", "day"]):
        if len(g) < 30:
            continue
        g = g.sort_values(["dt", "id"])
        vw, last = g["val"].sum() / g["qty"].sum(), float(g["px"].iloc[-1])
        gap = (last / vw - 1) * 100
        if best is None or abs(gap) > abs(best[0]):
            best = (gap, sym, day, vw, last, g)
    gap, sym, day, vw, last, g = best
    return dict(
        title="VWAP — жигнэсэн дундаж ханш",
        definition=["VWAP (Volume-Weighted Average Price) нь тухайн хугацаанд биелсэн бүх хэлцлийн үнийг ширхэгээр нь жигнэж гаргасан дундаж үнэ юм: Σ(үнэ × ширхэг) ÷ Σ ширхэг.",
                    "Сүүлийн хэлцлийн үнэ зөвхөн нэг л хэлцлийг төлөөлдөг бол VWAP өдрийн бүх арилжааг төлөөлнө. Манай тайлан өдрийн хаалтыг энэ аргаар (нийт хэлцлийн жигнэсэн дундажаар) тооцдог."],
        why=["Нэг хэлцлээр тодорсон санамсаргүй ханшаас хамгаална.",
             "Хөрөнгө оруулагч өдөртөө дунджаар ямар үнээр авч, зарж чадсаныг харуулна.",
             "Өдөр хоорондын өөрчлөлтийг ижил аргаар харьцуулах боломж олгоно."],
        example_title=f"{sym} · {day} ({A.wd(day)}) — сүүлийн хэлцэл ба VWAP-ийн зөрүү 5 минут тутмын үнийн замаар",
        example_note=f"{sym}-ийн {day}-нд сүүлийн хэлцэл {A.px(last)} боловч өдрийн ихэнх арилжаа {A.px(vw)}-ийн орчимд хийгдсэн. Сүүлийн хэлцлээр хэмжвэл {gap:+.2f}% буруу харагдана.",
        chart=dict(type="price", h=320, pts=day_path(g), vwap=float(vw), breaks=[0], day_labels=[f"{sym} · {day[5:]}"],
                   markers=[dict(i=35, price=last, val=2e6, text=f"сүүлийн хэлцэл {A.px(last)}")]),
        tiles=[(A.px(vw), "өдрийн VWAP", None), (A.px(last), "сүүлийн хэлцэл", None), (f"{gap:+.2f}%", "зөрүү", tiles_color(gap)),
               (f"{len(g):,}", "хэлцэл", None), (A.mn(float(g['val'].sum())), "арилжааны дүн", None)])


def t_official(W):
    rows, n, dom = [], 0, 0
    for day, gd in W["df"].groupby("day"):
        end = pd.Timestamp(f"{day} {A.CLOSE_TIME}")
        for sym, g in gd.groupby("sym"):
            lh = g[(g["dt"] > end - pd.Timedelta(hours=1)) & (g["dt"] <= end)]
            if lh.empty or lh["qty"].sum() == 0:
                continue
            n += 1
            e = A.executions(lh)
            sh = e["val"].max() / e["val"].sum()
            dom += sh >= 0.5
            off, vw = lh["val"].sum() / lh["qty"].sum(), g["val"].sum() / g["qty"].sum()
            if len(g) >= 20:
                rows.append(((off / vw - 1) * 100, sym, day, off, vw, sh))
    rows.sort(key=lambda r: -abs(r[0]))
    top = rows[:6]
    items = [(f"{s_} {d[5:]}", gp, GREEN if gp > 0 else RED, f"{A.px(o)} vs {A.px(v)} ({gp:+.1f}%)") for gp, s_, d, o, v, sh in top]
    t0 = top[0] if top else None
    return dict(
        title="Албан ёсны хаалт — сүүлийн 1 цагийн жигнэсэн дундаж",
        definition=["МХБ-ийн албан ёсны хаалтын ханш нь арилжааны сүүлийн 1 цагийн (12:00–13:00) хэлцлүүдийн жигнэсэн дундаж ханш юм.",
                    "Харин манай тайлан өдрийн нийт арилжааны жигнэсэн дундажийг “хаалт” гэж үзэж, албан ёсны хаалтыг лавлагаа болгон хамт харуулдаг."],
        why=["Сүүлийн цагт цөөн хэлцэл гарсан компанид албан ёсны хаалт нэг захиалгаас тодорч болно.",
             "Өдрийн жигнэсэн дундажтай харьцуулбал төгсгөлд ханш хүчирхэгжсэн үү, суларсан уу гэдэг харагдана.",
             "Албан ёсны хаалтаар тооцсон өөрчлөлт, тайлангийн өөрчлөлт ялгаатай байх шалтгааныг тайлбарлана."],
        example_title="Сүүлийн цагийн албан ёсны хаалт өдрийн VWAP-аас хамгийн их зөрсөн компани-өдрүүд",
        example_note=(f"Сүүлийн цагт арилжаалагдсан {n} компани-өдрийн {dom} (" + f"{dom / max(n, 1) * 100:.0f}%)-д сүүлийн цагийн арилжааны 50%+ нь ганц захиалгаас гарсан."
                      + (f" Хамгийн их зөрүү: {t0[1]} {t0[2][5:]} ({t0[0]:+.1f}%)." if t0 else "")),
        chart=dict(type="bars", items=items, row_h=34, label_w=110, val_w=200, h=34 * max(len(items), 1) + 10),
        tiles=[(f"{int(dom)}", "нэг захиалгаас тодорсон", None), (f"{n}", "сүүлийн цагт арилжигдсан компани-өдөр", None),
               (f"{dom / max(n, 1) * 100:.0f}%", "эзлэх хувь", None),
               (f"{t0[0]:+.1f}%" if t0 else "—", "хамгийн их зөрүү", tiles_color(t0[0]) if t0 else None), (f"{W['n_days']}", "арилжааны өдөр", None)])


def _cond_stats(W, key):
    x = W["df_all"][W["df_all"]["cond"].str.contains(key)]
    sec = x["dt"].dt.hour * 3600 + x["dt"].dt.minute * 60 + x["dt"].dt.second - 36000
    return x, sec


def t_sell_imbalance(W):
    x, sec = _cond_stats(W, "Sell Imbalance")
    total = W["df_all"]["val"].sum()
    within = float((sec <= 60).mean() * 100) if len(x) else 0.0
    ex = A.executions(x) if len(x) else x
    big = ex.loc[ex["val"].idxmax()] if len(ex) else None
    rows = []
    for d in W["dlist"]:
        xd = x[x["day"] == d]
        rows.append((f"{d[5:]} {A.wd(d)[:2]}", [float(v) for v in (xd["dt"].dt.hour * 3600 + xd["dt"].dt.minute * 60 + xd["dt"].dt.second - 36000)]))
    return dict(
        title="Sell Imbalance — нээлтийн арилжааны нөхцөл",
        definition=["Хэлцэл дээр “Sell Imbalance” нөхцөл тэмдэглэгддэг. Imbalance нь захиалгын тэнцвэргүй байдлыг (энд зарах тал давамгайлсныг) заана гэж ойлгож болно.",
                    f"Манай өгөгдөлд энэ нөхцөл өдөр бүр, бүх 20 компанид, голдуу 10:00 цагийн эхний секундүүдэд (нээлтийн арилжаанд) гарч байна. Энэ долоо хоногт хэлцлийн {within:.0f}% нь эхний 60 секундэд."],
        why=["Нээлтийн үнэ, өдрийн эхний хэлцлийг тодорхойлдог тул өдрийн ханшид нөлөөлнө.",
             "Нээлтийн арилжаа том хэмжээтэй байж болох тул өдрийн арилжааны дүнгийн мэдэгдэхүйц хэсгийг эзэлнэ.",
             "Нээлтийн үнэ ба өдрийн жигнэсэн дунджийг харьцуулж, нээлтэд авах нь үнэтэй байсан эсэхийг мэдэж болно."],
        example_title="Sell Imbalance хэлцлүүд нээлтээс хойших секундээр (өдөр бүрийн мөр, цэг = нэг хэлцэл)",
        example_note=(f"Хамгийн том нь {big['sym']} {big['dt']:%m-%d %H:%M:%S} — {A.sm(big['val'])}" + (f" ({int(big['n'])} хэлцэл нэгтгэсэн)" if big['n'] > 1 else "") + "." if big is not None else "Энэ хугацаанд Sell Imbalance хэлцэл гараагүй."),
        chart=dict(type="dots", rows=rows, span=60, step=10, h=34 * len(rows) + 30),
        tiles=[(f"{len(x):,}", "Sell Imbalance хэлцэл", None), (f"{x['val'].sum() / total * 100:.1f}%", "нийт арилжааны", None),
               (f"{x['sym'].nunique()}", "компани", None), (f"{within:.0f}%", "эхний 60 секундэд", None),
               (A.sm(float(big['val'])) if big is not None else "—", "хамгийн том", None)])


def t_reopen(W):
    x, sec = _cond_stats(W, "Re-Opening Price")
    total = W["df_all"]["val"].sum()
    cnt = x["sym"].value_counts().head(8)
    items = [(k, float(v), (42, 120, 214), f"{int(v)} хэлцэл") for k, v in cnt.items()]
    lo = f"{(x['dt'].min()):%H:%M}" if len(x) else "—"
    hi = f"{(x['dt'].max()):%H:%M}" if len(x) else "—"
    return dict(
        title="Re-Opening Price — дахин нээлтийн үнэ",
        definition=["Хэлцэл дээр “Re-Opening Price” (дахин нээлтийн үнэ) гэсэн нөхцөл тэмдэглэгддэг.",
                    "Sell Imbalance нь өдөр бүрийн нээлтэд гардаг бол энэ нөхцөл манай өгөгдөлд өдрийн дундуур, санамсаргүй цагт, цөөн компанид гарч байна."],
        why=["Өдрийн дундуур үнэ шинэ түвшинд тогтсон агшинг харуулна.",
             "Ийм нөхцөл олон давтагддаг компани нь үнийн хөдөлгөөн ихтэй байдаг эсэхийг шалгах сэжүүр болно.",
             "Эдгээр хэлцлийн үнэ өдрийн VWAP-д орсон байдаг тул хаалтад нөлөөлнө."],
        example_title="Re-Opening Price хэлцэл компаниар (энэ 7 хоног)",
        example_note=(f"Нийт {len(x)} хэлцэл, {x['sym'].nunique()} компани, {x['day'].nunique()} өдөр; цагийн завсар {lo}–{hi}; нийт арилжааны {x['val'].sum() / total * 100:.2f}%."
                      if len(x) else "Энэ хугацаанд Re-Opening Price хэлцэл гараагүй."),
        chart=dict(type="bars", items=items, row_h=34, label_w=100, val_w=140, h=34 * max(len(items), 1) + 10),
        tiles=[(f"{len(x):,}", "Re-Opening Price хэлцэл", None), (f"{x['sym'].nunique()}", "компани", None),
               (cnt.index[0] if len(cnt) else "—", "хамгийн олон дээр", None), (f"{lo}–{hi}", "цагийн завсар", None),
               (f"{x['val'].sum() / total * 100:.2f}%", "нийт арилжааны", None)])


def t_merged(W):
    e = A.executions(W["df_all"])
    big = e.sort_values(["n", "val"], ascending=False).iloc[0]
    g = W["df_all"][(W["df_all"]["sym"] == big["sym"]) & (W["df_all"]["dt"] == big["dt"])].sort_values("id")
    trades = [(float(p), int(q)) for p, q in zip(g["px"], g["qty"])]
    nprice = len({p for p, _ in trades})
    ct = float(W["df_all"][W["df_all"]["sym"] == big["sym"]]["val"].sum())
    return dict(
        title="Нэгтгэсэн хэлцэл",
        definition=["Нэг том захиалга хэд хэдэн жижиг захиалгатай таарахад олон мөр хэлцэл үүсдэг. Бид нэг компанийн яг ижил секундэд биелсэн хэлцлүүдийг нэг хэлцэл болгон нэгтгэдэг.",
                    "Нэгтгэсэн хэлцлийн ширхэг, дүн нь нийлбэр; үнэ нь жигнэсэн дундаж байна. Тайланд “×N” тэмдэгтээр нэгтгэсэн мөрийн тоог харуулдаг."],
        why=["Нэг захиалгыг олон жижиг хэлцэл мэт харуулахаас сэргийлж, жинхэнэ хэмжээг харуулна.",
             "“Хамгийн том хэлцэл”, “онцгой хэлцэл”-ийг зөв тодорхойлно.",
             "Захиалга хэдэн үнийн түвшнийг туулсныг (үнэд хэр нөлөөлснийг) харуулна."],
        example_title=f"{big['sym']} · {big['dt']:%m-%d %H:%M:%S} — {int(big['n'])} мөр хэлцэл нэг захиалгаар (үнийн түвшин бүрийн ширхэг)",
        example_note=f"{int(big['n'])} мөр хэлцэл {nprice} үнийн түвшинг {A.px(big['pmin'])}–{A.px(big['pmax'])} хооронд туулж, нийт {int(big['qty']):,} ш, {A.mn(big['val'])} болсон (компанийн 7 хоногийн дүнгийн {big['val'] / ct * 100:.0f}%).",
        chart=dict(type="ladder", trades=trades, h=int(min(760, max(16 * nprice + 10, 220)))),
        tiles=[(f"×{int(big['n'])}", "нэгтгэсэн мөр", None), (f"{int(big['qty']):,}", "нийт ширхэг", None), (A.mn(float(big['val'])), "дүн", None),
               (f"{A.px(big['pmin'])}–{A.px(big['pmax'])}", "үнийн завсар", None), (f"{nprice}", "үнийн түвшин", None)])


def t_huge(W):
    e = A.executions(W["df_all"])
    h = e[e["huge"]].sort_values("val", ascending=False)
    if len(h):
        b = h.iloc[0]
        d = b["dt"].strftime("%Y-%m-%d")
        dd_all = W["df_all"][W["df_all"]["day"] == d]
        dd_core = A.core_of(dd_all)
        prev_d = A.prev_closes([x for x in W["days"] if x < d])
        s_all, s_core = A.summarize(dd_all, prev_d or None), A.summarize(dd_core, prev_d or None)
        idx = lambda s_: (s_["Өөрчлөлт (%)"].mean(), (s_["Өөрчлөлт (%)"] * s_["Эргэлт (₮)"]).sum() / s_["Эргэлт (₮)"].sum())
        eq1, vw1 = idx(s_all)
        eq0, vw0 = idx(s_core)
        tot, core_t = float(dd_all["val"].sum()), float(dd_core["val"].sum())
        items = [("Өдрийн нийт арилжаа", tot, AMBER, A.mn(tot)), ("Онцгойгүй (ердийн)", core_t, (42, 120, 214), A.mn(core_t)),
                 ("Онцгой хэлцэл", tot - core_t, AMBER, A.mn(tot - core_t))]
        note = (f"{b['sym']} {b['dt']:%m-%d %H:%M:%S}: {int(b['qty']):,} ш × {A.px(b['px'])} = {A.mn(b['val'])}. "
                f"Тэр өдрийн жигнэсэн индекс онцгой хэлцэлтэй {vw1:+.2f}%, онцгойгүй {vw0:+.2f}% (тэнцүү жинтэй {eq1:+.2f}% / {eq0:+.2f}%).")
        tiles = [(f"{len(h)}", "онцгой хэлцэл", None), (A.mn(float(b['val'])), "хамгийн том", None),
                 (f"{b['val'] / tot * 100:.0f}%", "тэр өдрийн нийт арилжааны", None), (f"{vw1:+.2f}%", "жигнэсэн индекс (онцгойтой)", tiles_color(vw1)),
                 (f"{vw0:+.2f}%", "жигнэсэн индекс (онцгойгүй)", tiles_color(vw0))]
        title_ex = f"{d} ({A.wd(d)}) — онцгой хэлцэл арилжаа ба индексийг хэрхэн мушгисан бэ"
    else:
        b = e.loc[e["val"].idxmax()]
        items = [("Хамгийн том хэлцэл", float(b["val"]), (42, 120, 214), A.mn(float(b["val"]))),
                 ("Онцгойн босго", A.HUGE_VALUE, AMBER, A.mn(A.HUGE_VALUE))]
        note = f"Энэ хугацаанд онцгой хэлцэл гараагүй. Хамгийн том ердийн хэлцэл {b['sym']} {A.mn(b['val'])} нь онцгойн босгоос хол."
        tiles = [("0", "онцгой хэлцэл", None), (A.mn(float(b['val'])), "хамгийн том хэлцэл", None), (f"{b['val'] / A.HUGE_VALUE * 100:.0f}%", "босгын", None),
                 (f"{b['sym']}", "хамгийн том хэлцэл", None), (f"{W['n_days']}", "арилжааны өдөр", None)]
        title_ex = "Хамгийн том ердийн хэлцэл онцгойн босготой харьцуулахад"
    return dict(
        title="Онцгой том хэлцэл",
        definition=[f"Нэгтгэсэн хэлцэл {A.HUGE_VALUE / 1e9:g} тэрбум ₮-өөс дээш, эсвэл компанийн өдрийн дүнгийн {A.HUGE_SHARE:.0f}%-аас дээш (мөн {A.HUGE_FLOOR / 1e6:g} сая ₮-өөс дээш) бол “онцгой” гэж үзнэ.",
                    "Ийм хэлцэл индекс, хаалт, хөрвөх чадварын тооцоог мушгидаг тул ердийн арилжаанаас тусад нь харуулж, тайлангийн үзүүлэлтэд оруулдаггүй."],
        why=["Нэг хэлцэл бүх зах зээлийн арилжааг олон дахин нэмэгдүүлж чадна.",
             "Онцгой хэлцлийг оруулбал индексийн өөрчлөлт цөөн хэдэн компанийн нэг захиалгаас хамаарна.",
             "Ердийн арилжаагаар хэмжвэл зах зээлийн жинхэнэ хөдөлгөөн харагдана."],
        example_title=title_ex, example_note=note,
        chart=dict(type="bars", items=items, row_h=44, label_w=200, val_w=160, h=44 * len(items) + 10), tiles=tiles)


def t_liquidity(W):
    s = W["s"].sort_values(A.COL_IMPACT)
    colr = lambda v: GREEN if v < 10 else (42, 120, 214) if v < 50 else RED
    items = [(r["Symbol"], float(r[A.COL_IMPACT]), colr(r[A.COL_IMPACT]), f"{r[A.COL_IMPACT]:.1f}%") for _, r in s.iterrows()]
    best, worst = s.iloc[0], s.iloc[-1]
    thin = int((s[A.COL_IMPACT] >= A.THIN_PCT).sum())
    return dict(
        title="Хөрвөх чадвар",
        definition=["Хөрвөх чадвар нь хөрөнгийг үнийг нь хөдөлгөхгүйгээр хэр хурдан, хэр том хэмжээгээр арилжаалж чадахыг заана.",
                    f"Бид үүнийг {A.ORDER_SIZE / 1e6:g} сая ₮-ийн захиалга тухайн компанийн арилжааны дүнгийн хэдэн хувь болохоор хэмждэг: хувь бага байх тусам хөрвөх чадвар сайн."],
        why=["Хөрвөх чадвар сул компанид том захиалга өгвөл үнэ өөрөө хөдөлнө.",
             "Арилжааны дүнгийн 50%-иас дээш хувьтай бол нэг захиалга өдрийн бүх арилжаанаас их гэсэн үг.",
             "Хөрвөх чадвар долоо хоног тутам өөрчлөгддөг тул тогтмол хянах хэрэгтэй."],
        example_title=f"{A.ORDER_SIZE / 1e6:g} сая ₮-ийн захиалга 7 хоногийн арилжааны дүнгийн хэдэн хувь вэ (бага = сайн)",
        example_note="Ногоон: 10%-иас бага (сайн), цэнхэр: 10–50%, улаан: 50%+ (сул). Онцгой хэлцлийг оруулалгүй тооцсон.",
        chart=dict(type="bars", items=items, row_h=26, label_w=90, val_w=100, h=26 * len(items) + 10),
        tiles=[(best["Symbol"], "хамгийн сайн", None), (f"{best[A.COL_IMPACT]:.1f}%", "түүний хувь", POS), (worst["Symbol"], "хамгийн сул", None),
               (f"{worst[A.COL_IMPACT]:,.0f}%", "түүний хувь", NEG), (f"{thin}", f"сул ({A.THIN_PCT:.0f}%+) компани", None)])


def t_index(W):
    di = daily_index(W["df"], W["prev"])
    items = []
    for r in di:
        for nm, key in (("тэнцүү", "eq"), ("жигнэсэн", "vw")):
            v = r[key]
            items.append((f"{A.wd(r['day'])[:2]} {nm}", abs(v or 0.0), (GREEN if (v or 0) >= 0 else RED) if v is not None else (170, 180, 190),
                          "—" if v is None else f"{v:+.2f}%"))
    ok = [r for r in di if r["eq"] is not None and r["vw"] is not None]
    gap = max(ok, key=lambda r: abs(r["vw"] - r["eq"])) if ok else None
    avg = lambda k: sum(r[k] for r in ok) / len(ok) if ok else None
    return dict(
        title="МХБ-н 20 индекс: тэнцүү ба жигнэсэн",
        definition=["МХБ-н 20 нь тайлан дахь 20 компанийн өдрийн өөрчлөлтийг нэгтгэсэн манай өөрийн индекс. Өөрчлөлт = өдрийн жигнэсэн дундаж ханшийг өмнөх өдрийн жигнэсэн дундажтай харьцуулсан.",
                    "Тэнцүү жинтэй индекс компани бүрийг ижил жинтэй, жигнэсэн индекс арилжааны дүнгээр жигнэнэ. Хоёрын зөрүү их бол хөдөлгөөн цөөн томоохон компанийн арилжаанаас хамаарсан гэсэн үг."],
        why=["Тэнцүү жинтэй индекс зах зээлийн өргөн хөдөлгөөнийг (олон компани), жигнэсэн нь мөнгөний жинг харуулна.",
             "Хоёр индексийн зөрүүгээр нэг хоёр том компани зах зээлийг дагуулсан эсэхийг мэднэ.",
             "Онцгой том хэлцлийг хассан индекс жинхэнэ чиг хандлагыг илүү зөв харуулна."],
        example_title="Өдөр бүрийн МХБ-н 20: тэнцүү ба жигнэсэн өөрчлөлт (онцгой хэлцэлгүй)",
        example_note=(f"Хамгийн их зөрүүтэй өдөр {A.wd(gap['day'])}: тэнцүү {gap['eq']:+.2f}%, жигнэсэн {gap['vw']:+.2f}%." if gap else "Хангалттай өгөгдөл алга."),
        chart=dict(type="bars", items=items, row_h=28, label_w=130, val_w=100, h=28 * len(items) + 10),
        tiles=[(f"{avg('eq'):+.2f}%" if ok else "—", "дундаж тэнцүү", tiles_color(avg('eq')) if ok else None),
               (f"{avg('vw'):+.2f}%" if ok else "—", "дундаж жигнэсэн", tiles_color(avg('vw')) if ok else None),
               (A.wd(gap['day'])[:2] if gap else "—", "хамгийн их зөрүүтэй өдөр", None),
               (f"{abs(gap['vw'] - gap['eq']):.2f} п.п." if gap else "—", "зөрүү", None), (f"{len(di)}", "өдөр", None)])


TOPICS = [t_vwap, t_official, t_sell_imbalance, t_reopen, t_merged, t_huge, t_liquidity, t_index]


def build_term():
    days = A.all_days()
    upto = [d for d in days if d <= os.environ["WEEK_OF"]] if os.environ.get("WEEK_OF") else days
    dlist = upto[-5:]
    df_all, df, prev = load_window(dlist, days)
    s = A.summarize(df, prev)
    W = dict(df_all=df_all, df=df, prev=prev, s=s, days=days, dlist=dlist, n_days=len(dlist))
    k = int(os.environ.get("TERM_TOPIC") or (date.fromisoformat(dlist[-1]).isocalendar().week % len(TOPICS)))
    ctx = TOPICS[k % len(TOPICS)](W)
    ctx.update(no=k % len(TOPICS) + 1, range=f"{dlist[0][5:]} → {dlist[-1][5:]}")
    label = iso_label(date.fromisoformat(dlist[-1]))
    caption = f"📘 Арилжааны нэр томьёо №{ctx['no']}: {ctx['title']}\n{ctx['definition'][0]}\n\nБодит жишээ ({ctx['range']}): {ctx['example_note']}\n{A.DISCLAIMER_SHORT}"
    text = caption + "\n\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(ctx["why"], 1))
    return label, ctx, caption, text


def cmd_term():
    clear_latest("term")
    label, ctx, caption, text = build_term()
    save_outputs("term", label, lambda p: RX.render_term(ctx, p), caption, text)
    print("Нэр томьёо:", ctx["no"], ctx["title"])


# ================================================================== МЭДЭЭ БА ЗАХ ЗЭЭЛИЙН ХАРИУ
def fetch_news(pages=3):
    out = []
    for p in range(1, pages + 1):
        req = urllib.request.Request(NEWS_API + str(p), headers={"User-Agent": "Mozilla/5.0 MSE-news"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        res = data.get("results") if isinstance(data, dict) else data
        if not res:
            break
        out += [x for x in res if isinstance(x, dict)]
    return out


def cmd_news_collect():
    path = A.DATA_DIR / "news.json"
    cur = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    try:
        items = fetch_news(int(os.environ.get("NEWS_PAGES", "3")))
    except Exception as e:  # noqa: BLE001
        print("Мэдээ татаж чадсангүй:", repr(e))
        return 0
    n0 = len(cur)
    for it in items:
        nid = str(it.get("newsId") or it.get("id") or "")
        if nid and it.get("newsTitle"):
            cur[nid] = dict(id=nid, title=str(it["newsTitle"]).strip(), date=str(it.get("createdDate") or ""),
                            link=f"https://marketinfo.mn/news/detail/{nid}")
    keep = dict(sorted(cur.items(), key=lambda kv: kv[1]["date"], reverse=True)[:3000])
    A.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keep, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Мэдээ: {len(items)} татлаа, шинэ {len(keep) - n0}, нийт {len(keep)}.")
    return 0


STOPW = {"хк", "ххк", "ак", "хувьцаат", "компани"}


def nrm(s):
    return " ".join(w for w in re.sub(r"[^\w]+", " ", str(s).lower()).split() if w not in STOPW)


def match_companies(title, names, codes):
    t = " " + nrm(title) + " "
    hit = []
    tokens = set(re.findall(r"[A-Za-z]{2,5}", title))
    for sym in codes:
        nm = nrm(names.get(sym, ""))
        if (nm and len(nm) >= 4 and f" {nm} " in t) or sym.split("-")[0] in tokens:
            hit.append(sym)
    return hit


def parse_dt(s):
    t = str(s or "").strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            pass
    return None


def build_news():
    days, monday, week = week_days()
    names = load_names()
    path = A.DATA_DIR / "news.json"
    news = list(json.loads(path.read_text(encoding="utf-8")).values()) if path.exists() else []
    df_all, df, _ = load_window(week, days)
    hist = [d for d in days if d <= week[-1]][-12:]
    dfh = pd.concat([A.core_of(A.load_day(d)) for d in hist], ignore_index=True)
    gv, gq = dfh.groupby(["sym", "day"])["val"].sum(), dfh.groupby(["sym", "day"])["qty"].sum()
    close = (gv / gq).unstack("day")                                  # sym x day жигнэсэн дундаж
    turn = gv.unstack("day").fillna(0.0)
    chg = close.div(close.ffill(axis=1).shift(1, axis=1)) - 1
    mkt = chg.mean(axis=0, skipna=True)
    codes = [s for s in close.index]
    items, matched_news = [], 0
    for n in news:
        dt = parse_dt(n.get("date"))
        if not dt:
            continue
        syms = match_companies(n["title"], names, codes)
        if not syms:
            continue
        has_time = (dt.hour or dt.minute)
        later = [d for d in hist if (d > dt.strftime("%Y-%m-%d")) or (d == dt.strftime("%Y-%m-%d") and not (has_time and dt.hour >= 13))]
        if not later:
            continue
        rd = later[0]
        if rd not in week:
            continue
        matched_news += 1
        for sym in syms:
            c_ = chg.loc[sym, rd] if rd in chg.columns and pd.notna(chg.loc[sym, rd]) else None
            if c_ is None:
                continue
            prior = [d for d in hist if d < rd][-5:]
            avg_t = turn.loc[sym, prior].mean() if len(prior) >= 2 else None
            tmul = float(turn.loc[sym, rd] / avg_t) if avg_t and avg_t > 0 else None
            items.append(dict(when=f"{dt:%m-%d %H:%M}" if has_time else f"{dt:%m-%d}", sym=sym, title=n["title"],
                              react_day=f"{rd[5:]} {A.wd(rd)[:2]}", chg=float(c_ * 100), mkt=float(mkt[rd] * 100),
                              exc=float((c_ - mkt[rd]) * 100), turn=tmul, link=n.get("link")))
    items.sort(key=lambda x: -abs(x["exc"]))
    # дүгнэлт
    allexc = (chg.sub(mkt, axis=1) * 100).stack().abs()
    avg_all = float(allexc.mean()) if len(allexc) else None
    avg_news = sum(abs(i["exc"]) for i in items) / len(items) if items else None
    up = sum(1 for i in items if i["exc"] > 0)
    summary = [(f"Энэ 7 хоногт {matched_news} мэдээнд тайлан дахь компани дурдагдаж, {len(items)} (мэдээ × компани) хослол хэмжигдсэн.", BLUE)]
    if items:
        if len(items) >= 5 and avg_all:
            summary.append((f"Мэдээний дараах өдрийн дундаж |илүүдэл| {avg_news:.2f}% — бүх компани-өдрийн дундаж {avg_all:.2f}% ({avg_news / avg_all:.1f} дахин).", AMBER))
        else:
            summary.append((f"Дээж цөөн ({len(items)}) тул мэдээ ба үнийн хөдөлгөөний хамаарлыг дүгнэх боломжгүй.", AMBER))
        summary.append((f"Мэдээний дараа зах зээлээс илүү өссөн {up}, илүү унасан {len(items) - up}.", GREEN))
    summary.append(("Хамаарал ≠ шалтгаан: нэг өдөр олон мэдээ гарч болно, үнэд өөр хүчин зүйл нөлөөлнө. Мэдээг компанийн нэрээр автоматаар таарууллаа.", RED))
    shown = items[:8]
    ctx = dict(range=f"{week[0][5:]} → {week[-1][5:]}", items=shown, summary=summary,
               kpis=[(str(len(news)), "татсан мэдээ (нийт)", None), (str(matched_news), "тайлан дахь компани дурдсан", None),
                     (str(len(items)), "хэмжигдсэн хослол", None),
                     (f"{avg_news:.2f}%" if avg_news is not None else "—", "мэдээний дараах дундаж |илүүдэл|", None)])
    label = iso_label(monday)
    top = shown[:3]
    caption = "\n".join([f"📰 Мэдээ ба зах зээлийн хариу ({ctx['range']})", f"{matched_news} мэдээнд тайлан дахь компани дурдагдсан."]
                        + [f"• {i['sym']} ({i['when']}): {i['exc']:+.2f}% илүүдэл — {i['title'][:70]}" for i in top] + [A.DISCLAIMER_SHORT])
    text = caption + "\n\n" + "\n".join(f"{i['when']} {i['sym']} {i['title']} → {i['react_day']} {i['chg']:+.2f}% (зах зээл {i['mkt']:+.2f}%)" for i in shown)
    return label, ctx, caption, text, bool(shown)


def cmd_news():
    clear_latest("news")
    label, ctx, caption, text, has = build_news()
    if not has:
        print("Энэ 7 хоногт мэдээ-үнийн хос олдсонгүй — зураг гаргахгүй.")
        return 0
    save_outputs("news", label, lambda p: RX.render_news(ctx, p), caption, text)
    return 0


# ================================================================== БҮХ ЦАГ ҮЕИЙН ХААЛТЫН ХАНШ
def build_alltime():
    """data/history/<ТИКЕР>.csv (open.mse.mn) + манай өөрийн хэлцлээс (түүхээс хойших өдрүүд) бүх цаг үеийн хаалтын ханшийн зураг."""
    import bisect
    import history_mse as H
    names = load_names()
    series = {}
    for key in H.KEYS:
        bars = H.read_csv(key)
        if len(bars) >= 30:
            series[key] = {date.fromisoformat(d): b["close"] for d, b in bars.items()}
    if len(series) < 3:
        return None
    # түүхийн сүүлийн өдрөөс хойших өдрүүдийг манай хэлцлийн өгөгдлөөс (албан ёсны хаалт) нөхнө
    last_hist = max(max(s) for s in series.values())
    for d in [x for x in A.all_days() if date.fromisoformat(x) > last_hist]:
        for sym, g in A.core_of(A.load_day(d)).groupby("sym"):
            if sym in series:
                series[sym][date.fromisoformat(d)] = A.official_close(g)[0]
    items, flags = [], []
    for key, s in series.items():
        ds = sorted(s)
        cl = [s[d] for d in ds]
        ords = [d.toordinal() for d in ds]
        i_ath, i_atl = max(range(len(cl)), key=cl.__getitem__), min(range(len(cl)), key=cl.__getitem__)
        last = cl[-1]
        j = bisect.bisect_right(ords, ords[-1] - 365) - 1
        y1 = (last / cl[j] - 1) * 100 if j >= 0 and ords[-1] - ords[j] < 400 else None
        jumps = sum(1 for a, b in zip(cl, cl[1:]) if a > 0 and abs(b / a - 1) > 0.4)
        if jumps:
            flags.append(key)
        items.append(dict(key=key, name=names.get(key, ""), dates=ords, closes=cl, i_ath=i_ath, i_atl=i_atl, last=last,
                          ath=cl[i_ath], atl=cl[i_atl], ath_year=ds[i_ath].year, atl_year=ds[i_atl].year,
                          from_ath=(last / cl[i_ath] - 1) * 100, mult_atl=last / cl[i_atl], y1=y1, flag=jumps,
                          logy=max(cl) / max(min(cl), 1e-9) > 6, first_year=ds[0].year, last_label=f"{ds[-1]:%Y-%m-%d}", span=(ds[-1] - ds[0]).days / 365.25))
    items.sort(key=lambda it: -it["from_ath"])
    near = [it for it in items if it["from_ath"] >= -10]
    deep = [it for it in items if it["from_ath"] <= -50]
    avg = sum(it["from_ath"] for it in items) / len(items)
    longest = max(items, key=lambda it: it["span"])
    last_date = max(date.fromordinal(max(it["dates"])) for it in items)
    notes = ["Хаалт = МХБ-ийн албан ёсны хаалтын ханш (open.mse.mn); сүүлийн өдрүүд манай хэлцлийн өгөгдлөөс. ATH/ATL = түүхэн хамгийн өндөр/доод хаалт.",
             "Ханш тохируулаагүй: хувьцаа хуваалт, шинэ хувьцаа гаргалт, ногдол ашгийг тусгаагүй тул урт хугацааны өөрчлөлтийг ойролцоо гэж үзнэ."]
    if flags:
        notes.append("⚠ Өдрийн өөрчлөлт 40%-иас их тохиолдол бүхий компани (үнийн тохируулга хийгээгүй байж болзошгүй): " + ", ".join(flags))
    ctx = dict(items=items, notes=notes, range=f"{min(it['first_year'] for it in items)} → {last_date:%Y-%m-%d}",
               kpis=[(str(len(items)), "компани (түүхтэй)", None), (str(len(near)), "ATH-ийн ойролцоо (≤10%)", POS),
                     (str(len(deep)), "ATH-ээс 50%+ доогуур", NEG), (f"{avg:.0f}%", "ATH-ээс дундаж зөрүү", NEG if avg < 0 else POS),
                     (f"{longest['span']:.0f} жил", f"хамгийн урт түүх ({longest['key']})", None)])
    f_ = lambda lst: ", ".join(f"{it['key']} {it['from_ath']:.0f}%" if it["from_ath"] < -0.05 else f"{it['key']} ATH" for it in lst[:3])
    caption = "\n".join([f"📈 Бүх цаг үеийн хаалтын ханш ({ctx['range']})", f"ATH-ийн ойролцоо (≤10%): {f_(near) or '—'}",
                         f"ATH-ээс хамгийн хол: {f_(items[::-1])}", A.DISCLAIMER_SHORT])
    text = caption + "\n\n" + "\n".join(f"{it['key']}: одоо {A.px(it['last'])}, ATH {A.px(it['ath'])} ({it['ath_year']}), ATL {A.px(it['atl'])} ({it['atl_year']}), ATH-ээс {it['from_ath']:.0f}%" for it in items)
    return iso_label(last_date), ctx, caption, text


def cmd_alltime():
    clear_latest("alltime")
    res = build_alltime()
    if not res:
        print("data/history/-д хангалттай түүх алга (дор хаяж 3 компани). Эхлээд `history_mse.py backfill` ажиллуулна уу.")
        return 0
    label, ctx, caption, text = res
    save_outputs("alltime", label, lambda p: RX.render_alltime(ctx, p), caption, text)
    return 0


# ================================================================== САР, УЛИРАЛ, ЖИЛИЙН ХАНШИЙН ХӨДӨЛГӨӨН (%)
MONTH_CSV = "monthly_close.csv"   # заавал биш: data/monthly_close.csv (symbol,month,close), month = YYYY-MM


def month_end_closes(asof):
    """Тикер -> {(он, сар): хаалт}. Эх сурвалж: data/history/*.csv (өдрийн), түүхээс хойших өдрүүд манай хэлцлөөс
    (албан ёсны хаалт), мөн заавал биш data/monthly_close.csv. Хэлцэлгүй сарын хаалтыг өмнөхөөс нь хэвээр үргэлжлүүлнэ."""
    import csv as _csv
    import history_mse as H
    daily, flags = {}, set()
    for key in H.KEYS:
        bars = H.read_csv(key)
        if bars:
            daily[key] = {date.fromisoformat(d): b["close"] for d, b in bars.items() if date.fromisoformat(d) <= asof}
    monthly = {}
    p = A.DATA_DIR / MONTH_CSV
    if p.exists():
        with open(p, newline="", encoding="utf-8") as fh:
            for r in _csv.DictReader(fh):
                try:
                    y, m = map(int, r["month"].strip()[:7].split("-"))
                    monthly.setdefault(r["symbol"].strip(), {})[(y, m)] = float(r["close"])
                except (KeyError, ValueError):
                    continue
    last_hist = max([max(s) for s in daily.values() if s] or [date(1990, 1, 1)])
    for d in [x for x in A.all_days() if last_hist < date.fromisoformat(x) <= asof]:
        for sym, g in A.core_of(A.load_day(d)).groupby("sym"):
            if sym in daily:
                daily[sym][date.fromisoformat(d)] = A.official_close(g)[0]
    out = {}
    for key in set(daily) | set(monthly):
        me = dict(monthly.get(key, {}))
        s = daily.get(key, {})
        for d in sorted(s):
            me[(d.year, d.month)] = s[d]                       # сарын сүүлийн арилжааны өдрийн хаалт (өдрийн өгөгдөл давамгайлна)
        if s:
            cl = [s[d] for d in sorted(s)]
            if any(a > 0 and abs(b / a - 1) > 0.4 for a, b in zip(cl, cl[1:])):
                flags.add(key)
        if len(me) < 2:
            continue
        ks = sorted(me)
        y, m = ks[0]
        filled, last = {}, None
        while (y, m) <= (asof.year, asof.month):                # хоосон сарыг өмнөх хаалтаар дүүргэнэ
            last = me.get((y, m), last)
            filled[(y, m)] = last
            m += 1
            if m > 12:
                y, m = y + 1, 1
        out[key] = filled
    return out, flags


def build_periods(kind, asof=None):
    import history_mse as H
    if not asof:
        if os.environ.get("ASOF"):
            asof = date.fromisoformat(os.environ["ASOF"])
        else:
            days = A.all_days()
            asof = date.fromisoformat(days[-1]) if days else date.today()
    me, flags = month_end_closes(asof)
    if len(me) < 3:
        return None
    names = load_names()
    at = lambda k, y, m: me[k].get((y, m))
    ratio = lambda a, b: None if not a or not b else (a / b - 1) * 100
    nm = date(asof.year + (asof.month == 12), asof.month % 12 + 1, 1)
    lw = nm - timedelta(days=1)
    while lw.weekday() > 4:                                  # сарын сүүлийн ажлын өдөр
        lw -= timedelta(days=1)
    month_complete = asof >= lw
    partial = not month_complete
    if kind == "monthly":
        y = asof.year
        periods = [(f"{y}.{m:02d}", (y, m), (y, m - 1) if m > 1 else (y - 1, 12)) for m in range(1, asof.month + 1)]
        total_label, total_span = "Жилийн эхнээс", ((y, asof.month), (y - 1, 12))
        title, card_title = "Сарын ханшийн хөдөлгөөн", "Сар бүрийн хаалтын ханшийн өөрчлөлт, %"
        sub = "Сар бүрийн сүүлийн арилжааны өдрийн хаалтыг өмнөх сарын хаалттай харьцуулав."
        cap = 15.0
        label = f"{y}-{asof.month:02d}"
    elif kind == "quarterly":
        qs, (y, q) = [], (asof.year, (asof.month - 1) // 3 + 1)
        for _ in range(8):
            qs.append((y, q))
            q -= 1
            if q == 0:
                y, q = y - 1, 4
        qs.reverse()
        periods = []
        for y, q in qs:
            end_m = 3 * q if (y, q) != qs[-1] or asof.month == 3 * q else asof.month
            start_prev = (y, 3 * q - 3) if q > 1 else (y - 1, 12)
            periods.append((f"{y}.Q{q}", (y, end_m), start_prev))
        partial = not (asof.month in (3, 6, 9, 12) and month_complete)
        total_label = "Нийт\n8 улирал"
        total_span = (periods[-1][1], periods[0][2])
        title, card_title = "Улирлын ханшийн хөдөлгөөн", "Улирал бүрийн хаалтын ханшийн өөрчлөлт, %"
        sub = "Улирал бүрийн сүүлийн сарын хаалтыг өмнөх улирлын хаалттай харьцуулав."
        cap = 30.0
        label = f"{asof.year}-Q{(asof.month - 1) // 3 + 1}"
    else:
        years = list(range(max(min(min(k[0] for k in v) for v in me.values()), asof.year - 11), asof.year + 1))
        periods = [(str(y), (y, 12 if y < asof.year else asof.month), (y - 1, 12)) for y in years]
        partial = not (asof.month == 12 and month_complete)
        total_label, total_span = "Бүртгэгдсэнээс", ((asof.year, asof.month), None)
        title, card_title = "Жилийн ханшийн хөдөлгөөн", "Жил бүрийн хаалтын ханшийн өөрчлөлт, %"
        sub = "Жил бүрийн 12-р сарын хаалтыг өмнөх жилийн хаалттай харьцуулав."
        cap = 60.0
        label = str(asof.year)
    rows = []
    for key, s in me.items():
        vals = [ratio(s.get(e), s.get(b)) for _, e, b in periods]
        # хуучин үнэт цаасны түүх хоёрдугаар баганаас эхэлбэл эхний баганын өмнөх суурь байхгүй -> None
        total = ratio(s.get(total_span[0]), s[min(s)] if kind == "yearly" else s.get(total_span[1]))   # жил: бүртгэгдсэн анхны хаалтаас
        if all(v is None for v in vals):
            continue
        rows.append(dict(key=key, name=names.get(key, ""), flag=key in flags, vals=vals, total=total))
    if len(rows) < 3:
        return None
    rows.sort(key=lambda r: -(r["total"] if r["total"] is not None else -1e9))
    n = len(periods)
    avg = [(sum(r["vals"][i] for r in rows if r["vals"][i] is not None) / max(1, sum(1 for r in rows if r["vals"][i] is not None))
            if any(r["vals"][i] is not None for r in rows) else None) for i in range(n)]
    tv = [r["total"] for r in rows if r["total"] is not None]
    avg_total = sum(tv) / len(tv) if tv else None
    counts = [(sum(1 for r in rows if r["vals"][i] is not None and r["vals"][i] > 0), sum(1 for r in rows if r["vals"][i] is not None and r["vals"][i] < 0)) for i in range(n)] + \
             [(sum(1 for v in tv if v > 0), sum(1 for v in tv if v < 0))]
    last_vals = [(r["key"], r["vals"][-1]) for r in rows if r["vals"][-1] is not None]
    best, worst = max(last_vals, key=lambda t: t[1]), min(last_vals, key=lambda t: t[1])
    plabel = periods[-1][0] + ("*" if partial else "")
    notes = ["Хаалт = МХБ-ийн албан ёсны хаалтын ханш (open.mse.mn); сүүлийн өдрүүд манай хэлцлийн өгөгдлөөс. Өөрчлөлт = үеийн эцсийн хаалт ÷ өмнөх үеийн эцсийн хаалт − 1."
             + (" * = үе дуусаагүй (сүүлийн мэдэгдэж буй хаалтаар)." if partial else ""),
             "Ханш тохируулаагүй (хувьцаа хуваалт, шинэ гаргалт, ногдол ашиг тусгаагүй). Хэлцэлгүй саруудад хаалт өмнөхөөрөө үлдэнэ. — = тухайн үед хувьцаа бүртгэлгүй/өгөгдөлгүй."]
    if flags:
        notes.append("⚠ Өдрийн өөрчлөлт 40%-иас их тохиолдолтой компани (тохируулга хийгээгүй байж болзошгүй): " + ", ".join(sorted(k for k in flags if k in {r['key'] for r in rows})))
    ctx = dict(title=title, card_title=card_title, subtitle=sub, range=f"{periods[0][0]} → {plabel}", cols=[p[0] for p in periods],
               partial_last=partial, total_label=total_label, rows=rows, avg=avg, avg_total=avg_total, counts=counts, cap=cap, notes=notes,
               kpis=[(f"{avg[-1]:+.1f}%" if avg[-1] is not None else "—", f"{plabel}: дундаж (тэнцүү жин)", POS if (avg[-1] or 0) >= 0 else NEG),
                     (str(counts[n - 1][0]), f"өссөн ({plabel})", POS), (str(counts[n - 1][1]), f"унасан ({plabel})", NEG),
                     (f"{best[0]} {best[1]:+.1f}%", "хамгийн их өссөн", POS), (f"{worst[0]} {worst[1]:+.1f}%", "хамгийн их унасан", NEG)])
    cap_txt = ", ".join(f"{k} {v:+.1f}%" for k, v in sorted(last_vals, key=lambda t: -t[1])[:3])
    low_txt = ", ".join(f"{k} {v:+.1f}%" for k, v in sorted(last_vals, key=lambda t: t[1])[:3])
    caption = f"📊 {title} ({ctx['range']})\n{plabel}: дундаж {avg[-1]:+.1f}% · өссөн {counts[n - 1][0]} · унасан {counts[n - 1][1]}\nТэргүүлэгч: {cap_txt}\nХоцрогч: {low_txt}\n{A.DISCLAIMER_SHORT}"
    text = caption + "\n\n" + "\n".join(f"{r['key']}: " + " ".join("—" if v is None else f"{v:+.1f}%" for v in r["vals"]) for r in rows)
    return label, ctx, caption, text


def cmd_periods(kind):
    kinds = {"monthly": "Сар", "quarterly": "Улирал", "yearly": "Жил"}
    clear_latest(kind)
    res = build_periods(kind)
    if not res:
        print("data/history/-д хангалттай түүх алга. Эхлээд `history_mse.py backfill` (эсвэл data/monthly_close.csv) бэлдэнэ үү.")
        return 0
    label, ctx, caption, text = res
    save_outputs(kind, label, lambda p: RX.render_periods(ctx, p), caption, text)
    print(f"{kinds[kind]}: {len(ctx['rows'])} компани, {len(ctx['cols'])} үе")
    return 0


def cmd_periods_auto():
    """Сүүлд дууссан сар (мөн улирлын/жилийн эцэс бол улирал, жил)-ын хүснэгтийг гаргана.
    Өдөр бүр ажиллуулахад ижил зураг давтан илгээгдэхгүй (send_telegram.py агуулгаар нь шалгана)."""
    today = A.ub_today()
    asof = today.replace(day=1) - timedelta(days=1)
    os.environ["ASOF"] = asof.isoformat()
    for k in ("monthly", "quarterly", "yearly"):
        clear_latest(k)
    made = []
    for kind, ok in (("monthly", True), ("quarterly", asof.month in (3, 6, 9, 12)), ("yearly", asof.month == 12)):
        if ok:
            cmd_periods(kind)
            if (A.REPORT_DIR / f"latest_{kind}.png").exists():
                made.append(kind)
    print("Үүссэн:", made or "байхгүй")
    return 0


COMMANDS = {"spotlight": cmd_spotlight, "term": cmd_term, "news": cmd_news, "news-collect": cmd_news_collect, "alltime": cmd_alltime, "monthly": lambda: cmd_periods("monthly"), "quarterly": lambda: cmd_periods("quarterly"), "yearly": lambda: cmd_periods("yearly"), "periods-auto": cmd_periods_auto}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(COMMANDS[cmd]() or 0)
