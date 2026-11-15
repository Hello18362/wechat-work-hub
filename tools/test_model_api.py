"""模型配置接口的端到端验证：起真实服务、打真实接口、改完恢复原配置。"""
from __future__ import annotations

import json
import shutil
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(r"D:/path-to-project/product/wechat-work-hub")
sys.path.insert(0, str(ROOT))

ENV = ROOT / ".env"
SETTINGS = ROOT / "config" / "settings.yaml"
BAK_ENV = ROOT / ".env.__testbak"
BAK_SETTINGS = ROOT / "config" / "settings.yaml.__testbak"

shutil.copy2(ENV, BAK_ENV)
shutil.copy2(SETTINGS, BAK_SETTINGS)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (("  <- " + detail) if detail else ""))


try:
    from core.config import load_settings
    from web.server import build

    cfg = load_settings()
    cfg.setdefault("chatlog", {})["auto_refresh"] = {"enabled": False}
    server, url = build(cfg, port=5799)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(path: str):
        with opener.open(url + path, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def post(path: str, payload: dict):
        req = urllib.request.Request(
            url + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with opener.open(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    # 1. 读取配置
    st, body = get("/api/model")
    check("GET /api/model 返回 200", st == 200)
    check("返回 9 个服务商预设", len(body.get("presets") or []) == 9, str(len(body.get("presets") or [])))
    check("识别出已保存 Key", body.get("has_key") is True)
    hint = body.get("key_hint") or ""
    check("Key 已打码（含 * 且不含明文）", "*" in hint and len(hint) <= 13, hint)
    check("不下发明文 Key", "api_key" not in body)

    # 2. 测试连接：给一个必然连不上的本地端口，验证错误被翻译成人话
    st, body = post(
        "/api/model/test",
        {"api_key": "sk-test-not-real", "base_url": "http://127.0.0.1:9", "model": "x"},
    )
    check("连不上时返回 ok=False", st == 200 and body.get("ok") is False)
    check("错误信息可读（不是裸异常）", "连不上" in (body.get("message") or ""), body.get("message", ""))

    # 3. 测试连接：前端留空 Key 时，服务端应回退到「已保存的 Key」而不是报「未填」
    st, body = post("/api/model/test", {"api_key": "", "base_url": "http://127.0.0.1:9", "model": "q"})
    check(
        "空 Key 自动回退到已保存 Key（不报未填）",
        body.get("message") != "还没填 API Key",
        body.get("message", ""),
    )
    check(
        "回退后仍给出连接失败的可读原因",
        "连不上" in (body.get("message") or ""),
        body.get("message", ""),
    )

    # 4. 保存：在线模式，Key 留空应沿用原 Key，且不破坏 .env 其他键
    before_env = ENV.read_text(encoding="utf-8")
    st, body = post(
        "/api/model",
        {
            "provider": "openai",
            "api_key": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen2.5:7b",
        },
    )
    after_env = ENV.read_text(encoding="utf-8")
    check("保存在线配置成功", st == 200 and body.get("ok") is True, str(body)[:120])
    check("模式变为 online", body.get("mode") == "online", str(body.get("mode")))
    check("Key 留空时沿用原值（未清空）", "DEEPSEEK_API_KEY=\n" not in after_env)
    check("未破坏 WX_DECRYPTED_DIR", "WX_DECRYPTED_DIR=" in after_env)
    check("Base URL 已写入", "DEEPSEEK_BASE_URL=http://127.0.0.1:11434/v1" in after_env)
    check(".env 注释未被清空", after_env.count("#") >= before_env.count("#") - 1)

    settings_text = SETTINGS.read_text(encoding="utf-8")
    check("settings.yaml 的 provider 已改为 openai", 'provider: "openai"' in settings_text)
    check("settings.yaml 注释保留", "# deepseek   = 接 DeepSeek" in settings_text)
    check("vision 区块未被误改", 'provider: "dummy"' in settings_text)

    # 5. 保存：非法 provider
    st, body = post("/api/model", {"provider": "hack", "api_key": "x", "base_url": "http://a", "model": "m"})
    check("非法 provider 被拒绝（400）", st == 400 and body.get("ok") is False)

    # 6. 保存：在线模式缺 Base URL
    st, body = post("/api/model", {"provider": "deepseek", "api_key": "x", "base_url": "", "model": "m"})
    check("缺 Base URL 被拒绝（400）", st == 400)

    # 7. 切回离线模式
    st, body = post("/api/model", {"provider": "file_output", "api_key": "", "base_url": "", "model": ""})
    check("切回离线模式成功", st == 200 and body.get("mode") == "offline", str(body.get("mode")))

    # 8. 静态资源仍可访问（确保没把页面改坏）
    with opener.open(url + "/", timeout=10) as r:
        html = r.read().decode("utf-8")
    check("首页可访问且含模型入口", r.status == 200 and 'id="modelBtn"' in html)
    check("资源版本号已注入", "{{ASSET_V}}" not in html)

    server.shutdown()
finally:
    shutil.copy2(BAK_ENV, ENV)
    shutil.copy2(BAK_SETTINGS, SETTINGS)
    BAK_ENV.unlink(missing_ok=True)
    BAK_SETTINGS.unlink(missing_ok=True)
    print("\n已恢复 .env 与 settings.yaml")

total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== {passed}/{total} 通过 =====")
sys.exit(0 if passed == total else 1)
