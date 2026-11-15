# -*- coding: utf-8 -*-
"""悬浮窗的视觉常量。

所有尺寸都是 **96dpi 下的逻辑像素**，渲染时统一乘 dpi 缩放系数。
手感参数（吸附距离、动画时长）集中在这里，方便反复调。
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------- 尺寸

PANEL_W = 540
PANEL_H = 780
PANEL_RADIUS = 24
PANEL_MARGIN = 20          # 留白给投影

BALL = 68                  # 收起态直径
BALL_MARGIN = 14

SLIVER_W = 6               # 贴边隐藏后的细条宽度
SLIVER_H = 168
SLIVER_MARGIN = 12

PAD_X = 26                 # 面板左右内边距
HEADER_H = 96
CARDS_TOP = 112
CARDS_BOTTOM = 710
CARD_GAP = 12
CARD_RADIUS = 18
CARD_PAD = 16
MAX_CARDS = 6

# ---------------------------------------------------------------- 手感参数

SNAP_DIST = 24             # 拖到边缘多少像素内吸附
ANIM_MS = 260              # 收起/展开动画时长（项目统一 200–420ms）
HIDE_DELAY_MS = 1500       # 无操作多久缩成细条
SLIVER_HOVER_PAD = 12      # 光标距细条多少像素触发展开
POLL_MS = 100              # 光标轮询间隔
FRAME_MS = 16              # 动画帧间隔（约 60fps）
DATA_POLL_MS = 3000        # cards.json 检查间隔
BACKDROP_MS = 1500         # 磨砂背景重新取景间隔

# ---------------------------------------------------------------- 颜色

TINT = (16, 16, 18, 168)          # 玻璃暗色底，保证白字可读
TINT_DRAG = (16, 16, 18, 236)     # 拖动时的实底（关掉磨砂）
BORDER = (255, 255, 255, 46)
BORDER_TOP = (255, 255, 255, 92)  # 顶部亮边，模拟玻璃棱
SHADOW = (0, 0, 0, 96)

INK = (243, 242, 240, 255)
INK_2 = (166, 164, 161, 255)
INK_3 = (114, 112, 109, 255)
INK_DONE = (108, 106, 104, 255)

ACCENT = (255, 92, 40, 255)
ACCENT_DIM = (255, 92, 40, 210)
WARN = (255, 176, 76, 255)

CARD_FILL = (255, 255, 255, 16)
CARD_FILL_HOVER = (255, 255, 255, 26)
CARD_BORDER = (255, 255, 255, 22)
CARD_BORDER_HOVER = (255, 255, 255, 46)
DIVIDER = (255, 255, 255, 20)

PRIORITY = {
    "紧急": ((255, 92, 40, 34), (255, 92, 40, 255)),
    "高": ((255, 92, 40, 34), (255, 92, 40, 255)),
    "重要": ((255, 176, 76, 30), (255, 176, 76, 255)),
    "中": ((140, 170, 255, 26), (150, 178, 255, 255)),
    "常规": ((255, 255, 255, 14), (150, 148, 146, 255)),
}

# ---------------------------------------------------------------- 字体

_BOLD = [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
         r"C:\Windows\Fonts\simhei.ttf"]
_REG = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]

_font_cache: dict = {}


def font(size: int, bold: bool = False):
    """按像素尺寸取字体（带缓存）。"""
    key = (int(size), bool(bold))
    if key in _font_cache:
        return _font_cache[key]
    from PIL import ImageFont

    chosen = None
    for path in (_BOLD if bold else _REG):
        if os.path.exists(path):
            try:
                chosen = ImageFont.truetype(path, int(size))
                break
            except OSError:
                continue
    if chosen is None:
        chosen = ImageFont.load_default()
    _font_cache[key] = chosen
    return chosen


# ---------------------------------------------------------------- 动效

def ease_out_cubic(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_rect(r1, r2, t):
    return tuple(lerp(r1[i], r2[i], t) for i in range(4))
