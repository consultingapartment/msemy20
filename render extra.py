#!/usr/bin/env python3
"""Нэмэлт инфографикууд: "Долоо хоногийн компани", "Арилжааны нэр томьёо", "Мэдээ ба зах зээлийн хариу".

render_image.py-ийн Canvas, өнгө, хүснэгт, картыг дахин ашиглана (ижил openmindMSE хэв маяг).
Тоо бүр өгөгдлөөс шууд зурагдана (AI зураг биш).
"""
import math

from PIL import Image, ImageDraw

import render_image as R
from render_image import (AMBER, AMBER_BG, BG, BLUE, BLUE_BG, BORDER, CARD, CYAN, G, GREEN, GREEN_BG, HDR_SUB, LOGO_GREEN,
                          LOGO_RED, M, MUTED, NAVY1, NAVY2, RED, RED_BG, S, STRIPE, TXT, W, Canvas, card, chg_color,
                          draw_footer, head_h, list_box, table, table_h)


# ------------------------------------------------------------------ толгой, схем
def brand_header(c, title, label, sub, kpis, hdr_h=232):
    """kpis: [(утга, тайлбар, өнгө|None)] — тэнцүү өргөнтэй."""
    if c.dry:
        return
    for yy in range(hdr_h * S):
        t = yy / (hdr_h * S)
        col = tuple(int(NAVY1[i] + (NAVY2[i] - NAVY1[i]) * t) for i in range(3))
        c.d.line([0, yy, W * S, yy], fill=col)
    bx, by = M + 6, 78
    for i, hh in enumerate([22, 36, 52]):
        c.rect(bx + i * 20, by - hh, 14, hh, fill=CYAN, r=2)
    c.line(bx - 4, by - 30, bx + 28, by - 54, (255, 255, 255), 3)
    c.line(bx + 28, by - 54, bx + 18, by - 54, (255, 255, 255), 3)
    c.line(bx + 28, by - 54, bx + 28, by - 44, (255, 255, 255), 3)
    x0 = M + 92
    logo_left = W - M - c.tw("openmind", 52, True) - c.tw("MSE", 52, True)
    base = [(title, 50, True), (label, 38, True), (sub, 28, False)]
    total_w = sum(c.tw(t, s_, b_) for t, s_, b_ in base if t) + 34 + 16
    f = min(1.0, (logo_left - 24 - x0) / total_w)
    xx = x0
    for (t, s_, b_), col_, y_ in zip(base, [(255, 255, 255), CYAN, HDR_SUB], [54, 56, 58]):
        if t:
            xx += c.text(xx, y_, t, s_ * f, b_, col_, "lm") + 16 * f
    c.text(W - M, 50, "MSE", 52, True, LOGO_GREEN, "rm")
    c.text(W - M - c.tw("MSE", 52, True), 50, "openmind", 52, True, (255, 255, 255), "rm")
    c.text(W - M, 92, "powered by Big Short Ganbayar", 20, True, LOGO_RED, "rm")
    ky, kh = 118, 96
    n = len(kpis)
    cw = (W - 2 * M) / n
    for i, (val, cap, col) in enumerate(kpis):
        x = M + i * cw
        if i:
            c.line(x, ky + 6, x, ky + kh - 6, (70, 104, 160), 1)
        c.text(x + 18, ky + 36, val, 38, True, col or (255, 255, 255), "lm", maxw=cw - 30)
        c.text(x + 18, ky + 76, cap, 16, False, HDR_SUB, "lm", maxw=cw - 30)


def render(ctx, rows, header_fn, path, hdr_h=232, foot_h=58):
    def run(c, plan=None):
        header_fn(c, ctx, hdr_h)
        y, heights = hdr_h + G, []
        for ri, row in enumerate(rows):
            rh = max(fn(c, 0, 0, w, 0, ctx) for fn, w in row) if plan is None else plan[ri]
            heights.append(rh)
            if rh and plan is not None:
                x = M
                for fn, w in row:
                    fn(c, x, y, w, rh, ctx)
                    x += w + G
            if rh:
                y += rh + G
        if plan is not None:
            draw_footer(c, y, foot_h)
        return heights, y + foot_h

    heights, total = run(Canvas(None))
    c = Canvas(total)
    run(c, heights)
    c.img.save(path, "PNG", optimize=True)
    return path


# ------------------------------------------------------------------ график хэрэгслүүд
def layer(c, x, y, w, h, fn, ss=3):
    """Шугам, дүрсийг 3 дахин нягтаар зурж багасгана (гөлгөр ирмэг). fn(d, k): k = нэг логик px-ийн бодит px."""
    if c.dry:
        return
    k = S * ss
    img = Image.new("RGBA", (int(w * k), int(h * k)), (0, 0, 0, 0))
    fn(ImageDraw.Draw(img), k)
    img = img.resize((int(w * S), int(h * S)), Image.LANCZOS)
    c.img.paste(img, (int(x * S), int(y * S)), img)


def nice_ticks(lo, hi, n=4):
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    t = math.ceil(lo / step) * step
    out = []
    while t <= hi + 1e-9:
        out.append(t)
        t += step
    return out


