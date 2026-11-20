"""SQLite 直读采集器 —— 从 SIWX 解密后的微信 4.x 数据库读取群聊消息。

背景：chatlog 工具已停更，无法从微信 4.1.x 提取密钥。改用
SIWX（stories-in-wx）完成「密钥提取 + 数据库解密」，本模块直接
读取解密后的明文 SQLite 数据库，向流水线提供与 ChatlogClient
完全相同的接口（health / get_groups / get_messages）。

数据库来源（SIWX 解密输出目录）：
    <decrypted_dir>/message/message_0.db   消息（每会话一张 Msg_<md5> 表）
    <decrypted_dir>/contact/contact.db     联系人（昵称 / 备注 / 群信息）

映射规则（已在真实数据上验证）：
    表名 = "Msg_" + md5(会话 wxid)          命中率 46/47
    发送者 = real_sender_id → Name2Id.rowid → user_name → contact 昵称
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from collector.models import (
    TYPE_ARTICLE,
    TYPE_EMOJI,
    TYPE_FILE,
    TYPE_IMAGE,
    TYPE_SYSTEM,
    TYPE_TEXT,
    TYPE_VIDEO,
    TYPE_VOICE,
    Message,
)
from core.log import get_logger

logger = get_logger("sqlite_client")

_TYPE_MAP = {
    1: TYPE_TEXT,
    3: TYPE_IMAGE,
    34: TYPE_VOICE,
    43: TYPE_VIDEO,
    47: TYPE_EMOJI,     # 表情包：内容是 <msg><emoji .../> XML，必须单独渲染
    49: TYPE_ARTICLE,   # 复合消息（链接 / 文件 / 转发）
    57: TYPE_TEXT,      # 引用消息，取 <title> 作为正文
    10000: TYPE_SYSTEM,
    10002: TYPE_SYSTEM,
    51: TYPE_TEXT,      # 状态消息
}

_MEDIA_RE = re.compile(r"([0-9a-f]{32})", re.I)
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _decode_content(content: Any) -> str:
    """WCDB 压缩内容解码：zstd 魔数解压 + UTF-8；失败返回空串。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    raw = bytes(content)
    if raw[:4] == _ZSTD_MAGIC:
        try:
            import zstandard as _zstd

            raw = _zstd.ZstdDecompressor().decompressobj().decompress(raw)
        except ImportError:
            # zstandard 是核心依赖，装缺了等于这部分消息全丢 —— 必须出声
            logger.warning("未安装 zstandard，WCDB 压缩内容无法解压（消息可能缺失）；请重装：pip install -e .")
            return ""
        except Exception:
            return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""


