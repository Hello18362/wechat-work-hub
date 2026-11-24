# -*- coding: utf-8 -*-
"""一条命令把项目装好（给人和给 AI 用的是同一套）。

设计目标：**幂等**。跑一次、跑十次，结果一样；已经装好的步骤直接跳过。

用法::

    python tools/setup.py            # 交互式：缺什么补什么，动手前问一句
    python tools/setup.py --yes      # 不问，直接做（给 AI / 脚本用）
    python tools/setup.py --check    # 只体检，不装任何东西
    python tools/setup.py --json     # 机器可读结果（给 AI 判断用）
    python tools/setup.py --no-venv  # 不建 .venv，装进当前解释器

退出码：0 = 装好了且自检没有 ❌；1 = 有硬问题（看输出的「下一步」）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
MIN_PY = (3, 10)

results: list = []          # [(level, text)]  level: ok / info / warn / bad


# --------------------------------------------------------------------- 输出

def say(level: str, text: str) -> None:
    results.append((level, text))
    mark = {"ok": "[OK]  ", "info": "      ", "warn": "[!]   ", "bad": "[X]   "}[level]
    print(mark + text, flush=True)


def _short(path: str, limit: int = 72) -> str:
    """太长就缩成 …/尾部，避免把一行刷爆。"""
    path = str(path)
    if len(path) <= limit:
        return path
    return "…" + path[-(limit - 1):]


# --------------------------------------------------------------------- 探测

def _version_tuple(text: str) -> tuple:
    """'3.11.5' -> (3, 11, 5)；'3.11.9rc1' -> (3, 11, 9)；解析不了返回 ()。"""
    parts = []
    for chunk in str(text).strip().split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _python_ok(version_text: str) -> bool:
    vt = _version_tuple(version_text)
    return len(vt) >= 2 and vt[:2] >= MIN_PY


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _inside_venv() -> bool:
    try:
        return Path(sys.prefix).resolve() == VENV_DIR.resolve()
    except OSError:
        return False


def _run(cmd, cwd=None, timeout=1800):
    """跑一条命令，返回 (returncode, 输出末尾)。失败不抛异常。"""
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd or ROOT), capture_output=True, timeout=timeout,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        out = (proc.stdout or b"").decode("utf-8", "ignore")
        err = (proc.stderr or b"").decode("utf-8", "ignore")
        return proc.returncode, (out + err).strip()
    except FileNotFoundError as exc:
        return 1, "找不到命令：%s" % exc
    except subprocess.TimeoutExpired:
        return 1, "超时（>%ds）" % timeout


# --------------------------------------------------------------------- 步骤

def step_python() -> None:
    ver = "%d.%d.%d" % sys.version_info[:3]
    if _python_ok(ver):
        say("ok", "Python %s（%s）" % (ver, _short(sys.executable)))
    else:
        say("bad", "Python %s 太旧，需要 3.10 或更高。装完重开终端再跑一次。" % ver)
    if sys.version_info[:2] >= (3, 13):
        say("warn", "Python 3.13 上部分科学计算包可能没有 wheel；建议 3.11/3.12")


def step_venv(use_venv: bool, assume_yes: bool) -> Path:
    """确保有可用的解释器，返回之后所有命令该用的 python 路径。"""
    target = _venv_python()
    if not use_venv:
        say("info", "按要求不建虚拟环境，依赖装进当前解释器")
        return Path(sys.executable)
    if target.exists():
        say("ok", "虚拟环境已存在：%s" % _short(str(target)))
        return target
    if _inside_venv():
        return Path(sys.executable)

    say("info", "没有 .venv，准备创建（约 5~15 秒）")
    if not assume_yes:
        try:
            answer = input("     现在创建吗？[Y/n] ").strip().lower()
        except EOFError:
            answer = "y"
        if answer not in ("", "y", "yes"):
            say("warn", "跳过创建 .venv，依赖将装进当前解释器")
            return Path(sys.executable)

    rc, out = _run([sys.executable, "-m", "venv", str(VENV_DIR)], timeout=300)
    if rc != 0 or not target.exists():
        say("bad", "创建 .venv 失败：%s" % out.splitlines()[-1] if out else "未知原因")
        say("info", "常见原因：缺 ensurepip（重装 Python 勾选 pip）、无写权限、杀软拦截")
        return Path(sys.executable)
    say("ok", "虚拟环境已创建：%s" % _short(str(target)))
    return target


def step_deps(python: Path) -> None:
    rc, out = _run([str(python), "-c", "import requests, yaml, bs4, PIL, zstandard"])
    if rc == 0:
        say("ok", "核心依赖齐全（requests / PyYAML / bs4 / Pillow / zstandard）")
        return
    say("info", "开始安装依赖（首次约 20~60 秒；国内网络会自动换清华镜像）")
    rc, out = _run([str(python), "-m", "pip", "install", "-q", "-e", str(ROOT)])
    if rc != 0:
        say("warn", "直连 PyPI 没成功，换国内镜像再试一次…")
        rc, out = _run([str(python), "-m", "pip", "install", "-q",
                        "-e", str(ROOT), "-i", MIRROR])
    if rc != 0:
        say("bad", "依赖安装失败：%s" % (out.splitlines()[-1] if out else "未知原因"))
        say("info", "手动重试：%s -m pip install -e ." % _short(str(python)))
        return
    rc, out = _run([str(python), "-c", "import requests, yaml, bs4, PIL, zstandard"])
    if rc == 0:
        say("ok", "依赖已装好")
    else:
        say("bad", "装完仍然导不进来：%s" % (out.splitlines()[-1] if out else ""))


def _read_env_friendly(path: Path) -> str:
    """读 .env：UTF-8(BOM) → GBK → UTF-8 容错。与 core/config.py 同一套顺序。

    安装期这一步的意义是**把编码问题提前暴露并当场修掉**，而不是等用户改完
    配置、跑到 main.py 时才收到一屏 UnicodeDecodeError。
    """
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return path.read_text(encoding="gbk")
    except (UnicodeDecodeError, LookupError):
        return path.read_text(encoding="utf-8", errors="replace")


def _env_encoding_problem(path: Path) -> str:
    """返回 .env 的编码问题描述；没问题返回空串。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "带 BOM（配置键会被当成 \\ufeffWX_... 而静默失效）"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return "不是 UTF-8（像记事本存的 ANSI/GBK）"
    return ""


