# -*- coding: utf-8 -*-
"""注册 / 移除计划任务（开机自启 + 每天 08:00 出卡片）。

    python tools/install_tasks.py           注册（已存在会覆盖）
    python tools/install_tasks.py --status  看当前状态
    python tools/install_tasks.py --remove  全部移除

为什么要用计划任务而不是启动文件夹：
登录时触发 + 延迟 30 秒，能等微信先起来；卸载时也能干净删掉。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = "WeChatWorkHub"
TASK_DAILY = TASK_DIR + r"\每日卡片"
TASK_WIDGET = TASK_DIR + r"\悬浮窗"

SCHTASKS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "schtasks.exe")


def _pythonw() -> str:
    exe = sys.executable
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def _run(args) -> int:
    proc = subprocess.run([SCHTASKS] + args, capture_output=True)
    out = (proc.stdout or b"").decode("gbk", "replace").strip()
    err = (proc.stderr or b"").decode("gbk", "replace").strip()
    if out:
        print(out)
    if proc.returncode != 0 and err:
        print(err)
    return proc.returncode


def create_daily() -> int:
    tr = '"%s" "%s"' % (sys.executable, ROOT / "tools" / "daily_job.py")
    return _run(["/Create", "/TN", TASK_DAILY, "/TR", tr, "/SC", "DAILY",
                 "/ST", "08:00", "/F"])


def create_widget() -> int:
    tr = '"%s" "%s"' % (_pythonw(), ROOT / "tools" / "start_widget.py")
    return _run(["/Create", "/TN", TASK_WIDGET, "/TR", tr, "/SC", "ONLOGON",
                 "/DELAY", "0000:30", "/F"])


def remove() -> int:
    rc = 0
    for name in (TASK_DAILY, TASK_WIDGET):
        rc |= _run(["/Delete", "/TN", name, "/F"])
    return rc


def status() -> int:
    rc = _run(["/Query", "/TN", TASK_DIR, "/FO", "LIST"])
    if rc != 0:
        print("还没有注册过计划任务。")
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args(argv)

    if args.status:
        return status()
    if args.remove:
        print("移除计划任务……")
        remove()
        return status()

    print("注册两个计划任务：")
    print("  · 每天 08:00 刷新数据、出报告、写卡片")
    print("  · 登录后延迟 30 秒打开悬浮窗")
    print()
    create_daily()
    create_widget()
    print()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
