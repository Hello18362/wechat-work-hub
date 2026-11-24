# -*- coding: utf-8 -*-
"""控制台端到端链路自检（联系人 / 置顶 / 群列表 / 前端资源）。

用法：
    python tools/smoke_chain.py                # 进程内起一个临时服务自检
    python tools/smoke_chain.py --url http://127.0.0.1:5710   # 测已在跑的服务

为什么要这个脚本：
    之前反复出现「代码改好了、但浏览器报接口不存在」，根因是**服务进程还是旧的**
    （改了 .py 没重启），而单元测试和 py_compile 都发现不了。
    这个脚本把「前端资源 + 每个接口 + 数据规模」一次走通，专门堵这类问题。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

results: list[tuple[bool, str, str]] = []
skipped: list[tuple[str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((ok, name, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + ("  " + detail if detail else ""))
    return ok


def skip(name: str, reason: str = "") -> None:
    """这条现在没法验，但不是故障（例如样例数据没有联系人）。不计入失败。"""
    skipped.append((name, reason))
    print("  [SKIP] " + name + ("  " + reason if reason else ""))


def get(url: str, path: str, timeout: int = 30):
    with _OPENER.open(url + path, timeout=timeout) as r:
        return r.status, r.read()


def get_json(url: str, path: str, timeout: int = 30):
    status, body = get(url, path, timeout)
    return status, json.loads(body.decode("utf-8"))


def post_json(url: str, path: str, payload: dict, timeout: int = 30):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url + path, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with _OPENER.open(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def run_checks(url: str) -> bool:
    print("\n=== 1. 前端资源 ===")
    st, body = get(url, "/")
    html = body.decode("utf-8", "ignore")
    check(st == 200 and "<html" in html.lower(), "GET / 返回页面", "HTTP %s, %d bytes" % (st, len(body)))
    check('data-tab="friend"' in html, "页面含「好友」tab", "")
    check('data-tab="official"' in html, "页面含「公众号」tab", "")
    check('id="contactRoot"' in html, "页面含联系人详情弹窗", "")
    # 资源版本号：防止浏览器继续用缓存里的旧 app.js（旧界面点了没反应）
    check("{{ASSET_V}}" not in html and "?v=" in html, "首页资源带版本号（防旧缓存）", "")
    import re as _re

    m = _re.search(r'src="(/assets/app\.js\?v=\d+)"', html)
    if m:
        st, body = get(url, m.group(1))
        check(
            st == 200 and len(body) > 1000,
            "带 ?v= 访问 app.js 正常（服务端已剥查询串）",
            "HTTP %s, %d bytes" % (st, len(body)),
        )
    else:
        check(False, "首页未找到带版本号的 app.js 引用", "")

    st, body = get(url, "/assets/app.js")
    js = body.decode("utf-8", "ignore")
    check(st == 200 and "contactsMeta" in js, "app.js 是新版（含 contactsMeta）", "HTTP %s, %d bytes" % (st, len(body)))
    check("function openContact" in js, "app.js 含 openContact（条目可点击）", "")
    check("showNoisy" in js, "app.js 含无有效昵称开关", "")
    st, body = get(url, "/assets/style.css")
    css = body.decode("utf-8", "ignore")
    check(st == 200 and ".pop-hint" in css, "style.css 含联系人提示条样式", "")

    print("\n=== 2. 状态接口与能力自检 ===")
    st, d = get_json(url, "/api/status")
    feats = d.get("features") or []
    sample_mode = d.get("source_mode") == "sample"
    check(st == 200 and d.get("ok"), "GET /api/status 正常", "HTTP %s" % st)
    check("contacts" in feats, "服务端声明 contacts 能力（旧进程不会有）", "features=%s" % feats)
    check("pin" in feats, "服务端声明 pin 能力", "")
    # 别用 chatlog_online 判连通：样例模式下它恒为 true（是「客户端可用」，
    # 不是「chatlog 服务在线」）。只看 source_mode 与 data_source_ready。
    check(d.get("source_mode") in ("sqlite", "chatlog", "sample"),
          "source_mode 是已知取值", "source_mode=%s" % d.get("source_mode"))
    if d.get("data_source_ready") is None:
        # 老服务端没有这个字段（用户改了 Python 但没重启服务）——别判失败，
        # 提示重启即可，否则看起来像「装坏了」。
        skip("数据源可用（不等于 chatlog 服务在线）", "服务端是旧版本，没有该字段；重启服务再测")
    else:
        check(d.get("data_source_ready") is True, "数据源可用（不等于 chatlog 服务在线）",
              "data_source_ready=%s, chatlog_reachable=%s" % (
                  d.get("data_source_ready"), d.get("chatlog_reachable")))
    if sample_mode:
        print("       数据源 = 内置样例（没有真实联系人/公众号，下面相关项记为 SKIP 而不是失败）")

    print("\n=== 3. 群列表 / 置顶 ===")
    st, d = get_json(url, "/api/groups")
    groups = d.get("groups") or []
    check(st == 200 and len(groups) > 0, "GET /api/groups 有数据", "%d 个群" % len(groups))
    check(all("pinned" in g for g in groups), "每个群都带 pinned 字段", "")
    pinned = [g["name"] for g in groups if g.get("pinned")]
    check(True, "当前置顶群", str(pinned[:5]))

    target = groups[0]["name"]
    was = bool(groups[0].get("pinned"))
    st, d = post_json(url, "/api/groups/pin", {"group": target, "pinned": not was})
    check(st == 200 and d.get("ok") and d.get("pinned") == (not was), "POST /api/groups/pin 可切换", "HTTP %s" % st)
    st, d2 = get_json(url, "/api/groups")
    hit = [g for g in d2["groups"] if g["name"] == target]
    check(bool(hit) and bool(hit[0].get("pinned")) == (not was), "置顶状态已持久化并回读一致", "")
    post_json(url, "/api/groups/pin", {"group": target, "pinned": was})  # 还原
    check(True, "已还原置顶状态", "%s -> %s" % (target, was))

    print("\n=== 4. 联系人（核心）===")
    st, d = get_json(url, "/api/contacts?category=friend&limit=200")
    cs = d.get("contacts") or []
    total = d.get("total")
    check(st == 200 and d.get("ok"), "GET /api/contacts 正常", "HTTP %s" % st)
    # 三种数据源里，只有接真实微信记录才有联系人；样例数据本来就没有。
    if sample_mode or (isinstance(total, int) and total == 0):
        skip("好友总数 > 0", "当前数据源没有联系人（样例数据，或没配 WX_DECRYPTED_DIR）")
        skip("返回了好友条目", "同上")
    else:
        check(isinstance(total, int) and total > 0, "好友总数 > 0", "total=%s" % total)
        check(len(cs) > 0, "返回了好友条目", "本次返回 %d 条" % len(cs))
    check(len(cs) <= 200, "条数被 limit 限制（防前端卡死）", "返回 %d / 上限 200" % len(cs))
    check("truncated" in d and "matched" in d, "返回 total/matched/truncated 元信息", "")
    if cs:
        check(all("name" in c and "id" in c for c in cs), "条目字段完整（name/id）", "")
        check(
            all(("display" in c and "noisy" in c) for c in cs),
            "条目含 display / noisy（可识别无有效昵称）",
            "本页 noisy=%d" % sum(1 for c in cs if c.get("noisy")),
        )
        check(
            all((c.get("display") or "") for c in cs),
            "每条都有可读展示名（不会出现空名）",
            "",
        )
        print("       样例：", [c["name"] for c in cs[:5]])

    st, d = get_json(url, "/api/contacts?category=official&limit=200")
    offs = d.get("contacts") or []
    if sample_mode or not offs:
        skip("公众号列表有数据", "当前数据源没有公众号")
    else:
        check(st == 200 and len(offs) > 0, "公众号列表有数据", "%d 个" % len(offs))

    # 关键词搜索：拿一个真实好友名的片段去查，必须能命中
    if cs:
        kw = cs[0]["name"][:2]
        from urllib.parse import quote
        st, d = get_json(url, "/api/contacts?category=friend&limit=200&q=" + quote(kw))
        check(st == 200 and d.get("matched", 0) >= 1, "关键词搜索可命中", "q=%r matched=%s" % (kw, d.get("matched")))
        check(d.get("q") == kw, "服务端回显关键词", "")

    print("\n=== 5. 报告与任务接口 ===")
    st, d = get_json(url, "/api/runs")
    check(st == 200 and d.get("ok"), "GET /api/runs 正常", "HTTP %s, %d 份报告" % (st, len(d.get("runs") or [])))
    st, d = get_json(url, "/api/task")
    check(st == 200, "GET /api/task 正常", "HTTP %s" % st)

    failed = [r for r in results if not r[0]]
    print("\n" + "=" * 56)
    print("  总计 %d 项，通过 %d，失败 %d，跳过 %d" % (
        len(results) + len(skipped), len(results) - len(failed), len(failed), len(skipped)))
    if failed:
        print("  失败项：")
        for _, name, detail in failed:
            print("    - %s %s" % (name, detail))
    if skipped:
        print("  跳过项（不算失败）：")
        for name, reason in skipped:
            print("    - %s %s" % (name, reason))
    print("=" * 56)
    return not failed


def main() -> int:
    ap = argparse.ArgumentParser(description="控制台链路自检")
    ap.add_argument("--url", help="测试已在运行的服务，如 http://127.0.0.1:5710")
    ap.add_argument("--port", type=int, default=5788, help="进程内临时服务端口")
    args = ap.parse_args()

    if args.url:
        print("测试目标（外部服务）：", args.url)
        return 0 if run_checks(args.url.rstrip("/")) else 1

    from core.config import load_settings
    from web import server as srv

    cfg = load_settings()
    # 自检不需要自动解密，避免干扰
    cfg.setdefault("chatlog", {}).setdefault("auto_refresh", {})["enabled"] = False
    server, url = srv.build(cfg, host="127.0.0.1", port=args.port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.6)
    print("测试目标（进程内临时服务）：", url)
    try:
        ok = run_checks(url)
    finally:
        server.shutdown()
        server.server_close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
