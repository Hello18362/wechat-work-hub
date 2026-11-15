"""手动刷新微信解密数据。

给「刷新数据.bat」调用。路径推断完全复用控制台的自动刷新逻辑
（配置 > 环境变量 > 从解密目录上溯），所以换一台电脑、换一个目录都不用改脚本。

用法:
    python tools/refresh_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.auto_refresh import AutoRefresher, _resolve_siwx_run  # noqa: E402
from core.config import load_settings  # noqa: E402


def main() -> int:
    """跑一次解密并打印结果。"""
    try:
        cfg = load_settings()
    except Exception as exc:  # noqa: BLE001
        print(f"配置加载失败：{exc}")
        return 1

    decrypted = (cfg.get("chatlog") or {}).get("decrypted_dir") or ""
    if not decrypted:
        print("还没有配置解密目录。")
        print("请在项目根目录的 .env 里填一行：")
        print("    WX_DECRYPTED_DIR=C:/你的路径/siwx/output/wxid_xxxx")
        return 1

    print(f"解密目录：{decrypted}")
    siwx = _resolve_siwx_run(cfg)
    if siwx:
        print(f"解密工具：{siwx}")
    else:
        print("没找到 SIWX 的 run.py，将直接使用现有解密数据（可能不是最新的）。")

    refresher = AutoRefresher(cfg)
    ok = refresher.refresh_once(force=True)
    if ok:
        print("\n完成：解密数据已刷新。")
        return 0

    print(f"\n刷新失败：{refresher.last_error or '未知原因'}")
    print("如果只是想用现有数据，可以直接启动控制台，不影响已解密的部分。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
