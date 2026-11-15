# -*- coding: utf-8 -*-
"""悬浮窗本体：窗口、状态机、拖拽、吸边、动画。

三种形态：
    expanded  展开面板 540×780
    ball      收起玻璃球 68×68
    sliver    贴边细条 6×168

状态切换一律用「缩放 + 交叉淡化」完成（260ms，ease-out-cubic）：
把起点和终点的整图各自缓存好，每帧只做 resize + alpha 合成，
不逐帧重画内容，因此 60fps 也稳。
"""

from __future__ import annotations

import os
import sys
import time
from typing import Dict, List, Optional, Tuple

from PIL import Image

from . import render, theme as T, win32
from .store import CardStore, WidgetState

TID_FRAME = 1
TID_IDLE = 2

MENU_REPORT = 1001
MENU_RELOAD = 1002
MENU_TOGGLE = 1003
MENU_QUIT = 1004

MODES = ("expanded", "ball", "sliver")


def _xy(lparam: int) -> Tuple[int, int]:
    x = lparam & 0xFFFF
    y = (lparam >> 16) & 0xFFFF
    if x >= 0x8000:
        x -= 0x10000
    if y >= 0x8000:
        y -= 0x10000
    return x, y


class Widget:
    def __init__(self, demo: bool = False, start_mode: Optional[str] = None):
        self.store = CardStore()
        self.store.load()
        if demo and not self.store.cards():
            self.store.data = _demo_payload()
            self.store.data["cards"] = [dict(c) for c in self.store.data["cards"]]

        self.state = WidgetState()
        self.k = 1.0
        self.mode = start_mode or (self.state.get("mode") or "expanded")
        if self.mode not in MODES:
            self.mode = "expanded"
        self.side = self.state.get("side") or ""
        self.done_expanded = bool(self.state.get("done_expanded"))

        self.backdrop: Optional[Image.Image] = None
        self._backdrop_key = None
        self.hits: List[Dict] = []
        self.hover = -1
        self.hover_key = ""
        self.dragging = False
        self._drag: Optional[Dict] = None
        self._press: Optional[Dict] = None
        self.anim: Optional[Dict] = None
        self._last_leave = 0.0
        self._inside = True
        self._last_data = time.perf_counter()
        self._last_backdrop = 0.0
        self._last_topmost = 0.0
        self._ball_click_job: Optional[float] = None
        self._suppress_up = False
        self._last_img: Optional[Image.Image] = None
        self.running = True
        self._img_cache: Dict[str, Tuple[Image.Image, int]] = {}

        # 初始尺寸：先按 96dpi 建窗，拿到 hwnd 后再校正 DPI
        w, h = self._mode_size(self.mode)
        self.win = win32.LayeredWindow(int(w), int(h), self._wndproc)
        self.k = win32.window_scale(self.win.hwnd)
        self._place_initial()

        self.render(ss=2)
        self.win.show()
        self.win.timer(TID_IDLE, T.POLL_MS)
        self._flush_timers()

    # ------------------------------------------------------------ 几何

    def _mode_size(self, mode: str) -> Tuple[float, float]:
        k = getattr(self, "k", 1.0)
        if mode == "expanded":
            return ((T.PANEL_W + T.PANEL_MARGIN * 2) * k,
                    (T.PANEL_H + T.PANEL_MARGIN * 2) * k)
        if mode == "ball":
            return ((T.BALL + T.BALL_MARGIN * 2) * k,
                    (T.BALL + T.BALL_MARGIN * 2) * k)
        return ((T.SLIVER_W + T.SLIVER_MARGIN * 2) * k,
                (T.SLIVER_H + T.SLIVER_MARGIN * 2) * k)

    def _panel_size(self) -> Tuple[float, float]:
        return (T.PANEL_W * self.k, T.PANEL_H * self.k)

    def _work(self) -> Tuple[int, int, int, int]:
        px, py = self.panel_pos
        pw, ph = self._panel_size()
        return win32.monitor_work_rect(int(px + pw / 2), int(py + ph / 2))

    def _rect_for(self, mode: str, panel_pos=None) -> Tuple[float, float, float, float]:
        """返回窗口矩形 (x, y, w, h)，含投影留白。"""
        k = self.k
        px, py = panel_pos or self.panel_pos
        pw, ph = self._panel_size()
        if mode == "expanded":
            m = T.PANEL_MARGIN * k
            return (px - m, py - m, pw + 2 * m, ph + 2 * m)
        if mode == "ball":
            m = T.BALL_MARGIN * k
            bx = px + pw - T.BALL * k
            return (bx - m, py - m, T.BALL * k + 2 * m, T.BALL * k + 2 * m)
        # sliver
        left, top, right, bottom = self._work()
        m = T.SLIVER_MARGIN * k
        y = py + (ph - T.SLIVER_H * k) / 2
        if self.side == "right":
            x = right - T.SLIVER_W * k
        else:
            x = left
        return (x - m, y - m, T.SLIVER_W * k + 2 * m, T.SLIVER_H * k + 2 * m)

    def _place_initial(self) -> None:
        k = self.k
        left, top, right, bottom = win32.monitor_work_rect(*win32.cursor_pos())
        pw, ph = self._panel_size()
        sx, sy = self.state.get("panel_x"), self.state.get("panel_y")
        if sx is None or sy is None:
            px = right - pw - 40 * k
            py = top + (bottom - top - ph) / 2
        else:
            px, py = float(sx), float(sy)
        px = min(max(px, left), right - pw)
        py = min(max(py, top), bottom - ph)
        self.panel_pos = (px, py)
        if self.side and self.mode == "expanded":
            self.panel_pos = (left if self.side == "left" else right - pw, py)
        rect = self._rect_for(self.mode)
        self.win_rect = rect

    def _apply_rect(self, rect, paint: bool = True, img: Optional[Image.Image] = None) -> None:
        x, y, w, h = (int(round(v)) for v in rect)
        self.win_rect = (x, y, w, h)
        user32 = win32.user32
        user32.SetWindowPos(self.win.hwnd, None, x, y, w, h,
                            win32.SWP_NOZORDER | win32.SWP_NOACTIVATE)
        if paint:
            if img is None:
                img = self._render_image(ss=1, fast=True)
            self._paint(img, x, y)

    # ------------------------------------------------------------ 渲染

    def _view_state(self, drag: bool = False) -> Dict:
        cards = self.store.cards()
        meta = self.store.data
        return {
            "cards": cards,
            "done_expanded": self.done_expanded,
            "hover": self.hover,
            "hover_key": self.hover_key,
            "generated_at": meta.get("generated_at") or "",
            "stale_hours": self.store.stale_hours(),
            "groups": meta.get("groups") or 0,
            "total_messages": meta.get("total_messages") or 0,
            "empty": bool(meta.get("empty")) or not cards,
            "drag": drag,
        }

    def _render_image(self, ss: int = 2, fast: bool = False) -> Image.Image:
        st = self._view_state(drag=self.dragging and not self.anim)
        if self.mode == "expanded":
            img, hits = render.draw_panel(st, self.k, self.backdrop, ss=ss, fast=fast)
        elif self.mode == "ball":
            img, hits = render.draw_ball(st, self.k, self.backdrop, ss=ss, fast=fast)
        else:
            img, hits = render.draw_sliver(st, self.k, self.backdrop, ss=ss, fast=fast)
        self.hits = hits
        return img

    def render(self, ss: int = 2) -> None:
        img = self._render_image(ss=ss)
        x, y, w, h = self.win_rect
        self.win_rect = (x, y, img.width, img.height)
        self._paint(img, x, y)

    def _paint(self, img: Image.Image, x: float, y: float) -> None:
        self._last_img = img
        self.win.paint(img, int(x), int(y))

    def _alpha_at(self, cx: int, cy: int) -> int:
        """取当前画面某点的 alpha，用于判断该不该让点击穿透。"""
        img = self._last_img
        if img is None:
            return 255
        if 0 <= cx < img.width and 0 <= cy < img.height:
            try:
                return img.getpixel((cx, cy))[3]
            except Exception:
                return 255
        return 0

    # ------------------------------------------------------------ 磨砂背景

    def _refresh_backdrop(self, force: bool = False) -> bool:
        """抓一次窗口背后的桌面；和上次差异很小就跳过，省 CPU。"""
        if self.mode == "sliver":
            return False
        x, y, w, h = self.win_rect
        m = T.PANEL_MARGIN * self.k if self.mode == "expanded" else T.BALL_MARGIN * self.k
        rect = (int(x + m), int(y + m), int(w - 2 * m), int(h - 2 * m))
        if rect[2] < 8 or rect[3] < 8:
            return False
        try:
            shot = win32.capture(*rect)
        except Exception:
            return False
        key = (rect, _thumb(shot))
        if not force and key == self._backdrop_key:
            return False
        self._backdrop_key = key
        self.backdrop = shot
        return True

    # ------------------------------------------------------------ 动画

    def _animate(self, to_mode: str, dur_ms: int = T.ANIM_MS,
                 on_done=None) -> None:
        to_rect = self._rect_for(to_mode)
        from_img = self._render_image(ss=2)
        prev_mode, prev_rect = self.mode, self.win_rect

        self.mode = to_mode  # 先切换，才能渲染目标图
        to_img = self._render_image(ss=2)
        self.mode = prev_mode
        self.win_rect = prev_rect

        self.anim = {
            "from": prev_rect,
            "to": to_rect,
            "from_img": from_img,
            "to_img": to_img,
            "to_mode": to_mode,
            "t0": time.perf_counter(),
            "dur": max(0.08, dur_ms / 1000.0),
            "on_done": on_done,
        }
        self._flush_timers()

    def _anim_frame(self) -> None:
        a = self.anim
        now = time.perf_counter()
        t = (now - a["t0"]) / a["dur"]
        e = T.ease_out_cubic(t)
        rect = T.lerp_rect(a["from"], a["to"], e)
        w, h = max(1, int(round(rect[2]))), max(1, int(round(rect[3])))
        x, y = int(round(rect[0])), int(round(rect[1]))

        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if e < 0.999:
            fi = a["from_img"].resize((w, h), Image.BILINEAR)
            if e > 0.001:
                fi.putalpha(fi.getchannel("A").point(lambda v: int(v * (1 - e))))
            canvas = Image.alpha_composite(canvas, fi)
        if e > 0.001:
            ti = a["to_img"].resize((w, h), Image.BILINEAR)
            if e < 0.999:
                ti.putalpha(ti.getchannel("A").point(lambda v: int(v * e)))
            canvas = Image.alpha_composite(canvas, ti)

        self.win_rect = (x, y, w, h)
        win32.user32.SetWindowPos(self.win.hwnd, None, x, y, w, h,
                                  win32.SWP_NOZORDER | win32.SWP_NOACTIVATE)
        self._paint(canvas, x, y)

        if t >= 1.0:
            done = a["on_done"]
            self.mode = a["to_mode"]
            self.anim = None
            self._last_backdrop = 0.0
            self._refresh_backdrop(force=True)
            self.render(ss=2)
            self._flush_timers()
            if done:
                done()

    def _flush_timers(self) -> None:
        if self.anim:
            self.win.timer(TID_FRAME, T.FRAME_MS)
        else:
            self.win.kill_timer(TID_FRAME)

    # ------------------------------------------------------------ 形态切换

    def to_ball(self) -> None:
        if self.mode == "ball" or self.anim:
            return
        self._animate("ball")
        self.state.set(mode="ball")
        self.state.save()

    def to_expanded(self) -> None:
        if self.mode == "expanded" or self.anim:
            return
        if self.side:
            left, top, right, bottom = self._work()
            pw, ph = self._panel_size()
            self.panel_pos = (left if self.side == "left" else right - pw,
                              min(max(self.panel_pos[1], top), bottom - ph))
        self._animate("expanded")
        self.state.set(mode="expanded", panel_x=int(self.panel_pos[0]),
                       panel_y=int(self.panel_pos[1]))
        self.state.save()
        self._last_leave = time.perf_counter()

    def to_sliver(self) -> None:
        if self.mode != "expanded" or self.anim or not self.side:
            return
        self._animate("sliver", dur_ms=int(T.ANIM_MS * 0.85))

    # ------------------------------------------------------------ 鼠标

    def _hit_at(self, logical_x: float, logical_y: float) -> Optional[Dict]:
        for h in self.hits:
            x0, y0, x1, y1 = h["rect"]
            if x0 <= logical_x <= x1 and y0 <= logical_y <= y1:
                return h
        return None

    def _on_down(self, cx: int, cy: int) -> None:
        k = self.k
        hit = self._hit_at(cx / k, cy / k)
        self._press = {"x": cx, "y": cy, "win": (self.win_rect[0], self.win_rect[1]),
                       "hit": hit, "dragging": False}
        win32.user32.SetCapture(self.win.hwnd)

    def _on_move(self, cx: int, cy: int) -> None:
        p = self._press
        if p and (win32.user32.GetCapture() == self.win.hwnd):
            dx, dy = cx - p["x"], cy - p["y"]
            if not p["dragging"] and abs(dx) + abs(dy) > 4:
                p["dragging"] = True
                self.dragging = True
                self._hover_clear()
                self.render(ss=1)  # 拖动中用实底，关掉磨砂
            if p["dragging"]:
                self.win.move(p["win"][0] + dx, p["win"][1] + dy)
                self.win_rect = (p["win"][0] + dx, p["win"][1] + dy,
                                 self.win_rect[2], self.win_rect[3])
            return

        k = self.k
        hit = self._hit_at(cx / k, cy / k)
        idx = hit["index"] if hit and hit["kind"] == "card" else -1
        key = hit["kind"] if hit and hit["kind"] in ("collapse", "footer", "ball") else ""
        if (idx, key) != (self.hover, self.hover_key):
            self.hover, self.hover_key = idx, key
            win32.user32.SetCursor(win32.cursor(hand=bool(hit)))
            if not self.anim:
                self.render(ss=1)

    def _hover_clear(self) -> None:
        if self.hover != -1 or self.hover_key:
            self.hover, self.hover_key = -1, ""
            win32.user32.SetCursor(win32.cursor(False))

    def _on_up(self, cx: int, cy: int) -> None:
        win32.user32.ReleaseCapture()
        p, self._press = self._press, None
        if not p:
            return
        if p["dragging"]:
            self.dragging = False
            self._finish_drag()
            return

        hit = self._hit_at(cx / self.k, cy / self.k)
        if not hit:
            return
        kind = hit["kind"]
        now = time.perf_counter()
        if kind == "collapse":
            self.to_ball()
        elif kind == "footer":
            self.done_expanded = not self.done_expanded
            self.state.set(done_expanded=self.done_expanded)
            self.state.save()
            self.render(ss=2)
        elif kind == "card":
            self._open_report(hit.get("card") or {})
        elif kind == "ball":
            if self._suppress_up:
                # 双击序列里的第二次抬起，别再排一次展开
                self._suppress_up = False
                return
            if self._ball_click_job is not None:
                # 第二击：双击
                self._ball_click_job = None
                self._open_report(None)
            else:
                self._ball_click_job = now

    def _finish_drag(self) -> None:
        x, y, w, h = self.win_rect
        k = self.k
        left, top, right, bottom = win32.monitor_work_rect(int(x + w / 2), int(y + h / 2))
        margin = T.PANEL_MARGIN * k if self.mode == "expanded" else T.BALL_MARGIN * k
        px, py = x + margin, y + margin
        pw, ph = (self._panel_size() if self.mode == "expanded" else (T.BALL * k,) * 2)

        self.side = ""
        snap = T.SNAP_DIST * k
        if px - left <= snap:
            self.side = "left"
            px = left
        elif right - (px + pw) <= snap:
            self.side = "right"
            px = right - pw
        px = min(max(px, left), max(left, right - pw))
        py = min(max(py, top), max(top, bottom - ph))
        self.panel_pos = (px, py)
        self.state.set(panel_x=int(px), panel_y=int(py), side=self.side)
        self.state.save()

        target = self._rect_for(self.mode)
        self.anim = None
        self._apply_rect(target, paint=False)
        self._last_backdrop = 0.0
        self._refresh_backdrop(force=True)
        self.render(ss=2)
        self._last_leave = time.perf_counter()

    # ------------------------------------------------------------ 动作

    def _open_report(self, card) -> None:
        path = self.store.report_path(card) if card else self.store.latest_report()
        if not path:
            return
        try:
            os.startfile(str(path))  # noqa: S606
        except Exception:
            pass

    def reload_data(self) -> None:
        if self.store.load():
            self._last_backdrop = 0.0
            self.render(ss=2)

    # ------------------------------------------------------------ 计时器

    def _on_idle(self) -> None:
        now = time.perf_counter()
        if now - self._last_topmost > 1.0:
            self._last_topmost = now
            self.win.topmost()

        if now - self._last_data > T.DATA_POLL_MS / 1000.0:
            self._last_data = now
            if self.store.load() and not self.anim:
                self.render(ss=2)

        if (self.mode == "expanded" and not self.anim and not self.dragging
                and now - self._last_backdrop > T.BACKDROP_MS / 1000.0):
            self._last_backdrop = now
            if self._refresh_backdrop():
                self.render(ss=2)

        self._poll_cursor(now)

        if self._ball_click_job is not None and now - self._ball_click_job > 0.28:
            self._ball_click_job = None
            if self.mode == "ball":
                self.to_expanded()

    def _poll_cursor(self, now: float) -> None:
        if self.anim or self.dragging or not self.running:
            return
        cx, cy = win32.cursor_pos()
        x, y, w, h = self.win_rect
        inside = x <= cx <= x + w and y <= cy <= y + h

        if not inside and (self.hover != -1 or self.hover_key):
            self._hover_clear()
            self.render(ss=1)

        if self.mode == "sliver":
            pad = T.SLIVER_HOVER_PAD * self.k
            if x - pad <= cx <= x + w + pad and y - pad <= cy <= y + h + pad:
                self.to_expanded()
            return

        if self.mode == "expanded":
            if inside:
                self._inside = True
                self._last_leave = now
                return
            if self._inside:
                self._inside = False
                self._last_leave = now
            if self.side and (now - self._last_leave) * 1000 >= T.HIDE_DELAY_MS:
                self.to_sliver()

    # ------------------------------------------------------------ 窗口过程

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32.WM_MOUSEMOVE:
            cx, cy = _xy(lparam)
            self._on_move(cx, cy)
            return True, 0
        if msg == win32.WM_LBUTTONDOWN:
            cx, cy = _xy(lparam)
            self._on_down(cx, cy)
            return True, 0
        if msg == win32.WM_LBUTTONUP:
            cx, cy = _xy(lparam)
            self._on_up(cx, cy)
            return True, 0
        if msg == win32.WM_LBUTTONDBLCLK:
            if self.mode == "ball":
                self._ball_click_job = None
                self._suppress_up = True
                self._open_report(None)
            return True, 0
        if msg == win32.WM_RBUTTONUP:
            self._context_menu()
            return True, 0
        if msg == win32.WM_TIMER:
            if wparam == TID_FRAME:
                if self.anim:
                    self._anim_frame()
                return True, 0
            if wparam == TID_IDLE:
                self._on_idle()
                return True, 0
        if msg == win32.WM_NCHITTEST:
            # 投影留白（几乎全透明）处让点击穿透到桌面
            sx, sy = _xy(lparam)
            cx = int(sx - self.win_rect[0])
            cy = int(sy - self.win_rect[1])
            if self._alpha_at(cx, cy) < 16:
                return True, win32.HTTRANSPARENT
            return True, win32.HTCLIENT
        if msg == win32.WM_PAINT:
            return True, 0
        if msg == win32.WM_DISPLAYCHANGE:
            self._last_backdrop = 0.0
            self._refresh_backdrop(force=True)
            self.render(ss=2)
            return True, 0
        if msg == win32.WM_DPICHANGED:
            self.k = win32.window_scale(hwnd)
            self.anim = None
            self._apply_rect(self._rect_for(self.mode), paint=False)
            self._refresh_backdrop(force=True)
            self.render(ss=2)
            return True, 0
        if msg in (win32.WM_CLOSE, win32.WM_DESTROY):
            self.running = False
            self.state.set(mode=self.mode, side=self.side,
                           panel_x=int(self.panel_pos[0]), panel_y=int(self.panel_pos[1]))
            self.state.save()
            self.win.destroy()
            win32.post_quit()
            return True, 0
        if msg == win32.WM_ENDSESSION or msg == win32.WM_QUERYENDSESSION:
            self.state.save()
            return False, 0
        return False, 0

    def _context_menu(self) -> None:
        cx, cy = win32.cursor_pos()
        toggle_label = "展开面板" if self.mode != "expanded" else "收起成球"
        items = [(MENU_REPORT, "打开最新报告"), (MENU_RELOAD, "重新读取数据"), None,
                 (MENU_TOGGLE, toggle_label), (MENU_QUIT, "退出")]
        cmd = win32.popup_menu(self.win.hwnd, cx, cy, items)
        if cmd == MENU_REPORT:
            self._open_report(None)
        elif cmd == MENU_RELOAD:
            self.reload_data()
        elif cmd == MENU_TOGGLE:
            if self.mode == "expanded":
                self.to_ball()
            else:
                self.to_expanded()
        elif cmd == MENU_QUIT:
            self._wndproc(self.win.hwnd, win32.WM_CLOSE, 0, 0)

    def run(self) -> None:
        win32.message_loop()
        try:
            self.state.save()
        except Exception:
            pass


