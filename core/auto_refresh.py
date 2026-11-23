"""解密数据自动刷新。

背景：SIWX 解密是「手动快照」——它把微信加密库解密成一份明文拷贝，之后
微信新增的消息不会自动同步进来。用户常常「群里有新消息但控制台读不到」，
根因就是解密库过期。本模块提供一个后台守护线程，周期性检测解密库的
mtime，超过阈值就自动跑一次 SIWX 解密，从根上解决这个问题。

设计约束：
    · 不依赖第三方库，只用 subprocess + threading + pathlib。
    · 刷新失败不抛异常、不打断主流程，只记日志。
    · 并发安全：同一时刻只允许一个刷新在跑（用锁 + 布尔标志）。
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from core.log import get_logger

logger = get_logger("auto_refresh")


def _resolve_siwx_run(cfg: Dict[str, Any]) -> Optional[str]:
    """确定 SIWX run.py 的路径，按优先级：配置 > 环境变量 > 从解密目录上溯推断。"""
    ar = (cfg.get("chatlog") or {}).get("auto_refresh") or {}
    explicit = str(ar.get("siwx_run") or "").strip()
    if explicit:
        return explicit

    env = os.environ.get("WX_SIWX_RUN", "").strip()
    if env:
        return env

    # 兜底：<decrypted_dir> 通常是 <...>/siwx/output/<wxid>，上溯两级到 siwx/run.py
    dec = (cfg.get("chatlog") or {}).get("decrypted_dir") or ""
    if dec:
        try:
            p = Path(dec)
            # decrypted_dir = <...>/siwx/output/<wxid>
            #   p.parent        = <...>/siwx/output
            #   p.parent.parent = <...>/siwx
            siwx_dir = p.parent.parent if p.parent else None
            if siwx_dir and siwx_dir.name == "siwx":
                candidate = siwx_dir / "run.py"
                if candidate.exists():
                    return str(candidate)
        except Exception:  # pragma: no cover - 路径异常不值得打断
            pass
    return None


def _decrypted_db_mtime(cfg: Dict[str, Any]) -> Optional[float]:
    """返回 message_0.db 的 mtime（秒级 epoch），拿不到返回 None。"""
    dec = (cfg.get("chatlog") or {}).get("decrypted_dir") or ""
    if not dec:
        return None
    db = Path(dec) / "message" / "message_0.db"
    if not db.exists():
        return None
    try:
        return db.stat().st_mtime
    except OSError:  # pragma: no cover
        return None


#: SIWX 自己需要的第三方包（见它目录下的 requirements.txt）。
#: 用来判断「这个解释器能不能跑 SIWX」——只装本项目依赖的 venv 通常缺这两个。
SIWX_IMPORTS = ("psutil", "Crypto")


def _siwx_env() -> Dict[str, str]:
    """SIWX 子进程统一用 UTF-8，避免 GBK 控制台下 rich 输出 emoji 直接崩。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _python_candidates() -> list:
    """能拿来跑 SIWX 的解释器候选，按优先级：WX_PYTHON > 当前 > 系统 > PATH。"""
    out: list = []

    def add(value: str) -> None:
        value = (value or "").strip()
        if value and value not in out:
            out.append(value)

    add(os.environ.get("WX_PYTHON", ""))
    try:
        import sys

        if not getattr(sys, "frozen", False):
            add(sys.executable or "")
            add(getattr(sys, "_base_executable", "") or "")
    except Exception:  # pragma: no cover
        pass
    try:
        import shutil

        for name in ("python", "python3"):
            path = shutil.which(name)
            if path:
                add(path)
    except Exception:  # pragma: no cover
        pass
    return out