class SqliteClient:
    """解密 SQLite 直读客户端，接口与 ChatlogClient 对齐。"""

    source_mode = "sqlite"

    def __init__(self, decrypted_dir: str | Path) -> None:
        """Args: decrypted_dir — SIWX 解密输出目录（含 message/ contact/ 子目录）。"""
        self.base = Path(decrypted_dir)
        self._contact_cache: Optional[Dict[str, Dict[str, str]]] = None

    # ------------------------------------------------------------------ #
    # 基础
    # ------------------------------------------------------------------ #
    def _open(self, sub: str) -> Optional[sqlite3.Connection]:
        """打开子数据库，失败返回 None。"""
        path = self.base / sub
        if not path.exists():
            return None
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error:
            return None

    def health(self) -> bool:
        """message_0.db 存在且可打开即视为在线。"""
        conn = self._open("message/message_0.db")
        if conn is None:
            return False
        try:
            conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    # 联系人
    # ------------------------------------------------------------------ #
    def _contacts(self) -> Dict[str, Dict[str, str]]:
        """wxid → {nick, remark, alias}。只取一次，进程内缓存。"""
        if self._contact_cache is not None:
            return self._contact_cache
        cache: Dict[str, Dict[str, str]] = {}
        conn = self._open("contact/contact.db")
        if conn is not None:
            try:
                for row in conn.execute(
                    "SELECT username, nick_name, remark, alias FROM contact"
                ):
                    cache[row["username"]] = {
                        "nick": (row["nick_name"] or "").strip(),
                        "remark": (row["remark"] or "").strip(),
                        "alias": (row["alias"] or "").strip(),
                    }
            except sqlite3.Error:
                pass
            finally:
                conn.close()
        self._contact_cache = cache
        return cache

    @staticmethod
    def _display(wxid: str, info: Optional[Dict[str, str]]) -> str:
        """挑最友好的显示名：备注 > 昵称 > 别名 > wxid。"""
        if info:
            for key in ("remark", "nick", "alias"):
                if info.get(key):
                    return info[key]
        return wxid

    # ------------------------------------------------------------------ #
    # 群列表
    # ------------------------------------------------------------------ #
    def get_groups(self) -> List[Dict[str, Any]]:
        """列出「仍在群中」的群聊：[{name, id}]，按名称排序。

        已退出的群（contact.is_in_chat_room == 2）不再展示，避免占空间。
        """
        conn = self._open("message/message_0.db")
        if conn is None:
            return []
        contacts = self._contacts()
        # 已退群/被移出群的 wxid：is_in_chat_room == 2 表示当前不在群里
        exited = self._exited_chatrooms()
        tables = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'Msg_%'"
            )
        }
        groups: List[Dict[str, Any]] = []
        try:
            for row in conn.execute(
                "SELECT user_name FROM Name2Id WHERE user_name LIKE '%@chatroom'"
            ):
                wxid = row["user_name"]
                if wxid in exited:
                    continue
                if f"Msg_{hashlib.md5(wxid.encode()).hexdigest()}" not in tables:
                    continue
                groups.append(
                    {"name": self._display(wxid, contacts.get(wxid)), "id": wxid}
                )
        except sqlite3.Error:
            pass
        finally:
            conn.close()
        groups.sort(key=lambda g: g["name"])
        return groups

    def _exited_chatrooms(self) -> set:
        """返回已退出/被移出群的 wxid 集合（is_in_chat_room == 2）。"""
        conn = self._open("contact/contact.db")
        exited: set = set()
        if conn is None:
            return exited
        try:
            for row in conn.execute(
                "SELECT username FROM contact "
                "WHERE userName LIKE '%@chatroom' AND is_in_chat_room = 2"
            ):
                exited.add(row["username"])
        except sqlite3.Error:
            pass
        finally:
            conn.close()
        return exited

    def get_contacts(self, category: str = "friend") -> List[Dict[str, Any]]:
        """列出联系人（好友 / 公众号），供「好友功能」扩展使用。

        Args:
            category: `friend` 返回真实好友，`official` 返回公众号/订阅号。

        Returns:
            `[{"name", "id", "remark", "alias"}]`，按显示名排序。
        """
        conn = self._open("contact/contact.db")
        if conn is None:
            return []
        result: List[Dict[str, Any]] = []
        try:
            # 公众号/企业号的 username 常以 gh_ 开头（gh = 公众号）
            if category == "official":
                rows = conn.execute(
                    "SELECT username, nick_name, remark, alias FROM contact "
                    "WHERE userName LIKE 'gh_%' ORDER BY remark, nick_name"
                ).fetchall()
            else:
                # 真实好友：wxid_ 开头（非群、非公众号、非 openim 临时会话）。
                # 先拉全量，再用 Python 过滤噪音：无备注且昵称是纯符号/极短的，
                # 通常是「加了但没聊过的陌生人」，不展示。
                rows = conn.execute(
                    "SELECT username, nick_name, remark, alias FROM contact "
                    "WHERE userName LIKE 'wxid_%' "
                    "ORDER BY remark, nick_name"
                ).fetchall()
        except sqlite3.Error:
            return []
        finally:
            conn.close()

        for row in rows:
            username = row["username"]
            remark = (row["remark"] or "").strip()
            nick = (row["nick_name"] or "").strip()
            alias = (row["alias"] or "").strip()

            # 是否「没有能认出是谁的名字」：无备注，且昵称没有实质内容
            # （纯数字如 "11"/"09"、纯符号如 "( ´(00)`) "、过短）。
            # 注意：**不再静默丢弃**这类联系人——静默过滤会让好友"凭空消失"。
            # 这里只打标记，由前端「隐藏无有效昵称」开关决定是否展示。
            noisy = (not remark) and (not _is_meaningful_name(nick))
            if remark:
                display = remark
            elif not noisy:
                display = nick
            else:
                # 昵称没辨识度时退化为微信号，至少同名条目之间能区分开
                display = alias or username
            result.append(
                {
                    "name": display,  # 兼容旧字段：前端列表/搜索都用它
                    "display": display,
                    "id": username,
                    "nick": nick,
                    "remark": remark,
                    "alias": alias,
                    "noisy": noisy,
                }
            )
        # 排序很关键：接口默认只返回前 200 条，若把「无有效昵称」的排在前面，
        # 前端默认隐藏它们后第一页就只剩十几条，看起来像"好友丢了"。
        # 所以有辨识度的排前、有备注的更靠前，noisy 沉底。
        if category == "friend":
            result.sort(key=lambda x: (x["noisy"], 0 if x["remark"] else 1, x["display"]))
        else:
            result.sort(key=lambda x: x["display"])
        return result

    # ------------------------------------------------------------------ #
    # 消息
    # ------------------------------------------------------------------ #
    def _resolve_wxid(self, group_name: str) -> Optional[str]:
        """把群名称（或 wxid）解析成 wxid。"""
        contacts = self._contacts()
        target = group_name.strip().lower()
        if target.endswith("@chatroom"):
            return group_name.strip()
        for wxid, info in contacts.items():
            if not wxid.endswith("@chatroom"):
                continue
            for v in info.values():
                if v and v.lower() == target:
                    return wxid
        return None

    def get_messages(
        self,
        group_name: str,
        start_time: datetime,
        end_time: datetime,
        leaders: Optional[Iterable[Dict[str, Any]]] = None,
        keyword: Optional[str] = None,
    ) -> List[Message]:
        """拉取指定群在 [start_time, end_time] 内的消息，按时间升序。"""
        wxid = self._resolve_wxid(group_name)
        if wxid is None:
            return []
        table = f"Msg_{hashlib.md5(wxid.encode()).hexdigest()}"

        conn = self._open("message/message_0.db")
        if conn is None:
            return []
        try:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = ?", (table,)
            ).fetchone():
                return []

            id2name = {
                r["rowid"]: r["user_name"]
                for r in conn.execute("SELECT rowid, user_name FROM Name2Id")
            }
            contacts = self._contacts()
            leader_ids = {
                str(x.get("name", "")).strip().lower() for x in (leaders or []) if x
            }

            rows = conn.execute(
                f"SELECT local_id, local_type, sort_seq, real_sender_id, "
                f"create_time, message_content FROM {table} "
                f"WHERE create_time >= ? AND create_time <= ? "
                f"ORDER BY sort_seq ASC",
                (int(start_time.timestamp()), int(end_time.timestamp())),
            ).fetchall()

            messages: List[Message] = []
            for row in rows:
                raw_lt = int(row["local_type"] or 0)
                ltype = raw_lt & 0xFFFF
                # 微信 4.x 的 local_type 是 64 位：高 32 位是真正的消息子类型。
                # 高位 0x3E = 拍一拍（"A 拍了拍 B"），属无意义互动，直接跳过，
                # 避免它混进总结当成任务/链接。
                high = raw_lt >> 32
                if high == 0x3E:
                    continue
                msg_type = _TYPE_MAP.get(ltype, TYPE_SYSTEM)
                raw = _decode_content(row["message_content"]).strip()
                # 双保险：即使高位对不上，内容本身含「拍了拍」也跳过
                if "拍了拍" in raw:
                    continue
                # 复合消息(type=49)里 <appmsg type=6> 是文件（Word/Excel/PDF 等），
                # 单独标记为 TYPE_FILE，避免被当成公众号链接去抓 URL。
                if ltype == 49:
                    appmsg_type = re.search(r"<appmsg[^>]*>.*?<type>(\d+)</type>", raw, re.S)
                    if appmsg_type and int(appmsg_type.group(1)) == 6:
                        msg_type = TYPE_FILE
                sender_wxid = id2name.get(int(row["real_sender_id"] or 0), "")
                info = contacts.get(sender_wxid)
                if msg_type == TYPE_SYSTEM:
                    # 系统消息没有真实发送者，标成「系统」比「未知」清楚
                    sender_name = "系统"
                else:
                    sender_name = self._display(sender_wxid, info) if sender_wxid else "未知"
                is_leader = bool(sender_name) and sender_name.lower() in leader_ids

                content, note = self._render(msg_type, raw)
                if keyword and keyword.lower() not in (content + note).lower():
                    continue

                attachments: List[Dict[str, str]] = []
                if msg_type == TYPE_IMAGE:
                    # 图片 key 取 <img md5="..."> 属性（而非全文搜 hex，避免误抓 aeskey）
                    m = re.search(r'<img\b[^>]*\bmd5="([0-9a-fA-F]{32})"', raw)
                    if m:
                        attachments.append({"kind": "image", "key": m.group(1)})
                elif msg_type == TYPE_ARTICLE and content:
                    attachments.append({"kind": "url", "key": content})

                messages.append(
                    Message(
                        msg_id=f"{wxid}_{row['local_id']}",
                        group_name=group_name,
                        sender_name=sender_name,
                        sender_id=sender_wxid,
                        timestamp=datetime.fromtimestamp(int(row["create_time"])),
                        msg_type=msg_type,
                        content=content,
                        # 媒体类消息不保留原始 XML 乱码（图片/语音/视频/文件），
                        # 只对文字/文章保留原文，避免乱码泄漏进报告。
                        raw_content=(
                            raw[:2000]
                            if msg_type in (TYPE_TEXT, TYPE_ARTICLE)
                            else ""
                        ),
                        is_leader=is_leader,
                        attachments=attachments,
                        seq=int(row["sort_seq"] or 0),
                        note=note,
                    )
                )
            return messages
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    @staticmethod
    def _render(msg_type: str, raw: str) -> tuple[str, str]:
        """把原始内容渲染成 (content, note)。

        content 是**展示给用户 / 喂给 LLM 的可读文字**，绝不把压缩 XML、
        base64 等原始乱码塞进去；note 用于排障，只放简短说明。
        """
        if msg_type == TYPE_TEXT:
            # 引用消息（49/57 XML）：用户回复文本在 <title>
            m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", raw, re.S)
            if raw.lstrip().startswith("<") and m:
                return m.group(1).strip(), "[引用消息]"
            # 微信 4.x 的文字消息 message_content 开头常带「发送者wxid:」前缀，
            # 例如 "wxid_xxxxxxxxxxxx:\n正文"。把它剥掉，只留正文。
            clean = re.sub(r"^wxid_[0-9a-zA-Z_\-]+:\s*", "", raw)
            return clean, ""
        if msg_type == TYPE_SYSTEM:
            # 系统消息（入群/退群/撤回/群公告等）：message_content 是 <sysmsg> XML，
            # 可读文字在 <template><![CDATA[...]]></template> 里，含 "$username$" 占位符。
            # 必须提取成普通文字，否则整段 XML 会当正文漏进报告。
            stripped = re.sub(
                r"^[0-9a-zA-Z_\-]+(?:@chatroom)?:\s*", "", raw.strip(), count=1
            )
            tmpl = re.search(r"<template><!\[CDATA\[(.*?)\]\]></template>", stripped, re.S)
            if tmpl:
                text = tmpl.group(1).strip()
                # 按出现顺序把占位符替换成 link_list 里的真实昵称
                nicknames = re.findall(
                    r"<nickname><!\[CDATA\[(.*?)\]\]></nickname>", stripped, re.S
                )
                for nick in nicknames:
                    text = re.sub(
                        r"\$[a-zA-Z_]+\$", lambda _m, _n=nick: _n, text, count=1
                    )
                text = re.sub(r"\$[a-zA-Z_]+\$", "", text).strip()
                if text:
                    return text, "[系统消息]"
            plain = re.search(r"<plain><!\[CDATA\[(.*?)\]\]></plain>", stripped, re.S)
            if plain and plain.group(1).strip():
                return plain.group(1).strip(), "[系统消息]"
            return "", "[系统消息]"
        if msg_type == TYPE_IMAGE:
            # 图片消息的 message_content 是 XML，真正的图片 md5 在 <img md5="...">
            # 属性上。之前用 _MEDIA_RE 在全文搜 32 位 hex，会误抓 aeskey（加密密钥）
            # 当成 key，导致报告里冒出一串乱码。这里改从 md5 属性精确取值。
            #
            # 说明：微信 4.x 把图片存成加密的 .dat，且本地文件名与消息 md5 **对不上**
            # （实测 0/20 命中），无法还原成可显示的图片。这里退而求其次，把尺寸
            # 带出来，让读者知道"这里有一张图、多大"，而不是干巴巴的 [图片]。
            md5 = re.search(r'<img\b[^>]*\bmd5="([0-9a-fA-F]{32})"', raw)
            w = re.search(r'cdnthumbwidth="(\d+)"', raw)
            h = re.search(r'cdnthumbheight="(\d+)"', raw)
            size = ""
            if w and h and w.group(1) not in ("0", "") and h.group(1) not in ("0", ""):
                size = f" {w.group(1)}×{h.group(1)}"
            note = f"md5={md5.group(1)}" if md5 else ""
            return f"[图片{size}]", note
        if msg_type == TYPE_VOICE:
            # 语音：本地没有音频文件（微信只在播放时临时下载，VoiceTemp 是空的），
            # 所以无法转写/播放。但 XML 里有 voicelength（毫秒），把时长显示出来。
            ms = re.search(r'voicelength="(\d+)"', raw)
            dur = _fmt_ms(int(ms.group(1))) if ms else ""
            return (f"[语音 {dur}]" if dur else "[语音]"), "微信本地未缓存音频，无法转写"
        if msg_type == TYPE_VIDEO:
            sec = re.search(r'playlength="(\d+)"', raw)
            dur = _fmt_ms(int(sec.group(1)) * 1000) if sec else ""
            return (f"[视频 {dur}]" if dur else "[视频]"), ""
        if msg_type == TYPE_EMOJI:
            # 表情包：内容是 <msg><emoji md5="..." .../></msg>，绝不能当正文输出，
            # 否则报告里就是一整串 XML（用户看到的"一大串代码"）。
            return "[表情]", "表情包（不参与总结）"
        if msg_type == TYPE_FILE:
            # 文件消息（Word/Excel/PDF 等），文件名在 <title> 里。
            # 把文件名直接放进 content，让报告里能看出是什么文件。
            title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", raw, re.S)
            title_text = title.group(1).strip() if title else ""
            return (f"[文件] {title_text}" if title_text else "[文件]"), "文件消息"
        if msg_type == TYPE_ARTICLE:
            # type=49 里的链接/公众号文章：title + url（文件已在上层归为 TYPE_FILE）
            title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", raw, re.S)
            url = re.search(r"<url>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</url>", raw, re.S)
            note = f"链接标题：{title.group(1)}" if title else ""
            return (url.group(1) if url else ""), note
        # 兜底：未知类型且内容是 XML 时不直接展示，避免乱码泄漏进报告
        if raw.lstrip().startswith("<"):
            return "", "[暂不支持的消息类型]"
        return raw[:500], ""