# ------------------------------------------------------------------ 缩略指纹

def _thumb(img: Image.Image) -> bytes:
    return img.convert("L").resize((24, 24), Image.BILINEAR).tobytes()


# ------------------------------------------------------------------ 演示数据

def _demo_payload() -> Dict:
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "groups": 6,
        "total_messages": 86,
        "report_dir": "",
        "cards": [
            {"group": "示例项目群", "title": "收齐本周进度表并汇总",
             "priority": "紧急", "source": "张经理 08:31", "owner": "项目助理", "due": "今天 18:00",
             "done": False, "report": ""},
            {"group": "部门周会群", "title": "本周例会材料提交到行政",
             "priority": "紧急", "source": "王老师 09:13", "owner": "轮值人", "due": "周三 12:00",
             "done": False, "report": ""},
            {"group": "校园兼职群", "title": "确认下周排班表并回复到群里",
             "priority": "重要", "source": "周同学 10:02", "owner": "未指定", "due": "周四",
             "done": False, "report": ""},
            {"group": "学习小组", "title": "整理本周学习记录上传系统",
             "priority": "重要", "source": "李同学 14:20", "owner": "记录员", "due": "周五 17:00",
             "done": False, "report": ""},
            {"group": "宿舍群", "title": "公共区域卫生分工确认",
             "priority": "常规", "source": "赵同学 20:40", "owner": "全员", "due": "无明确截止",
             "done": False, "report": ""},
            {"group": "示例项目群", "title": "统计本周任务完成率",
             "priority": "常规", "source": "张经理 16:05", "owner": "项目助理", "due": "周日",
             "done": False, "report": ""},
            {"group": "部门周会群", "title": "上次的会议室申请已经批下来了",
             "priority": "常规", "source": "王老师 11:02", "owner": "轮值人", "due": "无明确截止",
             "done": True, "report": ""},
        ],
    }