def fmt_num(v):
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}".rstrip("0").rstrip(".")


def price_chart(c, x, y, w, h, pts, vwap=None, markers=(), breaks=(), day_labels=(), refs=()):
    """pts: үнийн цуваа. breaks: өдөр эхлэх индекс. markers: [{i, price, val, text}]. refs: [(үнэ, нэр, өнгө)]."""
    pl, pr, pt, pb = 66, 14, 12, 30
    px0, py0, pw, ph = x + pl, y + pt, w - pl - pr, h - pt - pb
    vals = list(pts) + ([vwap] if vwap else []) + [r[0] for r in refs] + [m["price"] for m in markers]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.12 or abs(hi) * 0.01 or 1
    lo, hi = lo - pad, hi + pad
    n = len(pts)
    X = lambda i: (i / max(1, n - 1)) * pw
    Y = lambda v: (1 - (v - lo) / (hi - lo)) * ph
    for tv in nice_ticks(lo, hi, 4):
        yy = py0 + Y(tv)
        c.line(px0, yy, px0 + pw, yy, BORDER, 0.6)
        c.text(px0 - 8, yy, fmt_num(tv), 12.5, False, MUTED, "rm")
    bl = list(breaks) + [n]
    for k, b in enumerate(breaks):
        if k:
            c.line(px0 + X(b), py0, px0 + X(b), py0 + ph, (170, 186, 210), 1)
        mid = (b + bl[k + 1]) / 2
        if k < len(day_labels):
            c.text(px0 + X(mid), py0 + ph + 16, day_labels[k], 13, True, MUTED, "mm")

    def draw(d, k):
        for rv, _, rc in refs:
            yy = Y(rv) * k
            for xs in range(0, int(pw * k), int(14 * k)):
                d.line([xs, yy, min(xs + 7 * k, pw * k), yy], fill=rc + (230,), width=int(1.6 * k))
        if vwap:
            yy = Y(vwap) * k
            for xs in range(0, int(pw * k), int(12 * k)):
                d.line([xs, yy, min(xs + 6 * k, pw * k), yy], fill=(235, 104, 52, 255), width=int(2 * k))
        d.line([(X(i) * k, Y(v) * k) for i, v in enumerate(pts)], fill=(42, 120, 214, 255), width=int(2.8 * k), joint="curve")
        for m in markers:
            r = (6 + min(10, math.sqrt(max(m["val"], 1) / 1e6) * 1.1)) * k
            cx, cy = X(m["i"]) * k, Y(m["price"]) * k
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(245, 158, 11, 120), outline=(217, 119, 6, 255), width=int(2 * k))
    layer(c, px0, py0, pw, ph, draw)
    c.line(px0, py0 + ph, px0 + pw, py0 + ph, (170, 186, 210), 1)
    placed = []   # [(x1, x2, y)] — шошгууд давхцахгүй байлгана
    for m in sorted(markers, key=lambda m: m["i"]):
        mx, my = px0 + X(m["i"]), py0 + Y(m["price"])
        left = mx > px0 + pw * 0.6
        tw_ = c.tw(m["text"], 12.5, True)
        x1 = mx - 16 - tw_ if left else mx + 16
        ly = my - 18
        for _ in range(6):
            hit = [p for p in placed if x1 < p[1] + 6 and x1 + tw_ > p[0] - 6 and abs(ly - p[2]) < 17]
            if not hit:
                break
            ly += 20 if ly < py0 + ph - 24 else -40
        ly = min(max(ly, py0 + 8), py0 + ph - 8)
        placed.append((x1, x1 + tw_, ly))
        c.text(x1, ly, m["text"], 12.5, True, TXT, "lm")
    for rv, name, rc in refs:
        c.text(px0 + pw - 4, py0 + Y(rv) - 9, name, 12, True, rc, "rm")
    if vwap:
        c.text(px0 + 6, py0 + Y(vwap) - 9, f"VWAP {fmt_num(vwap)}", 12, True, (235, 104, 52), "lm")


def stack_bars(c, x, y, w, h, labels, core, huge, ref=None, fmt=None, ref_label="дундаж"):
    """Өдрийн арилжааны дүн: ердийн (цэнхэр) + онцгой (шар). ref: тасархай шугам."""
    fmt = fmt or (lambda v: f"{v / 1e6:,.0f}")
    pl, pt, pb = 12, 22, 24
    ph = h - pt - pb
    top = max([a + b for a, b in zip(core, huge)] + ([ref] if ref else []) + [1]) * 1.08
    n = len(labels)
    slot = (w - pl) / n
    bw = min(70, slot * 0.55)

    def draw(d, k):
        for i in range(n):
            bx = (pl + slot * i + (slot - bw) / 2) * k
            hc, hh_ = core[i] / top * ph * k, huge[i] / top * ph * k
            base = (pt + ph) * k
            d.rounded_rectangle([bx, base - hc, bx + bw * k, base], radius=3 * k, fill=(42, 120, 214, 255))
            if hh_ > 0:
                d.rounded_rectangle([bx, base - hc - hh_, bx + bw * k, base - hc], radius=3 * k, fill=(245, 158, 11, 255))
        if ref:
            yy = (pt + ph - ref / top * ph) * k
            for xs in range(0, int(w * k), int(14 * k)):
                d.line([xs, yy, xs + 7 * k, yy], fill=(100, 116, 142, 255), width=int(1.6 * k))
    layer(c, x, y, w, h, draw)
    for i in range(n):
        cx = x + pl + slot * i + slot / 2
        tot = core[i] + huge[i]
        base = y + pt + ph
        c.text(cx, base - tot / top * ph - 11, fmt(tot), 13, True, TXT, "mm")
        c.text(cx, base + 13, labels[i], 13, True, MUTED, "mm")
    if ref:
        c.text(x + pl + 2, y + pt + ph - ref / top * ph - 10, f"{ref_label}: {fmt(ref)}", 11.5, True, MUTED, "lm")


