"""统一配置加载 / 环境变量 / 路径解析。

设计约定（对应施工提示词「配置驱动」）：
    · 所有可变参数（API 地址、模型名、群名、领导名单）只从 YAML / .env 读取
    · 代码里不出现字面量形式的业务参数
    · 配置项缺失时回落到 _DEFAULTS，不会因为改坏配置就崩掉整个程序
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from core.log import get_logger

logger = get_logger("config")

# --------------------------------------------------------------------------- #
# 路径常量
# --------------------------------------------------------------------------- #
def _detect_project_root() -> Path:
    """源码运行时指向项目根；PyInstaller 打包后指向 exe 所在目录。

    这样打包成桌面软件后，config/、runs/、logs/、.env 都放在 exe 旁边，
    用户可以直接修改和查看，不必进到 _internal 目录里。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT: Path = _detect_project_root()
CONFIG_DIR: Path = PROJECT_ROOT / "config"
PROMPT_DIR: Path = CONFIG_DIR / "prompts"

# --------------------------------------------------------------------------- #
# 默认配置：这里的每一项都可以被 config/settings.yaml 覆盖
# --------------------------------------------------------------------------- #
_DEFAULTS: Dict[str, Any] = {
    "chatlog": {
        "api_base": "http://127.0.0.1:5030",
        "timeout": 15,
        "page_size": 500,
        "max_pages": 20,
        # 自动刷新解密数据：SIWX 解密是「手动快照」，不会自动跟随微信更新。
        # 打开开关后，服务会周期性检测解密库 mtime，超过 stale_minutes 分钟
        # 就后台跑一次 SIWX 解密，避免「群里有新消息但读不到」反复发生。
        "auto_refresh": {
            "enabled": True,
            # SIWX run.py 的绝对路径；留空则用 WX_SIWX_RUN 环境变量，再兜底
            # 猜测 <decrypted_dir> 上溯三级到 binaries/siwx/run.py。
            "siwx_run": "",
            # 解密库超过多少分钟没更新就触发刷新（0 = 每次查询都刷，慎用）
            "stale_minutes": 30,
            # 后台检测间隔（秒）
            "interval_seconds": 300,
        },
        "endpoints": {
            "chatlog": "/api/v1/chatlog",
            "chatroom": "/api/v1/chatroom",
            "contact": "/api/v1/contact",
            "session": "/api/v1/session",
            "health": "/health",
            "voice": "/voice/{key}",
            "image": "/image/{key}",
            "video": "/video/{key}",
            "file": "/file/{key}",
            "data": "/data/{path}",
        },
    },
    "asr": {
        "enabled": True,
        "model": "large-v3",
        "device": "cpu",
        "compute_type": "int8",
        "language": "zh",
        "beam_size": 5,
        "vad_filter": True,
        "silk_decoder": "",
        "max_duration": 300,
    },
    "vision": {
        "provider": "dummy",
        "model": "doubao-vision-pro",
        "timeout": 30,
        "max_images": 20,
        "fallback_text": "图片",
    },
    "article": {
        "enabled": True,
        "timeout": 15,
        "max_chars": 3000,
        "retry": 1,
    },
    "summarizer": {
        "provider": "file_output",
        "prompt_template": "leader_brief",
        "model": "doubao-seed-1904",
        "pending_dir": "./runs/pending",
        "max_input_chars": 60000,
    },
    "output": {
        "dir": "./runs",
        "format": ["markdown"],
        "html_theme": "light",
        "include_meta": True,
    },
    "logging": {
        "level": "INFO",
        "dir": "./logs",
        "file": "hub.log",
        "max_bytes": 5242880,
        "backup_count": 5,
    },
    "web": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 5710,
        "open_browser": True,
    },
}


class ConfigError(RuntimeError):
    """配置文件缺失或格式非法时抛出。"""


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """把 override 递归合并进 base，返回新字典（不修改入参）。"""
    result: Dict[str, Any] = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def dig(data: Optional[Dict[str, Any]], dotted: str, default: Any = None) -> Any:
    """按点号路径安全取值：dig(cfg, "chatlog.api_base")。"""
    if not isinstance(data, dict):
        return default
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node if node is not None else default


