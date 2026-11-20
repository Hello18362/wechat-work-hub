# -*- coding: utf-8 -*-
"""用 pythonw 后台拉起悬浮窗（不留黑框），并确认窗口真的活着。

给「启动悬浮窗.bat」调用。之所以不把逻辑写在 bat 里：
bat 的 for /f + if defined 组合在不同机器上极易出歧义，Python 版能本地测。

    python tools/start_widget.py            已经开着就什么都不做
    python tools/start_widget.py --restart  先关掉再重开（窗口卡住时用）

历史坑：以前只在 0.2 秒内 FindWindow 到就算"启动成功"，可进程可能
刚建完窗口就崩了，于是用户双击后过一会儿发现卡片没了。现在改成
"先等窗口出现，再等 3 秒复查窗口还在、进程还活着"，不通过就打印崩溃日志。
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tools" / "desktop_widget.py"
DAEMON = ROOT / "tools" / "auto_daemon.py"
CARDS = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WeChatWorkHub" / "cards.json"
STOP_FILE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WeChatWorkHub" / "daemon.stop"
LAUNCH_LOG = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WeChatWorkHub" / "launcher.log"

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
DAEMON_MUTEX = "WeChatWorkHubAutoDaemon"
WIDGET_CLASS = "WeChatWorkHubWidget"


def log(msg: str) -> None:
    line = "%s  %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(msg)
    try:
        LAUNCH_LOG.parent.mkdir(parents=True, exist_ok=True)
        with LAUNCH_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _daemon_running() -> bool:
    """守护进程用同名互斥体防重复，这里问一下它是否已经在了。"""
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        k.CreateMutexW.restype = ctypes.c_void_p
        handle = k.CreateMutexW(None, 0, DAEMON_MUTEX)
        exists = ctypes.get_last_error() == 183          # ERROR_ALREADY_EXISTS
        if handle and not exists:
            k.CloseHandle(ctypes.c_void_p(handle))
        return exists
    except Exception:  # noqa: BLE001
        return False


def _spawn(path: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [_pythonw(), str(path)],
        cwd=str(ROOT),
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _pythonw() -> str:
    exe = sys.executable
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def _find_widget() -> int:
    """返回悬浮窗 hwnd，没有则 0。"""
    u = ctypes.windll.user32
    u.FindWindowW.restype = ctypes.c_void_p
    u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    return int(u.FindWindowW(WIDGET_CLASS, None) or 0)


def _kill_widgets() -> None:
    """按窗口句柄找进程结束掉（只杀本项目自己的窗口进程）。"""
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    hwnd = _find_widget()
    if not hwnd:
        return
    pid = ctypes.c_ulong()
    u.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
    u.PostMessageW(ctypes.c_void_p(hwnd), 0x0010, 0, 0)      # WM_CLOSE
    time.sleep(1.2)
    if _find_widget():
        handle = k.OpenProcess(0x0001, False, pid.value)      # PROCESS_TERMINATE
        if handle:
            k.TerminateProcess(handle, 1)
            k.CloseHandle(handle)
        time.sleep(0.8)


def _crash_tail(n: int = 12) -> str:
    path = LAUNCH_LOG.parent / "crash.log"
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="启动桌面悬浮窗")
    ap.add_argument("--restart", action="store_true", help="已经在运行也强制重启一次")
    args = ap.parse_args(argv)

    if not TARGET.exists():
        log("找不到 %s" % TARGET)
        return 1

    # 数据守护：发现微信有新消息就自动出报告、更新卡片。
    # 它自己有空转判断和 2 小时节流，重复启动会靠互斥体自动退出。
    # 它还负责每 60 秒看护悬浮窗（崩了自动拉起），所以这个要先起。
    if args.restart and _daemon_running():
        log("按 --restart 要求，让旧守护退出……")
        try:
            STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
            STOP_FILE.write_text("restart", encoding="utf-8")
        except OSError as exc:
            log("写停止信号失败（继续）：%s" % exc)
        for _ in range(16):                     # 最多等 8 秒
            time.sleep(0.5)
            if not _daemon_running():
                break
        else:
            log("旧守护没退出，跳过重启（新守护会被互斥体挡住，不影响窗口）")

    if DAEMON.exists() and not _daemon_running():
        try:
            _spawn(DAEMON)
            log("已启动数据守护（有新消息会自动更新卡片，并看护悬浮窗）。")
        except Exception as exc:  # noqa: BLE001
            log("数据守护启动失败（不影响窗口）：%s" % exc)

    if args.restart:
        log("按 --restart 要求，先关掉现有悬浮窗……")
        _kill_widgets()

    if _find_widget():
        log("悬浮窗已经在运行了，不用重复启动。（窗口卡住可加 --restart）")
        return 0

    # 没有卡片数据就先跑一次，免得一开窗就是空的
    if not CARDS.exists():
        log("第一次启动，先生成卡片数据……")
        try:
            subprocess.run([sys.executable, str(ROOT / "tools" / "make_daily_cards.py")],
                           cwd=str(ROOT), timeout=120)
        except Exception as exc:  # noqa: BLE001
            log("生成卡片数据失败（不影响启动）：%s" % exc)

    exe = _pythonw()
    log("启动器：%s" % exe)
    proc = _spawn(TARGET)
    log("已拉起进程 PID=%s，等待窗口出现……" % proc.pid)

    # 1) 等窗口出现（最多 10 秒）
    for _ in range(50):
        time.sleep(0.2)
        if _find_widget():
            break
    else:
        log("没等到窗口出现，进程退出码=%s" % proc.poll())
        tail = _crash_tail()
        if tail:
            log("最近的崩溃日志：\n%s" % tail)
        return 1

    # 2) 再等 3 秒复查：这一步就是为了抓"刚建完窗口就崩"的情况
    time.sleep(3.0)
    if not _find_widget():
        log("窗口出现后又消失了（进程退出码=%s）" % proc.poll())
        tail = _crash_tail()
        if tail:
            log("最近的崩溃日志：\n%s" % tail)
        return 1

    log("启动成功，窗口稳定。悬浮窗在屏幕右侧。")
    log("点击其他区域约 5 秒后会自动收成右侧细条，鼠标移到细条上会重新展开；也可以点标题栏右侧箭头手动收起。")
    log("崩溃/被结束也没关系：数据守护每 60 秒会把它拉回来。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