def step_env() -> None:
    env = ROOT / ".env"
    example = ROOT / ".env.example"
    if env.exists():
        problem = _env_encoding_problem(env)
        if problem:
            # 就地转成 UTF-8 无 BOM：内容一个字都不丢，只是换个编码存。
            text = _read_env_friendly(env)
            env.write_text(text, encoding="utf-8")
            say("warn", ".env 编码有问题（%s），已自动转成 UTF-8" % problem)
            say("info", "  以后用记事本改 .env，保存时编码选 UTF-8，别用 ANSI")
        text = _read_env_friendly(env)
        if "your_api_key_here" in text:
            say("warn", ".env 里还是占位 Key，总结会降级成本地草稿（链路不算断）")
        else:
            say("ok", ".env 已存在")
        return
    if not example.exists():
        say("warn", "没有 .env 也没有 .env.example，跳过（没有 Key 也能跑样例链路）")
        return
    env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    say("info", "已从 .env.example 生成 .env —— 这是**唯一需要人动手**的地方：")
    say("info", "  打开 .env，把 DEEPSEEK_API_KEY=your_api_key_here 换成真实 Key")
    say("info", "  （用记事本保存时，编码请选 UTF-8，别选 ANSI）")


def step_siwx(python: Path) -> None:
    """配了解密目录才关心：SIWX 自己有依赖。"""
    env = ROOT / ".env"
    dec = ""
    if env.exists():
        for line in _read_env_friendly(env).splitlines():
            if line.strip().startswith("WX_DECRYPTED_DIR="):
                dec = line.split("=", 1)[1].strip()
    if not dec:
        say("info", "没配解密目录：用内置样例数据也能把整条链路跑通（正常的首次状态）")
        return
    if not Path(dec).exists():
        say("warn", "WX_DECRYPTED_DIR 指向的目录不存在：%s" % _short(dec))
        return
    rc, out = _run([str(python), "tools/doctor.py", "--json"], timeout=180)
    try:
        payload = json.loads(out[out.index("{"):])
    except Exception:  # noqa: BLE001
        say("warn", "解密工具依赖没能确认（doctor 输出解析失败）")
        return
    siwx = [c for c in payload.get("checks", []) if c.get("id") == "siwx"]
    if not siwx:
        return
    item = siwx[0]
    if item.get("level") == "OK":
        say("ok", "解密工具可运行")
    elif item.get("fix"):
        say("warn", "解密工具缺包，自动刷新会失败。修：%s" % item["fix"])


