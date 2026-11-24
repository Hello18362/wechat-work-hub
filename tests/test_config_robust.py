"""配置文件的健壮性测试：编码、BOM、结构写错、leaders 简写。

这些坑只在「换台电脑 + 用记事本手改」时出现，所以用临时文件把行为钉死。

    python tests/test_config_robust.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import (  # noqa: E402
    ConfigError,
    _read_text_friendly,
    load_dotenv,
    load_groups,
)


class _TmpDir(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)
        self._saved = {}

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._dir.cleanup()

    def track(self, *names: str) -> None:
        for name in names:
            self._saved[name] = os.environ.get(name)
            os.environ.pop(name, None)


class EncodingTest(_TmpDir):
    def test_gbk_env_does_not_crash(self) -> None:
        """记事本存成 ANSI(GBK) 的 .env：旧代码在启动阶段就抛 UnicodeDecodeError。"""
        env = self.tmp / ".env"
        env.write_bytes("# 中文注释\nWX_DECRYPTED_DIR=C:/测试/路径\n".encode("gbk"))
        self.track("WX_DECRYPTED_DIR")
        load_dotenv(env)
        self.assertEqual(os.environ.get("WX_DECRYPTED_DIR"), "C:/测试/路径")

    def test_utf8_bom_env_key_is_recognized(self) -> None:
        """带 BOM 的 UTF-8：首行键名会带上 \\ufeff，配置被静默丢弃。"""
        env = self.tmp / ".env"
        env.write_bytes(b"\xef\xbb\xbf" + "WX_SIWX_RUN=C:/siwx/run.py\n".encode("utf-8"))
        self.track("WX_SIWX_RUN")
        load_dotenv(env)
        self.assertEqual(os.environ.get("WX_SIWX_RUN"), "C:/siwx/run.py")

    def test_gbk_groups_yaml_is_readable(self) -> None:
        path = self.tmp / "groups.yaml"
        path.write_bytes(
            "target_groups:\n  - name: 项目群\n    leaders:\n      - name: 张三\n".encode("gbk")
        )
        groups = load_groups(path)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["name"], "项目群")
        self.assertEqual(groups[0]["leaders"][0]["name"], "张三")

    def test_read_text_friendly_prefers_utf8(self) -> None:
        path = self.tmp / "a.txt"
        path.write_text("中文", encoding="utf-8")
        self.assertEqual(_read_text_friendly(path), "中文")


class StructureTest(_TmpDir):
    def test_top_level_not_mapping_raises_config_error(self) -> None:
        path = self.tmp / "groups.yaml"
        path.write_text("- 群A\n- 群B\n", encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_groups(path)

    def test_target_groups_not_list_raises_config_error(self) -> None:
        path = self.tmp / "groups.yaml"
        path.write_text("target_groups:\n  群A: 张三\n", encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_groups(path)

    def test_empty_file_returns_empty(self) -> None:
        path = self.tmp / "groups.yaml"
        path.write_text("# 只有注释\n", encoding="utf-8")
        self.assertEqual(load_groups(path), [])


class LeaderNormalizationTest(_TmpDir):
    def test_string_leader_shorthand(self) -> None:
        """`- 张三` 这种简写以前会抛 AttributeError: 'str' object has no attribute 'get'。"""
        path = self.tmp / "groups.yaml"
        path.write_text(
            "target_groups:\n"
            "  - name: 群A\n"
            "    leaders:\n"
            "      - 张三\n"
            "      - name: 李四\n"
            "        id: wxid_x\n",
            encoding="utf-8",
        )
        leaders = load_groups(path)[0]["leaders"]
        self.assertEqual(leaders[0], {"name": "张三", "id": ""})
        self.assertEqual(leaders[1], {"name": "李四", "id": "wxid_x"})

    def test_blank_and_null_leaders_are_dropped(self) -> None:
        path = self.tmp / "groups.yaml"
        path.write_text(
            "target_groups:\n"
            "  - name: 群A\n"
            "    leaders:\n"
            "      - ''\n"
            "      - null\n"
            "      - 42\n",
            encoding="utf-8",
        )
        self.assertEqual(load_groups(path)[0]["leaders"], [])

    def test_string_global_leaders_are_appended_once(self) -> None:
        path = self.tmp / "groups.yaml"
        path.write_text(
            "target_groups:\n"
            "  - name: 群A\n"
            "    leaders:\n"
            "      - 王五\n"
            "global_leaders:\n"
            "  - 王五\n"
            "  - 赵六\n",
            encoding="utf-8",
        )
        names = [l["name"] for l in load_groups(path)[0]["leaders"]]
        self.assertEqual(names, ["王五", "赵六"])  # 王五 不重复追加


if __name__ == "__main__":
    unittest.main(verbosity=2)