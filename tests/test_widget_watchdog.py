# -*- coding: utf-8 -*-
"""悬浮窗自愈判据的测试：动画卡死、拖动残留两种「没反应」。

跑法：python tests/test_widget_watchdog.py
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.widget.watchdog import (DRAG_MISSES, anim_action,   # noqa: E402
                                  drag_lost)


class AnimActionTest(unittest.TestCase):
    def _anim(self, t0=100.0, dur=0.28, last=None):
        a = {"t0": t0, "dur": dur, "to_mode": "expanded"}
        if last is not None:
            a["last"] = last
        return a

    def test_no_anim_means_nothing_to_do(self):
        self.assertIsNone(anim_action(None, 100.0))
        self.assertIsNone(anim_action({}, 100.0))

    def test_fresh_frame_leaves_it_alone(self):
        # 帧定时器 16ms 一跳，刚跑过一帧就别插手
        act = anim_action(self._anim(t0=100.0, last=100.10), 100.12)
        self.assertIsNone(act)

    def test_silent_timer_gets_a_tick(self):
        # 定时器停了，但动画才过了 0.1 秒，还来得及补帧
        act = anim_action(self._anim(t0=100.0, last=100.02), 100.10)
        self.assertEqual(act, "tick")

    def test_never_started_still_ticks(self):
        # 连一帧都没跑过（没有 last），不算超时就该补帧
        self.assertEqual(anim_action(self._anim(), 100.10), "tick")

    def test_overdue_animation_is_forced(self):
        # 0.28 秒的动画拖了 2 秒还没完 → 直接落终态，别让用户干等
        self.assertEqual(anim_action(self._anim(t0=100.0, last=100.02), 102.0),
                         "force")

    def test_force_uses_configured_grace(self):
        a = self._anim(t0=0.0, dur=1.0, last=0.0)
        self.assertEqual(anim_action(a, 1.5, grace=1.0), "tick")
        self.assertEqual(anim_action(a, 2.5, grace=1.0), "force")

    def test_tick_gap_is_respected(self):
        a = self._anim(t0=100.0, last=100.0)
        self.assertIsNone(anim_action(a, 100.05, tick_gap=0.06))
        self.assertEqual(anim_action(a, 100.2, tick_gap=0.06), "tick")


class DragLostTest(unittest.TestCase):
    def test_healthy_drag(self):
        self.assertFalse(drag_lost(True, True, 0))

    def test_not_dragging_is_never_lost(self):
        self.assertFalse(drag_lost(False, False, 99))

    def test_needs_repeated_confirmation(self):
        # 用户刚松手那一瞬不该被判定，要连续几次才认
        self.assertFalse(drag_lost(True, False, 1, limit=DRAG_MISSES))
        self.assertTrue(drag_lost(True, False, DRAG_MISSES))


if __name__ == "__main__":
    unittest.main(verbosity=2)