# -*- coding: utf-8 -*-
"""自动守护：新消息 → 出报告 → 抽卡片，全自动，无需人工。

设计原则（都是为了别乱花钱）：

  1. **没新消息就不跑**。查解密库里所有消息表的 MAX(create_time)，
     和上次处理时一样就说明没新消息，直接睡。
  2. **两次执行至少隔 MIN_GAP**。哪怕一直有新消息，也不会每 10 分钟跑一次。
  3. **开机先跑一次**（如果有新消息），保证早上打开电脑就有今天的卡片。
  4. 失败不重试轰炸，记日志后等下一轮。

用法：
    python tools/auto_daemon.py            # 常驻
    python tools/auto_daemon.py --once     # 只检查一次，打印决策，不执行
    python tools/auto_daemon.py --force    # 立刻执行一次（不管节流）
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

APP_DIR = Path(os.environ.get("LOCALAPPDATA") or ROOT) / "WeChatWorkHub"
STATE_FILE = APP_DIR / "daemon_state.json"
STOP_FILE = APP_DIR / "daemon.stop"        # 重启用：touch 一下，守护在下一轮自己退出
LOG_FILE = ROOT / "logs" / "auto_daemon.log"

MUTEX_NAME = "WeChatWorkHubAutoDaemon"

INSPECT_SEC = 600          # 每 10 分钟检查一次新消息（本地查询，免费）
WATCH_SEC = 60             # 每 60 秒看一眼悬浮窗还在不在（查窗口，几乎零成本）
MIN_GAP_SEC = 7200         # 两次执行至少隔 2 小时
JOB_TIMEOUT = 1800         # 单次 daily_job 最长 30 分钟

WIDGET_CLASS = "WeChatWorkHubWidget"
WIDGET_SCRIPT = ROOT / "tools" / "desktop_widget.py"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


# ---------------------------------------------------------------- 日志

def log(msg: str) -> None:
    line = "%s  %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    # pythonw 启动时 sys.stdout 是 None，print 会抛异常，必须兜住
    try:
        print(line, flush=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- 状态

def load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_state(state: dict) -> None:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        log("状态写入失败：%s" % exc)


# ---------------------------------------------------------------- 数据最新时间

def decrypted_dir() -> str:
    """从配置里拿解密目录。"""
    try:
        from core.config import load_settings

        cfg = load_settings()
        return str((cfg.get("chatlog") or {}).get("decrypted_dir") or "")
    except Exception:
        return ""


def latest_message_ts(folder: str) -> int:
    """扫所有 Msg_ 表，返回最大的 create_time。读不到返回 0。"""
    if not folder:
        return 0
    db = Path(folder) / "message" / "message_0.db"
    if not db.exists():
        return 0
    uri = "file:%s?mode=ro" % str(db).replace("\\", "/")
    newest = 0
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error:
        return 0
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
            ).fetchall()
        ]
        for t in tables:
            try:
                row = con.execute("SELECT MAX(create_time) FROM %s" % t).fetchone()
                if row and row[0] and int(row[0]) > newest:
                    newest = int(row[0])
            except sqlite3.Error:
                continue
    except sqlite3.Error:
        return 0
    finally:
        con.close()
    return newest


def ts_text(ts: int) -> str:
    if not ts:
        return "-"
    if ts > 10 ** 11:      # 毫秒
        ts //= 1000
    try:
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
    except (OSError, ValueError):
        return str(ts)


# ---------------------------------------------------------------- 执行

def run_daily_job() -> bool:
    """跑一次完整链路：刷新数据 → 出报告 → 抽卡片。"""
    cmd = [sys.executable, str(ROOT / "tools" / "daily_job.py"),
           "--date", "today"]
    log("开始执行：daily_job --date today（这一步会调用 AI，产生费用）")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, timeout=JOB_TIMEOUT)
    except subprocess.TimeoutExpired:
        log("执行超时（%d 秒），放弃本轮" % JOB_TIMEOUT)
        return False
    except Exception as exc:  # noqa: BLE001
        log("启动失败：%s" % exc)
        return False

    cost = time.time() - t0

    def _dec(raw: bytes) -> str:
        # Windows 控制台输出是 GBK，直接按 utf-8 解会出乱码
        for enc in ("gbk", "utf-8"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "replace")

    out = _dec(proc.stdout or b"")
    err = _dec(proc.stderr or b"")
    if proc.returncode == 0:
        tail = [ln for ln in out.strip().splitlines() if ln.strip()][-3:]
        log("执行完成（%.0fs）%s" % (cost, " | ".join(tail)))
        return True

    tail = [ln for ln in (err or out).strip().splitlines() if ln.strip()][-3:]
    log("执行失败（%.0fs）%s" % (cost, " | ".join(tail)))
    return False


# ---------------------------------------------------------------- 主循环

def decide(state: dict) -> tuple:
    """返回 (该不该跑, 原因)。"""
    folder = decrypted_dir()
    if not folder:
        return False, "读不到解密目录配置"

    newest = latest_message_ts(folder)
    if not newest:
        return False, "读不到消息数据（微信可能没登录）"

    last_newest = int(state.get("last_message_ts") or 0)
    last_run = float(state.get("last_run_at") or 0)
    gap = time.time() - last_run

    if newest <= last_newest:
        return False, "没有新消息（最新 %s）" % ts_text(newest)

    if gap < MIN_GAP_SEC:
        return False, "有新消息，但距上次执行只有 %.0f 分钟" % (gap / 60)

    return True, "有新消息（最新 %s，上次 %s）" % (ts_text(newest), ts_text(last_newest))


# ------------------------------------------------------------ 悬浮窗看护
#
# 悬浮窗以前"会自己消失"：崩溃、被任务管理器结束、或 Windows 回收，
# 用户就得自己去点 bat。守护进程反正常驻，顺手每隔 60 秒看一眼，
# 不在就拉起来——这样"双击完 bat 就一直在"才真正成立。

def widget_running() -> bool:
    try:
        u = ctypes.windll.user32
        u.FindWindowW.restype = ctypes.c_void_p
        u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        return bool(u.FindWindowW(WIDGET_CLASS, None))
    except Exception:  # noqa: BLE001  查不出来就别乱拉起
        return True


def _pythonw() -> str:
    exe = sys.executable
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def ensure_widget() -> bool:
    """窗口不在就拉起来。返回是否本次做了拉起动作。"""
    if not WIDGET_SCRIPT.exists() or widget_running():
        return False
    try:
        subprocess.Popen(
            [_pythonw(), str(WIDGET_SCRIPT)],
            cwd=str(ROOT),
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log("悬浮窗不在，已自动拉起")
        return True
    except Exception as exc:  # noqa: BLE001
        log("拉起悬浮窗失败：%s" % exc)
        return False


def acquire_mutex():
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, 0, MUTEX_NAME)
        if not handle:
            return None
        if ctypes.get_last_error() == 183:      # ERROR_ALREADY_EXISTS
            return None
        return handle
    except Exception:
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只检查一次并打印决策，不执行")
    ap.add_argument("--force", action="store_true", help="忽略节流，立即执行一次")
    args = ap.parse_args(argv)

    if args.once:
        state = load_state()
        should, reason = decide(state)
        try:
            print("决策：%s" % ("执行" if should else "跳过"))
            print("原因：%s" % reason)
            print("状态：%s" % json.dumps(state, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass
        return 0

    # 手动触发必须放在互斥锁之前：守护进程常驻时也要能立刻跑一次，
    # 否则 --force 永远会被"已有一个守护进程在运行"挡掉。
    if args.force:
        log("==== 手动触发一次完整链路 ====")
        ok = run_daily_job()
        state = load_state()
        state["last_run_at"] = time.time()
        if ok:
            state["last_message_ts"] = latest_message_ts(decrypted_dir())
        save_state(state)
        log("手动执行结束（%s）" % ("成功" if ok else "失败"))
        return 0

    mutex = acquire_mutex()
    if mutex is None:
        log("已有一个守护进程在运行，退出")
        return 0

    log("==== 自动守护启动（查消息 %d 分钟 / 看护悬浮窗 %d 秒 / 最小执行间隔 %d 分钟）===="
        % (INSPECT_SEC // 60, WATCH_SEC, MIN_GAP_SEC // 60))

    last_inspect = 0.0
    while True:
        try:
            # 重启握手：start_widget.py --restart 会放下这个文件
            if STOP_FILE.exists():
                try:
                    STOP_FILE.unlink()
                except OSError:
                    pass
                log("收到停止信号，守护退出（重启流程会再拉起新的）")
                return 0

            # 先把窗口看住：崩溃、被杀、被系统回收，最迟 1 分钟就回来
            ensure_widget()

            now = time.time()
            if now - last_inspect >= INSPECT_SEC:
                last_inspect = now
                state = load_state()
                should, reason = decide(state)
                log("检查：%s" % reason)
                if should:
                    ok = run_daily_job()
                    state = load_state()
                    state["last_run_at"] = time.time()
                    if ok:
                        state["last_message_ts"] = latest_message_ts(decrypted_dir())
                    save_state(state)
        except Exception as exc:  # noqa: BLE001 守护进程不能死
            log("循环异常（继续）：%s" % exc)

        time.sleep(WATCH_SEC)


if __name__ == "__main__":
    raise SystemExit(main())
