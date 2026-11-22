# -*- coding: utf-8 -*-
"""悬浮窗的视觉常量。

所有尺寸都是 **96dpi 下的逻辑像素**，渲染时统一乘 dpi 缩放系数。
手感参数（吸附距离、动画时长）集中在这里，方便反复调。
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------- 尺寸

PANEL_W = 482
PANEL_H = 780
PANEL_RADIUS = 24
PANEL_MARGIN = 20          # 留白给投影

BALL = 68                  # 收起态直径
BALL_MARGIN = 14

SLIVER_W = 10              # 贴边隐藏后的细条宽度（6px 在黑壁纸上等于消失，加到 10）
SLIVER_H = 168
SLIVER_MARGIN = 12

PAD_X = 26                 # 面板左右内边距（卡片宽度 = 540-2*PAD_X）
HEADER_H = 96
CARDS_TOP = 112
CARDS_BOTTOM = 710
CARD_GAP = 12
CARD_RADIUS = 18
CARD_PAD = 16
MAX_CARDS = 60             # 卡片不设上限，超出可视区就滚动
CARD_MIN_H = 78
ARCH_H = 44                # 归档行（折叠态）高度
ARCH_HEAD_H = 36           # 归档行（展开态的头部）高度
DONE_ROW_H = 56            # 归档展开后每条已完成任务的高度
SCROLL_STEP = 96           # 滚一格滚多少像素
SCROLL_EASE = 0.30         # 滚动跟随系数（越大越跟手）
SCROLL_FADE = 14           # 卡片区上下的渐隐高度

# 已完成任务收进列表底部的「归档」折叠行（不再挤在头部右上角）
CHECK_R = 9                # 卡片左侧完成按钮半径

# ---------------------------------------------------------------- 手感参数

SNAP_DIST = 24             # 拖到边缘多少像素内吸附
ANIM_MS = 200              # 收起/展开动画时长（项目统一 200–420ms，取最快档）
HIDE_DELAY_MS = 5000       # 鼠标点击别处/离开面板多久后自动收成右侧细条（用户要求「几秒后」）
SLIVER_HOVER_PAD = 12      # 光标距细条多少像素触发展开
POLL_MS = 100              # 光标轮询间隔
FRAME_MS = 8               # 动画帧间隔：WM_TIMER 会被系统合并，8ms 才够 60fps
DATA_POLL_MS = 3000        # cards.json 检查间隔
BACKDROP_MS = 1500         # 磨砂背景重新取景间隔

# ---------------------------------------------------------------- 颜色

TINT = (16, 16, 18, 168)          # 抓不到屏时的兜底底色
TINT_DRAG = (16, 16, 18, 232)     # 拖动时的实底（关掉磨砂）
BORDER = (255, 255, 255, 26)
BORDER_TOP = (255, 255, 255, 40)  # 顶部亮边，模拟玻璃棱
SHADOW = (0, 0, 0, 14)            # 光晕几乎去掉，只留一点边

# 压暗强度随背景亮度自适应：暗桌面更透，亮背景自动加深保证白字可读
TINT_ALPHA_MIN = 120              # 背景很暗时（最透）
TINT_ALPHA_MAX = 192              # 背景很亮时（最实）

# 磨砂模糊半径（按物理像素算；内部在半分辨率上做，所以实际传一半）
# 太小（1~2px）会变成「半透明脏玻璃」，壁纸细节直接透进来，卡片看着脏。
FROST_BLUR = 26.0
FROST_BLUR_FAST = 14.0            # 动画中的降级值，省 CPU

INK = (243, 242, 240, 255)
INK_2 = (180, 178, 175, 255)
INK_3 = (150, 148, 145, 255)
INK_DONE = (108, 106, 104, 255)

ACCENT = (255, 92, 40, 255)
ACCENT_DIM = (255, 92, 40, 196)
WARN = (255, 176, 76, 255)

CARD_FILL = (255, 255, 255, 34)   # 卡片白：太透会糊在玻璃里，看不出卡片边界
CARD_FILL_HOVER = (255, 255, 255, 54)
CARD_BORDER = (255, 255, 255, 52)
CARD_BORDER_HOVER = (255, 255, 255, 74)
DIVIDER = (255, 255, 255, 20)

PRIORITY = {
    # (底色, 字色)：字色比底色亮一档，暗底上才看得清
    "紧急": ((255, 92, 40, 40), (255, 156, 122, 255)),
    "高": ((255, 92, 40, 40), (255, 156, 122, 255)),
    "重要": ((255, 176, 76, 34), (255, 202, 134, 255)),
    "中": ((140, 170, 255, 30), (168, 192, 255, 255)),
    "常规": ((255, 255, 255, 16), (176, 174, 172, 255)),
}

# ---------------------------------------------------------------- 字体

# 字体候选：按顺序取第一个存在的文件。
# Windows 微软雅黑 → macOS 苹方 → Linux Noto / 文泉驿。
# 不加这条链的话，系统没有雅黑时会掉到 PIL 的位图默认字体，中文全变方块。
_BOLD = [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc",
         r"C:\Windows\Fonts\simhei.ttf",
         "/System/Library/Fonts/PingFang.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
         "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"]
_REG = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"]

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


def spring(t: float) -> float:
    """项目统一手感曲线 cubic-bezier(.22,1.2,.36,1)，带一点点回弹。

    CSS 里的贝塞尔要先解 x(t)=x 再取 y(t)，这里用二分，12 次足够精确，
    每帧只调一次，成本可以忽略。
    """
    t = min(1.0, max(0.0, t))
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(12):
        mid = (lo + hi) / 2
        x = 3 * (1 - mid) ** 2 * mid * 0.22 + 3 * (1 - mid) * mid * mid * 0.36 + mid ** 3
        if x < t:
            lo = mid
        else:
            hi = mid
    m = (lo + hi) / 2
    return 3 * (1 - m) ** 2 * m * 1.2 + 3 * (1 - m) * m * m * 1.0 + m ** 3


def ease_in_out(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_rect(r1, r2, t):
    return tuple(lerp(r1[i], r2[i], t) for i in range(4))