def resolve_path(path: Any, mkdir: bool = False) -> Path:
    """把配置里的相对路径解析为规范化的绝对路径（相对的是项目根目录）。

    务必做 `resolve()`：`./runs` 与 `<root>/runs` 是同一个目录但字符串不同，
    不归一化的话，`target.parent == runs_dir` 这类比较会时灵时不灵。
    """
    p = Path(str(path)).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    try:
        p = p.resolve()
    except OSError:  # 路径含非法字符等极端情况，退化为非规范化形式
        logger.debug("路径规范化失败：%s", p)
    if mkdir:
        p.mkdir(parents=True, exist_ok=True)
    return p


# --------------------------------------------------------------------------- #
# .env 加载（不引入 python-dotenv，保持依赖最小化）
# --------------------------------------------------------------------------- #
def load_dotenv(env_path: Optional[Path] = None) -> Dict[str, str]:
    """读取 .env 并写入 os.environ。

    已存在的环境变量优先（不会被 .env 覆盖），返回本次实际写入的键值对。
    """
    path = env_path or (PROJECT_ROOT / ".env")
    loaded: Dict[str, str] = {}
    if not path.exists():
        return loaded

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return loaded

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ and value:
            os.environ[key] = value
            loaded[key] = value
    return loaded


# --------------------------------------------------------------------------- #
# 主配置
# --------------------------------------------------------------------------- #
def load_settings(path: Optional[Path] = None, reload_env: bool = True) -> Dict[str, Any]:
    """加载 settings.yaml，与默认值深合并后返回。"""
    if reload_env:
        load_dotenv()

    target = Path(path) if path else (CONFIG_DIR / "settings.yaml")
    user_cfg: Dict[str, Any] = {}
    if target.exists():
        try:
            user_cfg = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:  # 配置写坏了也要能跑，用默认值兜底
            raise ConfigError(f"settings.yaml 解析失败：{exc}") from exc
    else:
        print(f"[config] 未找到 {target.name}，改用内置默认配置")

    if not isinstance(user_cfg, dict):
        raise ConfigError("settings.yaml 顶层必须是键值映射")

    cfg = deep_merge(_DEFAULTS, user_cfg)
    # 本机专属路径/密钥统一走环境变量（.env 已 gitignore，不上传到仓库）。
    # WX_DECRYPTED_DIR 指向 SIWX 解密输出目录，是本机绝对路径，不该写进公开的 settings.yaml。
    _local_decrypted = os.environ.get("WX_DECRYPTED_DIR", "")
    if _local_decrypted:
        cfg.setdefault("chatlog", {})["decrypted_dir"] = _local_decrypted
    # 环境变量兜底：兼容 DOUBAO_* / DEEPSEEK_* / OPENAI_* / VOLC_* 多种写法
    cfg.setdefault("_env", {})
    cfg["_env"]["api_key"] = (
        os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("DOUBAO_API_KEY")
        or os.environ.get("OPENAI_API_KEY", "")
    )
    cfg["_env"]["base_url"] = (
        os.environ.get("DEEPSEEK_BASE_URL")
        or os.environ.get("DOUBAO_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL", "")
    )
    cfg["_env"]["text_model"] = (
        os.environ.get("DEEPSEEK_TEXT_MODEL")
        or os.environ.get("DOUBAO_TEXT_MODEL")
        or os.environ.get("DOUBAO_TEXT_MODEL", "")
    )
    cfg["_env"]["vision_model"] = os.environ.get("DOUBAO_VISION_MODEL", "")

    # 端口/监听地址也可以用环境变量临时覆盖，方便「5710 被占用」时换个端口跑，
    # 而不必改动仓库里的 settings.yaml（改了容易忘记改回来）。
    _env_port = os.environ.get("WEB_PORT", "").strip()
    if _env_port:
        try:
            cfg.setdefault("web", {})["port"] = int(_env_port)
        except ValueError:
            pass
    _env_host = os.environ.get("WEB_HOST", "").strip()
    if _env_host:
        cfg.setdefault("web", {})["host"] = _env_host
    return cfg


