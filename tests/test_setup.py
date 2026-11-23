"""tools/setup.py 的单元测试（只管纯函数，不真装东西）。

运行方式::

    python tests/test_setup.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools import setup  # noqa: E402


class VersionTest(unittest.TestCase):
    def test_parses_normal_version(self) -> None:
        self.assertEqual(setup._version_tuple("3.11.9"), (3, 11, 9))

    def test_parses_two_part_version(self) -> None:
        self.assertEqual(setup._version_tuple("3.12"), (3, 12))

    def test_drops_trailing_garbage(self) -> None:
        """'3.11.9rc1' 这类要能解析出主版本，不能因为尾巴就当成空。"""
        self.assertEqual(setup._version_tuple("3.11.9rc1"), (3, 11, 9))

    def test_garbage_becomes_empty(self) -> None:
        self.assertEqual(setup._version_tuple("python"), ())

    def test_python_ok_threshold(self) -> None:
        self.assertTrue(setup._python_ok("3.10.0"))
        self.assertTrue(setup._python_ok("3.11.9"))
        self.assertTrue(setup._python_ok("3.12.7"))
        self.assertFalse(setup._python_ok("3.9.13"))
        self.assertFalse(setup._python_ok("2.7.18"))

    def test_python_ok_rejects_unparsable(self) -> None:
        self.assertFalse(setup._python_ok(""))
        self.assertFalse(setup._python_ok("unknown"))


class ShortTest(unittest.TestCase):
    def test_short_keeps_short_text(self) -> None:
        self.assertEqual(setup._short("C:/a/b", limit=20), "C:/a/b")

    def test_short_trims_long_text_keeping_tail(self) -> None:
        text = "C:/" + "x" * 100 + "/python.exe"
        out = setup._short(text, limit=30)
        self.assertEqual(len(out), 30)
        self.assertTrue(out.startswith("…"))
        self.assertTrue(out.endswith("/python.exe"))


class SummarizeDoctorTest(unittest.TestCase):
    def _payload(self, fail: int, total: int = 22, warn: int = 3, actions=None) -> dict:
        return {
            "ok": fail == 0,
            "counts": {"fail": fail, "warn": warn, "total": total},
            "next_actions": actions or [],
        }

    def test_no_fail_means_ok(self) -> None:
        ok, lines = setup.summarize_doctor(self._payload(0))
        self.assertTrue(ok)
        self.assertIn("失败 0", lines[0])

    def test_any_fail_means_not_ok(self) -> None:
        ok, lines = setup.summarize_doctor(self._payload(2))
        self.assertFalse(ok)
        self.assertIn("失败 2", lines[0])

    def test_actions_become_next_step_lines(self) -> None:
        payload = self._payload(0, actions=[
            {"name": "虚拟环境", "fix": "改用 .venv\\Scripts\\python.exe"},
        ])
        ok, lines = setup.summarize_doctor(payload)
        self.assertTrue(ok)
        self.assertTrue(any("虚拟环境" in line and "python.exe" in line for line in lines))

    def test_actions_are_capped(self) -> None:
        payload = self._payload(0, actions=[{"name": "n%d" % i, "fix": "f"} for i in range(20)])
        _, lines = setup.summarize_doctor(payload)
        self.assertLessEqual(len(lines), 7)  # 1 行总述 + 最多 6 条下一步

    def test_missing_counts_does_not_crash(self) -> None:
        ok, lines = setup.summarize_doctor({"ok": True})
        self.assertTrue(ok)
        self.assertIn("失败 0", lines[0])

    def test_plain_string_actions_are_supported(self) -> None:
        ok, lines = setup.summarize_doctor(self._payload(0, actions=["直接照做这一条"]))
        self.assertTrue(ok)
        self.assertTrue(any("直接照做这一条" in line for line in lines))


if __name__ == "__main__":
    unittest.main(verbosity=2)