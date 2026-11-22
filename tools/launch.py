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

# (import 名, pip 包名)。干净机器上缺第一个服务就起不来，且错误只埋在
# logs/console.out 里 —— 所以在拉起进程之前先检查并一键补装。
CORE_DEPS = (
    ("requests", "requests"),
    ("yaml", "PyYAML"),
    ("bs4", "beautifulsoup4"),
    ("PIL", "Pillow"),
)


def _missing_deps(deps=None) -> list:
    """探测缺失的核心依赖，返回缺失的 pip 包名列表（空列表 = 齐全）。

    参数可注入假包名，便于测试。
    """
    import importlib

    missing = []
    for module, package in deps if deps is not None else CORE_DEPS:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)
    return missing


def _install_deps() -> bool:
    """`pip install -e ROOT` 一把装齐，成功返回 True。"""
    print("正在自动安装依赖（首次可能要几分钟）…")
    rc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", str(ROOT)],
        cwd=str(ROOT),
    ).returncode
    return rc == 0


def _read_port_from_text(text: str, default: int = DEFAULT_PORT) -> int:
    """不依赖 PyYAML 也能读出 web.port（全新机器上 yaml 还没装时要用）。"""
    in_web = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw[:1].isspace():          # 顶格说明是新的一节
            head = stripped.split(":", 1)[0].strip()
            in_web = head == "web"
            continue
        if in_web and stripped.startswith("port:"):
            try:
                value = stripped.split(":", 1)[1].split("#", 1)[0]
                return int(value.strip().strip("\"'"))
            except (IndexError, ValueError):
                return default
    return default


def _read_port() -> int:
    """从 settings.yaml 读端口；读不到就用 5710（配置坏了也不该启动不了）。

    优先级：WEB_PORT 环境变量 > settings.yaml 的 web.port > 默认 5710。

    注意：全新机器上第一次运行时 PyYAML 还没装上，这里必须有不依赖 yaml 的
    兜底。否则端口会退回 5710，而服务起来后按配置监听别的端口 —— 探测永远
    探不到，表现就是「日志说已就绪，启动器却说启动超时」。
    """
    env_port = os.environ.get("WEB_PORT", "").strip()
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass          # 写错了就按配置文件走，不因为一个环境变量起不来
    cfg_path = ROOT / "config" / "settings.yaml"
    try:
        import yaml

        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        return int((cfg.get("web") or {}).get("port", DEFAULT_PORT))
    except Exception:  # noqa: BLE001
        pass
    try:
        return _read_port_from_text(cfg_path.read_text(encoding="utf-8"))
    except OSError:
        return DEFAULT_PORT


def _port_open(port: int) -> bool:
    """端口上有没有服务在监听。"""
    with socket.socket() as sock:
        sock.settimeout(0.6)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _service_http_ok(url: str, timeout: float = 1.0) -> bool:
    """HTTP 层探测 /health，与 connect_ex 构成双保险。

    个别环境（沙箱、安全软件）下裸端口探测会失灵，但服务其实已就绪；
    此时 HTTP 请求仍能通，就用它兜底，避免误报「启动超时」。
    """
    try:
        import urllib.request

        with urllib.request.urlopen(url + "/health", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def _log_tail(lines: int = 12) -> str:
    """取 console.out 末尾几行，启动失败时直接展示原因，别让用户翻文件。"""
    path = ROOT / "logs" / "console.out"
    if not path.exists():
        return f"（没有日志文件：{path}）"
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return f"（日志读取失败：{path}）"
    return "\n".join(content[-lines:])


def ready_url_from_log(text: str) -> str:
    """从服务日志里抓「本地控制台已就绪：http://…」那一行的地址。

    兜底用：万一端口读错了（比如配置改了），服务自己会说它监听在哪，
    启动器照着打开就行，不必让用户看「启动超时」却明明能访问。
    """
    marker = "本地控制台已就绪："
    for line in reversed(text.splitlines()):
        pos = line.find(marker)
        if pos >= 0:
            url = line[pos + len(marker):].strip()
            if url.startswith("http://") or url.startswith("https://"):
                return url
    return ""


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

    # 1) 依赖检查：缺 requests/yaml/bs4/Pillow 时后台服务会静默起不来，
    #    这里在拉进程之前拦住并给出补装选项，而不是让用户去翻 logs/console.out。
    missing = _missing_deps()
    if missing:
        print("缺少依赖：" + "、".join(missing))
        print(f"也可以手动安装：{sys.executable} -m pip install -e \"{ROOT}\"")
        if "--no-install" in sys.argv:
            print("检测到 --no-install，跳过自动安装。请先手动装好依赖再启动。")
            return 1
        answer = ""
        try:
            answer = input("是否现在自动安装？[Y/n] ").strip().lower()
        except EOFError:
            answer = "y"  # 没有交互终端（脚本/CI）时默认安装
        if answer not in ("", "y", "yes"):
            print("已取消。装好依赖后重新运行即可；也可以跑 python tools/doctor.py 看整体体检。")
            return 1
        if not _install_deps() or _missing_deps():
            print("依赖安装失败。请手动执行后重试：")
            print(f"  {sys.executable} -m pip install -e \"{ROOT}\"")
            print("也可以先跑 python tools/doctor.py 查看完整体检。")
            return 1
        print("依赖就绪。")

    # 2) 清理旧进程（只杀 Python，别人的程序不动）
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

    proc = subprocess.Popen(
        [str(launcher), str(entry)],
        cwd=str(ROOT),
        creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 3) 等端口就绪。全新安装后的第一次启动要给足时间：依赖刚装完，
    #    系统可能同时在扫描新 DLL，import 会比平时慢，最多等 60 秒。
    #    探测用双保险：connect_ex 失败时再走一次 HTTP /health（两种代码路径，
    #    避免个别环境下端口探测失灵导致误报「启动超时」）。
    url = f"http://127.0.0.1:{port}"
    first_start_after_install = bool(missing)
    waited = 0
    for _ in range(120):
        if _port_open(port) or _service_http_ok(url):
            print(f"启动成功：{url}")
            if "--no-browser" in sys.argv:
                return 0
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass
            return 0
        if proc.poll() is not None:
            print("后台服务启动后立刻退出了。最后几行日志：")
            print(_log_tail())
            return 1
        time.sleep(0.5)
        waited += 1
        if waited % 20 == 0:
            print(f"服务启动中…已等待 {waited // 2} 秒"
                  + ("（首次启动较慢，请耐心）" if first_start_after_install else ""))

    # 4) 兜底：探测失败但服务日志说已经就绪（多半是端口读错了，比如配置里
    #    改过端口、而启动器在依赖装好前读了配置）。这时候按日志里的地址打开，
    #    不要让用户对着一个其实能用的服务看「启动超时」。
    log_path = ROOT / "logs" / "console.out"
    try:
        ready = ready_url_from_log(log_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        ready = ""
    if ready:
        print(f"服务已就绪（按服务日志判断）：{ready}")
        print(f"提示：配置里的端口是 {port}，实际监听的是 {ready.rsplit(':', 1)[-1]}，"
              "建议检查 config/settings.yaml")
        if "--no-browser" not in sys.argv:
            try:
                webbrowser.open(ready)
            except Exception:  # noqa: BLE001
                pass
        return 0

    print("启动超时。最后几行日志：")
    print(_log_tail())
    print(f"完整日志：{ROOT / 'logs' / 'console.out'}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
