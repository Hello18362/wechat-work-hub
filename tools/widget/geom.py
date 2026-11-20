# -*- coding: utf-8 -*-
"""几何判定与换算（不碰 win32，Linux CI 也能测）。

这里只放纯函数：输入矩形/工作区，输出矩形。谁去调 SetWindowPos 由 app.py 负责。
"""

from __future__ import annotations

from . import theme as T


def hover_pad_hit(rect, cx: float, cy: float, pad: float) -> bool:
    """鼠标是否落在矩形外扩 pad 的范围内（细条悬停判定用）。"""
    x, y, w, h = rect
    return (x - pad <= cx <= x + w + pad) and (y - pad <= cy <= y + h + pad)


def visible_box(mode: str, rect, k: float = 1.0):
    """窗口矩形（含投影留白）→ 屏幕上真正看得见的矩形 (x, y, w, h)。

    拖动和吸边都必须按这个矩形算：留白不是内容，按留白算就会把窗口
    「贴边」贴到屏幕外去。
    """
    x, y, _w, _h = rect
    if mode == "expanded":
        m = T.PANEL_MARGIN * k
        return (x + m, y + m, T.PANEL_W * k, T.PANEL_H * k)
    if mode == "ball":
        m = T.BALL_MARGIN * k
        return (x + m, y + m, T.BALL * k, T.BALL * k)
    m = T.SLIVER_MARGIN * k
    return (x + m, y + m, T.SLIVER_W * k, T.SLIVER_H * k)


def panel_pos_from_box(mode: str, box, k: float = 1.0):
    """可见矩形 → panel_pos（面板左上角）。

    球形态贴在面板右下角，所以存的位置是「面板」坐标，球只是面板的一个角；
    直接把球的左上角当 panel_pos 存，下次渲染就会把球再往右推 414px。
    """
    x, y, _w, _h = box
    if mode == "ball":
        return (x - (T.PANEL_W - T.BALL) * k, y)
    return (x, y)


def clamp_to_work(box, work):
    """把可见矩形夹进工作区；比工作区还大就贴左上角。"""
    x, y, w, h = box
    left, top, right, bottom = work
    if x + w > right:
        x = max(left, right - w)
    if x < left:
        x = left
    if y + h > bottom:
        y = max(top, bottom - h)
    if y < top:
        y = top
    return (x, y, w, h)


def snap_x(box, work, snap: float):
    """靠近左右边缘就贴边，返回 (新的 x, side)；side 取 "left"/"right"/""。"""
    x, _y, w, _h = box
    left, _top, right, _bottom = work
    side = ""
    if x - left <= snap:
        side, x = "left", left
    elif right - (x + w) <= snap:
        side, x = "right", right - w
    return (x, side)