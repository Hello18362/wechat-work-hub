"""内置样例数据客户端（collector/sample_client.py）的单元测试。

纯标准库 unittest，运行方式::

    python tests/test_sample_client.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from collector.sample_client import SampleClient  # noqa: E402


def _write_group(data_dir: Path, name: str, payload: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class SampleClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _client(self) -> SampleClient:
        return SampleClient(data_dir=self.data_dir)

    def test_health_false_when_empty_dir(self) -> None:
        self.assertFalse(self._client().health())

    def test_health_true_when_json_present(self) -> None:
        _write_group(self.data_dir, "测试群", {"group": "测试群", "messages": []})
        self.assertTrue(self._client().health())

    def test_health_false_when_dir_missing(self) -> None:
        self.assertFalse(SampleClient(data_dir=Path(self._tmp.name) / "不存在").health())

    def test_get_groups_lists_names_only(self) -> None:
        _write_group(self.data_dir, "甲群", {"group": "甲群", "messages": []})
        _write_group(self.data_dir, "乙群", {"group": "乙群", "messages": []})
        groups = self._client().get_groups()
        self.assertEqual(sorted(g["name"] for g in groups), ["乙群", "甲群"])

    def test_get_messages_filters_by_date_range_and_marks_leader(self) -> None:
        _write_group(
            self.data_dir,
            "甲群",
            {
                "group": "甲群",
                "messages": [
                    {"time": "2026-10-26 09:00", "sender": "张三", "id": "a", "type": "text",
                     "content": "早", "leader": False, "seq": 1},
                    {"time": "2026-10-27 10:00", "sender": "李总", "id": "b", "type": "text",
                     "content": "今天交付", "leader": True, "seq": 2},
                    {"time": "2026-10-28 10:00", "sender": "王五", "id": "c", "type": "text",
                     "content": "明天再说", "leader": False, "seq": 3},
                ],
            },
        )
        messages = self._client().get_messages(
            "甲群",
            datetime(2026, 10, 27, 0, 0),
            datetime(2026, 10, 27, 23, 59, 59),
        )
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].sender_name, "李总")
        self.assertTrue(messages[0].is_leader)
        self.assertEqual(messages[0].content, "今天交付")

    def test_get_messages_sorted_by_time(self) -> None:
        _write_group(
            self.data_dir,
            "甲群",
            {
                "group": "甲群",
                "messages": [
                    {"time": "2026-10-27 10:05", "sender": "乙", "id": "2", "type": "text",
                     "content": "二", "leader": False, "seq": 2},
                    {"time": "2026-10-27 10:00", "sender": "甲", "id": "1", "type": "text",
                     "content": "一", "leader": False, "seq": 1},
                ],
            },
        )
        messages = self._client().get_messages(
            "甲群", datetime(2026, 10, 27, 0, 0), datetime(2026, 10, 27, 23, 59, 59)
        )
        self.assertEqual([m.content for m in messages], ["一", "二"])

    def test_bad_rows_are_skipped_not_fatal(self) -> None:
        _write_group(
            self.data_dir,
            "甲群",
            {
                "group": "甲群",
                "messages": [
                    "这不是对象",
                    {"time": "不是时间", "sender": "乙", "content": "跳过"},
                    {"time": "2026-10-27 10:00", "sender": "甲", "id": "1", "type": "text",
                     "content": "保留", "leader": True, "seq": 1},
                ],
            },
        )
        messages = self._client().get_messages(
            "甲群", datetime(2026, 10, 27, 0, 0), datetime(2026, 10, 27, 23, 59, 59)
        )
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "保留")

    def test_unknown_group_returns_empty(self) -> None:
        _write_group(self.data_dir, "甲群", {"group": "甲群", "messages": []})
        self.assertEqual(
            self._client().get_messages(
                "不存在的群", datetime(2026, 10, 27, 0, 0), datetime(2026, 10, 27, 23, 59, 59)
            ),
            [],
        )

    def test_media_accessors_return_none(self) -> None:
        client = self._client()
        self.assertIsNone(client.get_voice_file("x"))
        self.assertIsNone(client.get_image_file("x"))
        self.assertIsNone(client.close())


class BundledSamplesTest(unittest.TestCase):
    """仓库里自带的 data/samples/*.json 本身也要可解析（这是演示入口）。"""

    def test_bundled_samples_load(self) -> None:
        client = SampleClient()  # 默认 data_dir 指向仓库 data/samples
        self.assertTrue(client.health(), "仓库自带样例数据缺失或不可读")
        groups = {g["name"] for g in client.get_groups()}
        self.assertIn("XX项目工作群", groups)
        messages = client.get_messages(
            "XX项目工作群",
            datetime(2026, 10, 27, 0, 0),
            datetime(2026, 10, 27, 23, 59, 59),
        )
        self.assertGreaterEqual(len(messages), 1)
        self.assertTrue(any(m.is_leader for m in messages), "样例里必须有领导发言，否则演示报告没有内容")


if __name__ == "__main__":
    unittest.main(verbosity=2)