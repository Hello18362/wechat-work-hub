"""重新生成演示报告，用于验证修复后的产物已无重复标题等问题。"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector.chatlog_client import ChatlogClient  # noqa: E402
from collector.models import TYPE_ARTICLE, TYPE_IMAGE, TYPE_TEXT, TYPE_VOICE, Message  # noqa: E402
from core.config import load_settings  # noqa: E402
from core.pipeline import RunOptions, run_pipeline  # noqa: E402

# (分钟偏移, 发言人, wxid, 内容, 类型, 是否领导)
SCENES = [
    (
        "2026-10-22",
        "XX项目工作群",
        [
            (0, "张总", "wxid_zhang", "接口联调这周必须闭环，别拖到下周。", TYPE_TEXT, True),
            (4, "王五", "wxid_wang", "还差两个字段没对齐，今天下午补完。", TYPE_TEXT, False),
            (27, "李四", "wxid_lisi", "[语音]", TYPE_VOICE, False),
            (31, "王五", "wxid_wang", "这是目前的联调报错截图，[图片：异常堆栈截屏]", TYPE_IMAGE, False),
            (75, "张总", "wxid_zhang", "看到群里的方案文档了，按第二版推进。", TYPE_TEXT, True),
            (131, "李四", "wxid_lisi", "把压测报告发群里了，[链接：https://mp.weixin.qq.com/s/demo-perf]", TYPE_ARTICLE, False),
            (188, "张总", "wxid_zhang", "周三上午十点过一下方案，相关同学都参加。", TYPE_TEXT, True),
            (203, "王五", "wxid_wang", "收到，我先把冒烟用例补齐。", TYPE_TEXT, False),
        ],
    ),
    (
        "2026-10-22",
        "部门周会群",
        [
            (0, "陈总", "wxid_chen", "这周的周会改到下午三点，会议室 B。", TYPE_TEXT, True),
            (18, "赵敏", "wxid_zhao", "上周的复盘文档已经归档了。", TYPE_TEXT, False),
            (44, "陈总", "wxid_chen", "Q4 的人力缺口今天下班前给我一个数字。", TYPE_TEXT, True),
            (96, "赵敏", "wxid_zhao", "[图片：人力盘点表]", TYPE_IMAGE, False),
        ],
    ),
    (
        "2026-10-21",
        "XX项目工作群",
        [
            (0, "王五", "wxid_wang", "灰度环境的配置已经更新。", TYPE_TEXT, False),
            (22, "张总", "wxid_zhang", "压测目标明确到 P99 350ms，不要含糊。", TYPE_TEXT, True),
            (40, "李四", "wxid_lisi", "会场页那条链路要不要一起压？", TYPE_TEXT, False),
            (41, "张总", "wxid_zhang", "要，去年就是这里出的问题。", TYPE_TEXT, True),
            (88, "李四", "wxid_lisi", "[语音]", TYPE_VOICE, False),
        ],
    ),
    (
        "2026-10-21",
        "部门周会群",
        [
            (0, "陈总", "wxid_chen", "上季度的问题清单再过一遍。", TYPE_TEXT, True),
            (15, "赵敏", "wxid_zhao", "[链接：https://mp.weixin.qq.com/s/demo-retro]", TYPE_ARTICLE, False),
            (36, "陈总", "wxid_chen", "归档完同步到知识库。", TYPE_TEXT, True),
        ],
    ),
]


def build(day: str, group: str, rows) -> list:
    base = datetime.strptime(day, "%Y-%m-%d").replace(hour=9, minute=0)
    return [
        Message(
            msg_id=f"{day.replace('-', '')}{i:03d}",
            group_name=group,
            sender_name=who,
            sender_id=sid,
            timestamp=base + timedelta(minutes=offset),
            msg_type=kind,
            content=content,
            raw_content=content,
            is_leader=leader,
            seq=i,
        )
        for i, (offset, who, sid, content, kind, leader) in enumerate(rows)
    ]


def main() -> int:
    cfg = load_settings()
    ChatlogClient.health = lambda self: True

    for day, group, rows in SCENES:
        messages = build(day, group, rows)
        ChatlogClient.get_messages = lambda self, *a, _m=messages, **k: _m
        result = run_pipeline(
            cfg,
            RunOptions(group=group, date=day, formats=["markdown", "html"]),
            progress=lambda s, p, d: None,
        )
        md = result.markdown_path.read_text(encoding="utf-8")
        page = result.html_path.read_text(encoding="utf-8")
        assert md.count("## 总结") == 1, f"{group} 重复标题"
        assert "<h2>总结</h2>" not in page, f"{group} HTML 重复标题"
        print(
            f"  {group} {day}: {result.stats['total']} 条 "
            f"(领导 {result.stats['leader_count']}) -> {result.html_path.name}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
