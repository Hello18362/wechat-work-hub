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

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import theme as T

SS = 1  # 画布倍数。1x + 遮罩羽化 = 2x 的观感、1/3 的成本（见 _frost 注释）

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


_SHAPE_CACHE: Dict[tuple, Image.Image] = {}


def _cached(key, make):
    hit = _SHAPE_CACHE.get(key)
    if hit is None:
        hit = make()
        if len(_SHAPE_CACHE) > 16:
            _SHAPE_CACHE.clear()
        _SHAPE_CACHE[key] = hit
    return hit


def _round_mask(size, box, radius) -> Image.Image:
    m = Image.new("L", size, 0)
    r = max(1.0, min(radius, min(box[2] - box[0], box[3] - box[1]) / 2))
    ImageDraw.Draw(m).rounded_rectangle(box, radius=r, fill=255)
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
        r = max(1.0, min(radius * a, min(x1 - x0, y1 - y0) * a / 2))

        def _draw(d, ox, oy):
            d.rounded_rectangle(
                (x0 * a - ox, y0 * a - oy, x1 * a - ox, y1 * a - oy),
                radius=r, fill=fill, outline=outline,
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
        # REDUCING_GAP 是 Pillow 专门为降采样做的，比 LANCZOS 快且不糊
        resample = getattr(Image, "REDUCING_GAP", Image.BILINEAR)
        return self.img.resize((self.w, self.h), resample)


def _vgradient(width: int, height: int, color_fn) -> Image.Image:
    """竖向渐变：先算一列再横向拉伸，比逐行画矩形快一个数量级。"""
    height = max(2, int(height))
    col = Image.new("RGBA", (1, height), (0, 0, 0, 0))
    for y in range(height):
        col.putpixel((0, y), color_fn(y / (height - 1)))
    return col.resize((max(1, int(width)), height), Image.BILINEAR)


# ------------------------------------------------------------------ 玻璃

_GLASS_CACHE: Dict[tuple, Image.Image] = {}


def frost(w: float, h: float, margin: float, radius: float, k: float,
          backdrop: Optional[Image.Image], drag: bool, ss: int,
          fast: bool = False, bkey: int = 0, clear: bool = False) -> Image.Image:
    """带缓存的玻璃底板。

    玻璃只在「尺寸 / 拖拽 / 背景变化」时重算，hover 之类只重画内容，
    否则每次悬停都要 100ms+，手感会烂。
    """
    key = (int(round(w * k)), int(round(h * k)), round(margin, 2), round(radius, 2),
           round(k, 3), bool(drag), ss, bool(fast), bkey, bool(clear))
    hit = _GLASS_CACHE.get(key)
    if hit is not None:
        return hit
    img = _frost(w, h, margin, radius, k, backdrop, drag, ss, fast, clear)
    if len(_GLASS_CACHE) >= 8:
        _GLASS_CACHE.clear()
    _GLASS_CACHE[key] = img
    return img


def _frost(w: float, h: float, margin: float, radius: float, k: float,
           backdrop: Optional[Image.Image], drag: bool, ss: int,
           fast: bool = False, clear: bool = False) -> Image.Image:
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
        (sm, sm + 1 * k * f,
         max(sm + 2, sh.width - sm),
         max(sm + 2, sh.height - sm + 1 * k * f)),
        radius=max(1, min(radius * k * f, min(sh.width, sh.height) / 2)),
        fill=T.SHADOW,
    )
    sh = sh.filter(ImageFilter.GaussianBlur(max(1.2, 5 * k * f)))
    sh = sh.resize((cw, ch), Image.BILINEAR)
    out.paste(sh, (0, 0), sh)

    # --- 磨砂底（整条链路在半分辨率上做完再放大，省掉三次全画布合成）
    if clear:
        # Acrylic 模式：模糊由底层窗口（DWM 实时）提供，这一层只留装饰
        # （投影 / 描边 / 高光），中间必须全透明才能透出底层。
        panel = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    elif backdrop is not None and not drag:
        half = (max(8, cw // 2), max(8, ch // 2))
        # 模糊在**半分辨率**上做，所以半径取物理像素的一半（≈2 倍视觉半径）
        radius_px = max(1.0, (T.FROST_BLUR_FAST if fast else T.FROST_BLUR) * k * 0.5)
        bd = backdrop.resize(half, Image.BILINEAR).filter(ImageFilter.GaussianBlur(radius_px))
        # 去一点饱和：磨砂玻璃该是银灰调，不是彩色塑料
        bd = Image.blend(bd, bd.convert("L").convert("RGB"), 0.34)

        # 逐像素自适应压暗：亮的地方压得深、暗的地方几乎不压。
        # 均匀 alpha 解决不了「面板一半压在白色网页上」这种情况，会有一半字看不清。
        gray = bd.convert("L")
        lo, hi = T.TINT_ALPHA_MIN, T.TINT_ALPHA_MAX
        lut = [int(lo + (hi - lo) * (v / 255.0) ** 0.9) for v in range(256)]
        mask = gray.point(lut)
        panel = Image.composite(Image.new("RGB", half, (12, 12, 14)), bd, mask)
        panel = Image.blend(panel, Image.new("RGB", half, (22, 28, 44)), 34 / 255.0)
        # 一层很薄的白色霜：不然黑色桌面上整块窗会"消失"，跟背景糊成一片
        panel = Image.blend(panel, Image.new("RGB", half, (255, 255, 255)), 12 / 255.0)
        panel = panel.resize((cw, ch), Image.BILINEAR).convert("RGBA")
        panel.putalpha(255)
    else:
        color = T.TINT_DRAG if drag else T.TINT
        panel = Image.new("RGBA", (cw, ch), color)

    def _mk_mask():
        mk = _round_mask((cw, ch), box, rad)
        if ss == 1:
            mk = mk.filter(ImageFilter.GaussianBlur(max(0.45, 0.55 * k)))
        return mk

    mask = _cached(("mask", cw, ch, round(m, 2), round(rad, 2), ss, round(k, 3)), _mk_mask)
    out.paste(panel, (0, 0), mask)

    # --- 顶部高光（玻璃棱）：一列渐变再横向拉伸，比逐行画矩形快得多
    sheen_h = int((ch - 2 * m) * 0.40)
    if sheen_h > 2:
        strip = _vgradient(cw - 2 * m, sheen_h,
                           lambda t: (255, 255, 255, int(2 * (1 - t) ** 1.5)))
        sheen = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        sheen.paste(strip, (int(m), int(m)))
        sheen.putalpha(Image.composite(sheen.getchannel("A"),
                                       Image.new("L", (cw, ch), 0), mask))
        out = Image.alpha_composite(out, sheen)

    # --- 描边
    if ss == 1:
        out = _ring_border(out, (cw, ch), box, rad, k, T.BORDER, 1.1)
    else:
        stroke_w = max(1, int(round(1.1 * k * ss)))
        edge = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        ImageDraw.Draw(edge).rounded_rectangle(box, radius=rad, outline=T.BORDER,
                                               width=stroke_w)
        out = Image.alpha_composite(out, edge)

    # --- 顶部亮棱（往下渐隐）：只处理上沿那一窄条
    hi_h = int(max(10, (ch - 2 * m) * 0.26))
    if ss == 1:
        ring = _ring_alpha((cw, ch), box, rad, k, 1.6)
        ring = ring.crop((0, 0, cw, hi_h))
        fade = _vgradient(cw, hi_h, lambda t: (255, 255, 255, int(255 * (1 - t) ** 2)))
        a = Image.new("L", (cw, hi_h), 0)
        a.paste(ImageChops.multiply(ring, fade.getchannel("A")), (0, 0))
        layer = Image.new("RGBA", (cw, hi_h), (255, 255, 255, 0))
        lut = [min(255, v * T.BORDER_TOP[3] // 255) for v in range(256)]
        layer.putalpha(a.point(lut))
        out.alpha_composite(layer, (0, 0))
    else:
        band = Image.new("RGBA", (cw, hi_h), (0, 0, 0, 0))
        ImageDraw.Draw(band).rounded_rectangle(
            (m, m, cw - m, ch - m), radius=rad, outline=T.BORDER_TOP,
            width=max(1, int(round(1.6 * k * ss))))
        grad = _vgradient(cw, hi_h, lambda t: (255, 255, 255, int(255 * (1 - t) ** 2)))
        band.putalpha(Image.composite(band.getchannel("A"),
                                      Image.new("L", (cw, hi_h), 0), grad))
        out.alpha_composite(band, (0, 0))

    return out


def _ring_alpha(size, box, rad, k: float, width: float) -> Image.Image:
    return _cached(("ring", size, round(box[0], 2), round(box[2], 2), round(rad, 2),
                    round(k, 3), round(width, 2)), lambda: _ring_alpha_raw(size, box, rad, k, width))


def _ring_alpha_raw(size, box, rad, k: float, width: float) -> Image.Image:
    """圆角边缘的「环」：外形状减内形状，再轻微羽化，得到抗锯齿的 1px 细边。"""
    outer = Image.new("L", size, 0)
    ImageDraw.Draw(outer).rounded_rectangle(box, radius=rad, fill=255)
    inset = max(0.8, width * k * 0.5)
    inner = Image.new("L", size, 0)
    ImageDraw.Draw(inner).rounded_rectangle(
        (box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset),
        radius=max(1.0, rad - inset), fill=255)
    ring = ImageChops.subtract(outer, inner)
    return ring.filter(ImageFilter.GaussianBlur(max(0.4, 0.5 * k)))


def _ring_border(out: Image.Image, size, box, rad, k: float, color, width: float):
    ring = _ring_alpha(size, box, rad, k, width)
    lut = [min(255, v * color[3] // 255) for v in range(256)]
    layer = Image.new("RGBA", size, (color[0], color[1], color[2], 0))
    layer.putalpha(ring.point(lut))
    return Image.alpha_composite(out, layer)


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

# 归档行的哨兵卡片：只用于布局和命中，不参与排序
ARCHIVE = {"__archive__": True, "group": "", "title": "", "priority": "",
           "source": "", "owner": "", "due": "", "done": False}


def layout_cards(cards: List[Dict], done_expanded: bool):
    """返回 (rows, content_h)。

    rows: [(card, (x0, y0, x1, y1))]，y 相对**卡片区顶部**，不含滚动偏移。
        未完成任务在前；有已完成任务时，末尾跟一条「归档」行
        （折叠态一条 ARCH_H 高的行；展开态 = 头部 + 每条已完成的 DONE_ROW_H 行）。
    content_h: 所有卡片占用的总高度，比可视区大就需要滚动。
    """
    region_h = T.CARDS_BOTTOM - T.CARDS_TOP
    undone = [c for c in cards if not c.get("done")][: T.MAX_CARDS]
    done = [c for c in cards if c.get("done")]

    gap = T.CARD_GAP
    n = max(1, len(undone))
    # 有已完成时给归档行预留位置：未完成卡不算归档行就不超屏，
    # 折叠态的归档行正好贴住可视区底边，不需要滚动就能看到。
    usable_h = region_h
    if done:
        usable_h -= (T.ARCH_HEAD_H if done_expanded else T.ARCH_H) + gap

    if n <= 6:
        # 6 张以内铺满可视区（就是原来那版的高度关系）
        h = (usable_h - gap * (n - 1)) / n
        h = max(T.CARD_MIN_H, min(h, 120.0))
    else:
        # 超过 6 张：固定高度，靠滚动看剩下的
        h = 92.0

    rows = []
    x0, x1 = T.PAD_X, T.PANEL_W - T.PAD_X
    y = 0.0
    for card in undone:
        rows.append((card, (x0, y, x1, y + h)))
        y += h + gap

    if done:
        arch_h = T.ARCH_H if not done_expanded else T.ARCH_HEAD_H
        rows.append((dict(ARCHIVE), (x0, y, x1, y + arch_h)))
        y += arch_h + gap
        if done_expanded:
            for card in done:
                c = dict(card)
                c["done"] = True
                rows.append((c, (x0, y, x1, y + T.DONE_ROW_H)))
                y += T.DONE_ROW_H + gap

    content_h = (y - gap) if rows else 0.0
    return rows, content_h


# ------------------------------------------------------------------ 面板

def draw_panel(state: Dict, k: float, backdrop: Optional[Image.Image],
               ss: int = SS, fast: bool = False, bkey: int = 0,
               clear: bool = False) -> Tuple[Image.Image, List[Dict]]:
    """画展开态面板。返回 (整图, 命中区列表)。"""
    W = T.PANEL_W + T.PANEL_MARGIN * 2
    H = T.PANEL_H + T.PANEL_MARGIN * 2
    margin = T.PANEL_MARGIN
    hits: List[Dict] = []

    base = frost(W, H, margin, T.PANEL_RADIUS, k, backdrop,
                 state.get("drag", False), ss, fast, bkey, clear)
    cv = Canvas(W, H, k, ss, base)

    px = margin + T.PAD_X
    pr = margin + T.PANEL_W - T.PAD_X

    cards = state.get("cards") or []
    done_list = [c for c in cards if c.get("done")]
    undone = [c for c in cards if not c.get("done")]
    done = [c for c in cards if c.get("done")]
    urgent = [c for c in undone if c.get("priority") in ("紧急", "高")]
    hover_key = state.get("hover_key") or ""
    hover_idx = state.get("hover", -1)

    # ---- 收起按钮
    btn = 30.0
    bx1, bx0 = pr, pr - btn
    by0 = margin + 52
    by1 = by0 + btn
    cv.rounded(bx0, by0, bx1, by1, btn / 2,
               fill=(255, 255, 255, 30) if hover_key == "collapse" else (255, 255, 255, 14))
    _chevron_down(cv, (bx0 + bx1) / 2, (by0 + by1) / 2 + 1, 9, T.INK_2, 1.5)
    hits.append({"kind": "collapse", "rect": (bx0, by0, bx1, by1)})

    # ---- 头部右侧：只有收起按钮（归档收进列表底部，不再占头部）

    # ---- 卡片区（独立图层，天然被区域裁切，才能滚）
    rows, content_h = layout_cards(cards, state.get("done_expanded", False))
    region_h = T.CARDS_BOTTOM - T.CARDS_TOP
    max_scroll = max(0.0, content_h - region_h)
    scroll = min(max(0.0, float(state.get("scroll") or 0.0)), max_scroll)

    card_cv = Canvas(T.PANEL_W, region_h, k, ss)
    card_tx = Canvas(T.PANEL_W, region_h, k, ss)   # 文字层（1x 直接画）
    tdraw = ImageDraw.Draw(card_tx.img)
    geos = []

    for idx, (card, rect) in enumerate(rows):
        x0, y0, x1, y1 = rect
        y0 -= scroll
        y1 -= scroll
        if y1 < -4 or y0 > region_h + 4:
            continue

        # ---- 归档行（折叠 / 展开态的头）：整条是一个命中区，点击切换
        if card.get("__archive__"):
            hot = idx == hover_idx
            card_cv.rounded(x0, y0, x1, y1, T.CARD_RADIUS,
                            fill=(255, 255, 255, 30 if hot else 18),
                            outline=(255, 255, 255, 40 if hot else 28), width=1.0)
            cy = (y0 + y1) / 2
            txt = "已完成 %d 项" % len(done_list)
            if state.get("done_expanded"):
                txt += " · 点击收起"
            else:
                txt += " · 点击展开"
            tdraw.text(((x0 + 18) * k, cy * k), txt,
                       font=T.font(12 * k, True), fill=T.INK_2 if not hot else T.INK,
                       anchor="lm")
            if state.get("done_expanded"):
                _chevron_up(card_cv, x1 - 18, cy + 1, 9, T.INK_2, 1.6)
            else:
                _chevron_down(card_cv, x1 - 18, cy + 1, 9, T.INK_2, 1.6)
            hy0 = max(0.0, y0)
            hy1 = min(region_h, y1)
            if hy1 > hy0:
                hits.append({"kind": "archive", "index": idx, "card": dict(card),
                             "rect": (margin + x0, margin + T.CARDS_TOP + hy0,
                                      margin + x1, margin + T.CARDS_TOP + hy1)})
            continue

        # ---- 已完成的归档条目：点击任意处恢复
        if card.get("done"):
            hot = idx == hover_idx
            card_cv.rounded(x0, y0, x1, y1, T.CARD_RADIUS,
                            fill=(255, 255, 255, 30 if hot else 15),
                            outline=(255, 255, 255, 38 if hot else 24), width=1.0)
            ccx = x0 + 16 + T.CHECK_R
            ccy = (y0 + y1) / 2
            card_cv.ellipse(ccx - T.CHECK_R + 1, ccy - T.CHECK_R + 1,
                            ccx + T.CHECK_R - 1, ccy + T.CHECK_R - 1,
                            fill=(255, 255, 255, 22), outline=(255, 255, 255, 70), width=1.1)
            _check(card_cv, ccx - 1, ccy, T.CHECK_R * 0.85, T.INK_DONE, 1.5)
            tx0 = x0 + 16 + T.CHECK_R * 2 + 8
            f_t = T.font(12.5 * k, True)
            title = ellipsize(_MEAS, card.get("title") or "（无标题）", f_t,
                              (x1 - 16) - tx0)
            tdraw.text((tx0 * k, (y0 + 19) * k), title, font=f_t, fill=T.INK_DONE)
            meta = " · ".join(v for v in (card.get("group") or "",
                                          card.get("due") or "") if v)
            f_m = T.font(10.5 * k)
            meta_txt = ellipsize(_MEAS, meta, f_m, (x1 - 16) - tx0)
            tdraw.text((tx0 * k, (y0 + 39) * k), meta_txt, font=f_m, fill=T.INK_3)
            if hot:
                tdraw.text(((x1 - 16) * k, ((y0 + y1) / 2 + 1) * k), "恢复",
                           font=T.font(11 * k, True), fill=T.INK, anchor="rm")
            hy0 = max(0.0, y0)
            hy1 = min(region_h, y1)
            if hy1 > hy0:
                hits.append({"kind": "card", "index": idx, "card": dict(card),
                             "rect": (margin + x0, margin + T.CARDS_TOP + hy0,
                                      margin + x1, margin + T.CARDS_TOP + hy1)})
            continue

        # ---- 未完成卡片
        ch = y1 - y0
        compact = ch < 70
        pad_top = y0 + (11 if compact else max(11.0, (ch - 62) / 2))
        done_card = False
        hot = idx == hover_idx
        pri = card.get("priority") or "常规"

        # --- 形状
        card_cv.rounded(x0, y0, x1, y1, T.CARD_RADIUS,
                        fill=T.CARD_FILL_HOVER if hot else T.CARD_FILL,
                        outline=T.CARD_BORDER_HOVER if hot else T.CARD_BORDER,
                        width=1.0)
        # 左侧优先级色条（每一级都有，一眼扫出轻重缓急）
        bar_bg = T.PRIORITY.get(pri, T.PRIORITY["常规"])[0]
        card_cv.rounded(x0 + 1, y0 + 16, x0 + 4, y1 - 16, 1.5, fill=bar_bg)

        chip_h = 19.0
        chip_w = _text_len(_MEAS, pri, T.font(10.5 * k, True)) / k + 16
        cx1 = x1 - 14
        cx0 = cx1 - chip_w
        chip_y = pad_top + 6.5 - chip_h / 2
        bg, _fg = T.PRIORITY.get(pri, T.PRIORITY["常规"])
        card_cv.rounded(cx0, chip_y, cx1, chip_y + chip_h, chip_h / 2, fill=bg)
        if hot:
            _arrow_right(card_cv, x1 - 12, (y0 + y1) / 2, 9, T.INK_2, 1.5)

        # --- 左侧「完成」圆钮
        ccx = x0 + 15 + T.CHECK_R
        ccy = (y0 + y1) / 2
        check_hot = (hover_idx == idx and (state.get("hover_key") == "check"))
        if check_hot:
            card_cv.ellipse(ccx - T.CHECK_R, ccy - T.CHECK_R, ccx + T.CHECK_R, ccy + T.CHECK_R,
                            fill=T.ACCENT)
            _check(card_cv, ccx, ccy, T.CHECK_R * 1.05, (255, 255, 255, 255), 2.0)
        else:
            card_cv.ellipse(ccx - T.CHECK_R, ccy - T.CHECK_R, ccx + T.CHECK_R, ccy + T.CHECK_R,
                            outline=(255, 255, 255, 78), width=1.3)
        # 命中区必须换算成窗口坐标（卡片内坐标是相对卡片区的）
        hits.append({"kind": "check", "index": idx, "card": card,
                     "rect": (margin + ccx - T.CHECK_R - 3,
                              margin + T.CARDS_TOP + ccy - T.CHECK_R - 3,
                              margin + ccx + T.CHECK_R + 3,
                              margin + T.CARDS_TOP + ccy + T.CHECK_R + 3)})

        # --- 文字（让出左侧圆钮的位置）
        tx0 = x0 + 15 + T.CHECK_R * 2 + 9
        f_g = T.font(10.5 * k)
        room = (x1 - 14 - chip_w - 10) - tx0
        gname = ellipsize(_MEAS, card.get("group") or "未知群", f_g, room)
        tdraw.text((tx0 * k, pad_top * k), gname, font=f_g, fill=T.INK_3)

        _bg, fg = T.PRIORITY.get(pri, T.PRIORITY["常规"])
        tdraw.text(((cx0 + chip_w / 2) * k, (chip_y + chip_h / 2 + 0.5) * k), pri,
                   font=T.font(10.5 * k, True), fill=fg, anchor="mm")

        f_t = T.font(16 * k, True)
        title = ellipsize(_MEAS, card.get("title") or "（无标题）", f_t, (x1 - 15) - tx0)
        tdraw.text((tx0 * k, (pad_top + 23) * k), title, font=f_t, fill=T.INK)

        if not compact:
            source = (card.get("source") or "").strip()
            owner = (card.get("owner") or "").strip()
            due = (card.get("due") or "").strip()
            f_m = T.font(10.5 * k)
            meta_x = tx0
            due_soon = bool(due) and any(t in due for t in ("今天", "今日", "明天", "明日"))
            for label, value in (("来自", source), ("负责", owner), ("截止", due)):
                if not value or value in ("未指定", "-", "无明确截止"):
                    continue
                # 「来自 张经理」两段色：标签暗、内容亮，一眼分得清
                lw = _text_len(_MEAS, label + " ", f_m) / k
                tdraw.text((meta_x * k, (pad_top + 46) * k), label + " ", font=f_m,
                           fill=T.INK_3)
                val_max = (x1 - 15) - (meta_x + lw)
                val = ellipsize(_MEAS, value, f_m, val_max)
                if label == "截止" and due_soon:
                    vcol = T.WARN
                else:
                    vcol = T.INK_2
                tdraw.text(((meta_x + lw) * k, (pad_top + 46) * k), val, font=f_m,
                           fill=vcol)
                meta_x += lw + _text_len(_MEAS, val, f_m) / k + 14
                if meta_x > x1 - 15:
                    break

        # 命中区（窗口逻辑坐标，已裁到可视区）
        hy0 = max(0.0, y0)
        hy1 = min(region_h, y1)
        if hy1 > hy0:
            hits.append({"kind": "card", "index": idx, "card": card,
                         "rect": (margin + x0, margin + T.CARDS_TOP + hy0,
                                  margin + x1, margin + T.CARDS_TOP + hy1)})
        geos.append(idx)

    layer = card_cv.img
    layer.alpha_composite(card_tx.img, (0, 0))

    # 能滚的时候，上下边缘渐隐，滚到一半的卡片不会被硬切
    if max_scroll > 0.5:
        fade = int(T.SCROLL_FADE * k * ss)
        if fade > 1:
            grad = Image.new("L", (1, layer.height), 255)
            for yy in range(fade):
                v = int(255 * yy / fade)
                grad.putpixel((0, yy), v)
                grad.putpixel((0, layer.height - 1 - yy), v)
            layer.putalpha(ImageChops.multiply(layer.getchannel("A"),
                                               grad.resize(layer.size)))

    cv.img.alpha_composite(layer, (int(margin * k * ss), int((margin + T.CARDS_TOP) * k * ss)))

    # 滚动位置指示条（只在内容超出时出现，细到几乎不打扰）
    if max_scroll > 0.5:
        bar_x = margin + T.PANEL_W - 9
        bar_top = margin + T.CARDS_TOP + 4
        bar_area = region_h - 8
        bar_h = max(26.0, bar_area * region_h / content_h)
        bar_y = bar_top + (bar_area - bar_h) * (scroll / max_scroll)
        cv.rounded(bar_x, bar_y, bar_x + 3, bar_y + bar_h, 1.5,
                   fill=(255, 255, 255, 86))

    # ---- 底部分隔线 + 完成折叠条
    fy = margin + T.PANEL_H - 56
    cv.line([(px, fy), (pr, fy)], fill=T.DIVIDER, width=1.0)
    footer_y = fy + 16


    img = cv.flat()

    # ---------------------------------------------------------- 头部/底部文字（1×）
    tl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(tl)

    def put(x, y, s, size, color, bold=False, anchor="la"):
        td.text((x * k, y * k), s, font=T.font(size * k, bold), fill=color, anchor=anchor)

    put(px, 26, "今日待办", 11.5, T.INK_3, bold=True)
    gen = state.get("generated_at") or ""
    stale_h = state.get("stale_hours")
    if stale_h is not None and stale_h >= 3:
        put(pr, 26, "数据为 %d 小时前" % int(stale_h), 11.5, T.WARN, anchor="ra")
    elif gen:
        put(pr, 26, "更新于 %s" % (gen[11:16] if len(gen) >= 16 else gen), 11.5,
            T.INK_3, anchor="ra")

    num = str(len(undone))
    f_num = T.font(38 * k, True)
    td.text((px * k, 44 * k), num, font=f_num, fill=T.INK)
    nw = td.textlength(num, font=f_num) / k
    tx = px + nw + 9
    put(tx, 53, "项待办", 12.5, T.INK_2)
    if urgent:
        w1 = _text_len(td, "项待办", T.font(12.5 * k)) / k
        put(tx + w1 + 7, 55, "· %d 项紧急" % len(urgent), 11, T.ACCENT, bold=True)
    meta = []
    if state.get("groups"):
        meta.append("%d 个群" % state["groups"])
    if state.get("total_messages"):
        meta.append("%d 条消息" % state["total_messages"])
    if meta:
        put(tx, 71, " · ".join(meta), 10.5, T.INK_3)

    if done_list:
        if state.get("done_expanded"):
            put(px, footer_y, "点击已完成的卡片可以恢复", 11.5, T.INK_3)
        else:
            put(px, footer_y, "已完成 %d 条 · 收在下方归档栏" % len(done_list), 11.5, T.INK_3)
    else:
        put(px, footer_y, "今天没有已完成的任务", 11.5, T.INK_3)

    if state.get("empty") and not rows:
        put(margin + T.PANEL_W / 2, margin + 300, "今天还没有生成报告", 14, T.INK_2, anchor="mm")
        put(margin + T.PANEL_W / 2, margin + 326, "右键 →「重新读取数据」", 11, T.INK_3, anchor="mm")

    return Image.alpha_composite(img, tl), hits


# ------------------------------------------------------------------ 收起态玻璃球

def draw_ball(state: Dict, k: float, backdrop: Optional[Image.Image],
              ss: int = SS, fast: bool = False, bkey: int = 0,
              clear: bool = False) -> Tuple[Image.Image, List[Dict]]:
    W = T.BALL + T.BALL_MARGIN * 2
    H = W
    base = frost(W, H, T.BALL_MARGIN, T.BALL / 2, k, backdrop,
                 state.get("drag", False), ss, fast, bkey, clear)
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
                ss: int = SS, fast: bool = False, bkey: int = 0,
                clear: bool = False) -> Tuple[Image.Image, List[Dict]]:
    W = T.SLIVER_W + T.SLIVER_MARGIN * 2
    H = T.SLIVER_H + T.SLIVER_MARGIN * 2
    base = frost(W, H, T.SLIVER_MARGIN, T.SLIVER_W / 2, k, backdrop,
                 False, ss, fast, bkey, clear)
    cv = Canvas(W, H, k, ss, base)

    m = T.SLIVER_MARGIN
    cv.rounded(m + 0.5, m, W - m - 0.5, H - m, T.SLIVER_W / 2,
               fill=(255, 255, 255, 196))
    undone = [c for c in (state.get("cards") or []) if not c.get("done")]
    if any(c.get("priority") in ("紧急", "高") for c in undone):
        mid = H / 2
        cv.rounded(m + 0.5, mid - 24, W - m - 0.5, mid + 24,
                   T.SLIVER_W / 2, fill=T.ACCENT)

    return cv.flat(), [{"kind": "sliver", "rect": (m, m, W - m, H - m)}]