def step_doctor(python: Path) -> bool:
    rc, out = _run([str(python), "tools/doctor.py", "--json"], timeout=300)
    payload = None
    if out:
        try:
            payload = json.loads(out[out.index("{"):])
        except Exception:  # noqa: BLE001
            payload = None
    if payload is None:
        say("bad", "自检脚本跑不起来：%s" % (out.splitlines()[-1] if out else "无输出"))
        return False
    ok, lines = summarize_doctor(payload)
    for text in lines:
        say("info" if ok else "bad", text)
    if ok:
        say("ok", "自检通过：没有硬问题")
    else:
        say("bad", "自检有硬问题，见上面的「下一步」，或查 docs/部署与排错-AI版.md 第 5 节")
    return ok


def summarize_doctor(payload: dict) -> tuple:
    """把 doctor --json 的结果压成几行给人看。返回 (是否没有 FAIL, 行列表)。"""
    counts = payload.get("counts") or {}
    lines = ["自检结果：%s 项，失败 %s，提醒 %s" % (
        counts.get("total", 0), counts.get("fail", 0), counts.get("warn", 0))]
    for action in (payload.get("next_actions") or [])[:6]:
        if isinstance(action, dict):
            text = "%s → %s" % (action.get("name", ""), action.get("fix", ""))
        else:
            text = str(action)
        lines.append("下一步：" + text.replace("\n", " "))
    return (int(counts.get("fail", 0)) == 0), lines


# --------------------------------------------------------------------- 主流程

def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="一条命令装好本项目（幂等）")
    ap.add_argument("--yes", action="store_true", help="不问，直接做（给 AI 用）")
    ap.add_argument("--check", action="store_true", help="只体检，不装东西")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    ap.add_argument("--no-venv", action="store_true", help="不建 .venv，装进当前解释器")
    args = ap.parse_args(argv)

    if args.check:
        ok = step_doctor(Path(sys.executable))
        return 0 if ok else 1

    step_python()
    python = step_venv(not args.no_venv, args.yes)
    step_deps(python)
    step_env()
    step_siwx(python)
    ok = step_doctor(python)

    if args.json:
        bad = any(level == "bad" for level, _ in results)
        print(json.dumps({
            "ok": ok and not bad,
            "python": str(python),
            "steps": [{"level": lv, "text": t} for lv, t in results],
        }, ensure_ascii=False, indent=2))
    else:
        print("\n" + "=" * 60)
        print("  装完了。接下来两条命令：")
        print("=" * 60)
        print("  起服务：%s tools\\launch.py" % _short(str(python)))
        print("  （或者直接双击 一键启动.bat，它会用同一个 .venv）")
        print("  验收：  %s tools\\smoke_chain.py --url http://127.0.0.1:5710" % _short(str(python)))
        print("  出报告：%s main.py --group \"XX项目工作群\" --date 2026-10-27 -f both" % _short(str(python)))
        print()
        print("  唯一需要人动手的：把 .env 里的 DEEPSEEK_API_KEY 换成真实 Key。")
        print("  不填也能跑完（总结降级成本地草稿），链路不会断。")
    return 0 if (ok and not any(level == "bad" for level, _ in results)) else 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())