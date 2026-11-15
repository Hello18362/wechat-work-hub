# -*- coding: utf-8 -*-
"""把状态画成一张 RGBA 整图。

玻璃是**真的**玻璃：抓窗口背后的桌面 → 高斯模糊 → 压暗加青灰 → 叠高光与亮边。
因为背景已经模糊过，面板本身做成不透明，字始终清晰可读，
也不依赖任何未公开的模糊接口，Win10 / Win11 表现一致。

绘制分两层：
1. 形状层（超采样 2×）：圆角、卡片底、图标、高光、描边 → 缩小到物理尺寸
2. 文字层（1×）：直接按物理像素绘制，字最锐
两层最后合成。

注意：PIL 的 ImageDraw 在 RGBA 图上是**覆盖** alpha 而不是叠色，
所以所有半透明形状都走 Canvas 的局部 alpha 合成，否则会把玻璃底打穿。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter

from . import theme as T

SS = 2  # 形状层超采样倍数

# 量文字宽度用的画布（不参与输出）
_MEAS = ImageDraw.Draw(Image.new("RGBA", (8, 8)))


# ------------------------------------------------------------------ 小工具

def _text_len(d: ImageDraw.ImageDraw, s: str, f) -> float:
    try:
        return d.textlength(s, font=f)
    except Exception:
        box = d.textbbox((0, 0), s, font=f)
        return box[2] - box[0]


def ellipsize(d: ImageDraw.ImageDraw, s: str, f, max_w: float) -> str:
    """按像素宽度截断并加省略号。"""
    s = s or ""
    if not s or _text_len(d, s, f) <= max_w:
        return s
    ell = "…"
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _text_len(d, s[:mid] + ell, f) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return s[:lo] + ell


def _round_mask(size, box, radius) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=radius, fill=255)
    return m


class Canvas:
    """超采样画布。坐标一律用 96dpi 逻辑单位。"""

    def __init__(self, w: float, h: float, k: float, ss: int = SS,
                 base: Optional[Image.Image] = None):
        self.k = k
        self.ss = ss
        self.a = k * ss
        self.w = int(round(w * k))
        self.h = int(round(h * k))
        size = (self.w * ss, self.h * ss)
        self.img = base.copy() if base is not None else Image.new("RGBA", size, (0, 0, 0, 0))

    # -- 坐标
    def u(self, v: float) -> float:
        return v * self.a

    def radius(self, r: float) -> float:
        return max(1.0, r * self.a)

    # -- 局部 alpha 合成
    def _blend(self, x0, y0, x1, y1, draw_fn, pad: float = 2.0) -> None:
        a = self.a
        p = int(round(pad * a))
        bx0 = max(0, int(math.floor(x0 * a)) - p)
        by0 = max(0, int(math.floor(y0 * a)) - p)
        bx1 = min(self.img.width, int(math.ceil(x1 * a)) + p)
        by1 = min(self.img.height, int(math.ceil(y1 * a)) + p)
        if bx1 <= bx0 or by1 <= by0:
            return
        layer = Image.new("RGBA", (bx1 - bx0, by1 - by0), (0, 0, 0, 0))
        draw_fn(ImageDraw.Draw(layer), bx0, by0)
        region = self.img.crop((bx0, by0, bx1, by1))
        self.img.paste(Image.alpha_composite(region, layer), (bx0, by0))

    def rounded(self, x0, y0, x1, y1, radius: float = 0,
                fill=None, outline=None, width: float = 0, pad: float = 2.0) -> None:
        a = self.a

        def _draw(d, ox, oy):
            d.rounded_rectangle(
                (x0 * a - ox, y0 * a - oy, x1 * a - ox, y1 * a - oy),
                radius=max(1.0, radius * a), fill=fill, outline=outline,
                width=max(0, int(round(width * a))),
            )

        self._blend(x0, y0, x1, y1, _draw, pad + width)

    def ellipse(self, x0, y0, x1, y1, fill=None, outline=None, width: float = 0) -> None:
        a = self.a

        def _draw(d, ox, oy):
            d.ellipse((x0 * a - ox, y0 * a - oy, x1 * a - ox, y1 * a - oy),
                      fill=fill, outline=outline, width=max(0, int(round(width * a))))

        self._blend(x0, y0, x1, y1, _draw, 2 + width)

    def line(self, pts, fill, width: float = 1.0) -> None:
        a = self.a
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]

        def _draw(d, ox, oy):
            d.line([(x * a - ox, y * a - oy) for x, y in pts], fill=fill,
                   width=max(1, int(round(width * a))), joint="curve")

        self._blend(min(xs), min(ys), max(xs), max(ys), _draw, 2 + width)

    def flat(self) -> Image.Image:
        if self.ss == 1:
            return self.img
        return self.img.resize((self.w, self.h), Image.LANCZOS)


# ------------------------------------------------------------------ 玻璃

def _frost(w: float, h: float, margin: float, radius: float, k: float,
           backdrop: Optional[Image.Image], drag: bool, ss: int,
           fast: bool = False) -> Image.Image:
    """生成玻璃底板（不透明磨砂 + 投影）。

    w/h 是**逻辑**尺寸，内部按 k 换成物理像素再乘 ss。
    """
    pw = max(1, int(round(w * k)))
    ph = max(1, int(round(h * k)))
    cw, ch = pw * ss, ph * ss
    out = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))

    m = margin * k * ss
    rad = radius * k * ss
    box = (m, m, cw - m, ch - m)

    # --- 投影：在 1/2 分辨率上模糊，快且够用（阴影本身是虚的）
    f = 0.5
    sh = Image.new("RGBA", (max(1, int(pw * f)), max(1, int(ph * f))), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    sm = margin * k * f
    sd.rounded_rectangle(
        (sm, sm + 5 * k * f,
         max(sm + 2, sh.width - sm),
         max(sm + 2, sh.height - sm + 5 * k * f)),
        radius=max(1, min(radius * k * f, min(sh.width, sh.height) / 2)),
        fill=T.SHADOW,
    )
    sh = sh.filter(ImageFilter.GaussianBlur(max(1.2, 7 * k * f)))
    out = Image.alpha_composite(out, sh.resize((cw, ch), Image.BILINEAR))

    # --- 磨砂底
    if backdrop is not None and not drag:
        if fast:
            half = (max(8, cw // 2), max(8, ch // 2))
            bd = backdrop.resize(half, Image.BILINEAR)
            bd = bd.filter(ImageFilter.GaussianBlur(max(1.0, 4 * k)))
            bd = bd.resize((cw, ch), Image.BILINEAR)
        else:
            bd = backdrop.resize((cw, ch), Image.BILINEAR)
            bd = bd.filter(ImageFilter.GaussianBlur(max(1.0, 13 * k)))
        bd = bd.convert("RGBA")
        # 压暗：让白字有足够对比
        panel = Image.alpha_composite(bd, Image.new("RGBA", (cw, ch), (12, 12, 14, 216)))
        # 一点冷调，避免纯黑发死
        panel = Image.alpha_composite(panel, Image.new("RGBA", (cw, ch), (20, 25, 36, 40)))
        panel.putalpha(255)
    else:
        color = T.TINT_DRAG if drag else T.TINT
        panel = Image.new("RGBA", (cw, ch), color)

    mask = _round_mask((cw, ch), box, rad)
    out.paste(panel, (0, 0), mask)

    # --- 顶部高光（玻璃棱）
    sheen = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    sdr = ImageDraw.Draw(sheen)
    top = m
    bottom = m + (ch - 2 * m) * 0.40
    steps = 40
    for i in range(steps):
        t = i / (steps - 1)
        a = int(26 * (1 - t) ** 1.5)
        y0 = top + (bottom - top) * t
        y1 = top + (bottom - top) * (t + 1 / steps)
        sdr.rectangle((m, y0, cw - m, y1 + 1), fill=(255, 255, 255, a))
    keep = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(keep).rounded_rectangle(box, radius=rad, fill=255)
    sheen.putalpha(Image.composite(sheen.getchannel("A"), Image.new("L", (cw, ch), 0), keep))
    out = Image.alpha_composite(out, sheen)

    # --- 描边
    stroke_w = max(1, int(round(1.1 * k * ss)))
    edge = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(box, radius=rad, outline=T.BORDER, width=stroke_w)
    out = Image.alpha_composite(out, edge)

    # --- 顶部亮棱（往下渐隐）
    hi = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(hi).rounded_rectangle(box, radius=rad, outline=T.BORDER_TOP,
                                         width=max(1, int(round(1.6 * k * ss))))
    grad = Image.new("L", (cw, ch), 0)
    gd = ImageDraw.Draw(grad)
    fade_to = m + (ch - 2 * m) * 0.26
    for i in range(36):
        t = i / 35
        a = int(255 * (1 - t) ** 2)
        y0 = m + (fade_to - m) * t
        y1 = m + (fade_to - m) * (t + 1 / 36)
        gd.rectangle((0, y0, cw, y1 + 1), fill=a)
    hi.putalpha(Image.composite(hi.getchannel("A"), Image.new("L", (cw, ch), 0), grad))
    out = Image.alpha_composite(out, hi)

    return out


# ------------------------------------------------------------------ 图标

def _chevron_down(cv: Canvas, cx: float, cy: float, size: float, color, width: float):
    cv.line([(cx - size / 2, cy - size / 4), (cx, cy + size / 4),
             (cx + size / 2, cy - size / 4)], fill=color, width=width)


def _chevron_up(cv: Canvas, cx: float, cy: float, size: float, color, width: float):
    cv.line([(cx - size / 2, cy + size / 4), (cx, cy - size / 4),
             (cx + size / 2, cy + size / 4)], fill=color, width=width)


def _check(cv: Canvas, cx: float, cy: float, size: float, color, width: float):
    cv.line([(cx - size / 2, cy), (cx - size / 8, cy + size / 2.6),
             (cx + size / 2, cy - size / 2.8)], fill=color, width=width)


def _arrow_right(cv: Canvas, cx: float, cy: float, size: float, color, width: float):
    cv.line([(cx - size / 4, cy - size / 2), (cx + size / 4, cy),
             (cx - size / 4, cy + size / 2)], fill=color, width=width)


# ------------------------------------------------------------------ 布局

def layout_cards(cards: List[Dict], done_expanded: bool):
    """返回 [(card, (x0,y0,x1,y1))]，逻辑单位，相对面板左上角。"""
    top, bot = T.CARDS_TOP, T.CARDS_BOTTOM
    undone = [c for c in cards if not c.get("done")][: T.MAX_CARDS]
    done = [c for c in cards if c.get("done")]
    show_done = done[:2] if done_expanded else []

    gap = T.CARD_GAP
    done_h = 56
    reserve = len(show_done) * (done_h + gap)
    n = max(1, len(undone))
    h = (bot - top - reserve - gap * (n - 1)) / n
    h = max(66.0, min(h, 120.0))

    rows = []
    x0, x1 = T.PAD_X, T.PANEL_W - T.PAD_X
    y = top
    for card in undone:
        rows.append((card, (x0, y, x1, y + h)))
        y += h + gap
    if show_done:
        y = max(y + 2, bot - reserve)
        for card in show_done:
            if y + done_h > bot:
                break
            rows.append((card, (x0, y, x1, y + done_h)))
            y += done_h + gap
    return rows


# ------------------------------------------------------------------ 面板

def draw_panel(state: Dict, k: float, backdrop: Optional[Image.Image],
               ss: int = SS, fast: bool = False) -> Tuple[Image.Image, List[Dict]]:
    """画展开态面板。返回 (整图, 命中区列表)。"""
    W = T.PANEL_W + T.PANEL_MARGIN * 2
    H = T.PANEL_H + T.PANEL_MARGIN * 2
    margin = T.PANEL_MARGIN
    hits: List[Dict] = []

    base = _frost(W, H, margin, T.PANEL_RADIUS, k, backdrop,
                  state.get("drag", False), ss, fast)
    cv = Canvas(W, H, k, ss, base)

    px = margin + T.PAD_X                 # 面板内左右起点
    pr = margin + T.PANEL_W - T.PAD_X

    cards = state.get("cards") or []
    undone = [c for c in cards if not c.get("done")]
    done = [c for c in cards if c.get("done")]
    urgent = [c for c in undone if c.get("priority") in ("紧急", "高")]
    hover_key = state.get("hover_key") or ""
    hover_idx = state.get("hover", -1)

    # ---- 收起按钮
    btn = 30.0
    bx1, bx0 = pr, pr - btn
    by0 = margin + 46
    by1 = by0 + btn
    cv.rounded(bx0, by0, bx1, by1, btn / 2,
               fill=(255, 255, 255, 30) if hover_key == "collapse" else (255, 255, 255, 14))
    _chevron_down(cv, (bx0 + bx1) / 2, (by0 + by1) / 2 + 1, 9, T.INK_2, 1.5)
    hits.append({"kind": "collapse", "rect": (bx0, by0, bx1, by1)})

    # ---- 卡片
    rows = layout_cards(cards, state.get("done_expanded", False))
    for idx, (card, rect) in enumerate(rows):
        x0, y0, x1, y1 = rect
        ax0, ay0, ax1, ay1 = margin + x0, margin + y0, margin + x1, margin + y1
        hot = idx == hover_idx
        done_card = bool(card.get("done"))

        cv.rounded(ax0, ay0, ax1, ay1, T.CARD_RADIUS,
                   fill=T.CARD_FILL_HOVER if hot else T.CARD_FILL,
                   outline=T.CARD_BORDER_HOVER if hot else T.CARD_BORDER,
                   width=1.0)

        pri = card.get("priority") or "常规"
        if pri in ("紧急", "高") and not done_card:
            cv.rounded(ax0 + 0.5, ay0 + 16, ax0 + 3.5, ay1 - 16, 2, fill=T.ACCENT_DIM)

        # 优先级 chip
        chip_h = 19.0
        chip_w = _text_len(_MEAS, pri, T.font(10.5 * k, True)) / k + 16
        cx1 = ax1 - 14
        cx0 = cx1 - chip_w
        bg, _fg = T.PRIORITY.get(pri, T.PRIORITY["常规"])
        cv.rounded(cx0, ay0 + 12, cx1, ay0 + 12 + chip_h, chip_h / 2, fill=bg)

        hits.append({"kind": "card", "index": idx,
                     "rect": (ax0, ay0, ax1, ay1), "card": card})
        if idx == hover_idx:
            _arrow_right(cv, ax1 - 12, (ay0 + ay1) / 2, 9, T.INK_2, 1.5)

    # ---- 底部分隔线
    fy = margin + T.PANEL_H - 56
    cv.line([(px, fy), (pr, fy)], fill=T.DIVIDER, width=1.0)
    footer_y = fy + 16
    if done:
        label = "已完成 %d 条" % len(done)
        fw = _text_len(_MEAS, label, T.font(11.5 * k)) / k
        icon_x = px + fw + 13
        if hover_key == "footer":
            cv.rounded(px - 9, footer_y - 6, icon_x + 9, footer_y + 19, 9,
                       fill=(255, 255, 255, 18))
        if state.get("done_expanded"):
            _chevron_up(cv, icon_x, footer_y + 7, 7, T.INK_3, 1.4)
        else:
            _chevron_down(cv, icon_x, footer_y + 6, 7, T.INK_3, 1.4)
        hits.append({"kind": "footer",
                     "rect": (px - 9, footer_y - 7, icon_x + 10, footer_y + 20)})

    img = cv.flat()

    # ---------------------------------------------------------- 文字层（1×）
    tl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(tl)

    def put(x, y, s, size, color, bold=False, anchor="la"):
        td.text((x * k, y * k), s, font=T.font(size * k, bold), fill=color, anchor=anchor)

    # 顶部小标签 + 更新时间
    put(px, 20, "今日待办", 11.5, T.INK_3, bold=True)
    gen = state.get("generated_at") or ""
    stale_h = state.get("stale_hours")
    if stale_h is not None and stale_h >= 3:
        put(pr, 20, "数据为 %d 小时前" % int(stale_h), 11.5, T.WARN, anchor="ra")
    elif gen:
        put(pr, 20, "更新于 %s" % (gen[11:16] if len(gen) >= 16 else gen), 11.5,
            T.INK_3, anchor="ra")

    # 大数字
    num = str(len(undone))
    f_num = T.font(38 * k, True)
    td.text((px * k, 38 * k), num, font=f_num, fill=T.INK)
    nw = td.textlength(num, font=f_num) / k
    tx = px + nw + 9
    put(tx, 47, "项待办", 12.5, T.INK_2)
    if urgent:
        w1 = _text_len(td, "项待办", T.font(12.5 * k)) / k
        put(tx + w1 + 7, 49, "· %d 项紧急" % len(urgent), 11, T.ACCENT, bold=True)
    meta = []
    if state.get("groups"):
        meta.append("%d 个群" % state["groups"])
    if state.get("total_messages"):
        meta.append("%d 条消息" % state["total_messages"])
    if meta:
        put(tx, 65, " · ".join(meta), 10.5, T.INK_3)

    # 卡片文字
    for idx, (card, rect) in enumerate(rows):
        x0, y0, x1, y1 = rect
        ax0, ay0, ax1, ay1 = margin + x0, margin + y0, margin + x1, margin + y1
        done_card = bool(card.get("done"))
        pri = card.get("priority") or "常规"
        chip_h = 19.0
        chip_w = _text_len(td, pri, T.font(10.5 * k, True)) / k + 16
        cx1 = ax1 - 14
        cx0 = cx1 - chip_w

        # 群名
        f_g = T.font(10.5 * k)
        room = (ax1 - 14 - chip_w - 10) - (ax0 + 15)
        gname = ellipsize(td, card.get("group") or "未知群", f_g, room)
        td.text(((ax0 + 15) * k, (ay0 + 13) * k), gname, font=f_g,
                fill=T.INK_3 if not done_card else T.INK_DONE)

        # chip 文字
        _bg, fg = T.PRIORITY.get(pri, T.PRIORITY["常规"])
        td.text(((cx0 + chip_w / 2) * k, (ay0 + 12 + chip_h / 2 + 0.5) * k), pri,
                font=T.font(10.5 * k, True), fill=fg, anchor="mm")

        # 标题
        f_t = T.font((15.5 if not done_card else 15.0) * k, True)
        title = ellipsize(td, card.get("title") or "", f_t, ax1 - ax0 - 30)
        td.text(((ax0 + 15) * k, (ay0 + 37) * k), title, font=f_t,
                fill=T.INK if not done_card else T.INK_DONE)

        # 元信息
        bits = []
        if card.get("source"):
            bits.append(card["source"])
        if card.get("owner") and card["owner"] not in ("未指定", "-"):
            bits.append(card["owner"])
        if card.get("due") and card["due"] not in ("无明确截止", "-"):
            bits.append(card["due"])
        if done_card:
            bits = ["已完成"] + bits[:2]
        f_m = T.font(10.5 * k)
        meta_txt = ellipsize(td, "  ·  ".join(bits[:3]), f_m, ax1 - ax0 - 30)
        td.text(((ax0 + 15) * k, (ay0 + 62) * k), meta_txt, font=f_m,
                fill=T.INK_3 if not done_card else T.INK_DONE)

    # 底部文字
    if done:
        put(px, footer_y, "已完成 %d 条" % len(done), 11.5,
            T.INK_2 if hover_key == "footer" else T.INK_3)
    else:
        put(px, footer_y, "今天没有已完成的任务", 11.5, T.INK_3)

    if state.get("empty") and not rows:
        put(margin + T.PANEL_W / 2, margin + 300, "今天还没有生成报告", 14,
            T.INK_2, anchor="mm")
        put(margin + T.PANEL_W / 2, margin + 326, "右键 →「重新读取数据」", 11,
            T.INK_3, anchor="mm")

    return Image.alpha_composite(img, tl), hits


# ------------------------------------------------------------------ 收起态玻璃球

def draw_ball(state: Dict, k: float, backdrop: Optional[Image.Image],
              ss: int = SS, fast: bool = False) -> Tuple[Image.Image, List[Dict]]:
    W = T.BALL + T.BALL_MARGIN * 2
    H = W
    base = _frost(W, H, T.BALL_MARGIN, T.BALL / 2, k, backdrop,
                  state.get("drag", False), ss, fast)
    cv = Canvas(W, H, k, ss, base)

    cx = cy = W / 2
    undone = [c for c in (state.get("cards") or []) if not c.get("done")]
    urgent = [c for c in undone if c.get("priority") in ("紧急", "高")]

    if state.get("hover_key") == "ball":
        cv.ellipse(cx - T.BALL / 2 + 3, cy - T.BALL / 2 + 3,
                   cx + T.BALL / 2 - 3, cy + T.BALL / 2 - 3,
                   fill=(255, 255, 255, 18))
    if urgent:
        cv.ellipse(cx + 15, cy - 27, cx + 25, cy - 17, fill=T.ACCENT)

    n = len(undone)
    if not n:
        _check(cv, cx, cy - 5, 15, T.INK_2, 2)

    img = cv.flat()
    tl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(tl)
    if n:
        td.text((cx * k, (cy - 7) * k), str(n), font=T.font(23 * k, True),
                fill=T.INK, anchor="mm")
        td.text((cx * k, (cy + 17) * k), "项待办", font=T.font(9 * k),
                fill=T.INK_3, anchor="mm")
    else:
        td.text((cx * k, (cy + 17) * k), "清空", font=T.font(9.5 * k),
                fill=T.INK_3, anchor="mm")

    return (Image.alpha_composite(img, tl),
            [{"kind": "ball",
              "rect": (T.BALL_MARGIN, T.BALL_MARGIN, W - T.BALL_MARGIN, H - T.BALL_MARGIN)}])


# ------------------------------------------------------------------ 贴边细条

def draw_sliver(state: Dict, k: float, backdrop: Optional[Image.Image],
                ss: int = SS, fast: bool = False) -> Tuple[Image.Image, List[Dict]]:
    W = T.SLIVER_W + T.SLIVER_MARGIN * 2
    H = T.SLIVER_H + T.SLIVER_MARGIN * 2
    base = _frost(W, H, T.SLIVER_MARGIN, T.SLIVER_W / 2, k, backdrop, False, ss, fast)
    cv = Canvas(W, H, k, ss, base)

    m = T.SLIVER_MARGIN
    cv.rounded(m + 0.5, m, W - m - 0.5, H - m, T.SLIVER_W / 2,
               fill=(255, 255, 255, 60))
    undone = [c for c in (state.get("cards") or []) if not c.get("done")]
    if any(c.get("priority") in ("紧急", "高") for c in undone):
        mid = H / 2
        cv.rounded(m + 0.5, mid - 24, W - m - 0.5, mid + 24,
                   T.SLIVER_W / 2, fill=T.ACCENT)

    return cv.flat(), [{"kind": "sliver", "rect": (m, m, W - m, H - m)}]
