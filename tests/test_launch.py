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


class ReadPortTest(unittest.TestCase):
    """端口读取必须不依赖 PyYAML —— 全新机器上第一次运行时 yaml 还没装。"""

    SAMPLE = (
        "chatlog:\n"
        "  api_base: http://127.0.0.1:5030\n"
        "  timeout: 15\n"
        "asr:\n"
        "  model: small\n"
        "web:\n"
        "  host: 127.0.0.1\n"
        "  port: 5763\n"
        "  open_browser: true\n"
    )

    def test_reads_web_port(self) -> None:
        self.assertEqual(launch._read_port_from_text(self.SAMPLE), 5763)

    def test_ignores_port_under_other_sections(self) -> None:
        text = "chatlog:\n  port: 9999\nweb:\n  port: 5720\n"
        self.assertEqual(launch._read_port_from_text(text), 5720)

    def test_falls_back_when_absent(self) -> None:
        self.assertEqual(launch._read_port_from_text("web:\n  host: x\n"),
                         launch.DEFAULT_PORT)
        self.assertEqual(launch._read_port_from_text(""), launch.DEFAULT_PORT)

    def test_quoted_value_and_comment(self) -> None:
        text = "web:\n  port: \"5712\"  # 端口\n"
        self.assertEqual(launch._read_port_from_text(text), 5712)

    def test_real_config_parses_to_int(self) -> None:
        """仓库自带配置必须能被无 yaml 的解析路径读出整数端口。"""
        text = (PROJECT_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
        self.assertIsInstance(launch._read_port_from_text(text), int)


class ReadyUrlTest(unittest.TestCase):
    def test_extracts_url(self) -> None:
        log = ("===== 2026-11-22 17:22:30 后台服务启动 =====\n"
               "  本地控制台已就绪：http://127.0.0.1:5762\n"
               "  Ctrl+C 退出\n")
        self.assertEqual(launch.ready_url_from_log(log), "http://127.0.0.1:5762")

    def test_empty_when_not_ready(self) -> None:
        self.assertEqual(launch.ready_url_from_log("启动中…\n"), "")
        self.assertEqual(launch.ready_url_from_log(""), "")

    def test_uses_last_occurrence(self) -> None:
        log = ("  本地控制台已就绪：http://127.0.0.1:5710\n"
               "  本地控制台已就绪：http://127.0.0.1:5720\n")
        self.assertEqual(launch.ready_url_from_log(log), "http://127.0.0.1:5720")


if __name__ == "__main__":
    unittest.main(verbosity=2)