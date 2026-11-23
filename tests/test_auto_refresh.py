# -*- coding: utf-8 -*-
"""core/auto_refresh.py 里「挑一个能跑 SIWX 的 Python」这段逻辑的测试。

起因（很具体）：一键启动.bat 改成优先用项目 `.venv` 之后，`sys.executable`
只装了本项目依赖，缺 SIWX 自己的 psutil/pycryptodome，于是
「刷新数据 / 自动刷新」每次都 ModuleNotFoundError → 消息永远不更新。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core import auto_refresh as ar  # noqa: E402


class CandidateTest(unittest.TestCase):
    def test_python_候选包含当前解释器(self):
        cands = ar._python_candidates()
        self.assertTrue(cands)
        self.assertIn(sys.executable, cands)

    def test_WX_PYTHON_排在最前(self):
        with mock.patch.dict(os.environ, {"WX_PYTHON": r"C:\fake\python.exe"}):
            cands = ar._python_candidates()
        self.assertEqual(cands[0], r"C:\fake\python.exe")

    def test_候选不重复(self):
        cands = ar._python_candidates()
        self.assertEqual(len(cands), len(set(cands)))


class ProbeTest(unittest.TestCase):
    def test_不存在的解释器判为不可用(self):
        self.assertFalse(ar._probe_python(str(Path(tempfile.gettempdir()) / "no_such_py.exe")))

    def test_能导入就算可用(self):
        with mock.patch.object(ar, "SIWX_IMPORTS", ("json",)):
            self.assertTrue(ar._probe_python(sys.executable))

    def test_导不进来就算不可用(self):
        with mock.patch.object(ar, "SIWX_IMPORTS", ("definitely_not_a_module_xyz",)):
            self.assertFalse(ar._probe_python(sys.executable))


class PickTest(unittest.TestCase):
    def test_首个可用者胜出(self):
        with mock.patch.object(ar, "_python_candidates", return_value=["a", "b", "c"]), \
                mock.patch.object(ar, "_probe_python", side_effect=[False, True, True]):
            self.assertEqual(ar._pick_siwx_python(), "b")

    def test_全都不行返回None(self):
        with mock.patch.object(ar, "_python_candidates", return_value=["a"]), \
                mock.patch.object(ar, "_probe_python", return_value=False):
            self.assertIsNone(ar._pick_siwx_python())

    def test_修复提示含pip命令(self):
        hint = ar._siwx_dep_hint(r"C:\siwx\run.py")
        self.assertIn("pip install -r", hint)
        self.assertIn("requirements.txt", hint)


class DepsHintTest(unittest.TestCase):
    def test_SIWX_依赖清单不为空(self):
        self.assertIn("psutil", ar.SIWX_IMPORTS)


if __name__ == "__main__":
    unittest.main(verbosity=2)