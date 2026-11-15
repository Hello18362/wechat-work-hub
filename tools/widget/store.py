# -*- coding: utf-8 -*-
"""数据与状态存取。

两个文件都在 %LOCALAPPDATA%\\WeChatWorkHub\\：
- cards.json  ：调度任务写的卡片数据（小窗只读）
- widget.json ：小窗自己的位置与形态记忆
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WeChatWorkHub"
CARDS_FILE = APP_DIR / "cards.json"
STATE_FILE = APP_DIR / "widget.json"

PRIORITY_RANK = {"紧急": 0, "高": 1, "重要": 2, "中": 3, "常规": 4, "": 5}


def ensure_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ 卡片

def _norm_card(c: Dict) -> Dict:
    return {
        "group": (c.get("group") or "").strip(),
        "title": (c.get("title") or "").strip(),
        "priority": (c.get("priority") or "常规").strip(),
        "source": (c.get("source") or "").strip(),
        "owner": (c.get("owner") or "").strip(),
        "due": (c.get("due") or "").strip(),
        "done": bool(c.get("done")),
        "report": (c.get("report") or "").strip(),
    }


def sort_cards(cards: List[Dict]) -> List[Dict]:
    """未完成在前，按优先级；同级保持原顺序（稳定排序）。"""
    return sorted(cards, key=lambda c: (bool(c.get("done")),
                                        PRIORITY_RANK.get(c.get("priority") or "", 5)))


class CardStore:
    """监视 cards.json，变了就重新读。"""

    def __init__(self):
        self.data: Dict = {}
        self._mtime: float = 0.0
        self._loaded = False

    def report_dir(self) -> Optional[Path]:
        d = self.data.get("report_dir") or ""
        if d:
            p = Path(d)
            if p.exists():
                return p
        return None

    def report_path(self, card: Dict) -> Optional[Path]:
        name = card.get("report") or ""
        if not name:
            return None
        p = Path(name)
        if p.is_absolute() and p.exists():
            return p
        base = self.report_dir()
        if base:
            cand = base / name
            if cand.exists():
                return cand
        return None

    def latest_report(self) -> Optional[Path]:
        cards = self.cards()
        for c in cards:
            p = self.report_path(c)
            if p:
                return p
        return None

    def load(self) -> bool:
        """读盘，返回内容是否发生变化。"""
        ensure_dir()
        try:
            st = CARDS_FILE.stat()
        except OSError:
            if not self._loaded:
                self._loaded = True
                self.data = {}
                return True
            return False
        if st.st_mtime == self._mtime:
            return False
        self._mtime = st.st_mtime
        try:
            with open(CARDS_FILE, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception:
            return False
        if not isinstance(raw, dict):
            return False
        cards = [_norm_card(c) for c in (raw.get("cards") or []) if isinstance(c, dict)]
        raw["cards"] = sort_cards(cards)
        self.data = raw
        self._loaded = True
        return True

    def cards(self) -> List[Dict]:
        return self.data.get("cards") or []

    def stale_hours(self) -> Optional[float]:
        gen = self.data.get("generated_at") or ""
        if not gen:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(gen, fmt)
                return max(0.0, (datetime.now() - dt).total_seconds() / 3600.0)
            except ValueError:
                continue
        return None


# ------------------------------------------------------------------ 窗口状态

DEFAULT_STATE = {
    "panel_x": None,      # 面板左上角（不含投影留白）
    "panel_y": None,
    "mode": "expanded",   # expanded / ball / sliver
    "side": "",           # left / right：吸在哪边
    "done_expanded": False,
}


class WidgetState:
    def __init__(self):
        self.data = dict(DEFAULT_STATE)
        self.load()

    def load(self) -> None:
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                for key in DEFAULT_STATE:
                    if key in raw:
                        self.data[key] = raw[key]
        except Exception:
            pass

    def save(self) -> None:
        ensure_dir()
        tmp = STATE_FILE.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, STATE_FILE)
        except Exception:
            pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, **kwargs) -> None:
        self.data.update(kwargs)