def load_groups(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """加载 groups.yaml，返回已启用的目标群列表。"""
    target = Path(path) if path else (CONFIG_DIR / "groups.yaml")
    if not target.exists():
        return []

    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"groups.yaml 解析失败：{exc}") from exc

    groups = (data or {}).get("target_groups", []) or []
    global_leaders = (data or {}).get("global_leaders", []) or []

    result: List[Dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict) or not group.get("name"):
            continue
        if group.get("enabled") is False:
            continue
        leaders = list(group.get("leaders") or [])
        # 追加全局名单，去重（id 优先，其次 name）
        seen = {_leader_key(l) for l in leaders}
        for gl in global_leaders:
            if _leader_key(gl) not in seen:
                leaders.append(gl)
                seen.add(_leader_key(gl))
        result.append(
            {
                "name": str(group["name"]),
                "leaders": [l for l in leaders if l.get("name") or l.get("id")],
                "pinned": bool(group.get("pinned", False)),
            }
        )
    return result


def _leader_key(leader: Dict[str, Any]) -> str:
    """领导身份的唯一键，用于去重。"""
    if not isinstance(leader, dict):
        return ""
    ident = str(leader.get("id") or "").strip()
    return ident if ident else f"name::{str(leader.get('name') or '').strip()}"


def find_group(group_name: str, path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """按群名查找配置，找不到返回 None（不抛异常，交由上层决定策略）。"""
    for group in load_groups(path):
        if group.get("name") == group_name:
            return group
    return None


def get_leaders(
    group_name: str, path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """获取某群的领导名单；群未配置时返回空列表。"""
    group = find_group(group_name, path)
    return list(group.get("leaders", [])) if group else []


def load_groups_raw(path: Optional[Path] = None) -> Dict[str, Any]:
    """读取 groups.yaml 原始结构（供控制台「领导设置」面板展示与编辑）。

    与 load_groups 不同，这里返回未经展开的原始字典：
        {"target_groups": [...], "global_leaders": [...]}
    每个群条目保留 name / enabled / leaders(含 id) 原始字段。

    Returns:
        原始配置字典；文件不存在或解析失败时返回空结构。
    """
    target = Path(path) if path else (CONFIG_DIR / "groups.yaml")
    if not target.exists():
        return {"target_groups": [], "global_leaders": []}
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {"target_groups": [], "global_leaders": []}
    if not isinstance(data, dict):
        return {"target_groups": [], "global_leaders": []}
    return {
        "target_groups": list(data.get("target_groups", []) or []),
        "global_leaders": list(data.get("global_leaders", []) or []),
    }


def leaders_as_text(leaders: List[Dict[str, Any]]) -> str:
    """把领导名单渲染成 prompt 里 {leaders_list} 的可读文本。"""
    if not leaders:
        return "（未配置领导名单，请把所有有实指令意味的发言都视为重点）"
    lines = []
    for leader in leaders:
        name = str(leader.get("name") or "").strip()
        ident = str(leader.get("id") or "").strip()
        lines.append(f"- {name}（wxid: {ident}）" if ident else f"- {name}")
    return "\n".join(lines)


def save_group_leaders(
    group_name: str,
    leaders: List[Dict[str, Any]],
    path: Optional[Path] = None,
    global_leaders: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """把某个群的领导名单写回 groups.yaml（保留其他群的配置与字段）。

    设计约定：只增改 `leaders` 字段，其余字段（enabled / id 等）原样保留；
    群名不存在时，追加一个新群条目（默认 enabled）。写入采用「先读全文、
    原位替换、原子落盘」的策略，避免并发写坏 YAML。

    Args:
        group_name: 目标群名。
        leaders: 新的领导名单，形如 `[{"name": "张三", "id": ""}]`。
        path: 群配置文件路径，默认 config/groups.yaml。
        global_leaders: 全局兜底名单（可选，传入则一并写回）。

    Raises:
        ConfigError: YAML 解析失败或写入失败时抛出。
    """
    target = Path(path) if path else (CONFIG_DIR / "groups.yaml")

    if target.exists():
        try:
            data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"groups.yaml 解析失败：{exc}") from exc
    else:
        data = {}

    if not isinstance(data, dict):
        data = {}

    groups = list(data.get("target_groups", []) or [])
    gl = list(global_leaders) if global_leaders is not None else list(data.get("global_leaders", []) or [])

    # 规范化传入的 leaders：只保留有 name 或 id 的条目，去掉空白
    clean_leaders: List[Dict[str, str]] = []
    for leader in leaders or []:
        if not isinstance(leader, dict):
            continue
        name = str(leader.get("name") or "").strip()
        ident = str(leader.get("id") or "").strip()
        if not name and not ident:
            continue
        entry: Dict[str, str] = {"name": name}
        if ident:
            entry["id"] = ident
        clean_leaders.append(entry)

    found = False
    for group in groups:
        if isinstance(group, dict) and group.get("name") == group_name:
            group["leaders"] = clean_leaders
            found = True
            break
    if not found:
        groups.append({"name": group_name, "enabled": True, "leaders": clean_leaders})

    data["target_groups"] = groups
    data["global_leaders"] = gl

    # 原子落盘：先写临时文件再改名，避免写一半崩溃留下坏 YAML
    tmp = target.with_suffix(".yaml.tmp")
    try:
        tmp.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        tmp.replace(target)
    except OSError as exc:
        raise ConfigError(f"groups.yaml 写入失败：{exc}") from exc


def set_group_pinned(
    group_name: str, pinned: bool, path: Optional[Path] = None
) -> None:
    """设置某群的置顶状态，写回 groups.yaml。

    群名不存在时会追加一个新群条目（默认 enabled、无 leaders），
    置顶标记随群名走，与「关注的人」共用同一份配置。
    """
    target = Path(path) if path else (CONFIG_DIR / "groups.yaml")

    if target.exists():
        try:
            data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"groups.yaml 解析失败：{exc}") from exc
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}

    groups = list(data.get("target_groups", []) or [])
    found = False
    for group in groups:
        if isinstance(group, dict) and group.get("name") == group_name:
            group["pinned"] = bool(pinned)
            found = True
            break
    if not found:
        groups.append({"name": group_name, "enabled": True, "pinned": bool(pinned)})

    data["target_groups"] = groups
    tmp = target.with_suffix(".yaml.tmp")
    try:
        tmp.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        tmp.replace(target)
    except OSError as exc:
        raise ConfigError(f"groups.yaml 写入失败：{exc}") from exc