def _fmt_ms(ms: int) -> str:
    """把毫秒格式化成 5″ / 1′23″，用于语音、视频时长展示。"""
    if ms <= 0:
        return ""
    total = int(round(ms / 1000.0))
    if total < 60:
        return f"{total}″"
    m, s = divmod(total, 60)
    return f"{m}′{s}″"


def _is_meaningful_name(text: str) -> bool:
    """判断昵称是否「能认出是谁」：必须含中文或字母。

    特意排除**纯数字**与**纯符号**：真机里 "11"、"09"、"( ´(00)`)"
    这类昵称没有任何辨识度，直接展示会让人以为列表是乱码。
    以中文/字母为主、夹带数字的（如 "张三13800000000"）仍算有效。
    """
    if not text or len(text) < 2:
        return False
    import re as _re

    return bool(_re.search(r"[\u4e00-\u9fffA-Za-z]", text))


def build_sqlite_client_from_config(cfg: Dict[str, Any]) -> Optional[SqliteClient]:
    """按 settings.yaml 的 chatlog.decrypted_dir 构造；未配置返回 None。"""
    chatlog_cfg = cfg.get("chatlog", {}) or {}
    data_dir = chatlog_cfg.get("decrypted_dir") or ""
    if not data_dir:
        return None
    return SqliteClient(data_dir)