def bars_h(c, x, y, w, items, row_h=30, label_w=96, val_w=120, fs=15):
    """items: [(нэр, утга, өнгө, текст)]. Босоо биш, хэвтээ багана. Буцаах: ашигласан өндөр."""
    top = max([abs(i[1]) for i in items] + [1e-9])
    bw = w - label_w - val_w
    for k, (name, v, col, txt) in enumerate(items):
        yy = y + k * row_h + row_h / 2
        c.text(x, yy, name, fs, True, TXT, "lm", maxw=label_w - 8)
        c.rect(x + label_w, yy - 9, bw, 18, fill=STRIPE, r=4)
        c.rect(x + label_w, yy - 9, max(3, bw * abs(v) / top), 18, fill=col, r=4)
        c.text(x + w, yy, txt, fs - 1, True, TXT, "rm", maxw=val_w - 6)
    return len(items) * row_h


def dots_time(c, x, y, w, h, rows, t0_label="10:00:00", span=60, step=10):
    """rows: [(нэр, [нээлтээс хойших секунд])]. Цагийн тэнхлэг дээрх цэгэн график."""
    pl = 70
    pw = w - pl - 12
    n = len(rows)
    rh = (h - 26) / max(n, 1)
    for k in range(0, span + 1, step):
        xx = x + pl + pw * k / span
        c.line(xx, y, xx, y + h - 26, BORDER, 0.6)
        c.text(xx, y + h - 12, f"+{k}с", 12, False, MUTED, "mm")

    def draw(d, kk):
        for i, (_, secs) in enumerate(rows):
            cy = (i + 0.5) * rh
            for s_ in secs:
                if 0 <= s_ <= span:
                    cx = pw * s_ / span
                    r = 4.2 * kk
                    d.ellipse([cx * kk - r, cy * kk - r, cx * kk + r, cy * kk + r], fill=(42, 120, 214, 170))
    layer(c, x + pl, y, pw, h - 26, draw)
    for i, (name, secs) in enumerate(rows):
        c.text(x, y + (i + 0.5) * rh, name, 13.5, True, TXT, "lm", maxw=pl - 8)


def ladder(c, x, y, w, h, trades, fs=13):
    """Нэг захиалгын үнийн шатлал: [(үнэ, ширхэг)] дарааллаар. Босоо багана = үнэ, өргөн = ширхэг."""
    prices = sorted({p for p, _ in trades})
    agg = {p: sum(q for pp, q in trades if pp == p) for p in prices}
    top = max(agg.values())
    n = len(prices)
    rh = min(26, h / max(n, 1))
    lw = 84
    for i, p in enumerate(reversed(prices)):
        yy = y + i * rh + rh / 2
        c.text(x, yy, fmt_num(p), fs, True, TXT, "lm")
        bw = (w - lw - 90) * agg[p] / top
        c.rect(x + lw, yy - rh * 0.38, max(3, bw), rh * 0.76, fill=(42, 120, 214), r=3)
        c.text(x + lw + max(3, bw) + 8, yy, f"{agg[p]:,} ш", fs - 1, False, MUTED, "lm")
    return n * rh


# ------------------------------------------------------------------ жижиг блок
def chips_h(c, w, items, fs=15):
    return sum(max(34, len(c.wrap(t, fs, w - 28, True)) * 20 + 14) for t, _ in items)


def chips(c, x, y, w, items, fs=15):
    """items: [(текст, өнгө)] — өнгөт тэмдэгтэй, олон мөр болж болох жагсаалт. Буцаах: өндөр."""
    yy = y
    for txt, col in items:
        lines = c.wrap(txt, fs, w - 28, True)
        rh = max(34, len(lines) * 20 + 14)
        c.circle(x + 8, yy + rh / 2, 6, col)
        for i, ln in enumerate(lines):
            c.text(x + 24, yy + rh / 2 + (i - (len(lines) - 1) / 2) * 20, ln, fs, True, TXT, "lm")
        yy += rh
    return yy - y


def wrap_height(c, text, size, w, lh, bold=False):
    return len(c.wrap(text, size, w, bold)) * lh


def draw_wrapped(c, x, y, w, text, size, lh, fill=TXT, bold=False):
    for i, ln in enumerate(c.wrap(text, size, w, bold)):
        c.text(x, y + i * lh + lh / 2, ln, size, bold, fill, "lm")
    return len(c.wrap(text, size, w, bold)) * lh


