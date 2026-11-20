#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 demo-site 打包成「单个自包含 HTML」。

为什么需要它
------------
演示站是 4 个文件（index.html / style.css / demo.css / app.js / mock-api.js），
用微信发出去只能发**一个文件**，对方点开就是没有任何样式的白页
（CSS/JS 全部 404），状态永远停在「正在检测服务…」。

这个脚本把 CSS、JS、示例报告全部内联进一个 .html，
发微信、发邮件、扔 U 盘都能直接双击打开；手机端另加了适配样式。

用法
----
    python tools/build_singlefile.py

产物
----
    demo-site/dist/WeChatWorkHub-演示-单文件.html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent / "demo-site"
OUT_DIR = SITE / "dist"
OUT_FILE = OUT_DIR / "WeChatWorkHub-演示-单文件.html"

# 报告文件 → 内联进页面（单文件下没有 reports/ 目录）
REPORTS = ["demo-report-1.html", "demo-report-2.html", "demo-report-3.html"]

# 手机 / 微信内置浏览器适配。只在小屏生效，不改动桌面观感。
MOBILE_CSS = """
/* ===== 单文件版：提示条改为文档流首元素（微信里 fixed 会压住吸顶导航） ===== */
#demoBanner{position:static}

/* ===== 手机适配（build_singlefile 注入，小屏才生效） ===== */
@media (max-width:640px){
  html{-webkit-text-size-adjust:100%}
  .nav{padding:10px 14px;gap:10px}
  .nav-mark{width:28px;height:28px;border-radius:9px;font-size:11px}
  .nav-title{font-size:17px}
  .nav-sub{display:none}
  .nav-widget{display:none}
  .status{font-size:11px}
  .status-text{display:none}          /* 窄屏只留状态点 */
  .status-dot{width:7px;height:7px}
  .wrap{padding:0 14px 64px}
  .hero{grid-template-columns:1fr;gap:12px;margin:12px 0 16px}
  .hero-card{padding:18px;min-height:0}
  .hero-num{font-size:54px}
  .hero-sub{font-size:12px}
  .board{padding:14px}
  .board-row{flex-direction:column;align-items:stretch;gap:10px}
  .field{width:100%}
  .control{width:100%;min-width:0}
  .field-inline{padding-bottom:0}
  .board-actions{margin-left:0;width:100%;gap:8px}
  .board-actions>*{flex:1;justify-content:center;white-space:nowrap}
  .pop{min-width:0;left:0;right:0;width:auto;max-width:none}
  .cal-grid{font-size:12px}
  .content-head{gap:8px;flex-wrap:wrap}
  .section-title{font-size:16px}
  .foot{flex-direction:column;gap:4px;font-size:11px}
  .to-top{right:14px;bottom:14px}
}
"""


def read(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


def strip_bom(text: str) -> str:
    return text[1:] if text.startswith("\ufeff") else text


def js_safe(text: str) -> str:
    """把字符串塞进 <script> 里：转义 </ 防止提前闭合脚本标签。"""
    return text.replace("</", "<\\/")


def build() -> Path:
    html = read("index.html")
    style = strip_bom(read("style.css"))
    demo_css = strip_bom(read("demo.css"))
    mock = strip_bom(read("mock-api.js"))
    app = strip_bom(read("app.js"))

    # ---- 1. 内联样式 ----
    css_all = (
        "/* ===== style.css ===== */\n" + style
        + "\n/* ===== demo.css ===== */\n" + demo_css
        + "\n" + MOBILE_CSS
    )
    for link in ('<link rel="stylesheet" href="style.css">',
                 '<link rel="stylesheet" href="demo.css">'):
        if link not in html:
            raise SystemExit("[x] index.html 里找不到 %s，模板可能改过了" % link)
        html = html.replace(link, "")
    html = html.replace("</head>", "<style>\n" + css_all + "\n</style>\n</head>")

    # ---- 2. 示例报告内联 ----
    reports = {}
    for name in REPORTS:
        p = SITE / "reports" / name
        if not p.exists():
            print("[!] 缺少示例报告：%s（跳过）" % name)
            continue
        reports[name] = strip_bom(p.read_text(encoding="utf-8"))
    payload = json.dumps(reports, ensure_ascii=False)

    # ---- 2.5 演示提示条：直接写进文档流最前面（多文件版由 JS 追加） ----
    banner = (
        '<div id="demoBanner"><span class="demo-dot"></span>'
        "<strong>演示模式</strong>"
        '<span class="demo-text">页面为沙盘演示，所有群聊、联系人和报告内容均为示例数据，'
        "不含任何真实信息。可自由点击体验。</span></div>"
    )
    if "<body>" in html:
        html = html.replace("<body>", "<body>\n" + banner, 1)
    else:
        raise SystemExit("[x] index.html 里找不到 <body>")

    # ---- 3. 内联脚本 ----
    html = html.replace(
        '<script src="mock-api.js"></script>',
        "<script>\nwindow.__DEMO_REPORTS__ = " + js_safe(payload) + ";\n"
        + js_safe(mock) + "\n</script>",
    )
    if '<script src="app.js"></script>' not in html:
        raise SystemExit("[x] index.html 里找不到 app.js 的 script 标签")
    html = html.replace(
        '<script src="app.js"></script>',
        "<script>\n" + js_safe(app) + "\n</script>",
    )

    # ---- 4. 去掉指向 widget.html 的导航（单文件里没有那个页面） ----
    html = html.replace(
        '<a class="nav-widget" href="widget.html"><span class="wd"></span>桌面悬浮窗</a>',
        '<!-- 单文件版不含「桌面悬浮窗」演示页（需在电脑上打开 widget.html） -->',
    )

    # ---- 5. 标题标注版本 ----
    html = html.replace(
        "<title>WeChat Work Hub · 控制台（演示版）</title>",
        "<title>WeChat Work Hub · 控制台（演示版 · 单文件）</title>",
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(html, encoding="utf-8")

    # ---- 自检：不许再有外部引用 ----
    bad = []
    for token in ('src="mock-api.js"', 'src="app.js"', 'href="style.css"',
                  'href="demo.css"', 'href="widget.html"'):
        if token in html:
            bad.append(token)
    if bad:
        raise SystemExit("[x] 仍有外部引用：%s" % ", ".join(bad))

    kb = OUT_FILE.stat().st_size / 1024
    print("[ok] %s" % OUT_FILE)
    print("     大小 %.0f KB · 内联报告 %d 份 · 无外部依赖" % (kb, len(reports)))
    return OUT_FILE


if __name__ == "__main__":
    try:
        build()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print("[x] 打包失败：%s" % exc)
        sys.exit(1)
