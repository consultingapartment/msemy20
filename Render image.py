#!/usr/bin/env python3
"""7 хоногийн тайланг нэг өндөр чанартай зураг (PNG) болгон зурна.

Тоо бүр analyze.py-ийн өгөгдлөөс шууд зурагдана (AI зураг биш), тиймээс алдаа гарахгүй.
Хэрэгтэй: Pillow ба Cyrillic фонт (fonts-liberation эсвэл fonts-dejavu-core).
    WEEKLY_FONT / WEEKLY_FONT_BOLD орчны хувьсагчаар өөр фонт зааж болно.
"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

S = 2            # нягтрал: логик 1 px = 2 бодит px (зураг 2800 px өргөнтэй)
W = 1400         # логик өргөн
M, G = 28, 18    # захын зай, картуудын завсар

BG = (232, 239, 248)
CARD = (255, 255, 255)
BORDER = (205, 217, 234)
NAVY1, NAVY2 = (8, 25, 60), (22, 62, 112)
BLUE = (30, 86, 160)
TXT = (18, 32, 62)
MUTED = (100, 116, 142)
GREEN = (22, 160, 74)
RED = (220, 38, 38)
GREEN_BG, RED_BG = (226, 246, 233), (253, 232, 232)
BLUE_BG, AMBER_BG, AMBER = (226, 238, 252), (255, 244, 214), (217, 119, 6)
CYAN = (86, 204, 255)
LOGO_GREEN, LOGO_RED = (61, 220, 132), (255, 64, 64)
STRIPE = (244, 248, 253)
HDR_SUB = (176, 200, 232)

_FONT_SETS = [
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]


def _find_fonts():
    reg, bold = os.environ.get("WEEKLY_FONT"), os.environ.get("WEEKLY_FONT_BOLD")
    if reg and bold and os.path.exists(reg) and os.path.exists(bold):
        return reg, bold
    for reg, bold in _FONT_SETS:
        if os.path.exists(reg) and os.path.exists(bold):
            return reg, bold
    raise RuntimeError("Cyrillic фонт олдсонгүй (fonts-liberation эсвэл fonts-dejavu-core суулгана уу)")


def _fmt():
    import analyze as A  # хэлбэржүүлэлтийг analyze.py-тай ижил байлгана
    return A


class Canvas:
    def __init__(self, h=None):
        self.dry = h is None
        self.fonts = {}
        self.reg, self.bold = _find_fonts()
        if not self.dry:
            self.img = Image.new("RGB", (W * S, int(h) * S), BG)
            self.d = ImageDraw.Draw(self.img)

    def font(self, size, bold=False):
        key = (round(size * 2) / 2, bold)
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(self.bold if bold else self.reg, int(round(key[0] * S)))
        return self.fonts[key]

    def tw(self, s, size, bold=False):
        return self.font(size, bold).getlength(s) / S

    def fit(self, s, size, bold, maxw, minsize=9):
        while maxw and size > minsize and self.tw(s, size, bold) > maxw:
            size -= 0.5
        return size

    def wrap(self, s, size, maxw, bold=False):
        words, lines, cur = s.split(" "), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if self.tw(t, size, bold) <= maxw or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def rect(self, x, y, w, h, fill=None, outline=None, r=0, bw=1):
        if self.dry:
            return
        box = [x * S, y * S, (x + w) * S - 1, (y + h) * S - 1]
        width = int(bw * S) if outline else 0
        if r:
            self.d.rounded_rectangle(box, radius=r * S, fill=fill, outline=outline, width=width)
        else:
            self.d.rectangle(box, fill=fill, outline=outline, width=width)

    def circle(self, cx, cy, r, fill):
        if not self.dry:
            self.d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=fill)

    def line(self, x1, y1, x2, y2, fill, w=1):
        if not self.dry:
            self.d.line([x1 * S, y1 * S, x2 * S, y2 * S], fill=fill, width=max(1, int(w * S)))

    def text(self, x, y, s, size=18, bold=False, fill=TXT, anchor="lm", maxw=None):
        size = self.fit(s, size, bold, maxw)
        if not self.dry:
            self.d.text((x * S, y * S), s, font=self.font(size, bold), fill=fill, anchor=anchor)
        return self.tw(s, size, bold)

    def star(self, cx, cy, r, fill):
        if self.dry:
            return
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rad = r if i % 2 == 0 else r * 0.45
            pts.append(((cx + rad * math.cos(ang)) * S, (cy + rad * math.sin(ang)) * S))
        self.d.polygon(pts, fill=fill)

    def triangle_warn(self, x, y, size, fill):
        if self.dry:
            return
        self.d.polygon([((x + size / 2) * S, y * S), ((x + size) * S, (y + size * 0.88) * S), (x * S, (y + size * 0.88) * S)], fill=fill)
        self.text(x + size / 2, y + size * 0.62, "!", size * 0.62, True, (255, 255, 255), "mm")


def chg_color(v, eps=0.005):
    return GREEN if v > eps else RED if v < -eps else MUTED


# ------------------------------------------------------------------ хүснэгт
def table_h(rows, row_h, head_h, sub_h=None):
    return head_h + sum((sub_h if (sub_h and any(isinstance(c, tuple) and len(c) > 3 for c in r)) else row_h) for r in rows)


def table(c, x, y, cols, rows, row_h=32, head_h=38, fs=15, hfs=12.5, sub_h=46):
    """cols: [(гарчиг, өргөн, 'l'|'r'|'c')]; cell: str | (str, өнгө, bold) | (str, өнгө, bold, дэд текст)."""
    tw_ = sum(w for _, w, _ in cols)
    c.rect(x, y, tw_, head_h, fill=BLUE, r=6)
    cx = x
    for title, w, al in cols:
        lines = title.split("\n")
        for i, ln in enumerate(lines):
            yy = y + head_h / 2 + (i - (len(lines) - 1) / 2) * (hfs + 2)
            ax = {"l": cx + 8, "r": cx + w - 8, "c": cx + w / 2}[al]
            c.text(ax, yy, ln, hfs, True, (255, 255, 255), {"l": "lm", "r": "rm", "c": "mm"}[al], maxw=w - 10)
        cx += w
    yy = y + head_h
    for i, row in enumerate(rows):
        has_sub = any(isinstance(cell, tuple) and len(cell) > 3 for cell in row)
        h = sub_h if has_sub else row_h
        if i % 2 == 1:
            c.rect(x, yy, tw_, h, fill=STRIPE)
        c.line(x, yy + h, x + tw_, yy + h, BORDER, 0.6)
        cx = x
        for (title, w, al), cell in zip(cols, row):
            txt, col, bold, sub = (cell, TXT, False, None) if isinstance(cell, str) else \
                (cell[0], cell[1] or TXT, cell[2] if len(cell) > 2 else False, cell[3] if len(cell) > 3 else None)
            ax = {"l": cx + 8, "r": cx + w - 8, "c": cx + w / 2}[al]
            anc = {"l": "lm", "r": "rm", "c": "mm"}[al]
            cy = yy + h / 2 - (7 if sub else 0)
            if txt.startswith("★"):
                c.star(cx + 12, yy + h / 2, 7.5, (245, 158, 11))
                rest = txt[1:].strip()
                if rest:
                    c.text(cx + 24, yy + h / 2, rest, fs - 1, bold, col, "lm", maxw=w - 28)
            else:
                c.text(ax, cy, txt, fs, bold, col, anc, maxw=w - 12)
            if sub:
                c.text(ax, yy + h / 2 + 11, sub, fs - 3.5, False, MUTED, anc, maxw=w - 12)
            cx += w
        yy += h
    return yy


# ------------------------------------------------------------------ карт
def head_h(c, sub, w):
    if not sub:
        return 50
    return 46 + 17 * len(c.wrap(sub, 13, w - 36)) + 6


def card(c, x, y, w, h, title, sub=None, dot=BLUE):
    c.rect(x, y, w, h, fill=CARD, outline=BORDER, r=14)
    c.circle(x + 22, y + 26, 7, dot)
    c.text(x + 38, y + 26, title, 22, True, TXT, "lm", maxw=w - 56)
    if sub:
        for i, ln in enumerate(c.wrap(sub, 13, w - 36)):
            c.text(x + 18, y + 54 + i * 17, ln, 13, False, MUTED, "lm")


def list_box(c, x, y, w, title, items, head_fill, head_txt, bg, cap=None, rows=3, row_h=28):
    """Жижиг жагсаалтын хайрцаг: толгой + мөрүүд. items: [(зүүн, баруун, баруун өнгө)]."""
    cap_h = 18 if cap else 0
    h = 30 + cap_h + rows * row_h + 10
    c.rect(x, y, w, h, fill=bg, r=10)
    c.rect(x, y, w, 30, fill=head_fill, r=10)
    c.rect(x, y + 18, w, 12, fill=head_fill)
    c.text(x + 12, y + 15, title, 14.5, True, head_txt, "lm", maxw=w - 20)
    if cap:
        c.text(x + 12, y + 30 + 10, cap, 11.5, False, MUTED, "lm", maxw=w - 20)
    yy = y + 30 + cap_h + 6
    for left, right, col in items[:rows]:
        c.text(x + 12, yy + row_h / 2, left, 16, True, TXT, "lm", maxw=w * 0.5)
        c.text(x + w - 12, yy + row_h / 2, right, 16, True, col, "rm", maxw=w * 0.55)
        yy += row_h
    if not items:
        c.text(x + w / 2, y + 30 + cap_h + 26, "—", 16, False, MUTED, "mm")
    return h


def card_huge(c, x, y, w, h, ctx):
    A = _fmt()
    hs = ctx["huge"]
    sub = f"({ctx['huge_rule']}; доорх тооцоонд ОРООГҮЙ)"
    hh = head_h(c, sub, w)
    show = hs[:4]
    cols = [("Компани", 70, "l"), ("Цаг / Өдөр", 118, "l"), ("Дүн", 104, "r"), ("Нийт\nдүнд %", 66, "r"), ("Компанид\n%", 66, "r")]
    need = hh + (46 + 40 * len(show) + 34 + (24 if len(hs) > 4 else 0) if hs else 56) + 14
    if c.dry:
        return need
    card(c, x, y, w, h, "Онцгой том хэлцэл", sub, dot=(37, 99, 235))
    if not hs:
        c.text(x + w / 2, y + hh + 24, "Энэ 7 хоногт онцгой том хэлцэл гараагүй", 16, False, MUTED, "mm", maxw=w - 30)
        return need
    rows = [[(r["sym"], None, True), r["when"], (A.mn(r["val"]).replace(" ₮", ""), None, True), f"{r['mkt']:.1f}%", f"{r['co']:.0f}%"] for r in show]
    yb = table(c, x + 18, y + hh, cols, rows, row_h=40, head_h=40, fs=16)
    tot_h = sum(h_["val"] for h_ in hs)
    c.text(x + 18, yb + 20, f"Нийлбэр {A.mn(tot_h)} · нийт арилжааны {tot_h / ctx['total_all'] * 100:.1f}%", 15, True, TXT, "lm", maxw=w - 36)
    if len(hs) > 4:
        c.text(x + 18, yb + 44, f"… бусад {len(hs) - 4} онцгой хэлцэл (Excel-ийн \"Онцгой том хэлцэл\" хуудсанд)", 12.5, False, MUTED, "lm", maxw=w - 36)
    return need


def card_days(c, x, y, w, h, ctx):
    A = _fmt()
    sub = "(арилжааны дүн · хэлцэл · МХБ-н 20 тэнцүү / жигнэсэн өөрчлөлт" + (", онцгойгүй)" if ctx["has_huge"] else ")")
    hh = head_h(c, sub, w)
    cols = [("Өдөр", 44, "l"), ("Арилжаа\n(онцгойгүй)" if ctx["has_huge"] else "Арилжаа", 128, "r"), ("Хэлцэл", 64, "r"), ("Тэнцүү\n%", 76, "r"), ("Жигнэсэн\n%", 82, "r")]
    rows = []
    for d in ctx["days"]:
        extra = f"нийт {A.sm(d['val_all'])}" if d["val_all"] - d["val"] > 1 else None
        val = (A.sm(d["val"]), None, True, extra) if extra else (A.sm(d["val"]), None, True)
        eq = ("—", MUTED, False) if d["eq"] is None else (f"{d['eq']:+.2f}%", chg_color(d["eq"]), True)
        vw = ("—", MUTED, False) if d["vw"] is None else (f"{d['vw']:+.2f}%", chg_color(d["vw"]), True)
        rows.append([(d["d"], None, True), val, f"{d['deals']:,}", eq, vw])
    need = hh + table_h(rows, 34, 40, 46) + 14
    if c.dry:
        return need
    card(c, x, y, w, h, "Өдөр бүр", sub, dot=(14, 165, 233))
    table(c, x + 18, y + hh, cols, rows, row_h=34, head_h=40, fs=15, sub_h=46)
    return need


def card_index(c, x, y, w, h, ctx):
    ix = ctx["index"]
    sub = f"({ix['basis']}{'; онцгой хэлцэлгүй' if ctx['has_huge'] else ''})"
    hh = head_h(c, sub, w)
    need = hh + 82 + 34 + 92 + 14
    if c.dry:
        return need
    card(c, x, y, w, h, "МХБ-н 20 (7 хоног)", sub, dot=(37, 99, 235))
    iw = w - 36
    tw2 = (iw - 12) / 2
    yy = y + hh
    for i, (lab, v) in enumerate([("Тэнцүү", ix["eq"]), ("Жигнэсэн", ix["vw"])]):
        tx = x + 18 + i * (tw2 + 12)
        col = chg_color(v)
        c.rect(tx, yy, tw2, 74, fill=GREEN_BG if v > 0 else RED_BG if v < 0 else BLUE_BG, r=10)
        c.text(tx + tw2 / 2, yy + 20, lab, 15, True, TXT, "mm")
        c.text(tx + tw2 / 2, yy + 50, f"{v:+.2f}%", 30, True, col, "mm", maxw=tw2 - 12)
    yy += 74 + 12
    xx = x + 18
    for txt, col in [(f"↑{ix['up']}", GREEN), (f"↓{ix['dn']}", RED), (f"={ix['flat']}", MUTED)]:
        wd = c.text(xx, yy + 12, txt, 20, True, col, "lm")
        xx += wd + 16
    yy += 34
    tw3 = (iw - 24) / 3
    tiles = [("Татсан", ix["pull"], RED_BG, RED), ("Түлхсэн", ix["push"], GREEN_BG, GREEN), ("Эхний 4 компани", None, BLUE_BG, BLUE)]
    for i, (lab, val, bg, col) in enumerate(tiles):
        tx = x + 18 + i * (tw3 + 12)
        c.rect(tx, yy, tw3, 84, fill=bg, r=10)
        c.text(tx + tw3 / 2, yy + 16, lab, 12.5, True, TXT, "mm", maxw=tw3 - 10)
        if val:
            c.text(tx + tw3 / 2, yy + 42, val[0], 20, True, TXT, "mm", maxw=tw3 - 10)
            c.text(tx + tw3 / 2, yy + 68, f"{val[1]:+.2f} п.п.", 15, True, col, "mm", maxw=tw3 - 10)
        else:
            c.text(tx + tw3 / 2, yy + 52, f"{ix['top4']:.0f}%", 28, True, col, "mm")
    return need


def _price_rows(ctx, rows, A, start):
    out = []
    for i, r in enumerate(rows, start):
        out.append([str(i), (r["sym"], None, True), f"{A.px(r['vwap'])} → {A.px(r['close'])}",
                    (f"{r['chg']:+.2f}%", chg_color(r["chg"]), True), f"{r['rng']:.1f}%", A.sm(r["val"])])
    return out


def card_prices(c, x, y, w, h, ctx):
    A = _fmt()
    sub = "(7 хоногийн жигнэсэн дундаж → хаалт · өөрчлөлт · мужийн өргөн % · арилжааны дүн" + (" · онцгойгүй)" if ctx["has_huge"] else ")")
    hh = head_h(c, sub, w)
    cols = [("№", 26, "c"), ("Компани", 62, "l"), ("Дундаж → Хаалт", 128, "r"), ("Өөрчлөлт", 70, "r"), ("Мужийн\nөргөн %", 50, "r"), ("Арилжааны\nдүн", 94, "r")]
    pr = ctx["prices"]
    half = (len(pr) + 1) // 2
    foot = "Дундаж = 7 хоногийн нийт арилжааны жигнэсэн дундаж ханш · Хаалт = сүүлийн өдрийн жигнэсэн дундаж · Өөрчлөлт = өмнөх хаалттай харьцуулсан · Муж = (дээд / доод − 1)"
    need = hh + 40 + 10 * 32 + 14 + 38 + 8
    if c.dry:
        return need
    card(c, x, y, w, h, "7 хоногийн жигнэсэн дундаж → хаалт", sub, dot=(22, 163, 74))
    tx = x + 18
    yb = table(c, tx, y + hh, cols, _price_rows(ctx, pr[:half], A, 1), row_h=32, head_h=40, fs=15)
    table(c, tx + sum(cw for _, cw, _ in cols) + 24, y + hh, cols, _price_rows(ctx, pr[half:], A, half + 1), row_h=32, head_h=40, fs=15)
    for i, ln in enumerate(c.wrap(foot, 12, w - 36)):
        c.text(x + 18, y + hh + 40 + 10 * 32 + 22 + i * 16, ln, 12, False, MUTED, "lm")
    return need


def card_movers_stack(c, x, y, w, h, ctx):
    A = _fmt()
    bw = (w - 36 - 12) / 2
    # 1) өсөлт / уналт
    h1 = 50 + 30 + 3 * 28 + 10 + 14
    # 2) төгсгөл
    h2 = 50 + 30 + 18 + 3 * 28 + 10 + 14
    # 3) нэг хэлцлээр хөдөлсөн
    sg = ctx["single"]
    sg_txt = ", ".join(f"{s_[0]} {s_[1]:+.2f}% ({s_[2]:.0f}%)" for s_ in sg) if sg else "Илрээгүй"
    sg_lines = c.wrap(sg_txt, 15, w - 36 - 50, True)
    h3 = 50 + 22 + 20 * len(sg_lines) + 14
    gaps = 2 * G
    need = h1 + h2 + h3 + gaps
    if c.dry:
        return need
    extra = max(0, h - need) / 3
    y1 = y
    card(c, x, y1, w, h1 + extra, "Өсөлт / Уналт (7 хоног)", None, dot=(22, 163, 74))
    list_box(c, x + 18, y1 + 46, bw, "Өсөлт", [(s_, f"{v:+.2f}%", GREEN) for s_, v in ctx["up3"]], (209, 242, 220), GREEN, (240, 250, 244))
    list_box(c, x + 18 + bw + 12, y1 + 46, bw, "Уналт", [(s_, f"{v:+.2f}%", RED) for s_, v in ctx["dn3"]], (252, 221, 221), RED, (254, 244, 244))
    y2 = y1 + h1 + extra + G
    card(c, x, y2, w, h2 + extra, "Төгсгөлийн хүч", None, dot=(245, 158, 11))
    list_box(c, x + 18, y2 + 46, bw, "Төгсгөлд суларсан", [(s_, f"{v:+.2f}%", RED) for s_, v in ctx["weak"]], (252, 221, 221), RED, (254, 244, 244),
             cap="(сүүлийн 1 цагийн ханш хаалтаас доор)")
    list_box(c, x + 18 + bw + 12, y2 + 46, bw, "Төгсгөлд хүчирхэгжсэн", [(s_, f"{v:+.2f}%", GREEN) for s_, v in ctx["strong"]], (209, 242, 220), GREEN, (240, 250, 244),
             cap="(сүүлийн 1 цагийн ханш хаалтаас дээгүүр)")
    y3 = y2 + h2 + extra + G
    h3e = h3 + extra
    c.rect(x, y3, w, h3e, fill=AMBER_BG, outline=(240, 200, 120), r=14)
    c.triangle_warn(x + 16, y3 + 16, 28, AMBER)
    c.text(x + 54, y3 + 24, "Нэг хэлцлээр хөдөлсөн байж болзошгүй", 16.5, True, TXT, "lm", maxw=w - 70)
    c.text(x + 54, y3 + 44, "(арилжааны дүнгийн хэдэн % нь ганц хэлцэл)", 12, False, MUTED, "lm", maxw=w - 70)
    for i, ln in enumerate(sg_lines):
        c.text(x + 18, y3 + 66 + i * 20, ln, 15, True, AMBER if sg else MUTED, "lm")
    return need


def _biggest_rows(ctx, rows, start):
    A = _fmt()
    out = []
    for i, r in enumerate(rows, start):
        mark = ("★ " if r["huge"] else "") + (f"×{r['n']}" if r["n"] > 1 else "") + (" SI" if r["si"] else "")
        out.append([str(i), (r["sym"], None, True), r["when"], (A.sm(r["val"]), None, True), f"{r['mkt']:.2f}%", f"{r['co']:.0f}%",
                    (mark.strip(), MUTED, False)])
    return out


def card_biggest(c, x, y, w, h, ctx):
    sub = "(цаг · дүн · нийт арилжаанд % · тухайн компанид %)"
    hh = head_h(c, sub, w)
    cols = [("№", 26, "c"), ("Компани", 58, "l"), ("Цаг / Өдөр", 110, "l"), ("Дүн", 88, "r"), ("Зах\nзээл %", 54, "r"), ("Компа-\nни %", 50, "r"), ("", 44, "l")]
    bg = ctx["biggest"]
    half = (len(bg) + 1) // 2
    legend = "×N = нэг секундэд нэг компанийн N хэлцлийг нэгтгэсэн (нэг том захиалга байж болзошгүй) · SI = Sell Imbalance"
    has_star = any(r["huge"] for r in bg)
    need = hh + 40 + 10 * 32 + 14 + 40 + (18 if has_star else 0)
    if c.dry:
        return need
    card(c, x, y, w, h, "Компани бүрийн хамгийн том хэлцэл", sub, dot=(245, 158, 11))
    tx = x + 18
    table(c, tx, y + hh, cols, _biggest_rows(ctx, bg[:half], 1), row_h=32, head_h=40, fs=15)
    table(c, tx + sum(cw for _, cw, _ in cols) + 24, y + hh, cols, _biggest_rows(ctx, bg[half:], half + 1), row_h=32, head_h=40, fs=15)
    lines = c.wrap(legend, 12, w - 36)
    for i, ln in enumerate(lines):
        c.text(x + 18, y + hh + 40 + 10 * 32 + 20 + i * 16, ln, 12, False, MUTED, "lm")
    if has_star:
        ys = y + hh + 40 + 10 * 32 + 20 + len(lines) * 16
        c.star(x + 24, ys, 6.5, (245, 158, 11))
        c.text(x + 36, ys, "= онцгой том хэлцэл", 12, False, MUTED, "lm")
    return need


def card_liq(c, x, y, w, h, ctx):
    A = _fmt()
    sub = f"(арилжааны дүн, сая ₮; {ctx['liq_label']})" if ctx["liq_label"] else None
    hh = head_h(c, sub, w)
    box_h = 30 + 3 * 30 + 10
    imp = ctx["impact"]
    thin = ", ".join(f"{s_} {A.p0(v)}" for s_, v in imp["thin"]) or "—"
    best = ", ".join(f"{s_} {A.p0(v)}" for s_, v in imp["best"])
    ln_best = c.wrap(f"сайн: {best}", 14, w - 52, True)
    ln_thin = c.wrap(f"сул ({imp['thin_pct']:.0f}%+): {thin}", 14, w - 52, True)
    foot_h = 38 + 19 * (len(ln_best) + len(ln_thin)) + 10
    need = hh + (box_h + 10) * 2 + foot_h + 14
    if c.dry:
        return need
    card(c, x, y, w, h, "Хөрвөх чадвар", sub, dot=(14, 165, 233))
    bw = w - 36
    yy = y + hh

    def items(lst):
        return [(s_, f"{b:,.1f} → {cc:,.1f}  ({rt})", col) for s_, b, cc, rt, col in lst]

    bh = list_box(c, x + 18, yy, bw, "Нэмэгдсэн", items(ctx["liq_up"]), (209, 242, 220), GREEN, (240, 250, 244), rows=3, row_h=30)
    yy += bh + 10
    bh = list_box(c, x + 18, yy, bw, "Буурсан", items(ctx["liq_dn"]), (252, 221, 221), RED, (254, 244, 244), rows=3, row_h=30)
    yy += bh + 10
    c.rect(x + 18, yy, bw, foot_h, fill=BLUE_BG, r=10)
    c.text(x + 30, yy + 18, f"{imp['order']:g} сая ₮ захиалга / 7 хоногийн арилжааны дүн", 14, True, TXT, "lm", maxw=bw - 24)
    ty = yy + 40
    for ln in ln_best:
        c.text(x + 30, ty, ln, 14, True, GREEN, "lm")
        ty += 19
    for ln in ln_thin:
        c.text(x + 30, ty, ln, 14, True, RED, "lm")
        ty += 19
    return need


def card_extra(c, x, y, w, h, ctx):
    ex = ctx["extras"]
    cols = []
    if ex["streak_up"] or ex["streak_dn"]:
        t = []
        if ex["streak_up"]:
            t.append(("Бүх өдөр өссөн: " + ", ".join(ex["streak_up"]), GREEN))
        if ex["streak_dn"]:
            t.append(("Бүх өдөр унасан: " + ", ".join(ex["streak_dn"]), RED))
        cols.append(("Тогтмол хөдөлгөөн", t))
    if ex["vol"]:
        cols.append(("Хэлбэлзэл (өдрийн дундаж муж)", [("Их: " + ", ".join(f"{s_} {v:.1f}%" for s_, v in ex["vol"]), RED),
                                                      ("Тайван: " + ", ".join(f"{s_} {v:.1f}%" for s_, v in ex["calm"]), GREEN)]))
    if ex["corr_pos"] or ex["corr_neg"]:
        t = []
        if ex["corr_pos"]:
            t.append(("Хамт: " + ", ".join(f"{a}–{b} {r:+.2f}" for a, b, r in ex["corr_pos"]), GREEN))
        if ex["corr_neg"]:
            t.append(("Эсрэг: " + ", ".join(f"{a}–{b} {r:+.2f}" for a, b, r in ex["corr_neg"]), RED))
        cols.append(("Хамаарал (өдрийн өгөөж)", t))
    if ex["hours"]:
        cols.append(("Арилжааны дүн цагаар", [(" · ".join(f"{lab} {v:.0f}%" for lab, v in ex["hours"]), TXT)]))
    if not cols:
        return 0
    n = len(cols)
    cw = (w - 36 - (n - 1) * 16) / n
    lines = [[(ln, col) for txt, col in blocks for ln in c.wrap(txt, 14, cw - 4, True)] for _, blocks in cols]
    need = 50 + 30 + max(len(ls) for ls in lines) * 20 + 14
    if c.dry:
        return need
    card(c, x, y, w, h, "Бусад ажиглалт", None, dot=(100, 116, 139))
    for i, ((title, _), ls) in enumerate(zip(cols, lines)):
        cx = x + 18 + i * (cw + 16)
        c.text(cx, y + 62, title, 14, True, MUTED, "lm", maxw=cw)
        for j, (ln, col) in enumerate(ls):
            c.text(cx, y + 86 + j * 20, ln, 14, True, col, "lm")
    return need


# ------------------------------------------------------------------ толгой, хөл
def draw_header(c, ctx, hdr_h):
    A = _fmt()
    if c.dry:
        return
    for yy in range(hdr_h * S):
        t = yy / (hdr_h * S)
        col = tuple(int(NAVY1[i] + (NAVY2[i] - NAVY1[i]) * t) for i in range(3))
        c.d.line([0, yy, W * S, yy], fill=col)
    # дүрс: шатлан өсөх багана + сум
    bx, by = M + 6, 78
    for i, hh in enumerate([22, 36, 52]):
        c.rect(bx + i * 20, by - hh, 14, hh, fill=CYAN, r=2)
    c.line(bx - 4, by - 30, bx + 28, by - 54, (255, 255, 255), 3)
    c.line(bx + 28, by - 54, bx + 18, by - 54, (255, 255, 255), 3)
    c.line(bx + 28, by - 54, bx + 28, by - 44, (255, 255, 255), 3)
    x0 = M + 92
    # лого зүүн ирмэгтэй давхцахгүйн тулд гарчгийг шаардлагатай бол жижигсгэнэ
    logo_left = W - M - c.tw("openmind", 52, True) - c.tw("MSE", 52, True)
    base = [("МХБ 7 хоног", 54, True), (ctx["label"], 38, True), (f"({ctx['range']})", 32, False)]
    total_w = sum(c.tw(t, s_, b_) for t, s_, b_ in base) + 34 + 16
    f = min(1.0, (logo_left - 24 - x0) / total_w)
    xx = x0
    cols_ = [(255, 255, 255), CYAN, (255, 255, 255)]
    ys = [54, 56, 58]
    for (t, s_, b_), col_, y_ in zip(base, cols_, ys):
        xx += c.text(xx, y_, t, s_ * f, b_, col_, "lm") + (18 if t.startswith("МХБ") else 16) * f
    # лого: openmind + MSE (ногоон), доор нь powered by (улаан)
    s1, s2 = 52, 52
    wm = c.tw("MSE", s2, True)
    wo = c.tw("openmind", s1, True)
    rx = W - M
    c.text(rx, 50, "MSE", s2, True, LOGO_GREEN, "rm")
    c.text(rx - wm, 50, "openmind", s1, True, (255, 255, 255), "rm")
    c.text(rx, 92, "powered by Big Short Ganbayar", 20, True, LOGO_RED, "rm")
    # KPI мөр
    ky, kh = 118, 96
    cells = [
        (f"{ctx['deals']:,}", "хэлцэл", 215),
        (A.mn(ctx["total_all"]), f"(онцгойгүй {A.mn(ctx['total_core'])})" if ctx["has_huge"] else "нийт арилжааны дүн", 380),
        (str(ctx["ndays"]), "арилжааны өдөр", 200),
        (str(ctx["ncomp"]), "компани", 170),
        (None, None, W - 2 * M - 215 - 380 - 200 - 170),
    ]
    x = M
    for i, (val, lab, wcell) in enumerate(cells):
        if i > 0:
            c.line(x, ky + 6, x, ky + kh - 6, (70, 104, 160), 1)
        if val is not None:
            c.text(x + 18, ky + 36, val, 40, True, (255, 255, 255), "lm", maxw=wcell - 30)
            c.text(x + 18, ky + 76, lab, 17, False, HDR_SUB, "lm", maxw=wcell - 30)
        elif ctx["avg_change"] is not None:
            v = ctx["avg_change"]
            wv = c.text(x + 18, ky + 48, f"{v:+.2f}%", 40, True, LOGO_GREEN if v >= 0 else (255, 120, 120), "lm")
            lab2 = "Өдрийн дундаж арилжааны дүн өмнөх 7 хоногоос" + (" (онцгойгүй)" if ctx["has_huge"] else "")
            for k, ln in enumerate(c.wrap(lab2, 16, wcell - wv - 50)):
                c.text(x + 18 + wv + 14, ky + 34 + k * 20, ln, 16, False, HDR_SUB, "lm")
        x += wcell


def draw_footer(c, y, fh):
    if c.dry:
        return
    c.rect(0, y, W, fh, fill=NAVY1)
    c.triangle_warn(M, y + fh / 2 - 13, 26, (245, 190, 40))
    c.text(M + 40, y + fh / 2, "Энэ нь хөрөнгө оруулалтын зөвлөгөө биш, зөвхөн биелсэн хэлцлийн статистик тойм юм.", 17, False, (255, 255, 255), "lm")
    c.text(W - M, y + fh / 2, "openmindMSE · powered by Big Short Ganbayar", 14, True, HDR_SUB, "rm")


ROWS = [
    [(card_huge, 460), (card_days, 430), (card_index, 418)],
    [(card_prices, 920), (card_movers_stack, 406)],
    [(card_biggest, 920), (card_liq, 406)],
    [(card_extra, 1344)],
]


def _layout(c, ctx, plan=None):
    HDR, FOOT = 232, 58
    draw_header(c, ctx, HDR)
    y = HDR + G
    heights = []
    for ri, row in enumerate(ROWS):
        if plan is None:
            needs = [fn(c, 0, 0, w, 0, ctx) for fn, w in row]
            rh = max(needs)
        else:
            rh = plan[ri]
        heights.append(rh)
        if rh and plan is not None:
            x = M
            for fn, w in row:
                fn(c, x, y, w, rh, ctx)
                x += w + G
        if rh:
            y += rh + G
    if plan is not None:
        draw_footer(c, y, FOOT)
    return heights, y + FOOT


def render_weekly(ctx, path):
    dry = Canvas(None)
    heights, total_h = _layout(dry, ctx)
    c = Canvas(total_h)
    _layout(c, ctx, heights)
    c.img.save(path, "PNG", optimize=True)
    return path
