# -*- coding: utf-8 -*-
"""悬浮窗自愈判据（纯函数，不碰 win32，Linux CI 也能测）。

背景：用户两次报「缩到边缘之后就没反应了」。查下来是天蓝色那边
动画/拖动状态卡住：`self.anim` 一直非空，于是轮询直接早退——
鼠标悬停不展开、点也没反应，窗口就僵在那儿。

判据放这里，是为了让「什么算卡住」有测试兜着，而不是散在定时器里。
"""

from __future__ import annotations

TICK_GAP = 0.06      # 帧定时器正常 16ms 一跳；超过 60ms 没动就当它没在跑
FORCE_GRACE = 1.0    # 动画超过「预期时长 + 1 秒」还没完，直接落终态
DRAG_MISSES = 3      # 左键明明松了却还在拖，连续几次确认后才自愈


def anim_action(anim, now: float, tick_gap: float = TICK_GAP,
                grace: float = FORCE_GRACE):
    """动画该不该由看门狗插手：返回 "tick" / "force" / None。

    - 帧定时器一切正常 → None（别抢它的活）
    - 定时器没动静但动画还没超时 → "tick"（补一帧，把动画接着推下去）
    - 早该结束却还没结束 → "force"（直接落到终态，别让用户干等）
    """
    if not anim:
        return None
    last = anim.get("last")
    if last is not None and now - last <= tick_gap:
        return None
    t0 = anim.get("t0")
    age = now - (now if t0 is None else float(t0))
    dur = anim.get("dur")
    if age > (0.0 if dur is None else float(dur)) + grace:
        return "force"
    return "tick"


def drag_lost(dragging, left_button_down, misses: int,
              limit: int = DRAG_MISSES) -> bool:
    """按着左键在拖，但系统里左键其实早松了——鼠标抬起事件丢了。

    连续 limit 次都这样才认定，避免用户刚松手那一瞬被误判。
    """
    return bool(dragging) and not left_button_down and misses >= limit