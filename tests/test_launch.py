"""tools/launch.py 的单元测试（依赖探测逻辑）。

纯标准库 unittest，运行方式::

    python tests/test_launch.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools import launch  # noqa: E402


class MissingDepsTest(unittest.TestCase):
    def test_real_module_imports_report_empty(self) -> None:
        """能 import 的模块不应该被报告为缺失（builtins 必然存在）。"""
        self.assertEqual(launch._missing_deps([("builtins", "builtins")]), [])

    def test_fake_module_reports_its_pip_name(self) -> None:
        """探测不到的模块要返回对应的 pip 包名，供提示与安装使用。"""
        self.assertEqual(
            launch._missing_deps([("no_such_module_for_test", "fake-package-name")]),
            ["fake-package-name"],
        )

    def test_default_deps_are_well_formed(self) -> None:
        """CORE_DEPS 必须是 (import 名, pip 包名) 二元组列表。"""
        self.assertTrue(launch.CORE_DEPS)
        for entry in launch.CORE_DEPS:
            self.assertIsInstance(entry, tuple)
            self.assertEqual(len(entry), 2)
            self.assertTrue(entry[0] and entry[1])

    def test_service_http_ok_returns_early_on_timeout(self) -> None:
        """对不存在的服务做 HTTP 探测要快速返回 False，不能卡住启动流程。"""
        self.assertFalse(launch._service_http_ok("http://127.0.0.1:1", timeout=0.3))

    def test_service_http_ok_false_on_dead_port(self) -> None:
        """大概率空闲端口上无服务时返回 False。"""
        self.assertFalse(
            launch._service_http_ok("http://127.0.0.1:58921", timeout=0.4)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)