def get_pinned_groups(path: Optional[Path] = None) -> set:
    """返回置顶群名的集合。"""
    target = Path(path) if path else (CONFIG_DIR / "groups.yaml")
    if not target.exists():
        return set()
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return set()
    if not isinstance(data, dict):
        return set()
    return {
        str(g["name"])
        for g in (data.get("target_groups", []) or [])
        if isinstance(g, dict) and g.get("pinned")
    }


# --------------------------------------------------------------------------- #
# Prompt 模板
# --------------------------------------------------------------------------- #
def load_prompt_template(
    name: str = "leader_brief", extra_vars: Optional[Dict[str, str]] = None
) -> str:
    """加载 config/prompts/<name>.md 的原始内容。

    模板里除 {chat_content} / {leaders_list} 之外的自定义变量可通过 extra_vars 传入。
    """
    target = PROMPT_DIR / f"{name}.md"
    if not target.exists():
        fallback = PROMPT_DIR / "leader_brief.md"
        if fallback.exists():
            target = fallback
        else:
            raise ConfigError(f"prompt 模板不存在：{PROMPT_DIR / (name + '.md')}")
    return target.read_text(encoding="utf-8")


def list_prompt_templates() -> List[str]:
    """列出所有可用 prompt 模板名（不含扩展名）。"""
    if not PROMPT_DIR.exists():
        return []
    return sorted(p.stem for p in PROMPT_DIR.glob("*.md"))


