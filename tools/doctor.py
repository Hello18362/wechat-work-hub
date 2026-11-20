# -*- coding: utf-8 -*-
"""部署自检：一条命令告诉你「这台机器上能不能跑，还缺什么」。

    python tools/doctor.py

只检查、不修改任何东西。所有检查项都用标准库实现，
即使第三方依赖没装齐也能跑起来（会告诉你缺哪个）。
"""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OK = "✅"
WARN = "⚠️ "
BAD = "❌"
SKIP = "➖"

results = []          # (级别, 项目, 说明, 建议)


def add(level, name, detail, fix=""):
    results.append((level, name, detail, fix))


# --------------------------------------------------------------------- 检查项

def check_python():
    v = sys.version_info
    ver = "%d.%d.%d" % (v.major, v.minor, v.micro)
    if v >= (3, 10):
        add(OK, "Python 版本", ver)
    else:
        add(BAD, "Python 版本", "%s（需要 3.10+）" % ver,
            "去 https://www.python.org/downloads/ 装 3.11 或更新版本")
    add(OK if v < (3, 13) else WARN, "Python 兼容性",
        ver,
        "" if v < (3, 13) else "3.13 上部分依赖可能还没发轮子，推荐 3.11")


def check_deps():
    required = [
        ("requests", "HTTP 请求（采集 / 调模型）"),
        ("yaml", "读 config/*.yaml"),
        ("bs4", "解析公众号文章正文"),
        ("PIL", "渲染桌面卡片与悬浮窗"),
    ]
    for mod, why in required:
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, "__version__", "")
            add(OK, "依赖 " + mod, ("%s  " % ver) + why)
        except Exception as exc:  # noqa: BLE001
            add(BAD, "依赖 " + mod, "缺失（%s）" % why,
                "pip install -e .   # 或单独 pip install %s" %
                {"yaml": "PyYAML", "bs4": "beautifulsoup4", "PIL": "Pillow"}.get(mod, mod))

    optional = [
        ("faster_whisper", "语音转写", "可选：不装则语音降级为 [语音]"),
        ("markdown", "Markdown→HTML", "可选：不装走内置简易渲染"),
    ]
    for mod, why, note in optional:
        try:
            importlib.import_module(mod)
            add(OK, "可选 " + mod, why)
        except Exception:  # noqa: BLE001
            add(SKIP, "可选 " + mod, note)


def check_platform():
    plat = sys.platform
    if plat == "win32":
        add(OK, "操作系统", "Windows（悬浮窗可用）")
    else:
        add(WARN, "操作系统", "%s（悬浮窗不可用）" % plat,
            "采集 / AI 报告 / 本地控制台可以正常用，只有桌面悬浮窗是 Windows 专属")


def check_fonts():
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    hit = next((p for p in candidates if os.path.exists(p)), None)
    if hit:
        add(OK, "中文字体", os.path.basename(hit))
    else:
        add(WARN, "中文字体", "没找到常见中文字体",
            "卡片中文可能显示为方块。Windows 装「微软雅黑」，Linux 装 fonts-noto-cjk")


def check_config():
    env = ROOT / ".env"
    if env.exists():
        add(OK, ".env", "存在")
        txt = env.read_text(encoding="utf-8", errors="replace")
        key = ""
        for line in txt.splitlines():
            if line.strip().startswith("DEEPSEEK_API_KEY="):
                key = line.split("=", 1)[1].strip()
        if not key or "your_api_key" in key:
            add(WARN, "大模型 Key", "没配置或还是占位符",
                "不配也能跑：会在 runs/pending/ 生成待处理文件，手动交给任意 AI 即可")
        else:
            add(OK, "大模型 Key", "已配置（%s…）" % key[:6])
    else:
        add(BAD, ".env", "不存在",
            "copy .env.example .env  然后填 WX_DECRYPTED_DIR 和 DEEPSEEK_API_KEY")

    groups = ROOT / "config" / "groups.yaml"
    if groups.exists():
        add(OK, "config/groups.yaml", "存在")
    else:
        add(BAD, "config/groups.yaml", "不存在",
            "copy config\\groups.example.yaml config\\groups.yaml")


