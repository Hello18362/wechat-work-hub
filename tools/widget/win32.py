# -*- coding: utf-8 -*-
"""Win32 底层封装：DPI、分层窗口、桌面取景、光标与菜单。

只用 ctypes，无第三方依赖（Pillow 仅用于图像对象）。

设计要点：
- 窗口用 WS_EX_LAYERED + UpdateLayeredWindow，内容是一张带 alpha 的整图，
  因此圆角、柔和投影、逐像素半透明全部由 Pillow 画，不依赖 SetWindowRgn（会有锯齿）。
- 进程先声明 per-monitor v2 DPI 感知，之后所有坐标都是**物理像素**，
  位图和绘制尺寸一致，字不会被系统二次缩放。
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, sizeof
from ctypes import wintypes

from PIL import Image

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

# ------------------------------------------------------------------ 常量

WS_POPUP = 0x80000000
CS_DBLCLKS = 0x0008
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = -1

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
DIB_RGB_COLORS = 0
BI_RGB = 0
SRCCOPY = 0x00CC0020

WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_TIMER = 0x0113
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_MOUSEWHEEL = 0x020A
WM_MOUSELEAVE = 0x02A3
WM_SETCURSOR = 0x0020
WM_DISPLAYCHANGE = 0x007E
WM_DPICHANGED = 0x02E0
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
HTCLIENT = 1

IDC_ARROW = 32512
IDC_HAND = 32649

SPI_GETWORKAREA = 0x0030
MONITOR_DEFAULTTONEAREST = 2

WCA_ACCENT_POLICY = 19
ACCENT_DISABLED = 0
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_AUTO = 0
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2
DWMSBT_TRANSIENTWINDOW = 3

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_GRAYED = 0x00000001
TPM_LEFTALIGN = 0x0000
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080


# ------------------------------------------------------------------ 结构体

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", WPARAM), ("lParam", LPARAM),
                ("time", wintypes.DWORD), ("pt", POINT)]


class ACCENTPOLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t)]


# ------------------------------------------------------------------ 函数签名

user32.RegisterClassExW.argtypes = [POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [POINTER(MSG)]
user32.DispatchMessageW.argtypes = [POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.GetCursorPos.argtypes = [POINTER(POINT)]
user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, POINTER(MONITORINFO)]
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.SetCursor.argtypes = [wintypes.HANDLE]
user32.SetCapture.argtypes = [wintypes.HWND]
user32.SetCapture.restype = wintypes.HWND
user32.GetCapture.argtypes = []
user32.GetCapture.restype = wintypes.HWND
user32.ReleaseCapture.argtypes = []
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                         wintypes.LPVOID, wintypes.UINT]
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, POINTER(POINT), POINTER(SIZE),
    wintypes.HDC, POINTER(POINT), wintypes.COLORREF,
    POINTER(BLENDFUNCTION), wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t,
                               wintypes.LPCWSTR]
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                  wintypes.LPVOID]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, POINTER(BITMAPINFO), wintypes.UINT,
                                   POINTER(ctypes.c_void_p), wintypes.HANDLE,
                                   wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                         wintypes.DWORD]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                            wintypes.UINT, wintypes.LPVOID, POINTER(BITMAPINFO),
                            wintypes.UINT]

dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                         wintypes.LPVOID, wintypes.DWORD]


# ------------------------------------------------------------------ DPI

def enable_dpi_awareness() -> None:
    """声明 per-monitor v2 感知。必须在建窗口前调用。"""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctx = ctypes.c_void_p(-4)
        if user32.SetProcessDpiAwarenessContext(ctx):
            return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def window_scale(hwnd: int) -> float:
    """窗口所在显示器的缩放系数（1.0 = 96dpi）。"""
    try:
        dpi = user32.GetDpiForWindow(hwnd) or 96
    except Exception:
        dpi = 96
    return max(1.0, dpi / 96.0)


def monitor_work_rect(x: int, y: int) -> tuple[int, int, int, int]:
    """给定屏幕点所在显示器的工作区（排除任务栏），物理像素。"""
    mon = user32.MonitorFromPoint(POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = sizeof(MONITORINFO)
    if user32.GetMonitorInfoW(mon, byref(info)):
        r = info.rcWork
        return (r.left, r.top, r.right, r.bottom)
    r = RECT()
    if user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, byref(r), 0):
        return (r.left, r.top, r.right, r.bottom)
    return (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def screen_size() -> tuple[int, int]:
    return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def cursor_pos() -> tuple[int, int]:
    p = POINT()
    user32.GetCursorPos(byref(p))
    return (p.x, p.y)


_cursors = {}


def cursor(hand: bool = False):
    key = bool(hand)
    if key not in _cursors:
        _cursors[key] = user32.LoadCursorW(None, ctypes.cast(IDC_HAND if hand else IDC_ARROW,
                                                              wintypes.LPCWSTR))
    return _cursors[key]


# ------------------------------------------------------------------ 分层窗口

class LayeredWindow:
    """一个无边框、置顶、逐像素半透明的窗口。

    内容完全由外部传入的 RGBA 整图决定（UpdateLayeredWindow），
    窗口自身不参与绘制，因此不会闪。
    """

    _class_atom = None
    _class_name = "WeChatWorkHubWidget"

    def __init__(self, w: int, h: int, wndproc_hook):
        self._wndproc_hook = wndproc_hook
        self._proc = WNDPROC(self._dispatch)
        self._surface = None
        self._size = (0, 0)
        self.hwnd = self._create(w, h)

    # -- 创建 -------------------------------------------------------
    def _register(self):
        if LayeredWindow._class_atom:
            return
        wc = WNDCLASSEXW()
        wc.cbSize = sizeof(WNDCLASSEXW)
        wc.style = CS_DBLCLKS
        wc.lpfnWndProc = self._proc
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.hCursor = cursor(False)
        wc.lpszClassName = self._class_name
        atom = user32.RegisterClassExW(byref(wc))
        if not atom:
            err = ctypes.get_last_error()
            if err not in (0, 1410):  # 1410 = 类已存在
                raise ctypes.WinError(err)
        LayeredWindow._class_atom = atom or 1

    def _create(self, w: int, h: int) -> int:
        self._register()
        ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
        hwnd = user32.CreateWindowExW(
            ex, self._class_name, "WeChat Work Hub", WS_POPUP,
            0, 0, w, h, None, None, kernel32.GetModuleHandleW(None), None,
        )
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = hwnd
        return hwnd

    # -- 消息路由 ---------------------------------------------------
    def _dispatch(self, hwnd, msg, wparam, lparam):
        try:
            handled, result = self._wndproc_hook(hwnd, msg, wparam, lparam)
            if handled:
                return result
        except Exception:
            import traceback
            traceback.print_exc()
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # -- 绘制 -------------------------------------------------------
    def _ensure_surface(self, w: int, h: int):
        if self._surface and self._size == (w, h):
            return self._surface
        if self._surface:
            mem_dc, bmp, bits, old = self._surface
            gdi32.SelectObject(mem_dc, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem_dc)

        screen_dc = user32.GetDC(None)
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # 负数 = 自上而下
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        bmp = gdi32.CreateDIBSection(screen_dc, byref(bmi), DIB_RGB_COLORS,
                                     byref(bits), None, 0)
        user32.ReleaseDC(None, screen_dc)
        if not bmp:
            raise ctypes.WinError(ctypes.get_last_error())
        old = gdi32.SelectObject(mem_dc, bmp)
        self._surface = (mem_dc, bmp, bits, old)
        self._size = (w, h)
        return self._surface

    def paint(self, img: Image.Image, x: int, y: int) -> None:
        """把整图贴到窗口上。x/y 是窗口左上角屏幕坐标（物理像素）。"""
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        w, h = img.size
        mem_dc, _bmp, bits, _old = self._ensure_surface(w, h)
        data = img.tobytes("raw", "BGRA")
        ctypes.memmove(bits, data, len(data))

        screen_dc = user32.GetDC(None)
        dst = POINT(int(x), int(y))
        size = SIZE(w, h)
        src = POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        ok = user32.UpdateLayeredWindow(self.hwnd, screen_dc, byref(dst), byref(size),
                                        mem_dc, byref(src), 0, byref(blend), ULW_ALPHA)
        user32.ReleaseDC(None, screen_dc)
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def move(self, x: int, y: int) -> None:
        """只挪位置，不重绘（拖动时用这个，避免逐帧重画卡顿）。"""
        user32.SetWindowPos(self.hwnd, None, int(x), int(y), 0, 0,
                            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def show(self) -> None:
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

    def hide(self) -> None:
        user32.ShowWindow(self.hwnd, SW_HIDE)

    def topmost(self) -> None:
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def destroy(self) -> None:
        user32.DestroyWindow(self.hwnd)
        if self._surface:
            mem_dc, bmp, _bits, old = self._surface
            gdi32.SelectObject(mem_dc, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem_dc)
            self._surface = None

    # -- 定时器 -----------------------------------------------------
    def timer(self, tid: int, ms: int) -> None:
        user32.SetTimer(self.hwnd, tid, ms, None)

    def kill_timer(self, tid: int) -> None:
        user32.KillTimer(self.hwnd, tid)


# ------------------------------------------------------------------ 桌面取景

def capture(x: int, y: int, w: int, h: int) -> Image.Image:
    """抓屏幕一块区域（不含其它分层窗口，即不会抓到自己），返回 RGB 图。"""
    w, h = max(1, int(w)), max(1, int(h))
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bmp = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    if not bmp:
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
        return Image.new("RGB", (w, h), (24, 24, 26))
    old = gdi32.SelectObject(mem_dc, bmp)

    # 不加 CAPTUREBLT：分层窗口（含自己）不会被抓进来
    gdi32.BitBlt(mem_dc, 0, 0, w, h, screen_dc, int(x), int(y), SRCCOPY)
    gdi32.SelectObject(mem_dc, old)

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB
    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, byref(bmi), DIB_RGB_COLORS)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(None, screen_dc)

    if not got:
        return Image.new("RGB", (w, h), (24, 24, 26))
    return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)


# ------------------------------------------------------------------ 系统模糊（可选档）

def set_accent(hwnd: int, state: int = ACCENT_ENABLE_ACRYLICBLURBEHIND,
               tint: int = 0x99101010) -> bool:
    """Win10 未公开接口：给窗口加 Acrylic。失败返回 False。

    注意：本项目的窗口是 UpdateLayeredWindow 的分层窗口，
    DWM 不会为分层窗口做背景模糊，所以这条只作为「原生档」的尝试。
    """
    try:
        fn = user32.SetWindowCompositionAttribute
    except AttributeError:
        return False
    policy = ACCENTPOLICY(state, 2, tint, 0)
    data = WINCOMPATTRDATA(WCA_ACCENT_POLICY, ctypes.cast(ctypes.pointer(policy),
                                                          ctypes.c_void_p),
                           sizeof(ACCENTPOLICY))
    try:
        return bool(fn(hwnd, byref(data)))
    except Exception:
        return False


def set_backdrop(hwnd: int, kind: int = DWMSBT_TRANSIENTWINDOW) -> bool:
    """Win11 官方接口 DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE)。"""
    try:
        value = ctypes.c_int(kind)
        hr = dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                                          byref(value), sizeof(value))
        return hr == 0
    except Exception:
        return False


def windows_build() -> int:
    try:
        return int(kernel32.GetVersion())
    except Exception:
        return 0


def message_loop() -> None:
    msg = MSG()
    while True:
        ret = user32.GetMessageW(byref(msg), None, 0, 0)
        if ret in (0, -1):
            break
        user32.TranslateMessage(byref(msg))
        user32.DispatchMessageW(byref(msg))


def post_quit() -> None:
    user32.PostQuitMessage(0)


# ------------------------------------------------------------------ 右键菜单

def popup_menu(hwnd: int, x: int, y: int, items) -> int:
    """items: [(cmd_id, 文本) | None(分隔线)]，返回选中的 cmd_id（0 = 取消）。"""
    menu = user32.CreatePopupMenu()
    if not menu:
        return 0
    for item in items:
        if item is None:
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        else:
            cmd, text = item
            user32.AppendMenuW(menu, MF_STRING, cmd, text)
    user32.SetForegroundWindow(hwnd)
    cmd = user32.TrackPopupMenu(menu, TPM_LEFTALIGN | TPM_RETURNCMD | TPM_NONOTIFY,
                                int(x), int(y), 0, hwnd, None)
    user32.DestroyMenu(menu)
    return int(cmd)