# --------------------------------------------------------------------------- #
# 模型配置读写（供控制台「模型设置」面板使用）
# --------------------------------------------------------------------------- #
#: 各服务商的预填值。用户在下拉里选一个，前端就把 base_url / model 填好，
#: 只需要再补一个自己的 Key —— 这是「不会配置的人也能用」的关键。
MODEL_PRESETS: List[Dict[str, str]] = [
    {
        "id": "deepseek",
        "label": "DeepSeek（推荐，便宜）",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "key_url": "https://platform.deepseek.com/api_keys",
    },
    {
        "id": "doubao",
        "label": "火山方舟 / 豆包",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "",
        "key_url": "https://console.volcengine.com/ark",
        "note": "模型名要填方舟控制台里的「推理接入点 ID」，形如 ep-xxxxxx",
    },
    {
        "id": "moonshot",
        "label": "月之暗面 Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "key_url": "https://platform.moonshot.cn/console/api-keys",
    },
    {
        "id": "qwen",
        "label": "阿里通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "key_url": "https://bailian.console.aliyun.com/",
    },
    {
        "id": "zhipu",
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
        "key_url": "https://bigmodel.cn/usercenter/apikeys",
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_url": "https://platform.openai.com/api-keys",
    },
    {
        "id": "ollama",
        "label": "Ollama（本地，不出网）",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:7b",
        "note": "本地模型不校验 Key，但这里必须填一个非空占位值（例如 ollama），否则会被判定为未配置。",
    },
    {
        "id": "lmstudio",
        "label": "LM Studio（本地，不出网）",
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "",
        "note": "模型名填 LM Studio 里已加载的模型标识。",
    },
    {
        "id": "custom",
        "label": "其他 OpenAI 兼容服务 / 中转",
        "base_url": "",
        "model": "",
        "note": "地址要填到版本号那一层，例如 https://xxx.com/v1（程序会自行拼接 /chat/completions）。",
    },
]

#: .env 里与模型相关的三个键。写死在这里，避免各处字符串散落。
_ENV_KEY_API = "DEEPSEEK_API_KEY"
_ENV_KEY_BASE = "DEEPSEEK_BASE_URL"
_ENV_KEY_MODEL = "DEEPSEEK_TEXT_MODEL"


def env_file_path() -> Path:
    """返回 .env 的绝对路径。"""
    return PROJECT_ROOT / ".env"


def mask_key(key: str) -> str:
    """把 Key 打码成 `sk-****abcd`，用于回显给前端。

    只保留前 3 位和后 4 位：够用户确认「填的是哪一把」，又不至于泄漏。
    """
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}{'*' * 6}{key[-4:]}"


