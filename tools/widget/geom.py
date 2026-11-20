# -*- coding: utf-8 -*-
"""纯几何判定（不依赖 win32，Linux CI 也能测）。"""

from __future__ import annotations


def hover_pad_hit(rect, cx: float, cy: float, pad: float) -> bool:
    """光标是否落在矩形外扩 pad 的范围内（细条悬停判定）。"""
    x, y, w, h = rect
    return (x - pad <= cx <= x + w + pad) and (y - pad <= cy <= y + h + pad)