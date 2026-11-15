"""一键启动：清理旧进程 → 后台拉起控制台 → 等端口就绪 → 打开浏览器。

为什么把逻辑从 .bat 挪到这里：
批处理里做「找 Python、拼路径、判断端口」很容易在别人的机器上出错，而且
没法测试。放到 Python 里逻辑可读、可跑测试、出错也有明确的中文提示。

用法（由 一键启动.bat 调用）：
    python tools/launch.py
    python tools/launch.py --no-browser     # 调试用，不弹浏览器
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 5710


def _read_port() -> int:
    """从 settings.yaml 读端口；读不到就用 5710（配置坏了也不该启动不了）。"""
    try:
        import yaml

        cfg = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}
        return int((cfg.get("web") or {}).get("port", DEFAULT_PORT))
    except Exception:  # noqa: BLE001
        return DEFAULT_PORT


def _port_open(port: int) -> bool:
    """端口上有没有服务在监听。"""
    with socket.socket() as sock:
        sock.settimeout(0.6)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _pids_listening(port: int) -> list[str]:
    """找出正在监听该端口的进程 PID。"""
    try:
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            encoding="gbk",
            errors="replace",
        ).stdout
    except OSError:
        return []
    pids: list[str] = []
    for line in out.splitlines():
        parts = line.split()
        # 形如：TCP  127.0.0.1:5710  0.0.0.0:0  LISTENING  23088
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
            if parts[4].isdigit() and parts[4] not in pids:
                pids.append(parts[4])
    return pids


def _is_python_process(pid: str) -> bool:
    """确认这个 PID 是 Python 进程，避免误杀别的东西。"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="gbk",
            errors="replace",
        ).stdout
    except OSError:
        return False
    return "python" in out.lower()


def main() -> int:
    """启动控制台，返回退出码。"""
    port = _read_port()
    print(f"项目目录：{ROOT}")

    entry = ROOT / "tools" / "serve_hidden.py"
    if not entry.exists():
        print(f"找不到启动文件：{entry}")
        print("请确认这个脚本位于项目根目录的 tools/ 目录下，且没有被单独拷贝到别处。")
        return 1

    # 1) 清理旧进程（只杀 Python，别人的程序不动）
    for pid in _pids_listening(port):
        if not _is_python_process(pid):
            print(f"端口 {port} 被其他程序占用（PID {pid}），请先关闭它再试。")
            return 1
        print(f"关闭旧的 Python 服务（PID {pid}）")
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)

    for _ in range(20):
        if not _port_open(port):
            break
        time.sleep(0.3)

    if _port_open(port):
        print(f"端口 {port} 仍被占用，无法启动。")
        return 1

    # 2) 后台拉起（pythonw 无窗口；没有就退回 python，只是会多一个黑窗口）
    launcher = Path(sys.executable)
    pythonw = launcher.with_name("pythonw.exe")
    if pythonw.exists():
        launcher = pythonw
    print(f"使用的解释器：{launcher}")
    print("正在启动后台服务…")

    subprocess.Popen(
        [str(launcher), str(entry)],
        cwd=str(ROOT),
        creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 3) 等端口就绪（最多 20 秒）
    url = f"http://127.0.0.1:{port}"
    for _ in range(40):
        if _port_open(port):
            print(f"启动成功：{url}")
            if "--no-browser" not in sys.argv:
                try:
                    webbrowser.open(url)
                except Exception:  # noqa: BLE001
                    pass
            return 0
        time.sleep(0.5)

    print("启动超时。请查看 logs/console.out 里的报错。")
    print(f"日志路径：{ROOT / 'logs' / 'console.out'}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
