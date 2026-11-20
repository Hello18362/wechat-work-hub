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

import math
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageFilter

from . import render, theme as T, win32
from .geom import (clamp_to_work, hover_pad_hit, panel_pos_from_box, snap_x,
                   visible_box)
from .store import CardStore, DoneStore, WidgetState, card_key

TID_FRAME = 1
TID_IDLE = 2

MENU_REPORT = 1001
MENU_RELOAD = 1002
MENU_TOGGLE = 1003
MENU_QUIT = 1004

MODES = ("expanded", "ball", "sliver")
CARD_DUMP = __import__("pathlib").Path(os.environ.get("LOCALAPPDATA") or ".") / "WeChatWorkHub" / "paint.png"

DEBUG = os.environ.get("WIDGET_DEBUG") == "1"
DUMP = os.environ.get("WIDGET_DUMP") == "1"


def _dbg(*parts) -> None:
    """WIDGET_DEBUG=1 时把关键事件写进 %LOCALAPPDATA%\\WeChatWorkHub\\widget.log"""
    if not DEBUG:
        return
    try:
        from .store import APP_DIR, ensure_dir
        ensure_dir()
        with open(APP_DIR / "widget.log", "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%H:%M:%S ") + " ".join(str(p) for p in parts) + "\n")
    except Exception:
        pass


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
        # 一律以展开态启动：以前会恢复上次的 ball/sliver，
        # 而那个状态往往是自动收缩留下的，重启后用户就找不到卡片了。
        self.mode = start_mode or "expanded"
        if self.mode not in MODES:
            self.mode = "expanded"
        self.side = self.state.get("side") or ""
        self.done_expanded = bool(self.state.get("done_expanded"))

        self.backdrop: Optional[Image.Image] = None
        self._backdrop_key = None
        self._bd_rect = None
        self._bd_time = 0.0
        self._prewarm_stamp = None
        self._bd_seq = 0
        self.hits: List[Dict] = []
        self.hover = -1
        self.hover_key = ""
        self.dragging = False
        self._drag: Optional[Dict] = None
        self._press: Optional[Dict] = None
        self.anim: Optional[Dict] = None
        self._last_leave = time.perf_counter()   # 启动时先给满延迟，别一开机就缩成细条
        self._inside = True
        self._last_data = time.perf_counter()
        self._last_backdrop = 0.0
        self._last_topmost = 0.0
        self.done = DoneStore()
        self._fly = None
        self.scroll = 0.0
        self.scroll_target = 0.0
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

        self._shown = False
        self._refresh_backdrop(force=True)   # 窗口此刻还没显示，抓到的是干净桌面
        self.render(ss=1)
        self.win.show()
        self._shown = True
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

    def _visible_box(self, rect=None) -> Tuple[float, float, float, float]:
        """当前形态在屏幕上真正看得见的矩形（不含投影留白）。"""
        return visible_box(self.mode, rect or self.win_rect, self.k)

    def _ensure_on_screen(self) -> bool:
        """可见矩形跑出工作区就夹回来；返回是否动过位置。

        启动时和拖拽结束后都调一次——用户把窗口拖到屏幕外，或者旧版本
        把位置存歪了，都能靠这里救回来，不用重装。
        """
        box = self._visible_box()
        work = self._work()
        x, y, w, h = clamp_to_work(box, work)
        if (x, y) == (box[0], box[1]):
            return False
        self.panel_pos = panel_pos_from_box(self.mode, (x, y, w, h), self.k)
        self.state.set(panel_x=int(self.panel_pos[0]), panel_y=int(self.panel_pos[1]))
        self.state.save()
        _dbg("rescue", "box", box, "->", (x, y, w, h), "panel", self.panel_pos)
        return True

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
        if self._ensure_on_screen():
            self.win_rect = self._rect_for(self.mode)

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

    def _view_cards(self):
        out = []
        for c in self.store.cards():
            c = dict(c)
            if self.done.is_done(c):
                c["done"] = True
            out.append(c)
        return out

    def _view_state(self, drag: bool = False) -> Dict:
        cards = self._view_cards()
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
            "scroll": self.scroll,
        }

    def _render_image(self, ss: int = 2, fast: bool = False) -> Image.Image:
        st = self._view_state(drag=False)
        bkey = self._bd_seq
        if self.mode == "expanded":
            img, hits = render.draw_panel(st, self.k, self.backdrop, ss=ss,
                                          fast=fast, bkey=bkey)
        elif self.mode == "ball":
            img, hits = render.draw_ball(st, self.k, self.backdrop, ss=ss,
                                         fast=fast, bkey=bkey)
        else:
            img, hits = render.draw_sliver(st, self.k, self.backdrop, ss=ss,
                                           fast=fast, bkey=bkey)
        self.hits = hits
        return img

    def render(self, ss: int = 2) -> None:
        img = self._render_image(ss=ss)
        x, y, w, h = self.win_rect
        self.win_rect = (x, y, img.width, img.height)
        self._paint(img, x, y)

    def _paint(self, img: Image.Image, x: float, y: float) -> None:
        self._last_img = img
        if DUMP:
            try:
                img.save(str(CARD_DUMP))
            except Exception:
                pass
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

    def _refresh_backdrop(self, force: bool = False, rect=None, hide=None) -> bool:
        """抓一次窗口背后的桌面；和上次差异很小就跳过，省 CPU。"""
        if self.mode == "sliver":
            return False
        if rect is None:
            x, y, w, h = self.win_rect
            rect = (int(x), int(y), int(w), int(h))
        else:
            rect = tuple(int(v) for v in rect)
        # 必须抓**整个窗口**（含投影留白），否则模糊图会被平移一个 margin 贴上去
        if rect[2] < 8 or rect[3] < 8:
            return False
        # BitBlt 会把我们自己的分层窗口一起抓进去。不先 hide 就抓，
        # 等于把自己的半透明面板又压暗一遍，每轮再抓自己 → 滚雪球变成实心黑块。
        # 展开动画前抓屏时窗口还是小球，只挡一小块，没必要 hide（避免闪一下）
        do_hide = getattr(self, "_shown", False) if hide is None else bool(hide and getattr(self, "_shown", False))
        was_visible = getattr(self, "_shown", False)
        if do_hide:
            self.win.hide()
        try:
            shot = win32.capture(*rect)
        except Exception:
            shot = None
        finally:
            if do_hide:
                self.win.show()
                self.win.topmost()
        if shot is None:
            return False
        key = (rect, _thumb(shot))
        if not force and key == self._backdrop_key:
            return False
        self._backdrop_key = key
        self.backdrop = shot
        self._bd_rect = rect
        self._bd_time = time.perf_counter()
        self._bd_seq += 1
        return True

    # ------------------------------------------------------------ 动画

    def _animate(self, to_mode: str, dur_ms: int = T.ANIM_MS,
                 on_done=None) -> None:
        _prep0 = time.perf_counter()
        to_rect = self._rect_for(to_mode)
        # 目标比当前大（球 -> 面板）时，先按目标尺寸抓一张干净背景，
        # 否则会把 96x96 的小图拉成整屏，糊成一片
        if to_rect[2] * to_rect[3] > self.win_rect[2] * self.win_rect[3] * 1.2:
            need = (self._bd_rect != tuple(int(v) for v in to_rect)
                    or time.perf_counter() - self._bd_time > 6)
            if need:
                self._refresh_backdrop(force=True, rect=to_rect, hide=False)
        from_img = self._render_image(ss=1)
        prev_mode, prev_rect = self.mode, self.win_rect

        self.mode = to_mode  # 先切换，才能渲染目标图
        to_img = self._render_image(ss=1)
        self.mode = prev_mode
        self.win_rect = prev_rect

        self.anim = {
            "_t": [],
            "from": prev_rect,
            "to": to_rect,
            "from_img": from_img,
            "to_img": to_img,
            "to_mode": to_mode,
            "t0": time.perf_counter(),
            "dur": max(0.08, dur_ms / 1000.0),
            "on_done": on_done,
        }
        _dbg("anim start", prev_mode, "->", to_mode,
             "prep %.0fms" % ((time.perf_counter() - _prep0) * 1000))
        self._flush_timers()

    def _anim_frame(self) -> None:
        a = self.anim
        now = time.perf_counter()
        t = (now - a["t0"]) / a["dur"]
        e = T.spring(t)                      # 统一手感曲线，带一点点回弹
        rect = T.lerp_rect(a["from"], a["to"], e)
        w, h = max(1, int(round(rect[2]))), max(1, int(round(rect[3])))
        x, y = int(round(rect[0])), int(round(rect[1]))

        # 每帧只做 C 层运算：两次 resize + 一次 blend。
        # 绝对不能用 .point(lambda)：那是逐像素跑 Python，一帧几十毫秒，必卡。
        _t0 = time.perf_counter() if DEBUG else 0.0
        fi = a["from_img"].resize((w, h), Image.BILINEAR)
        # 退场那一侧随进度变糊：文字化开，读不出内容，像失焦转移而不是两个画面互相透
        if e < 0.999:
            fi = fi.filter(ImageFilter.GaussianBlur(0.4 + 3.2 * e * (1.0 if w > 160 else 0.6)))
        ti = a["to_img"].resize((w, h), Image.BILINEAR)
        # 透明度曲线分开给：起点快速退场（(1-e)^2），终点提前登场（e^0.5）。
        # 直接用 max(fi, ti) 保不透明 → 面板缩到球大小那几帧是「缩小的黑色方块」（黑框）；
        # 两边都线性插值 → 中途两个画面叠着发浑。分开给两边都躲开。
        k_in = min(1.0, max(0.0, e))
        down = [int(v * (1 - k_in) ** 2) for v in range(256)]
        up = [min(255, int(v * (k_in ** 0.5))) for v in range(256)]
        canvas = Image.blend(fi, ti, k_in)
        canvas.putalpha(ImageChops.lighter(fi.getchannel("A").point(down),
                                          ti.getchannel("A").point(up)))
        if DEBUG:
            a["_t"].append((time.perf_counter() - _t0) * 1000)

        self.win_rect = (x, y, w, h)
        win32.user32.SetWindowPos(self.win.hwnd, None, x, y, w, h,
                                  win32.SWP_NOZORDER | win32.SWP_NOACTIVATE)
        self._paint(canvas, x, y)

        if t >= 1.0:
            done = a["on_done"]
            self.mode = a["to_mode"]
            self.anim = None
            self.render(ss=1)      # 用缓存的玻璃，立刻出图，不阻塞
            self._flush_timers()
            if DEBUG and a.get("_t"):
                ms = a["_t"]
                _dbg("anim done", self.mode, "frames", len(ms),
                     "avg %.1fms" % (sum(ms) / len(ms)), "max %.1fms" % max(ms))
            if done:
                done()

    def _flush_timers(self) -> None:
        if not self.anim and abs(self.scroll_target - self.scroll) < 0.4:
            self.scroll = self.scroll_target
        if self.anim or self._fly or abs(self.scroll_target - self.scroll) >= 0.4:
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
        _dbg("to_expanded called mode=%s anim=%s" % (self.mode, bool(self.anim)))
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

    def to_sliver(self, auto: bool = False) -> None:
        if self.mode != "expanded" or self.anim:
            return
        if not self.side:
            if not auto:
                return
            # 自动收缩时选离面板更近的那条边，不要生硬地一律贴右侧
            left, top, right, bottom = self._work()
            pw, _ph = self._panel_size()
            self.side = ("left" if self.panel_pos[0] + pw / 2 < (left + right) / 2
                         else "right")
            self.state.set(side=self.side)
            self.state.save()
        self._animate("sliver", dur_ms=int(T.ANIM_MS * 0.85))
        self.state.set(mode="sliver")
        self.state.save()

    # ------------------------------------------------------------ 鼠标

    def _hit_at(self, logical_x: float, logical_y: float) -> Optional[Dict]:
        for h in self.hits:
            x0, y0, x1, y1 = h["rect"]
            if x0 <= logical_x <= x1 and y0 <= logical_y <= y1:
                return h
        return None

    def _on_down(self, cx: int, cy: int) -> None:
        k = self.k
        if self.anim:
            # 形变动画进行中的命中区还是上一形态的，容易误触，这一下点击直接丢掉
            return
        hit = self._hit_at(cx / k, cy / k)
        sx, sy = win32.cursor_pos()
        self._press = {"sx": sx, "sy": sy,
                       "win": (self.win_rect[0], self.win_rect[1]),
                       "hit": hit, "dragging": False}
        win32.user32.SetCapture(self.win.hwnd)

    def _on_move(self, cx: int, cy: int) -> None:
        p = self._press
        if p:
            if not win32.user32.GetCapture():
                # 丢了鼠标捕获，别把按下状态留成脏数据
                self._press = None
                if self.dragging:
                    self.dragging = False
                    self.render(ss=1)
            else:
                # 拖拽必须用**屏幕**坐标：窗口跟着动，客户区坐标会自我反馈
                sx, sy = win32.cursor_pos()
                dx, dy = sx - p["sx"], sy - p["sy"]
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
        # 细条上不等到 100ms 轮询：鼠标一碰到就立刻展开
        if self.mode == "sliver" and hit and hit.get("kind") == "sliver":
            self.to_expanded()
            return
        idx = hit["index"] if hit and hit["kind"] == "card" else -1
        key = hit["kind"] if hit and hit["kind"] in ("collapse", "ball",
                                                     "check", "archive") else ""
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
        _dbg("up", hit["kind"] if hit else None)
        # 在细条上按下就松开：直接展开。此时面板已经弹开，
        # 不能再用「松开瞬间的命中区」派发，否则会误触刚展开的卡片。
        if (p.get("hit") or {}).get("kind") == "sliver":
            self.to_expanded()
            return
        if not hit:
            return
        kind = hit["kind"]
        now = time.perf_counter()
        if kind == "collapse":
            self.to_ball()
        elif kind == "archive":
            self.done_expanded = not self.done_expanded
            self.state.set(done_expanded=self.done_expanded)
            self.state.save()
            self.render(ss=1)
        elif kind == "check":
            self._complete_card(hit.get("card") or {})
        elif kind == "card":
            if hit.get("card", {}).get("done"):
                self._restore_card(hit.get("card") or {})
            else:
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
        """松手：按「看得见的那块」吸边、夹进工作区，再换回 panel 坐标。

        旧实现按留白矩形 + 小球尺寸算，右吸边后小球会被推出屏幕 300 多像素，
        这正是「缩成小球再拖一下就再也叫不出来」的原因。
        """
        k = self.k
        x, y, w, h = self.win_rect
        work = win32.monitor_work_rect(int(x + w / 2), int(y + h / 2))
        box = self._visible_box()
        sx, side = snap_x(box, work, T.SNAP_DIST * k)
        box = clamp_to_work((sx, box[1], box[2], box[3]), work)
        self.panel_pos = panel_pos_from_box(self.mode, box, k)
        self.side = side
        _dbg("drag end", "box", box, "panel", self.panel_pos, "side", side, "mode", self.mode)
        self.state.set(panel_x=int(self.panel_pos[0]), panel_y=int(self.panel_pos[1]),
                       side=side)
        self.state.save()

        target = self._rect_for(self.mode)
        self.anim = None
        self._apply_rect(target, paint=False)
        self._last_backdrop = 0.0
        self._refresh_backdrop(force=True)
        self.render(ss=1)
        self._last_leave = time.perf_counter()

    # ------------------------------------------------------------ 动作

    def _open_report(self, card) -> None:
        path = self.store.report_path(card) if card else self.store.latest_report()
        if not path:
            return
        try:
            os.startfile(str(path))  # noqa: S606
        except Exception:
            return
        # 报告已经在浏览器里打开了，小窗自己让开：自动收成玻璃球
        if self.mode == "expanded" and not self.anim:
            self.to_ball()

    def reload_data(self) -> None:
        if self.store.load():
            self._last_backdrop = 0.0
            self.render(ss=1)

    # ------------------------------------------------------------ 滚轮

    def _prewarm_expanded(self) -> None:
        """球形态空闲时，先把「展开态那块玻璃」生成好。

        否则点球展开时要在动画开始前现抓背景 + 现算整块玻璃（约 70ms），
        点下去会明显顿一下。预热之后展开的准备只要十几毫秒。
        """
        stamp = (self.panel_pos, self.k)
        try:
            rect = self._rect_for("expanded")
            self._refresh_backdrop(force=True, rect=rect, hide=False)
            render.frost(T.PANEL_W + T.PANEL_MARGIN * 2, T.PANEL_H + T.PANEL_MARGIN * 2,
                         T.PANEL_MARGIN, T.PANEL_RADIUS, self.k, self.backdrop,
                         False, 1, False, self._bd_seq)
            self._prewarm_stamp = stamp      # 位置不变就不再重复预热
        except Exception as exc:  # noqa: BLE001
            self._prewarm_stamp = stamp
            _dbg("prewarm failed: %s" % exc)

    def _max_scroll(self) -> float:
        rows, content_h = render.layout_cards(self._view_cards(), False)
        return max(0.0, content_h - (T.CARDS_BOTTOM - T.CARDS_TOP))

    def scroll_by(self, dy: float) -> None:
        if self.mode != "expanded" or self.anim:
            return
        top = self._max_scroll()
        self.scroll_target = min(max(0.0, self.scroll_target + dy), top)
        if abs(self.scroll_target - self.scroll) > 0.3:
            self._flush_timers()

    def _rect_of(self, kind: str, card) -> Optional[Tuple[float, float, float, float]]:
        key = card_key(card)
        for h in self.hits:
            if h["kind"] == kind and card_key(h.get("card") or {}) == key:
                return h["rect"]
        return None

    def _rect_of_first(self, kind: str) -> Optional[Tuple[float, float, float, float]]:
        for h in self.hits:
            if h["kind"] == kind:
                return h["rect"]
        return None

    def _complete_card(self, card) -> None:
        """把任务标成完成：卡片缩小飞进列表底部的归档栏。"""
        if not card:
            return
        from_rect = self._rect_of("card", card)
        src = None
        if from_rect and self._last_img is not None:
            k = self.k
            box = tuple(int(round(v * k)) for v in from_rect)
            w = max(1, min(self._last_img.width - box[0], box[2] - box[0]))
            h = max(1, min(self._last_img.height - box[1], box[3] - box[1]))
            try:
                src = self._last_img.crop((box[0], box[1], box[0] + w, box[1] + h))
            except Exception:
                src = None

        self.done.mark(card)
        self.scroll_target = min(self.scroll_target, self._max_scroll())
        self.render(ss=1)

        to_rect = self._rect_of_first("archive")
        _dbg("complete", "from", from_rect, "to", to_rect, "src", src.size if src else None)
        if src is not None and from_rect and to_rect:
            # t0 留空，等第一帧真正执行时再起算——否则前面被消息队列堵掉的时间
            # 会白白吃掉动画进度，看起来就像"没有动画"
            self._fly = {"img": src, "from": from_rect, "to": to_rect,
                         "t0": None, "dur": 0.30}
            self._flush_timers()
        else:
            self._flush_timers()

    def _restore_card(self, card) -> None:
        """点迷你卡：任务恢复成未完成，回到列表里。"""
        if not card:
            return
        self.done.unmark(card)
        self.render(ss=1)
        self._flush_timers()

    def _fly_frame(self) -> None:
        f = self._fly
        now = time.perf_counter()
        if f["t0"] is None:
            f["t0"] = now
        t = (now - f["t0"]) / f["dur"]
        e = T.spring(t)
        k = self.k
        fx, fy, fw, fh = f["from"]
        tx, ty, tw, th = f["to"]
        x = T.lerp(fx, tx, e)
        y = T.lerp(fy, ty, e) - math.sin(math.pi * min(1.0, max(0.0, t))) * 10
        w = T.lerp(fw, tw, e)
        h = T.lerp(fh, th, e)

        img = self._render_image(ss=1)
        pw, ph = max(1, int(w * k)), max(1, int(h * k))
        piece = f["img"].resize((pw, ph), Image.BILINEAR)
        if e > 0.78:
            # 最后一段才淡出，让迷你卡接管；太早淡会像卡没飞过去就消失了
            a = max(0.0, 1.0 - (e - 0.78) / 0.22)
            piece.putalpha(piece.getchannel("A").point([int(v * a) for v in range(256)]))
        img.alpha_composite(piece, (int(x * k), int(y * k)))
        self._paint(img, self.win_rect[0], self.win_rect[1])

        if t >= 1.0:
            self._fly = None
            self.render(ss=1)
            self._flush_timers()

    def _scroll_frame(self) -> None:
        d = self.scroll_target - self.scroll
        if abs(d) < 0.4:
            self.scroll = self.scroll_target
            self.render(ss=1)
            self._flush_timers()
            return
        # 指数追随 + 最小步长，滚起来是"惯性滑一段再停"的手感
        self.scroll += d * T.SCROLL_EASE
        self.render(ss=1)

    # ------------------------------------------------------------ 计时器

    def _on_idle(self) -> None:
        now = time.perf_counter()
        if now - self._last_topmost > 1.0:
            self._last_topmost = now
            self.win.topmost()

        if now - self._last_data > T.DATA_POLL_MS / 1000.0:
            self._last_data = now
            if self.store.load() and not self.anim:
                self.render(ss=1)

        # 空闲时不再定时重抓：每次重抓都得 hide/show，会闪，而且完全没必要
        if (self.mode == "ball" and not self.anim and not self.dragging
                and self._prewarm_stamp != (self.panel_pos, self.k)):
            self._prewarm_expanded()

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
            if hover_pad_hit(self.win_rect, cx, cy, pad):
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
            # 用户要求：鼠标点击其他区域（离开面板）几秒后，自动收成右侧细条；
            # 鼠标移到细条上会重新展开（悬停逻辑在 sliver 分支）。
            if now - self._last_leave > T.HIDE_DELAY_MS / 1000.0:
                self.to_sliver(auto=True)

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
        if msg == win32.WM_MOUSEWHEEL:
            delta = (wparam >> 16) & 0xFFFF
            if delta >= 0x8000:
                delta -= 0x10000
            self.scroll_by(-delta / 120.0 * T.SCROLL_STEP)
            return True, 0
        if msg == win32.WM_RBUTTONUP:
            self._context_menu()
            return True, 0
        if msg == win32.WM_TIMER:
            if wparam == TID_FRAME:
                if self.anim:
                    self._anim_frame()
                elif self._fly:
                    self._fly_frame()
                else:
                    self._scroll_frame()
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
            self.render(ss=1)
            return True, 0
        if msg == win32.WM_DPICHANGED:
            self.k = win32.window_scale(hwnd)
            self.anim = None
            self._apply_rect(self._rect_for(self.mode), paint=False)
            self._refresh_backdrop(force=True)
            self.render(ss=1)
            return True, 0
        if msg in (win32.WM_CLOSE, win32.WM_DESTROY):
            self.running = False
            self.state.set(mode=self.mode, side=self.side,
                           panel_x=int(self.panel_pos[0]), panel_y=int(self.panel_pos[1]))
            self.state.save()
            self.win.destroy()
            win32.timer_resolution(False)
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