def check_datasource():
    """能不能读到微信解密库，这是整条链路的前提。"""
    cfg = None
    try:
        from core.config import load_settings
        cfg = load_settings()
    except Exception as exc:  # noqa: BLE001
        add(WARN, "配置加载", "失败：%s" % exc, "检查 config/settings.yaml 是否为合法 YAML")
        return

    dec = str((cfg.get("chatlog") or {}).get("decrypted_dir") or "")
    if not dec:
        add(BAD, "微信解密目录", "没配置",
            "在 .env 里写 WX_DECRYPTED_DIR=解密工具输出的目录（含 message/message_0.db）")
        return

    if not os.path.isdir(dec):
        add(BAD, "微信解密目录", "配置了但目录不存在：%s" % dec,
            "确认解密工具是否正常输出，或改 .env 里的路径")
        return

    db = Path(dec) / "message" / "message_0.db"
    if not db.exists():
        add(BAD, "消息数据库", "缺少 message/message_0.db",
            "解密工具没有输出完整，重新解密一次")
        return

    add(OK, "微信解密目录", dec)
    try:
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
            import datetime
            t = datetime.datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M")
            add(OK, "消息数据库", "%d 张表，最新消息 %s" % (len(tables), t))
        else:
            add(WARN, "消息数据库", "能打开但没读到消息",
                "微信可能没登录，或者解密的是空库")
    except Exception as exc:  # noqa: BLE001
        add(WARN, "消息数据库", "读取失败：%s" % exc,
            "可能正被微信占用，稍后再试")


def check_widget():
    """悬浮窗专用的几项。"""
    if sys.platform != "win32":
        add(SKIP, "桌面悬浮窗", "非 Windows，跳过")
        return

    try:
        importlib.import_module("PIL.Image")
        add(OK, "悬浮窗依赖", "Pillow 可用")
    except Exception:  # noqa: BLE001
        add(BAD, "悬浮窗依赖", "缺 Pillow", "pip install Pillow")
        return

    cards = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WeChatWorkHub" / "cards.json"
    if cards.exists():
        try:
            import json
            d = json.loads(cards.read_text(encoding="utf-8"))
            add(OK, "卡片数据", "%d 条（%s）" % (len(d.get("cards") or []),
                                             d.get("generated_at") or "?"))
        except Exception:  # noqa: BLE001
            add(WARN, "卡片数据", "文件存在但解析失败", "删掉它，跑一次 make_daily_cards.py")
    else:
        add(WARN, "卡片数据", "还没有 cards.json",
            "python tools/make_daily_cards.py  或先用 --demo 看效果")


def check_optional_tools():
    if shutil.which("ffmpeg"):
        add(OK, "ffmpeg", "已安装（语音 SILK 转码用）")
    else:
        add(SKIP, "ffmpeg", "未安装：语音消息会降级为 [语音]")


# --------------------------------------------------------------------- 输出

def main() -> int:
    print()
    print("=" * 64)
    print("  WeChat Work Hub · 部署自检")
    print("  项目路径：%s" % ROOT)
    print("=" * 64)
    print()

    check_python()
    check_deps()
    check_platform()
    check_fonts()
    check_config()
    check_datasource()
    check_widget()
    check_optional_tools()

    bad = [r for r in results if r[0] == BAD]
    warn = [r for r in results if r[0] == WARN]

    for level, name, detail, fix in results:
        print("%s %-18s %s" % (level, name, detail))

    fixes = [r for r in results if r[3]]
    if fixes:
        print()
        print("-" * 64)
        print("  需要处理")
        print("-" * 64)
        for level, name, detail, fix in fixes:
            print("  %s %s" % ("→" if level == BAD else "·", name))
            print("     %s" % fix)

    print()
    print("=" * 64)
    if bad:
        print("  结论：还差 %d 项必需条件，先按上面的建议处理。" % len(bad))
    elif warn:
        print("  结论：可以跑起来，但有 %d 项需要注意（不影响主流程）。" % len(warn))
    else:
        print("  结论：环境完整，可以直接用。")
    print("=" * 64)
    print()
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
