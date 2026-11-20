# -*- coding: utf-8 -*-
"""每日任务：刷新数据 → 逐群出报告 → 写卡片数据。

计划任务里的那一步就是跑这个。单独跑也行：

    python tools/daily_job.py                # 置顶群 + 昨天
    python tools/daily_job.py --date today
    python tools/daily_job.py --no-refresh   # 跳过解密刷新，只用现有数据

失败兜底：某个群失败就跳过并记日志，其余继续；
全部失败则保留上一次的 cards.json（不覆盖），悬浮窗顶部会显示「数据为 N 小时前」。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "daily_job.log"


def log(msg: str) -> None:
    line = "%s  %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def refresh_data() -> bool:
    log("① 刷新微信解密数据")
    try:
        from core.auto_refresh import AutoRefresher
        from core.config import load_settings

        cfg = load_settings()
        refresher = AutoRefresher(cfg)
        ok = refresher.refresh_once(force=True)
        log("   解密刷新：%s" % ("成功" if ok else (refresher.last_error or "失败")))
        return ok
    except Exception as exc:  # noqa: BLE001
        log("   解密刷新异常（继续用现有数据）：%s" % exc)
        return False


def pinned_groups() -> list:
    try:
        import make_daily_cards as m

        groups = m.read_pins()
    except Exception as exc:  # noqa: BLE001
        log("   读置顶群失败：%s" % exc)
        groups = []
    return groups


def make_report(group: str, day: str) -> bool:
    cmd = [sys.executable, str(ROOT / "main.py"),
           "--group", group, "--date", day, "-f", "both", "--no-progress"]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, timeout=1800)
    except subprocess.TimeoutExpired:
        log("   %s：超时（30 分钟），跳过" % group)
        return False
    except Exception as exc:  # noqa: BLE001
        log("   %s：启动失败 %s" % (group, exc))
        return False
    cost = time.time() - t0
    if proc.returncode == 0:
        log("   %s：完成（%.1fs）" % (group, cost))
        return True
    tail = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip().splitlines()
    log("   %s：失败（%.1fs）%s" % (group, cost, tail[-1] if tail else ""))
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="yesterday", help="yesterday / today / 2026-11-15")
    ap.add_argument("--no-refresh", action="store_true")
    ap.add_argument("--no-report", action="store_true", help="只重算卡片，不出报告")
    args = ap.parse_args(argv)

    log("==== 每日任务开始（日期 %s）====" % args.date)

    if not args.no_refresh:
        refresh_data()

    groups = pinned_groups()
    if not groups:
        log("没有置顶群，跳过出报告这一步。")
    elif args.no_report:
        log("按参数跳过出报告。")
    else:
        log("② 逐群生成报告（%d 个置顶群）" % len(groups))
        ok = 0
        for g in groups:
            if make_report(g, args.date):
                ok += 1
        log("   报告：成功 %d / %d" % (ok, len(groups)))

    log("③ 汇总卡片数据")
    try:
        import make_daily_cards as m

        rc = m.main([] if args.date in ("yesterday", "today") else ["--date", args.date])
        log("   卡片：%s" % ("写入成功" if rc == 0 else "没有可用数据，保留旧数据"))
    except Exception as exc:  # noqa: BLE001
        log("   卡片异常：%s" % exc)

    log("==== 每日任务结束 ====")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