# ================================================================== 1. ДОЛОО ХОНОГИЙН КОМПАНИ
def sp_header(c, ctx, hdr_h):
    sp = ctx
    brand_header(c, "Долоо хоногийн компани", sp["sym"], f"({sp['range']})", sp["kpis"], hdr_h)


def sp_chart(c, x, y, w, h, ctx):
    sub = f"{ctx['name']} · 5 минут тутмын хамгийн сүүлийн хэлцлийн үнэ (ердийн арилжаа)" if ctx.get("name") else "5 минут тутмын хамгийн сүүлийн хэлцлийн үнэ"
    hh = head_h(c, sub, w)
    need = hh + 270 + 36 + 150 + 18
    if c.dry:
        return need
    card(c, x, y, w, h, "Үнийн зам", sub, dot=(42, 120, 214))
    price_chart(c, x + 14, y + hh, w - 28, 270, ctx["pts"], ctx["vwap"], ctx["markers"], ctx["breaks"], ctx["day_labels"])
    ly = y + hh + 270 + 18
    c.text(x + 18, ly, "Өдрийн арилжааны дүн, сая ₮:", 13.5, True, MUTED, "lm")
    c.rect(x + 214, ly - 6, 12, 12, fill=(42, 120, 214), r=2)
    c.text(x + 232, ly, "ердийн", 13.5, False, MUTED, "lm")
    c.rect(x + 292, ly - 6, 12, 12, fill=(245, 158, 11), r=2)
    c.text(x + 310, ly, "онцгой хэлцэл", 13.5, False, MUTED, "lm")
    stack_bars(c, x + 14, y + hh + 270 + 28, w - 28, 150, ctx["day_labels"], [d["core"] for d in ctx["dayvals"]],
               [d["huge"] for d in ctx["dayvals"]], ctx.get("ref_avg"), ref_label=ctx.get("ref_label", "дундаж"))
    return need


def sp_reasons(c, x, y, w, h, ctx):
    hh = 50
    ev = ctx["events"]
    rs = ctx["reasons"]
    ev_h = sum(max(1, len(c.wrap(t, 14, w - 36 - 92, False))) * 18 + 8 for _, t in ev)
    need = hh + 8 + chips_h(c, w - 36, rs) + 46 + ev_h + 20
    if c.dry:
        return need
    card(c, x, y, w, h, "Яагаад энэ компани?", None, dot=(245, 158, 11))
    yy = y + hh + 8
    yy += chips(c, x + 18, yy, w - 36, rs) + 14
    c.text(x + 18, yy + 12, "Онцлох үйл явдал", 16, True, TXT, "lm")
    yy += 32
    for when, text in ev:
        lines = c.wrap(text, 14, w - 36 - 92)
        c.text(x + 18, yy + 9, when, 13, True, BLUE, "lm", maxw=86)
        for i, ln in enumerate(lines):
            c.text(x + 18 + 92, yy + 9 + i * 18, ln, 14, False, TXT, "lm")
        yy += max(1, len(lines)) * 18 + 8
    return need


def sp_days(c, x, y, w, h, ctx):
    hh = 50
    cols = [("Өдөр", 90, "l"), ("Хаалт\n(жигнэсэн дундаж)", 200, "r"), ("Өөрчлөлт", 140, "r"), ("Арилжааны\nдүн", 160, "r"),
            ("Хэлцэл", 130, "r"), ("Өдрийн муж", 164, "r")]
    rows = []
    for d in ctx["days"]:
        rows.append([(d["d"], None, True), (fmt_num(d["close"]), None, True),
                     ("—", MUTED, False) if d["chg"] is None else (f"{d['chg']:+.2f}%", chg_color(d["chg"]), True),
                     R._fmt().sm(d["val"]), f"{d['deals']:,}", f"{d['rng']:.1f}%"])
    need = hh + table_h(rows, 34, 44) + 18
    if c.dry:
        return need
    card(c, x, y, w, h, "Өдөр бүр", None, dot=(14, 165, 233))
    table(c, x + 18, y + hh, cols, rows, row_h=34, head_h=44, fs=15)
    return need


