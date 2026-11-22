# -*- coding: utf-8 -*-
"""tools/doctor.py 的契约测试。

为什么只测「结构」不测「结论」：doctor 的检查项跟机器环境强相关
（有没有微信、有没有 Key、端口有没有被占），在 CI 上不可能全绿。
这里守住的是更重要的东西：
· 退出码 / JSON 结构稳定（AI 与文档都在按字段名解析）；
· 单独一个检查项炸掉，不能把整个 doctor 带崩；
· 关键 id 必须存在（文档里引用过这些 id）。
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCTOR = PROJECT_ROOT / "tools" / "doctor.py"

REQUIRED_IDS = {
    "python",
    "venv",
    "dep_yaml",
    "dep_requests",
    "datasource",
    "settings",
    "service",
}


def _run(*args):
    return subprocess.run(
        [sys.executable, str(DOCTOR)] + list(args),
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


class DoctorJsonTest(unittest.TestCase):
    def test_json_is_parseable_and_stable(self):
        proc = _run("--json")
        self.assertIn(proc.returncode, (0, 1), proc.stderr[-2000:])
        data = json.loads(proc.stdout)

        for key in ("ok", "root", "python", "counts", "checks", "next_actions"):
            self.assertIn(key, data)
        self.assertIsInstance(data["ok"], bool)
        self.assertIsInstance(data["checks"], list)
        self.assertTrue(data["checks"])

        for check in data["checks"]:
            for key in ("id", "level", "name", "detail", "fix"):
                self.assertIn(key, check, check)
            self.assertTrue(check["id"])
            self.assertTrue(check["level"])

        counts = data["counts"]
        self.assertEqual(counts["total"], len(data["checks"]))
        self.assertEqual(counts["fail"] + counts["warn"] <= counts["total"], True)

    def test_exit_code_matches_ok_flag(self):
        """有 ❌ 时必须退 1（脚本能据此判断），没有 ❌ 时退 0。"""
        proc = _run("--json")
        data = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 0 if data["ok"] else 1)

    def test_required_ids_present(self):
        data = json.loads(_run("--json").stdout)
        ids = {c["id"] for c in data["checks"]}
        missing = REQUIRED_IDS - ids
        self.assertFalse(missing, "doctor 少了这些检查项：%s" % sorted(missing))

    def test_every_fix_is_actionable_text(self):
        """给了 fix 就必须是能执行的句子，不能是空串或纯标点。"""
        data = json.loads(_run("--json").stdout)
        for check in data["checks"]:
            fix = (check.get("fix") or "").strip()
            if fix:
                self.assertGreater(len(fix), 6, check)
                self.assertTrue(any(ch.isalnum() for ch in fix), check)


class DoctorHumanOutputTest(unittest.TestCase):
    def test_human_output_has_conclusion(self):
        proc = _run()
        self.assertIn(proc.returncode, (0, 1))
        self.assertIn("结论", proc.stdout)
        self.assertIn("部署自检", proc.stdout)

    def test_help_works(self):
        proc = _run("--help")
        self.assertEqual(proc.returncode, 0, proc.stderr[-1000:])
        self.assertIn("--json", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)