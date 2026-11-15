# -*- coding: utf-8 -*-
"""把 runs/ 里的报告批量转成「对外分享版」，并生成一个合集首页。

分享版做了三件事：
    1. 去掉「聊天记录」整节——不把群里其他人的原话发出去；
    2. 对手机号 / 身份证 / 邮箱打码；
    3. 页面上标注「摘要版」。

产物：share/ 目录（每份一个 HTML）+ share/index.html（合集首页）。
整个 share/ 目录可以直接拖到 Vercel / GitHub Pages / 任意静态托管。

用法：
    python tools/make_share.py                # 转换 runs/ 下全部报告
    python tools/make_share.py --limit 5      # 只转最近 5 份
    python tools/make_share.py --out my_share # 自定义输出目录
"""
from __future__ import annotations

import argparse
import html as html_mod
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from output.html import render_report, safe_filename  # noqa: E402


def parse_markdown(md_path: Path) -> dict | None:
    """从报告 Markdown 里抽出元信息 + 总结正文（不含聊天记录）。"""
    text = md_path.read_text(encoding="utf-8", errors="ignore")

    # 标题：# 群名 · 日期 工作简报
    m = re.match(r"^#\s*(?P<group>.+?)\s*·\s*(?P<date>\d{4}-\d{2}-\d{2})", text)
    if not m:
        return None
    group = m.group("group").strip()
    date = m.group("date")

    def grab(pattern: str, default: int = 0) -> int:
        hit = re.search(pattern, text)
        return int(hit.group(1)) if hit else default

    total = grab(r"\*\*消息总数\*\*[：:]\s*(\d+)")
    leaders = grab(r"\*\*领导发言数\*\*[：:]\s*(\d+)")

    counts: dict[str, int] = {}
    dist = re.search(r"分布[：:]\s*(.+)", text)
    if dist:
        for label, num in re.findall(r"(\S+?)\s*(\d+)", dist.group(1)):
            if label:
                counts[label] = int(num)

    # 总结正文：从 ## 总结 到 ## 聊天记录（或文件末尾）
    start = text.find("## 总结")
    if start < 0:
        return None
    body_start = start + len("## 总结")
    end = text.find("## 聊天记录", body_start)
    summary = (text[body_start:end] if end > 0 else text[body_start:]).strip()
    if not summary:
        return None

    return {
        "group": group,
        "date": date,
        "total": total,
        "leaders": leaders,
        "counts": counts,
        "summary": summary,
    }


def build_index(entries: list[dict], out_dir: Path) -> Path:
    """生成合集首页（同样对外分享，样式与报告一致的黑白极简）。"""
    rows = []
    for item in entries:
        name = html_mod.escape(item["group"])
        rows.append(
            f'<a class="card" href="{html_mod.escape(item["file"])}">'
            f'<span class="date">{item["date"]}</span>'
            f'<span class="group">{name}</span>'
            f'<span class="meta">{item["total"]} 条消息 · {item["leaders"]} 条领导发言</span>'
            f"</a>"
        )
    body = "\n".join(rows) or '<p class="empty">还没有报告</p>'

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>群聊工作简报 · 合集</title>
<style>
  :root{{--bg:#f6f6f4;--ink:#121212;--ink-2:#5c5c5c;--line:#e2e2df;--accent:#FF5C28}}
  *{{box-sizing:border-box}}
  body{{margin:0;padding:40px 20px;background:var(--bg);color:var(--ink);
       font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}
  .wrap{{max-width:760px;margin:0 auto}}
  h1{{font-size:26px;margin:0 0 6px}}
  .sub{{color:var(--ink-2);font-size:13px;margin-bottom:28px;line-height:1.6}}
  .list{{display:flex;flex-direction:column;gap:10px}}
  .card{{display:flex;flex-direction:column;gap:4px;padding:16px 18px;background:#fff;
        border:1px solid var(--line);border-radius:14px;text-decoration:none;color:inherit;
        transition:transform .25s cubic-bezier(.22,1.35,.36,1),border-color .25s ease}}
  .card:hover{{transform:translateY(-2px);border-color:var(--ink)}}
  .date{{font-size:12px;color:var(--accent);font-weight:700;letter-spacing:.02em}}
  .group{{font-size:16px;font-weight:700}}
  .meta{{font-size:12px;color:var(--ink-2)}}
  .empty{{color:var(--ink-2)}}
  .foot{{margin-top:32px;font-size:12px;color:var(--ink-2);line-height:1.7;
        border-top:1px solid var(--line);padding-top:16px}}
</style>
</head>
<body>
<div class="wrap">
  <h1>群聊工作简报</h1>
  <p class="sub">AI 提炼的摘要版 · 不含群内聊天原文 · 手机号等信息已打码<br>
     生成时间 {datetime.now():%Y-%m-%d %H:%M}</p>
  <div class="list">
{body}
  </div>
  <p class="foot">本页面由 WeChat Work Hub 本地生成。内容为 AI 摘要，可能存在偏差，仅供内部参考。</p>
</div>
</body>
</html>
"""
    target = out_dir / "index.html"
    target.write_text(page, encoding="utf-8")
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description="生成对外分享版报告")
    ap.add_argument("--runs", default=str(ROOT / "runs"), help="报告来源目录")
    ap.add_argument("--out", default=str(ROOT / "share"), help="输出目录")
    ap.add_argument("--limit", type=int, default=0, help="只处理最近 N 份（0 = 全部）")
    args = ap.parse_args()

    runs_dir = Path(args.runs)
    out_dir = Path(args.out)
    if not runs_dir.exists():
        print("找不到报告目录：", runs_dir)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    md_files = sorted(runs_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if args.limit > 0:
        md_files = md_files[: args.limit]

    entries: list[dict] = []
    skipped = 0
    for md in md_files:
        info = parse_markdown(md)
        if not info:
            skipped += 1
            continue
        stats = {
            "total": info["total"],
            "leader_count": info["leaders"],
            "counts": info["counts"],
            "span_minutes": 0,
            "top_speakers": [],
        }
        html_text = render_report(
            info["summary"],
            [],                      # 分享版不需要消息原文
            info["group"],
            info["date"],
            stats=stats,
            title=f'{info["group"]} · {info["date"]} 工作简报（分享版）',
            share=True,
        )
        fname = f'{info["date"]}_{safe_filename(info["group"])}.html'
        (out_dir / fname).write_text(html_text, encoding="utf-8")
        entries.append({**info, "file": fname})

    # 按日期倒序
    entries.sort(key=lambda e: (e["date"], e["group"]), reverse=True)
    index = build_index(entries, out_dir)

    print("已生成 %d 份分享版报告" % len(entries))
    if skipped:
        print("跳过 %d 份（无总结或格式不符）" % skipped)
    print("输出目录：", out_dir)
    print("合集首页：", index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
