# -*- coding: utf-8 -*-
"""从最新报告里抽出任务卡片，写成悬浮窗要的 cards.json。

链路：置顶群 → runs/ 里该群最新一份报告 → extract_task_cards → 排序 → cards.json

用法:
    python tools/make_daily_cards.py             # 只跑置顶群（config/pins.yaml 或 groups.yaml 的 pinned）
    python tools/make_daily_cards.py --all       # 不看置顶，所有群都算
    python tools/make_daily_cards.py --date 2026-11-15
    python tools/make_daily_cards.py --demo      # 写示例数据（调样式用）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import load_settings  # noqa: E402
from output.md_lite import extract_task_cards  # noqa: E402

APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WeChatWorkHub"
CARDS_FILE = APP_DIR / "cards.json"

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)$")
MSG_RE = re.compile(r"消息总数\**\s*[:：]\s*(\d+)")
PRIORITY_RANK = {"紧急": 0, "高": 1, "重要": 2, "中": 3, "常规": 4, "": 5}


# ------------------------------------------------------------------ 配置

def _yaml_load(path: Path):
    try:
        import yaml
    except ImportError:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return None


def read_pins() -> List[str]:
    """读置顶群。优先级：config/pins.yaml > groups.yaml 里的 pinned: true。"""
    pins_file = ROOT / "config" / "pins.yaml"
    if pins_file.exists():
        data = _yaml_load(pins_file) or {}
        names = data.get("pinned") if isinstance(data, dict) else data
        if isinstance(names, list):
            return [str(n).strip() for n in names if str(n).strip()]

    groups_file = ROOT / "config" / "groups.yaml"
    if not groups_file.exists():
        return []
    data = _yaml_load(groups_file) or {}
    pinned: List[str] = []
    for item in data.get("target_groups") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        flag = bool(item.get("pinned"))
        # 历史配置里 pinned 有时被写到了 leaders 下面，一并兼容
        if not flag:
            for leader in item.get("leaders") or []:
                if isinstance(leader, dict) and leader.get("pinned"):
                    flag = True
                    break
        if flag:
            pinned.append(name)
    return pinned


def runs_dir() -> Path:
    try:
        cfg = load_settings()
        raw = (cfg.get("output") or {}).get("dir") or "./runs"
    except Exception:
        raw = "./runs"
    p = Path(raw)
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    return p


# ------------------------------------------------------------------ 报告

def scan_reports(folder: Path) -> Dict[str, Dict[str, Path]]:
    """{群名: {日期: md 路径}}"""
    table: Dict[str, Dict[str, Path]] = {}
    if not folder.exists():
        return table
    for f in folder.glob("*.md"):
        m = DATE_RE.match(f.stem)
        if not m:
            continue
        day, group = m.group(1), m.group(2)
        table.setdefault(group, {})[day] = f
    return table


def norm_name(name: str) -> str:
    """群名归一化：全角括号/空格差异不该导致匹配失败。"""
    return (str(name).strip()
            .replace("（", "(").replace("）", ")")
            .replace("　", "").replace(" ", ""))


def match_group(table: Dict[str, Dict[str, Path]], group: str) -> Optional[str]:
    if group in table:
        return group
    key = norm_name(group)
    for real in table:
        if norm_name(real) == key:
            return real
    return None


def pick_report(table, group: str, upto: str) -> Optional[Path]:
    days = table.get(group) or {}
    usable = [d for d in days if d <= upto]
    if not usable:
        return None
    return days[max(usable)]


def html_beside(md_path: Path) -> Path:
    html = md_path.with_suffix(".html")
    return html if html.exists() else md_path


def collect(groups: List[str], upto: str) -> Dict:
    folder = runs_dir()
    table = scan_reports(folder)
    cards: List[Dict] = []
    used_groups = []
    total_msgs = 0
    missing = []

    for group in groups:
        real = match_group(table, group)
        md = pick_report(table, real, upto) if real else None
        if not md:
            missing.append(group)
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            missing.append(group)
            continue
        hit = MSG_RE.search(text)
        if hit:
            try:
                total_msgs += int(hit.group(1))
            except ValueError:
                pass
        report_name = html_beside(md).name
        label = real or group
        got = []
        for card in extract_task_cards(text):
            card = dict(card)
            card["group"] = label
            card["report"] = report_name
            card["priority"] = card.get("priority") or "常规"
            got.append(card)
        if got:
            used_groups.append(label)
            cards.extend(got)

    cards.sort(key=lambda c: (bool(c.get("done")),
                              PRIORITY_RANK.get(c.get("priority") or "", 5)))
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "groups": len(used_groups),
        "total_messages": total_msgs,
        "report_dir": str(folder),
        "empty": not cards,
        "missing_groups": missing,
        "cards": cards,
    }


def write(payload: Dict) -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CARDS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, CARDS_FILE)
    return CARDS_FILE


# ------------------------------------------------------------------ 入口

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成悬浮窗卡片数据")
    ap.add_argument("--all", action="store_true", help="不看置顶，所有有报告的群都算")
    ap.add_argument("--date", default=None, help="按哪天算（默认今天）")
    ap.add_argument("--demo", action="store_true", help="写示例数据")
    ap.add_argument("--group", action="append", default=None, help="指定群名，可重复")
    args = ap.parse_args(argv)

    if args.demo:
        from widget.app import _demo_payload
        payload = _demo_payload()
        payload["report_dir"] = str(runs_dir())
        print("已写入示例数据：%s" % write(payload))
        return 0

    upto = args.date or date.today().isoformat()

    if args.group:
        groups = args.group
    elif args.all:
        groups = list(scan_reports(runs_dir()).keys())
    else:
        groups = read_pins()
        if not groups:
            print("没有读到置顶群（config/pins.yaml 不存在，groups.yaml 里也没有 pinned: true）。")
            print("改用 --all 会把所有有报告的群都算进来。")
            return 2

    payload = collect(groups, upto)
    if not payload["cards"] and not args.all:
        # 置顶群这几天没任务 / 没报告：退一步用全部有报告的群，别让窗空着
        fallback = list(scan_reports(runs_dir()).keys())
        alt = collect(fallback, upto)
        if alt["cards"]:
            print("置顶群没有可用任务，已改用全部群（%d 个）的数据。" % alt["groups"])
            payload = alt

    path = write(payload)
    print("群 %d 个 · 卡片 %d 张 · 消息 %d 条"
          % (payload["groups"], len(payload["cards"]), payload["total_messages"]))
    if payload["missing_groups"]:
        print("没有报告的群（已跳过）：%s" % "、".join(payload["missing_groups"]))
    print("已写入：%s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