def _read_env_map() -> Dict[str, str]:
    """把 .env 解析成字典（不写入 os.environ，仅用于回显）。"""
    path = env_file_path()
    result: Dict[str, str] = {}
    if not path.exists():
        return result
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return result
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _write_env_updates(updates: Dict[str, str]) -> None:
    """把若干键值写进 .env，保留原有注释与其他键。

    实现要点：
      · 逐行扫描，命中的键就地替换，没命中的追加到末尾；
      · 先写临时文件再原子改名，避免写到一半断电把 .env 写坏
        （.env 里还有解密目录这类不好恢复的配置）；
      · 同时更新 os.environ —— `load_dotenv` 只在键不存在时写入，
        不更新进程环境的话，保存后本次运行仍然用旧 Key。
    """
    path = env_file_path()
    existing_lines: List[str] = []
    if path.exists():
        try:
            existing_lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ConfigError(f"读取 .env 失败：{exc}") from exc
    else:
        existing_lines = [
            "# 本文件保存本机密钥与路径，已被 .gitignore 忽略，不要提交。",
            "# 由控制台「模型设置」自动维护，也可以手工编辑。",
            "",
        ]

    pending = dict(updates)
    out: List[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in pending:
                out.append(f"{key}={pending.pop(key)}")
                continue
        out.append(line)
    for key, value in pending.items():
        out.append(f"{key}={value}")

    text = "\n".join(out).rstrip("\n") + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise ConfigError(f"写入 .env 失败：{exc}") from exc

    for key, value in updates.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def _set_yaml_scalars_in_section(text: str, section: str, values: Dict[str, str]) -> str:
    """在 YAML 文本的某个顶层区块内改写/补充若干标量，**保留原有注释与缩进**。

    为什么不用 yaml.safe_load + dump：dump 会丢掉 settings.yaml 里所有的
    中文注释，而那注释是给别人改配置时看的，不能丢。
    """
    lines = text.splitlines()
    out: List[str] = []
    pending = dict(values)
    inside = False
    section_indent = 0
    child_indent = 2
    found_section = False

    def flush_pending() -> None:
        for k, v in list(pending.items()):
            out.append(" " * child_indent + f"{k}: {v}")
            pending.pop(k)

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if not inside:
            if indent == 0 and stripped.startswith(f"{section}:"):
                inside = True
                found_section = True
                section_indent = indent
                child_indent = 2
            out.append(line)
            continue

        # 遇到同级或更外层的键 → 区块结束
        if stripped and not stripped.startswith("#") and indent <= section_indent:
            flush_pending()
            inside = False
            out.append(line)
            continue

        matched = False
        for key in list(pending):
            if stripped.startswith(f"{key}:"):
                child_indent = indent if indent > section_indent else child_indent
                out.append(" " * indent + f"{key}: {pending.pop(key)}")
                matched = True
                break
        if not matched:
            # 记录区块内实际的子级缩进，供补写缺失键时对齐
            if stripped and not stripped.startswith("#") and indent > section_indent:
                child_indent = indent
            out.append(line)

    if inside:
        flush_pending()

    if not found_section:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{section}:")
        for k, v in values.items():
            out.append(f"  {k}: {v}")

    return "\n".join(out).rstrip("\n") + "\n"


def saved_api_key() -> str:
    """取出已保存的明文 Key（仅供服务端内部使用，绝不下发到前端）。"""
    env_map = _read_env_map()
    return (
        env_map.get(_ENV_KEY_API)
        or os.environ.get(_ENV_KEY_API)
        or os.environ.get("DOUBAO_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()


def read_model_config(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """读取当前模型配置，供控制台回显（Key 只返回打码后的形式）。"""
    cfg = cfg or load_settings(reload_env=False)
    env_map = _read_env_map()

    summarizer = cfg.get("summarizer", {}) or {}
    provider = str(summarizer.get("provider", "file_output"))
    api_key = (
        env_map.get(_ENV_KEY_API)
        or os.environ.get(_ENV_KEY_API)
        or os.environ.get("DOUBAO_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    )
    base_url = (
        env_map.get(_ENV_KEY_BASE)
        or os.environ.get(_ENV_KEY_BASE)
        or os.environ.get("DOUBAO_BASE_URL")
        or ""
    )
    model = env_map.get(_ENV_KEY_MODEL) or str(summarizer.get("model") or "")

    online = provider in ("deepseek", "doubao", "openai")
    return {
        "ok": True,
        "provider": provider,
        "mode": "online" if (online and api_key) else "offline",
        "base_url": base_url,
        "model": model,
        "has_key": bool(api_key),
        "key_hint": mask_key(api_key),
        "presets": MODEL_PRESETS,
        "env_path": str(env_file_path()),
        "env_exists": env_file_path().exists(),
        "vision_provider": (cfg.get("vision", {}) or {}).get("provider", "dummy"),
    }


def save_model_config(
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
) -> Dict[str, Any]:
    """保存模型配置到 .env 与 settings.yaml。

    Args:
        provider: `file_output`（离线）或 `deepseek` / `doubao` / `openai`（在线）。
        api_key: 明文 Key。传空字符串表示清除。
        base_url: OpenAI 兼容地址，写到版本号那一层。
        model: 模型名或接入点 ID。

    Returns:
        同 `read_model_config` 的结构，便于前端保存后立即刷新显示。
    """
    provider = (provider or "file_output").strip().lower()
    if provider not in ("file_output", "deepseek", "doubao", "openai"):
        raise ConfigError(f"不支持的 provider：{provider}")

    base_url = (base_url or "").strip().rstrip("/")
    model = (model or "").strip()

    if provider != "file_output":
        if not base_url:
            raise ConfigError("在线模式必须填写 Base URL")
        if not base_url.startswith(("http://", "https://")):
            raise ConfigError("Base URL 必须以 http:// 或 https:// 开头")
        if not model:
            raise ConfigError("在线模式必须填写模型名")

    _write_env_updates(
        {
            _ENV_KEY_API: (api_key or "").strip(),
            _ENV_KEY_BASE: base_url,
            _ENV_KEY_MODEL: model,
        }
    )

    # 同步 settings.yaml：provider 决定走在线还是离线；model 同步一份便于排查
    settings_path = CONFIG_DIR / "settings.yaml"
    try:
        text = settings_path.read_text(encoding="utf-8") if settings_path.exists() else ""
        text = _set_yaml_scalars_in_section(
            text,
            "summarizer",
            {
                "provider": f'"{provider}"',
                "model": f'"{model or "deepseek-chat"}"',
            },
        )
        settings_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"写入 settings.yaml 失败：{exc}") from exc

    logger.info(
        "模型配置已更新：provider=%s model=%s key=%s",
        provider,
        model or "-",
        mask_key(api_key) or "(空)",
    )
    return read_model_config()
