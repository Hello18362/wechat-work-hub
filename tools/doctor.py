# -*- coding: utf-8 -*-
"""部署自检：一条命令告诉你「这台机器上能不能跑，还缺什么」。

    python tools/doctor.py          # 人看：彩色分节 + 结论 + 下一步
    python tools/doctor.py --json   # 机器看：给 AI 解析，含每项的 id / level / fix

只检查、不修改任何东西。所有检查项都用标准库实现，
即使第三方依赖没装齐也能跑起来（会告诉你缺哪个）。

退出码：0 = 没有阻塞项（WARN 不影响运行）；1 = 有 FAIL，必须处理。

设计说明（给后来改这个文件的人）：
· 每条检查都有稳定的 id，--json 的字段不要随便改名，AI 与文档都在引用；
· 「没有真实数据源」不算失败——新版会回退到 data/samples 内置样例，
  所以要报 WARN 而不是 FAIL，否则全新机器上 doctor 永远是红的。
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import shutil
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OK = "✅"
WARN = "⚠️ "
BAD = "❌"
SKIP = "➖"

results = []          # (level, name, detail, fix, ident)


def add(level, name, detail, fix="", ident=""):
    results.append((level, name, detail, fix, ident))


# --------------------------------------------------------------------- 小工具

def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_json(url: str, timeout: float = 1.5):
    """轻量 GET —— 失败返回 None，不抛。"""
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None


def _settings():
    """尽力加载配置，失败返回 None（调用方自己报）。"""
    try:
        from core.config import load_settings
        return load_settings()
    except Exception:  # noqa: BLE001
        return None


def _web_port() -> int:
    cfg = _settings() or {}
    try:
        return int(((cfg.get("web") or {}).get("port") or 5710))
    except (TypeError, ValueError):
        return 5710


# --------------------------------------------------------------------- 检查项

def check_python():
    v = sys.version_info
    ver = "%d.%d.%d" % (v.major, v.minor, v.micro)
    if v >= (3, 10):
        add(OK, "Python 版本", ver, "", "python")
    else:
        add(BAD, "Python 版本", "%s（需要 3.10+）" % ver,
            "去 https://www.python.org/downloads/ 装 3.11 或更新版本", "python")
    if v >= (3, 13):
        add(WARN, "Python 兼容性", "%s 偏新" % ver,
            "3.13 上部分依赖可能还没发轮子，推荐 3.11（py -3.11 -m venv .venv）",
            "python_compat")
    exe = sys.executable
    add(OK, "解释器", exe, "", "python_exe")


def check_venv():
    """最常见的坑：依赖装在 .venv 里，双击 bat 却用了系统 Python。"""
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    proj_venv = ROOT / ".venv" / "Scripts" / "python.exe"
    if not proj_venv.exists():
        proj_venv = ROOT / ".venv" / "bin" / "python"
    if in_venv:
        add(OK, "虚拟环境", "当前就在虚拟环境里（%s）" % sys.prefix, "", "venv")
    elif proj_venv.exists():
        add(WARN, "虚拟环境", "项目里有 .venv，但现在用的是系统 Python",
            "改用：%s   （或者直接双击 一键启动.bat，它已优先使用 .venv）" % proj_venv,
            "venv")
    else:
        add(SKIP, "虚拟环境", "没在用虚拟环境（能用，但依赖会装进全局）",
            "想隔离就：python -m venv .venv 然后 .venv\\Scripts\\pip install -e .", "venv")


def check_deps():
    required = [
        ("requests", "HTTP 请求（采集 / 调模型）", "requests"),
        ("yaml", "读 config/*.yaml", "PyYAML"),
        ("bs4", "解析公众号文章正文", "beautifulsoup4"),
        ("PIL", "渲染桌面卡片与悬浮窗", "Pillow"),
        ("zstandard", "解压微信 WCDB 压缩内容（缺了会静默丢消息）", "zstandard"),
    ]
    for mod, why, pkg in required:
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, "__version__", "") or ""
            add(OK, "依赖 " + mod, ("%s  " % ver) + why, "", "dep_" + mod)
        except Exception as exc:  # noqa: BLE001
            add(BAD, "依赖 " + mod, "缺失（%s）：%s" % (why, exc),
                "pip install -e .   # 或单独 pip install %s" % pkg, "dep_" + mod)

    try:
        importlib.import_module("faster_whisper")
        add(OK, "可选 faster-whisper", "语音转写可用", "", "dep_faster_whisper")
    except Exception:  # noqa: BLE001
        add(SKIP, "可选 faster-whisper", "未安装：语音降级为 [语音] 占位",
            "要用语音转写：pip install -e \".[asr]\"（首次运行会下模型，几百 MB）",
            "dep_faster_whisper")


def check_platform():
    if sys.platform == "win32":
        add(OK, "操作系统", "Windows %s（悬浮窗可用）" % platform.release(), "", "os")
    else:
        add(WARN, "操作系统", "%s（悬浮窗不可用）" % sys.platform,
            "采集 / 报告 / 本地控制台可以正常用，只有桌面悬浮窗是 Windows 专属", "os")
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    if enc and enc not in ("utf-8", "utf8", "ascii"):
        add(WARN, "控制台编码", enc,
            "中文可能显示为乱码；用 chcp 65001 或 set PYTHONUTF8=1 再跑", "console_encoding")


def check_path():
    """路径里的空格/中文/超长，是「别人能跑我跑不了」的常见来源。"""
    p = str(ROOT)
    notes = []
    if " " in p:
        notes.append("含空格")
    if any(ord(ch) > 127 for ch in p):
        notes.append("含中文")
    if len(p) > 100:
        notes.append("路径较长（%d 字符）" % len(p))
    if notes:
        add(WARN, "项目路径", "%s：%s" % (p, "、".join(notes)),
            "一般没事；若遇到子进程/ffmpeg 报「找不到文件」，把项目挪到 D:\\wwh 这类纯英文短路径再试",
            "path")
    else:
        add(OK, "项目路径", p, "", "path")


def check_writable():
    targets = [ROOT / "runs", ROOT / "logs", ROOT / "data" / "uploads"]
    bad = []
    for t in targets:
        try:
            t.mkdir(parents=True, exist_ok=True)
            probe = t / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except Exception as exc:  # noqa: BLE001
            bad.append("%s（%s）" % (t.name, exc))
    if bad:
        add(BAD, "写权限", "不可写：" + "；".join(bad),
            "把项目放到自己有权限的目录（不要放 Program Files / C:\\ 根）", "writable")
    else:
        add(OK, "写权限", "runs / logs / data/uploads 都可写", "", "writable")


def check_config():
    settings = ROOT / "config" / "settings.yaml"
    if not settings.exists():
        add(BAD, "config/settings.yaml", "不存在",
            "从仓库重新取回 config/settings.yaml（这个文件必须跟着仓库走）", "settings")
        return
    try:
        import yaml  # noqa: F401
    except Exception:  # noqa: BLE001
        add(SKIP, "config/settings.yaml", "缺 PyYAML，暂时没法校验内容",
            "先 pip install -e .，再跑本命令", "settings")
        return
    cfg = _settings()
    if cfg is None:
        add(BAD, "config/settings.yaml", "解析失败（YAML 语法错或被改坏）",
            "python -c \"import yaml,sys;yaml.safe_load(open(r'config/settings.yaml',encoding='utf-8'))\" 看报哪行",
            "settings")
        return
    add(OK, "config/settings.yaml", "解析正常", "", "settings")

    groups = ROOT / "config" / "groups.yaml"
    if groups.exists():
        add(OK, "config/groups.yaml", "存在", "", "groups")
    else:
        add(WARN, "config/groups.yaml", "不存在（目标群/领导名单为空）",
            "copy config\\groups.example.yaml config\\groups.yaml 再改群名", "groups")


def check_datasource():
    """三态：真实解密库 / 本机 chatlog 服务 / 内置样例。任一可用就算通过。"""
    cfg = _settings()
    if cfg is None:
        add(SKIP, "数据源", "配置读不出来，跳过", "", "datasource")
        return

    dec = str((cfg.get("chatlog") or {}).get("decrypted_dir") or "")
    if dec and os.path.isdir(dec):
        db = Path(dec) / "message" / "message_0.db"
        if db.exists():
            add(OK, "数据源", "解密库可用：%s" % dec, "", "datasource")
            try:
                import datetime
                import sqlite3
                uri = "file:%s?mode=ro" % str(db).replace("\\", "/")
                con = sqlite3.connect(uri, uri=True, timeout=5)
                tables = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
                ).fetchall()
                newest = 0
                for (t,) in tables[:60]:
                    row = con.execute("SELECT MAX(create_time) FROM %s" % t).fetchone()
                    if row and row[0]:
                        newest = max(newest, int(row[0]))
                con.close()
                if newest:
                    if newest > 10 ** 11:
                        newest //= 1000
                    t = datetime.datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M")
                    add(OK, "消息数据库", "%d 张表，最新消息 %s" % (len(tables), t), "", "message_db")
                else:
                    add(WARN, "消息数据库", "能打开但没读到消息",
                        "微信没登录，或解密出来是空库；重新解密一次", "message_db")
            except Exception as exc:  # noqa: BLE001
                add(WARN, "消息数据库", "读取失败：%s" % exc,
                    "可能正被微信占用，稍后再试", "message_db")
            return
        add(WARN, "数据源", "配了解密目录但缺 message/message_0.db",
            "解密没跑完，重新解一次；实在没有就先把 decrypted_dir 留空用样例数据", "datasource")
        return

    # 没有解密目录：看本机 chatlog 服务是否在
    api = str((cfg.get("chatlog") or {}).get("api_base") or "http://127.0.0.1:5030")
    port = 5030
    try:
        from urllib.parse import urlparse
        port = urlparse(api).port or port
    except Exception:  # noqa: BLE001
        pass
    if 5030 and _port_open(port):
        add(OK, "数据源", "本机 chatlog 服务在线（%s）" % api, "", "datasource")
        return

    samples = sorted((ROOT / "data" / "samples").glob("*.json")) if (ROOT / "data" / "samples").is_dir() else []
    if samples:
        add(WARN, "数据源", "没有真实数据源，将使用内置样例（%d 个群）" % len(samples),
            "这是正常的首次体验状态。要接真实微信：见 docs/部署与排错-AI版.md 第 4 节",
            "datasource")
    else:
        add(BAD, "数据源", "既没有解密目录，也没有内置样例数据",
            "确认仓库完整（data/samples/*.json 应存在）；否则 git checkout -- data/samples",
            "datasource")


def check_siwx():
    """解密工具（SIWX）自己的依赖：缺了它「刷新数据」永远失败、消息永远不更新。

    典型症状：控制台日志里
      File "...\siwx\discover.py", line 6, in <module>
        import psutil
      ModuleNotFoundError: No module named 'psutil'
    原因：一键启动.bat 现在优先用项目 `.venv`，而 .venv 里只装了本项目的依赖。
    """
    cfg = _settings()
    if cfg is None:
        add(SKIP, "解密工具依赖", "配置读不出来，跳过", "", "siwx")
        return
    dec = str((cfg.get("chatlog") or {}).get("decrypted_dir") or "")
    if not dec:
        add(SKIP, "解密工具依赖", "没配解密目录，用不到解密工具", "", "siwx")
        return

    siwx_run = ""
    try:
        from core.auto_refresh import _pick_siwx_python, _resolve_siwx_run, _siwx_dep_hint

        siwx_run = _resolve_siwx_run(cfg) or ""
        if not siwx_run:
            add(WARN, "解密工具依赖", "没找到 SIWX 的 run.py",
                "把 SIWX 放在解密目录上级，或在 .env 设 WX_SIWX_RUN=<...>\\run.py", "siwx")
            return
        ok_py = _pick_siwx_python()
        if ok_py:
            add(OK, "解密工具依赖", "可运行（%s）" % ok_py, "", "siwx")
        else:
            add(BAD, "解密工具依赖", "找不到装好 psutil/pycryptodome 的 Python，自动刷新必定失败",
                _siwx_dep_hint(siwx_run), "siwx")
    except Exception as exc:  # noqa: BLE001
        add(WARN, "解密工具依赖", "检查失败：%s" % exc, "手动跑一次：python tools\\refresh_data.py", "siwx")


def check_model():
    cfg = _settings() or {}
    key = (cfg.get("_env") or {}).get("api_key") or os.environ.get("DEEPSEEK_API_KEY") or ""
    if key and "your" not in key.lower():
        add(OK, "大模型 Key", "已配置（%s…）" % key[:6], "", "model_key")
    else:
        add(WARN, "大模型 Key", "没配置或还是占位符",
            "不配也能跑：总结降级为离线草稿，报告照样出。要用真模型：复制 .env.example 为 .env 填 DEEPSEEK_API_KEY",
            "model_key")
    vision = str(((cfg.get("vision") or {}).get("provider")) or "dummy")
    if vision in ("dummy", "", "none"):
        add(SKIP, "图片理解", "未启用（图片降级为占位）", "要识图：settings.yaml 的 vision.provider 改成你的服务",
            "vision")


def check_asr():
    if shutil.which("ffmpeg"):
        add(OK, "ffmpeg", "已安装（语音 SILK 转码用）", "", "ffmpeg")
    else:
        add(SKIP, "ffmpeg", "未安装：SILK 语音无法转码",
            "可选。要转语音：winget install Gyan.FFmpeg 或去 ffmpeg.org 下 Windows 版解压加 PATH",
            "ffmpeg")
    cfg = _settings() or {}
    model = str(((cfg.get("asr") or {}).get("model")) or "")
    if model:
        heavy = model in ("large-v3", "large-v2", "large")
        add(WARN if heavy else OK, "语音模型", model,
            "CPU 上 large 系列很慢（一段语音几十秒），建议 small 或 base" if heavy else "",
            "asr_model")


def check_service():
    """控制台是不是已经在跑；跑着就顺便问它一句 /health。"""
    port = _web_port()
    base = "http://127.0.0.1:%d" % port
    health = _http_json(base + "/health")
    if health and health.get("status") == "ok":
        other_root = str(health.get("root") or "")
        if other_root and os.path.normcase(os.path.normpath(other_root)) != \
                os.path.normcase(os.path.normpath(str(ROOT))):
            add(WARN, "本地控制台", "端口 %d 上是另一个副本：%s" % (port, other_root),
                "两份代码同时跑会互相抢端口/写同一份 runs。要用当前这份，先停掉那个进程再 "
                "python tools/launch.py；或者用 WEB_PORT=5720 换个端口",
                "service")
            return
        add(OK, "本地控制台", "已在运行（%s，v%s，已运行 %s 秒）" % (
            base, health.get("version", "?"), int(health.get("uptime_seconds") or 0)), "", "service")
        status = _http_json(base + "/api/status") or {}
        src = status.get("source_mode")
        if src:
            add(OK, "运行中的数据源", str(src), "", "service_source")
        return
    if _port_open(port):
        add(WARN, "本地控制台", "端口 %d 被别的程序占用（不是本项目的 /health）" % port,
            "换端口：改 config/settings.yaml 的 web.port，或设环境变量 WEB_PORT=5720", "service")
    else:
        add(SKIP, "本地控制台", "没在运行（%s 无法连接）" % base,
            "启动：双击 一键启动.bat，或 python tools/launch.py", "service")


def check_widget():
    if sys.platform != "win32":
        add(SKIP, "桌面悬浮窗", "非 Windows，跳过", "", "widget")
        return
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WeChatWorkHub"
    cards = base / "cards.json"
    if cards.exists():
        try:
            d = json.loads(cards.read_text(encoding="utf-8"))
            add(OK, "卡片数据", "%d 条（%s）" % (len(d.get("cards") or []),
                                             d.get("generated_at") or "?"), "", "widget_cards")
        except Exception:  # noqa: BLE001
            add(WARN, "卡片数据", "存在但解析失败", "删掉它，跑 python tools/make_daily_cards.py", "widget_cards")
    else:
        add(SKIP, "卡片数据", "还没有 cards.json（悬浮窗会显示空态）",
            "python tools/make_daily_cards.py  或加 --demo 看效果", "widget_cards")

    crash = base / "crash.log"
    if crash.exists():
        add(WARN, "悬浮窗崩溃日志", "存在 crash.log",
            "看最后 40 行：%s（常见原因见 docs/部署与排错-AI版.md 第 7 节）" % crash, "widget_crash")


# --------------------------------------------------------------------- 输出

def run_checks():
    results.clear()
    for fn in (check_python, check_venv, check_deps, check_platform, check_path,
               check_writable, check_config, check_datasource, check_siwx,
               check_model, check_asr, check_service, check_widget):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            add(WARN, "检查项 " + fn.__name__, "自己出错：%s" % exc,
                "这属于 doctor 的 bug，把这段贴给维护者", fn.__name__)
    return results


def to_json(rows) -> dict:
    checks = [{"id": r[4] or r[1], "level": r[0].strip(), "name": r[1],
               "detail": r[2], "fix": r[3]} for r in rows]
    bad = [c for c in checks if c["level"].startswith("❌")]
    warn = [c for c in checks if c["level"].startswith("⚠")]
    return {
        "ok": not bad,
        "root": str(ROOT),
        "python": sys.version.split()[0],
        "counts": {"fail": len(bad), "warn": len(warn), "total": len(checks)},
        "checks": checks,
        "next_actions": [c["fix"] for c in checks if c["fix"] and (c in bad or c in warn)],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="部署自检：这台机器能不能跑，还缺什么")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON（给 AI 用）")
    args = ap.parse_args(argv)

    rows = run_checks()
    if args.json:
        print(json.dumps(to_json(rows), ensure_ascii=False, indent=2))
        return 0 if not any(r[0] == BAD for r in rows) else 1

    print()
    print("=" * 68)
    print("  WeChat Work Hub · 部署自检")
    print("  项目路径：%s" % ROOT)
    print("  Python：%s" % sys.version.split()[0])
    print("=" * 68)
    print()
    for level, name, detail, _fix, _id in rows:
        print("%s %-16s %s" % (level, name, detail))

    fixes = [r for r in rows if r[3]]
    if fixes:
        print()
        print("-" * 68)
        print("  下一步（按顺序处理）")
        print("-" * 68)
        for level, name, _detail, fix, _id in fixes:
            if level == BAD or level == WARN:
                print("  %s %s" % ("→" if level == BAD else "·", name))
                print("     %s" % fix)

    bad = [r for r in rows if r[0] == BAD]
    warn = [r for r in rows if r[0] == WARN]
    print()
    print("=" * 68)
    if bad:
        print("  结论：有 %d 项必须先处理（❌）。处理完再跑一次本命令。" % len(bad))
    elif warn:
        print("  结论：可以跑（%d 项提醒，不影响主流程）。" % len(warn))
    else:
        print("  结论：环境完整，可以直接用。")
    print("  详细排错：docs/部署与排错-AI版.md")
    print("=" * 68)
    print()
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())