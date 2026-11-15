# -*- coding: utf-8 -*-
"""桌面悬浮窗入口。

    python tools/desktop_widget.py               正常启动（有控制台）
    python tools/desktop_widget.py --demo        用示例数据看效果
    python tools/desktop_widget.py --snapshot x.png --mode expanded
                                                 只渲染一张图，不出窗口（调样式用）
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from widget import theme as T, win32  # noqa: E402

MUTEX_NAME = "WeChatWorkHubWidget_SingleInstance"


def _single_instance():
    """返回 (是否首实例, 句柄)。句柄必须持有到进程结束。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, 0, MUTEX_NAME)
    already = ctypes.get_last_error() == 183
    return (not already), handle


def _snapshot(path: str, mode: str, scale: float) -> int:
    """渲染一张静态图。背景抓真实桌面，方便直接看玻璃效果。"""
    from widget import render
    from widget.app import _demo_payload
    from widget.store import sort_cards

    payload = _demo_payload()
    cards = sort_cards(payload["cards"])
    st = {
        "cards": cards,
        "done_expanded": False,
        "hover": 1,
        "hover_key": "",
        "generated_at": payload["generated_at"],
        "stale_hours": 1.2,
        "groups": payload["groups"],
        "total_messages": payload["total_messages"],
        "empty": False,
        "drag": False,
    }
    backdrop = None
    try:
        if mode == "expanded":
            backdrop = win32.capture(0, 0, int((T.PANEL_W + 40) * scale),
                                     int((T.PANEL_H + 40) * scale))
        else:
            backdrop = win32.capture(0, 0, 200, 200)
    except Exception:
        backdrop = None

    if mode == "expanded":
        img, _hits = render.draw_panel(st, scale, backdrop)
    elif mode == "ball":
        img, _hits = render.draw_ball(st, scale, backdrop)
    else:
        img, _hits = render.draw_sliver(st, scale, backdrop)
    out = os.path.abspath(path)
    img.save(out)
    print(f"已保存 {out}  ({img.width}x{img.height})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="微信群聊待办悬浮窗")
    ap.add_argument("--demo", action="store_true", help="没有 cards.json 时用示例数据")
    ap.add_argument("--mode", choices=["expanded", "ball", "sliver"], default=None,
                    help="强制以某个形态启动")
    ap.add_argument("--snapshot", default=None, help="只渲染静态图到指定路径")
    ap.add_argument("--scale", type=float, default=1.0, help="snapshot 的缩放")
    args = ap.parse_args(argv)

    win32.enable_dpi_awareness()

    if args.snapshot:
        return _snapshot(args.snapshot, args.mode or "expanded", args.scale)

    first, handle = _single_instance()
    if not first:
        print("悬浮窗已经在运行了（右下角找找，或看托盘上方的玻璃球）。")
        return 0

    from widget.app import Widget

    app = Widget(demo=args.demo, start_mode=args.mode)
    print("悬浮窗已启动。拖到屏幕左右边缘 24px 内会自动吸附。")
    print("右键玻璃球/面板可打开菜单，选「退出」结束。")
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