def sp_facts(c, x, y, w, h, ctx):
    hh = 50
    cp = ctx["compare"]
    tiles = ctx["facts"]
    need = hh + 8 + (len(tiles) // 2 + len(tiles) % 2) * 92 + 24 + 100
    if c.dry:
        return need
    card(c, x, y, w, h, "Индекстэй харьцуулбал", None, dot=(22, 163, 74))
    yy = y + hh + 8
    iw = (w - 36 - 12) / 2
    for i, (cap, val, col, sub) in enumerate(tiles):
        tx = x + 18 + (i % 2) * (iw + 12)
        ty = yy + (i // 2) * 92
        c.rect(tx, ty, iw, 82, fill=BLUE_BG if col is None else (GREEN_BG if col == GREEN else RED_BG), r=10)
        c.text(tx + iw / 2, ty + 16, cap, 12.5, True, TXT, "mm", maxw=iw - 10)
        c.text(tx + iw / 2, ty + 44, val, 24, True, col or BLUE, "mm", maxw=iw - 10)
        c.text(tx + iw / 2, ty + 68, sub, 12, False, MUTED, "mm", maxw=iw - 10)
    ty = yy + (len(tiles) // 2 + len(tiles) % 2) * 92 + 10
    lines = c.wrap(ctx["big_text"], 14, w - 52, True)
    c.rect(x + 18, ty, w - 36, 14 + 20 * len(lines) + 12 + 22, fill=AMBER_BG, r=10)
    c.text(x + 30, ty + 16, "Хамгийн том хэлцэл", 13.5, True, AMBER, "lm")
    for i, ln in enumerate(lines):
        c.text(x + 30, ty + 40 + i * 20, ln, 14, True, TXT, "lm")
    return need


SP_ROWS = [[(sp_chart, 920), (sp_reasons, 406)], [(sp_days, 920), (sp_facts, 406)]]


def render_spotlight(ctx, path):
    return render(ctx, SP_ROWS, sp_header, path)


# ================================================================== 2. НЭР ТОМЬЁО
def tm_header(c, ctx, hdr_h):
    brand_header(c, "Арилжааны нэр томьёо", f"№{ctx['no']}", f"({ctx['range']})", ctx["tiles"][:5], hdr_h)


def tm_def(c, x, y, w, h, ctx):
    hh = 50
    tw_ = w - 36
    paras = ctx["definition"]
    need = hh + 62 + sum(wrap_height(c, p, 19, tw_, 28) + 10 for p in paras) + 16
    if c.dry:
        return need
    card(c, x, y, w, h, "Энэ юу вэ?", None, dot=(37, 99, 235))
    yy = y + hh + 8
    c.text(x + 18, yy + 22, ctx["title"], 40, True, BLUE, "lm", maxw=tw_)
    yy += 56
    for p in paras:
        yy += draw_wrapped(c, x + 18, yy, tw_, p, 19, 28) + 10
    return need


def tm_example(c, x, y, w, h, ctx):
    hh = head_h(c, ctx["example_title"], w)
    ch = ctx["chart"]
    chart_h = ch.get("h", 300)
    note_lines = c.wrap(ctx["example_note"], 14, w - 36)
    need = hh + chart_h + 16 + len(note_lines) * 20 + 18
    if c.dry:
        return need
    card(c, x, y, w, h, "Энэ 7 хоногийн бодит жишээ", ctx["example_title"], dot=(22, 163, 74))
    cy = y + hh
    t = ch["type"]
    if t == "price":
        price_chart(c, x + 14, cy, w - 28, chart_h, ch["pts"], ch.get("vwap"), ch.get("markers", ()), ch.get("breaks", ()),
                    ch.get("day_labels", ()), ch.get("refs", ()))
    elif t == "bars":
        bars_h(c, x + 18, cy + 6, w - 36, ch["items"], row_h=ch.get("row_h", 30), label_w=ch.get("label_w", 96), val_w=ch.get("val_w", 150))
    elif t == "dots":
        dots_time(c, x + 18, cy, w - 36, chart_h, ch["rows"], span=ch.get("span", 60), step=ch.get("step", 10))
    elif t == "ladder":
        ladder(c, x + 18, cy + 6, w - 36, chart_h - 6, ch["trades"])
    for i, ln in enumerate(note_lines):
        c.text(x + 18, cy + chart_h + 16 + i * 20 + 10, ln, 14, False, MUTED, "lm")
    return need


def tm_why(c, x, y, w, h, ctx):
    hh = 50
    why = ctx["why"]
    need = hh + 10 + sum(wrap_height(c, t, 16, w - 36 - 26, 23, True) + 14 for t in why) + 8
    if c.dry:
        return need
    card(c, x, y, w, h, "Яагаад чухал вэ?", None, dot=(245, 158, 11))
    yy = y + hh + 10
    for i, t in enumerate(why, 1):
        c.circle(x + 30, yy + 11, 11, BLUE)
        c.text(x + 30, yy + 11, str(i), 13, True, (255, 255, 255), "mm")
        yy += draw_wrapped(c, x + 52, yy, w - 36 - 26, t, 16, 23, TXT, True) + 14
    return need


TM_ROWS = [[(tm_def, 1344)], [(tm_example, 880), (tm_why, 446)]]


def render_term(ctx, path):
    return render(ctx, TM_ROWS, tm_header, path)


# ================================================================== 3. МЭДЭЭ БА ЗАХ ЗЭЭЛИЙН ХАРИУ
def nw_header(c, ctx, hdr_h):
    brand_header(c, "Мэдээ ба зах зээлийн хариу", "", f"({ctx['range']})", ctx["kpis"], hdr_h)


def nw_table(c, x, y, w, h, ctx):
    items = ctx["items"]
    sub = "Мэдээ гарсны дараах арилжааны өдрийн хаалтын өөрчлөлтийг МХБ-н 20-той харьцуулав (хамаарал ≠ шалтгаан)"
    hh = head_h(c, sub, w)
    rh = 58
    need = hh + 44 + rh * max(1, len(items)) + 16
    if c.dry:
        return need
    card(c, x, y, w, h, "Мэдээнд дурдагдсан компаниуд", sub, dot=(37, 99, 235))
    cols = [("Мэдээ гарсан", 128), ("Компани", 90), ("Мэдээний гарчиг", 604), ("Хариу өдөр", 108), ("Компани\n%", 94),
            ("Зах зээл\n%", 94), ("Илүүдэл\n%", 94), ("Арилжаа\n(дундажаас)", 96)]
    tx, ty = x + 18, y + hh
    tw_ = sum(cw for _, cw in cols)
    c.rect(tx, ty, tw_, 44, fill=BLUE, r=6)
    cx = tx
    for i, (title, cw) in enumerate(cols):
        al = "l" if i < 4 else "r"
        for k, ln in enumerate(title.split("\n")):
            yy = ty + 22 + (k - (len(title.split("\n")) - 1) / 2) * 15
            c.text(cx + 10 if al == "l" else cx + cw - 10, yy, ln, 12.5, True, (255, 255, 255), "lm" if al == "l" else "rm", maxw=cw - 14)
        cx += cw
    yy = ty + 44
    if not items:
        c.text(tx + tw_ / 2, yy + 30, "Энэ 7 хоногт тайлан дахь компаниудыг дурдсан мэдээ олдсонгүй", 16, False, MUTED, "mm")
    for k, it in enumerate(items):
        if k % 2:
            c.rect(tx, yy, tw_, rh, fill=STRIPE)
        c.line(tx, yy + rh, tx + tw_, yy + rh, BORDER, 0.6)
        cx = tx
        vals = [it["when"], it["sym"], it["title"], it["react_day"], it["chg"], it["mkt"], it["exc"], it["turn"]]
        for i, ((_, cw), v) in enumerate(zip(cols, vals)):
            if i == 2:
                for j, ln in enumerate(c.wrap(v, 15, cw - 16)[:2]):
                    c.text(cx + 10, yy + 19 + j * 19, ln, 15, False, TXT, "lm")
            elif i in (4, 5, 6):
                txt = "—" if v is None else f"{v:+.2f}%"
                c.text(cx + cw - 10, yy + rh / 2, txt, 16, True, MUTED if v is None else chg_color(v), "rm")
            elif i == 7:
                c.text(cx + cw - 10, yy + rh / 2, "—" if v is None else f"{v:.1f}×", 16, True, TXT, "rm")
            else:
                c.text(cx + 10, yy + rh / 2, v, 15 if i != 1 else 16, i == 1, TXT, "lm", maxw=cw - 14)
            cx += cw
        yy += rh
    return need


def nw_summary(c, x, y, w, h, ctx):
    hh = 50
    lines = ctx["summary"]
    wrapped = [c.wrap(t, 16, w - 36 - 26, True) for t, _ in lines]
    need = hh + 10 + sum(len(wl) * 24 + 10 for wl in wrapped) + 8
    if c.dry:
        return need
    card(c, x, y, w, h, "Дүгнэлт", None, dot=(245, 158, 11))
    yy = y + hh + 10
    for (t, col), wl in zip(lines, wrapped):
        c.circle(x + 28, yy + 12, 6, col)
        for j, ln in enumerate(wl):
            c.text(x + 48, yy + 12 + j * 24, ln, 16, True, TXT, "lm")
        yy += len(wl) * 24 + 10
    return need


NW_ROWS = [[(nw_table, 1344)], [(nw_summary, 1344)]]


def render_news(ctx, path):
    return render(ctx, NW_ROWS, nw_header, path)


# ================================================================== 4. БҮХ ЦАГ ҮЕИЙН ХААЛТЫН ХАНШ
def decimate(vals, n=520):
    """Өгөгдлийг цөөлөхдөө хэсэг бүрийн хамгийн их/бага цэгийг хадгална (ATH, ATL алга болохгүй)."""
    total = len(vals)
    if total <= n:
        return list(enumerate(vals))
    out, buckets = [], n // 2
    step = total / buckets
    for b in range(buckets):
        lo, hi = int(b * step), min(total, int((b + 1) * step))
        seg = vals[lo:hi]
        if not seg:
            continue
        imn = min(range(len(seg)), key=seg.__getitem__) + lo
        imx = max(range(len(seg)), key=seg.__getitem__) + lo
        out += [(i, vals[i]) for i in sorted({imn, imx})]
    if out[-1][0] != total - 1:
        out.append((total - 1, vals[-1]))
    return out


def spark(c, x, y, w, h, dates, closes, i_ath, i_atl, logy):
    pts = decimate(closes)
    t0, t1 = dates[0], dates[-1]
    f = math.log if logy else (lambda v: v)
    lo, hi = min(f(v) for v in closes), max(f(v) for v in closes)
    pad = (hi - lo) * 0.1 or 1.0
    lo, hi = lo - pad * 0.6, hi + pad
    X = lambda d: (d - t0) / max(1, t1 - t0) * w
    Y = lambda v: (1 - (f(v) - lo) / (hi - lo)) * h

    def draw(d, k):
        poly = [(X(dates[i]) * k, Y(v) * k) for i, v in pts]
        d.polygon(poly + [(poly[-1][0], h * k), (poly[0][0], h * k)], fill=(42, 120, 214, 38))
        d.line(poly, fill=(42, 120, 214, 255), width=int(2.0 * k), joint="curve")
        for idx, col in ((i_ath, (34, 160, 90, 255)), (i_atl, (220, 38, 38, 255)), (len(closes) - 1, (42, 120, 214, 255))):
            cx, cy, r = X(dates[idx]) * k, Y(closes[idx]) * k, 4.6 * k
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col, outline=(255, 255, 255, 255), width=int(1.6 * k))
    layer(c, x, y, w, h, draw)
    for idx, lab, col, dy in ((i_ath, "ATH", GREEN, -13), (i_atl, "ATL", RED, 14)):
        px_, py_ = x + X(dates[idx]), y + Y(closes[idx])
        c.text(min(max(px_, x + 14), x + w - 14), min(max(py_ + dy, y + 7), y + h - 7), lab, 11, True, col, "mm")


def at_header(c, ctx, hdr_h):
    brand_header(c, "Бүх цаг үеийн хаалтын ханш", "", f"({ctx['range']})", ctx["kpis"], hdr_h)


def at_card(c, x, y, w, h, ctx, i):
    items = ctx["items"]
    if i >= len(items):
        return 0
    if c.dry:
        return 262
    A = R._fmt()
    it = items[i]
    c.rect(x, y, w, h, fill=CARD, outline=BORDER, r=14)
    c.text(x + 16, y + 24, it["key"], 21, True, TXT, "lm")
    nm = it.get("name") or ""
    c.text(x + 16, y + 45, nm, 12, False, MUTED, "lm", maxw=w - 130)
    fa = it["from_ath"]
    bg, fg = (GREEN_BG, GREEN) if fa >= -10 else (AMBER_BG, AMBER) if fa >= -50 else (RED_BG, RED)
    label = "ATH" if fa >= -0.05 else f"{fa:.0f}%"
    cw_ = max(54, c.tw(label, 15, True) + 20)
    c.rect(x + w - 16 - cw_, y + 12, cw_, 28, fill=bg, r=14)
    c.text(x + w - 16 - cw_ / 2, y + 26, label, 15, True, fg, "mm")
    if it["flag"]:
        c.triangle_warn(x + w - 16 - cw_ - 26, y + 14, 20, AMBER)
    spark(c, x + 14, y + 60, w - 28, 118, it["dates"], it["closes"], it["i_ath"], it["i_atl"], it["logy"])
    c.text(x + 16, y + 192, str(it["first_year"]), 11.5, False, MUTED, "lm")
    c.text(x + w - 16, y + 192, it["last_label"], 11.5, False, MUTED, "rm")
    cols = [("Одоо", A.px(it["last"]), TXT), (f"ATH · {it['ath_year']}", A.px(it["ath"]), GREEN), (f"ATL · {it['atl_year']}", A.px(it["atl"]), RED)]
    cwid = (w - 32) / 3
    for k, (cap, val, col) in enumerate(cols):
        cx_ = x + 16 + k * cwid
        c.text(cx_, y + 210, cap, 11.5, False, MUTED, "lm", maxw=cwid - 4)
        c.text(cx_, y + 229, val, 16, True, col, "lm", maxw=cwid - 4)
    y1 = it["y1"]
    sub = (f"1 жилд {y1:+.0f}% · " if y1 is not None else "") + f"ATL-ээс ×{it['mult_atl']:.1f}"
    c.text(x + 16, y + 250, sub, 12, False, MUTED, "lm", maxw=w - 28)
    return 262


def at_note(c, x, y, w, h, ctx):
    lines = ctx["notes"]
    wrapped = [c.wrap(t, 14, w - 36) for t in lines]
    need = 22 + sum(len(wl) * 20 + 6 for wl in wrapped) + 12
    if c.dry:
        return need
    c.rect(x, y, w, h, fill=AMBER_BG, outline=(240, 200, 120), r=14)
    yy = y + 20
    for wl in wrapped:
        for ln in wl:
            c.text(x + 18, yy, ln, 14, False, TXT, "lm")
            yy += 20
        yy += 6
    return need


def _make_at_card(i):
    return lambda c, x, y, w, h, ctx: at_card(c, x, y, w, h, ctx, i)


def render_alltime(ctx, path):
    n = len(ctx["items"])
    rows = [[(_make_at_card(r * 4 + k), 322) for k in range(4)] for r in range((n + 3) // 4)] + [[(at_note, 1344)]]
    render(ctx, rows, at_header, path)
    demo_mark(path)
    return path


def demo_mark(path):
    """DEMO_DATA=1 үед (зохиомол өгөгдлөөр туршихад) зургийг "ЗОХИОМОЛ ӨГӨГДӨЛ" гэж тод тэмдэглэнэ."""
    import os
    if os.environ.get("DEMO_DATA") != "1":
        return
    im = Image.open(path).convert("RGBA")
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    f = Canvas(None).font(120, True)
    txt = "ЗОХИОМОЛ ӨГӨГДӨЛ"
    tmp = Image.new("RGBA", (int(f.getlength(txt)) + 40, 200), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text((20, 20), txt, font=f, fill=(220, 38, 38, 70))
    tmp = tmp.rotate(24, expand=True, resample=Image.BICUBIC)
    for oy in range(200, im.height, 900):
        ov.paste(tmp, ((im.width - tmp.width) // 2, oy - tmp.height // 2), tmp)
    Image.alpha_composite(im, ov).convert("RGB").save(path, "PNG", optimize=True)


# ================================================================== 5. САР, УЛИРАЛ, ЖИЛИЙН ХАНШИЙН ХӨДӨЛГӨӨН (%)
def heat_color(v, cap):
    """Өсөлт ногоон, уналт улаан; хэмжээгээр нь өнгө бүдэг/тод болно. Буцаах: (дэвсгэр, үсгийн өнгө)."""
    if v is None:
        return STRIPE, MUTED
    a = min(1.0, abs(v) / cap)
    al = 0.30 + 0.70 * a
    base = (34, 170, 90) if v >= 0 else (222, 54, 48)
    col = tuple(int(255 - (255 - b) * al) for b in base)
    return col, ((255, 255, 255) if al > 0.58 else TXT)


def pt_header(c, ctx, hdr_h):
    brand_header(c, ctx["title"], "", f"({ctx['range']})", ctx["kpis"], hdr_h)


def pt_table(c, x, y, w, h, ctx):
    cols, rows = ctx["cols"], ctx["rows"]
    sub = ctx["subtitle"]
    hh = head_h(c, sub, w)
    rh, hd = 36, 40
    n_sum = 2
    need = hh + hd + rh * (len(rows) + n_sum) + 24
    if c.dry:
        return need
    card(c, x, y, w, h, ctx["card_title"], sub, dot=(22, 163, 74))
    ncols = len(cols) + 1                       # + нийт багана
    tx, ty = x + 18, y + hh
    tw_ = w - 36
    first = 262
    cw = (tw_ - first) / ncols
    c.rect(tx, ty, tw_, hd, fill=BLUE, r=6)
    c.text(tx + 12, ty + hd / 2, "Компани", 13.5, True, (255, 255, 255), "lm")
    labels = [lab + ("*" if i == len(cols) - 1 and ctx["partial_last"] else "") for i, lab in enumerate(cols)] + [ctx["total_label"]]
    for i, lab in enumerate(labels):
        parts = lab.split("\n")
        for k, ln in enumerate(parts):
            c.text(tx + first + cw * i + cw / 2, ty + hd / 2 + (k - (len(parts) - 1) / 2) * 15, ln, 13, True, (255, 255, 255), "mm", maxw=cw - 6)
    yy = ty + hd
    gap = 2.5

    def cells(vals, cap, bold_total=True):
        for i, v in enumerate(vals):
            bg, fg = heat_color(v, cap if i < len(cols) else cap * 2.2)
            cx = tx + first + cw * i
            c.rect(cx + gap, yy + gap, cw - 2 * gap, rh - 2 * gap, fill=bg, r=5)
            c.text(cx + cw / 2, yy + rh / 2, "—" if v is None else f"{v:+.2f}%", 13.5, True, fg, "mm", maxw=cw - 8)

    for k, row in enumerate(rows):
        if k % 2:
            c.rect(tx, yy, first, rh, fill=STRIPE)
        c.text(tx + 12, yy + rh / 2 - 6, row["key"], 15, True, TXT, "lm")
        if row["flag"]:
            c.triangle_warn(tx + 12 + c.tw(row["key"], 15, True) + 6, yy + rh / 2 - 15, 14, AMBER)
        c.text(tx + 12, yy + rh / 2 + 10, row["name"], 11, False, MUTED, "lm", maxw=first - 20)
        cells(row["vals"] + [row["total"]], ctx["cap"])
        yy += rh
    # нэгтгэл мөр
    c.line(tx, yy + 1, tx + tw_, yy + 1, (170, 186, 210), 1.2)
    c.text(tx + 12, yy + rh / 2, "МХБ-н 20 (тэнцүү жин)", 13.5, True, TXT, "lm", maxw=first - 16)
    cells(ctx["avg"] + [ctx["avg_total"]], ctx["cap"])
    yy += rh
    c.text(tx + 12, yy + rh / 2, "Өссөн ↑ / Унасан ↓", 13.5, True, TXT, "lm", maxw=first - 16)
    for i, (u, d) in enumerate(ctx["counts"]):
        cx = tx + first + cw * i
        c.text(cx + cw / 2, yy + rh / 2, f"{u} / {d}", 13.5, True, TXT, "mm", maxw=cw - 6)
    return need


def pt_note(c, x, y, w, h, ctx):
    wrapped = [c.wrap(t, 14, w - 36) for t in ctx["notes"]]
    need = 22 + sum(len(wl) * 20 + 6 for wl in wrapped) + 12
    if c.dry:
        return need
    c.rect(x, y, w, h, fill=AMBER_BG, outline=(240, 200, 120), r=14)
    yy = y + 20
    for wl in wrapped:
        for ln in wl:
            c.text(x + 18, yy, ln, 14, False, TXT, "lm")
            yy += 20
        yy += 6
    return need


def render_periods(ctx, path):
    render(ctx, [[(pt_table, 1344)], [(pt_note, 1344)]], pt_header, path)
    demo_mark(path)
    return path
