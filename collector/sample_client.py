"""内置样例数据客户端：让全新安装、尚未配置任何真实数据源的机器也能跑通全链路。

设计目标（对应 P0-5「无数据源什么都跑不了」）：
    · 零依赖、零网络：样例是仓库自带的 JSON 文件（data/samples/*.json）；
    · 接口签名与 `ChatlogClient` 完全对齐（health / get_groups / get_messages /
      get_voice_file / get_image_file / close），pipeline 无需感知差异；
    · 只在明确的兜底条件下启用（见 `chatlog_client.build_client_from_config`），
      一旦用户配置了真实数据源，本客户端自动让位。

样例数据是虚构的演示内容，不含任何真实聊天记录。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from collector.models import Message, TYPE_TEXT, normalize_type

# 一个群每天的样例消息数量上限（防御异常输入，永远不要相信文件内容）
_MAX_MESSAGES_PER_GROUP = 500


class SampleClient:
    """从 data/samples/*.json 读取内置样例群聊的只读客户端。"""

    source_mode = "sample"

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else Path(__file__).resolve().parents[1] / "data" / "samples"
        self._files: Dict[str, Path] = {}
        self._scan()

    # ------------------------------ 内部 ------------------------------ #
    def _scan(self) -> None:
        """扫描样例目录，建立「群名 -> 文件路径」索引（坏文件在读取时报具体错误）。"""
        self._files = {}
        if not self.data_dir.is_dir():
            return
        for path in sorted(self.data_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            name = str((payload or {}).get("group") or "").strip()
            if name:
                self._files[name] = path

    def _load_group(self, group_name: str) -> Dict[str, Any]:
        """读取一个群的样例文件；失败抛 ValueError（由调用方决定如何降级）。"""
        path = self._files.get(str(group_name).strip())
        if path is None:
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"样例文件不是对象：{path}")
        return payload

    # ------------------------------ 数据源接口 ------------------------------ #
    def health(self) -> bool:
        """有至少一个可读的样例群文件即视为可用。"""
        return bool(self._files)

    def get_groups(self) -> List[Dict[str, Any]]:
        return [
            {"name": name, "id": "", "member_count": 0}
            for name in self._files
        ]

    def get_messages(
        self,
        group_name: str,
        start_time: datetime,
        end_time: datetime,
        leaders: Optional[Iterable[Dict[str, Any]]] = None,
        keyword: Optional[str] = None,
    ) -> List[Message]:
        """返回该群在 [start_time, end_time] 内的样例消息（按时间升序）。

        `leaders` 参数保持与 ChatlogClient 同签名；样例文件的 leader 标记
        已预先写入（用 `leader: true` 字段），不依赖 groups.yaml 的配置。
        """
        payload = self._load_group(group_name)
        rows = payload.get("messages") or []
        if not isinstance(rows, list):
            return []

        messages: List[Message] = []
        for index, row in enumerate(rows[: _MAX_MESSAGES_PER_GROUP]):
            msg = self._to_message(row, group_name, index)
            if msg is None:
                continue
            if msg.timestamp and not (start_time <= msg.timestamp <= end_time):
                continue
            if keyword and keyword not in (msg.content or ""):
                continue
            messages.append(msg)

        messages.sort(key=lambda m: m.sort_key)
        return messages

    def get_voice_file(self, *args: Any, **kwargs: Any) -> None:
        """样例数据不含语音附件。"""
        return None

    def get_image_file(self, *args: Any, **kwargs: Any) -> None:
        """样例数据不含图片附件。"""
        return None

    def close(self) -> None:
        """无连接可释放（保持接口一致性）。"""

    # ------------------------------ 解析 ------------------------------ #
    @staticmethod
    def _to_message(row: Any, group_name: str, index: int) -> Optional[Message]:
        """把一行样例 JSON 转成 Message；坏行跳过（与 ChatlogClient 同策略）。"""
        if not isinstance(row, dict):
            return None
        time_text = str(row.get("time") or "").strip()
        try:
            timestamp = datetime.fromisoformat(time_text)
        except ValueError:
            return None
        msg_type = normalize_type(row.get("type", TYPE_TEXT))
        return Message(
            msg_id=str(row.get("id") or f"sample-{index}"),
            group_name=str(group_name),
            sender_name=str(row.get("sender") or "未知"),
            sender_id=str(row.get("id") or f"sample-{index}"),
            timestamp=timestamp,
            msg_type=msg_type,
            content=str(row.get("content") or ""),
            raw_content=str(row.get("content") or ""),
            is_leader=bool(row.get("leader")) if isinstance(row.get("leader"), bool) else False,
            seq=int(row.get("seq", index)),
            note="样例数据（虚构，用于演示链路）",
        )