def _probe_python(exe: str, timeout: float = 12.0) -> bool:
    """这个解释器能不能 import SIWX 依赖。"""
    try:
        proc = subprocess.run(
            [exe, "-c", "import " + ", ".join(SIWX_IMPORTS)],
            capture_output=True, timeout=timeout, env=_siwx_env(),
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001 - 探测失败就当不可用
        return False


def _pick_siwx_python() -> Optional[str]:
    """挑一个真能跑 SIWX 的解释器；一个都不行返回 None。

    背景：本项目一旦用 `.venv` 运行（一键启动.bat 已改成优先 .venv），
    `sys.executable` 就只装了本项目依赖，缺 psutil/pycryptodome，
    SIWX 一跑就 ModuleNotFoundError → 自动刷新永远失败、消息永远不更新。
    """
    for exe in _python_candidates():
        if _probe_python(exe):
            return exe
    return None


def _siwx_dep_hint(siwx_run: str) -> str:
    """给用户的可执行修复步骤（一条能直接粘进命令行的命令）。"""
    req = Path(siwx_run).parent / "requirements.txt"
    cands = _python_candidates()
    exe = cands[0] if cands else "python"
    return '%s -m pip install -r "%s"' % (exe, req)


def _run_siwx(siwx_run: str, python: str = "python") -> bool:
    """跑一次 SIWX 解密，成功返回 True。

    SIWX 的退出码并不总能反映真实结果：当所有库都「缓存命中、无需重解」时，
    它仍可能因「其他未登录账号密钥为 0/N」而返回非 0。所以这里不只看 exit code，
    而是结合 stdout 内容判断目标账号是否完成了解密。
    """
    try:
        env = _siwx_env()
        proc = subprocess.run(
            [python, siwx_run, "auto"],
            capture_output=True,
            timeout=300,  # 5 分钟上限，防止卡死
            env=env,
        )
        out = (proc.stdout or b"").decode("utf-8", "ignore")
        err = (proc.stderr or b"").decode("utf-8", "ignore")
        combined = out + err

        # 成功标志：至少有一个账号「密钥 20/20」或出现了「解密完成」。
        # 「缓存命中 N」也说明解密库无需更新（数据已经是新的），同样算成功。
        ok = (
            "20/20" in combined
            or "解密完成" in combined
            or "缓存命中" in combined
        )
        if proc.returncode == 0:
            ok = True
        if not ok:
            tail = combined[-300:]
            if "ModuleNotFoundError" in combined or "No module named" in combined:
                logger.warning(
                    "SIWX 少装了自己的依赖（这个解释器：%s）。修：%s",
                    python, _siwx_dep_hint(siwx_run))
            logger.warning("SIWX 自动刷新失败（exit=%s）：%s", proc.returncode, tail)
        return ok
    except subprocess.TimeoutExpired:
        logger.warning("SIWX 自动刷新超时（>300s），已放弃本轮")
        return False
    except Exception as exc:  # noqa: BLE001 - 刷新失败不能拖垮服务
        logger.warning("SIWX 自动刷新异常：%s", exc)
        return False


class AutoRefresher:
    """后台守护：周期性检查解密库，过期就自动解密。"""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self._cfg = cfg
        self._lock = threading.Lock()
        self._running = False
        self._stop = threading.Event()
        #: 叫醒信号：外部 kick() 时让守护线程立刻开始下一轮检查，
        #: 这样「发现过期」到「开始解密」的延迟很短，且**不阻塞调用方**。
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_run_at: Optional[float] = None
        self.last_error: str = ""
        #: 连续失败次数，用于指数退避（避免失败后疯狂重试刷爆日志）
        self._fail_count: int = 0

    # ------------------------------------------------------------------ #
    def _should_refresh(self) -> bool:
        ar = (self._cfg.get("chatlog") or {}).get("auto_refresh") or {}
        if not ar.get("enabled", True):
            return False

        # 节流：刚跑过 SIWX 不久就不再空跑（SIWX 缓存命中时不会重写 mtime，
        # 若只看 mtime 会陷入「每轮都判过期、每轮都空跑」的死循环）。
        # 连续失败时冷却时间指数增长（最多 1 小时），避免一直失败一直重试。
        if self.last_run_at is not None:
            base = max(60, int(ar.get("interval_seconds", 300) or 300))
            cool = base * (2 ** min(self._fail_count, 4))  # 1x/2x/4x/8x/16x
            cool = min(cool, 3600)
            if time.time() - self.last_run_at < cool:
                return False

        stale_min = int(ar.get("stale_minutes", 30) or 30)
        mtime = _decrypted_db_mtime(self._cfg)
        if mtime is None:
            # 解密库不存在，说明还没解过，也需要跑一次
            return True
        age_min = (time.time() - mtime) / 60.0
        return age_min > stale_min

    def refresh_once(self, force: bool = False) -> bool:
        """立即检查并（如需要）刷新一次；force=True 跳过时效判断。"""
        if not force and not self._should_refresh():
            return False
        if not self._lock.acquire(blocking=False):
            return False  # 已有刷新在跑
        try:
            siwx = _resolve_siwx_run(self._cfg)
            if not siwx:
                self.last_error = "未找到 SIWX run.py，请配置 chatlog.auto_refresh.siwx_run 或 WX_SIWX_RUN"
                logger.warning(self.last_error)
                return False
            python = _pick_siwx_python()
            if not python:
                self.last_error = (
                    "找不到能运行 SIWX 的 Python（缺 psutil / pycryptodome 等）。"
                    "请执行：" + _siwx_dep_hint(siwx) +
                    "；或在 .env 里用 WX_PYTHON 指定一个装好这些包的解释器。"
                )
                logger.warning(self.last_error)
                return False
            ok = _run_siwx(siwx, python=python)
            self.last_run_at = time.time()
            if ok:
                self.last_error = ""
                self._fail_count = 0
            else:
                self._fail_count += 1
                logger.warning("自动刷新失败（连续第 %d 次），下次冷却 %d 秒",
                               self._fail_count, min(300 * (2 ** min(self._fail_count, 4)), 3600))
            return ok
        finally:
            self._lock.release()

    def _loop(self) -> None:
        ar = (self._cfg.get("chatlog") or {}).get("auto_refresh") or {}
        interval = max(60, int(ar.get("interval_seconds", 300) or 300))
        while not self._stop.is_set():
            # 先检查后等待：服务刚起来时立刻（后台）刷一次，页面不必等。
            try:
                if self._should_refresh():
                    logger.info("检测到解密库过期，触发自动解密…")
                    self.refresh_once()
            except Exception as exc:  # noqa: BLE001 - 守护线程不能因异常退出
                logger.warning("自动刷新循环异常：%s", exc)
            # 正常按 interval 等；被 kick() 叫醒则立刻开始下一轮检查。
            self._wake.wait(interval)
            self._wake.clear()

    def kick(self) -> None:
        """非阻塞地叫醒守护线程，让它立刻检查一轮。

        关键：**绝不在调用线程里跑 SIWX**。HTTP 请求线程调用本方法后
        立即返回，解密由守护线程执行，页面不会因此卡住。
        """
        self._wake.set()

    def start(self) -> None:
        """启动后台守护线程（幂等）。"""
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="auto-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止后台守护线程。"""
        self._stop.set()
        self._wake.set()  # 叫醒等待中的循环，让它立刻看到 _stop 并退出
        self._running = False


# 模块级单例，供 server 与 app 复用
_REFRESHER: Optional[AutoRefresher] = None
_REFRESHER_LOCK = threading.Lock()


def get_refresher(cfg: Dict[str, Any]) -> AutoRefresher:
    """返回全局单例；配置变化时重建。"""
    global _REFRESHER
    with _REFRESHER_LOCK:
        if _REFRESHER is None or _REFRESHER._cfg is not cfg:
            if _REFRESHER is not None:
                _REFRESHER.stop()
            _REFRESHER = AutoRefresher(cfg)
        return _REFRESHER
