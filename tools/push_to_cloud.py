from __future__ import annotations

"""把本机某天一个或多个群的聊天记录推送到云端服务。"""

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLOUD = "http://127.0.0.1:5720"
MAX_MEDIA_FILE_BYTES = 10 * 1024 * 1024
MAX_MEDIA_REQUEST_BYTES = 50 * 1024 * 1024
MAX_MEDIA_FILES = 20
MEDIA_KINDS = {"voice", "image"}
CLOUD_TYPES = {"text", "voice", "image", "article"}


class PushError(RuntimeError):
    """单群预检或构造失败；调用方可隔离该群继续。"""


@dataclass(frozen=True)
class MediaPart:
    field: str
    kind: str
    filename: str
    payload: bytes

    @property
    def size(self) -> int:
        return len(self.payload)


@dataclass(frozen=True)
class PreparedGroup:
    rows: list[dict[str, Any]]
    media: list[MediaPart]


def _load_runtime():
    """只在真正执行 CLI 时导入老项目模块，避免被参赛项目同名包污染。"""
    root_text = str(ROOT)
    sys.path[:] = [entry for entry in sys.path if entry != root_text]
    sys.path.insert(0, root_text)
    # 该脚本可能被测试进程从参赛仓库导入；不要复用错误根目录下的同名包。
    for name, module in list(sys.modules.items()):
        if name != "collector" and not name.startswith("collector.") and name != "core" and not name.startswith("core."):
            continue
        origin = getattr(module, "__file__", None)
        if origin and not Path(origin).resolve().is_relative_to(ROOT):
            sys.modules.pop(name, None)
    from collector.chatlog_client import build_client_from_config
    from core.config import load_settings
    from core.pipeline import parse_date

    return build_client_from_config, load_settings, parse_date


def stable_msg_id(group: str, date_text: str, source_id: Any, used: set[str]) -> str:
    """生成服务端允许的、跨重复推送稳定的消息 ID。"""
    source = str(source_id or "unknown")
    digest = hashlib.sha1(f"{group}\0{date_text}\0{source}".encode("utf-8")).hexdigest()[:16]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", source).strip("-")[:48] or "msg"
    candidate = f"{stem}-{digest}"
    serial = 2
    while candidate in used:
        candidate = f"{stem}-{digest}-{serial}"
        serial += 1
    used.add(candidate)
    return candidate


def _cloud_type(msg_type: Any) -> str:
    value = str(msg_type or "text").strip().lower()
    return value if value in CLOUD_TYPES else "text"


def _message_attachments(msg: Any) -> list[dict[str, Any]]:
    """读取现有采集器的附件元数据；未显式保留的语音/图片也补一个声明。"""
    raw = getattr(msg, "attachments", None)
    attachments = [dict(item) for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []
    kinds = {str(item.get("kind") or "").lower() for item in attachments}
    msg_type = str(getattr(msg, "msg_type", "") or "").lower()
    if msg_type in MEDIA_KINDS and msg_type not in kinds:
        key = getattr(msg, "raw_content", "") or getattr(msg, "msg_id", "")
        attachments.append({"kind": msg_type, "key": key})
    return attachments


def _read_media(client: Any, msg: Any, kind: str, key: Any) -> MediaPart:
    if kind not in MEDIA_KINDS:
        raise PushError(f"不支持的媒体类型：{kind}")
    getter = getattr(client, f"get_{kind}_file", None)
    if not callable(getter):
        raise PushError(f"数据源不提供 {kind} 文件接口")
    lookup = str(key or "").strip()
    if not lookup:
        raise PushError(f"{kind} 缺少媒体 key（消息 {getattr(msg, 'msg_id', '')}）")
    path_value = getter(lookup)
    if not path_value:
        raise PushError(f"{kind} 媒体不存在或下载失败（消息 {getattr(msg, 'msg_id', '')}）")
    path = Path(path_value)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PushError(f"{kind} 媒体文件不可读：{path.name}（{exc}）") from exc
    if size <= 0:
        raise PushError(f"{kind} 媒体文件为空：{path.name}")
    if size > MAX_MEDIA_FILE_BYTES:
        raise PushError(f"{kind} 媒体超过 10MiB：{path.name}（{size} 字节）")
    suffix = path.suffix.lower()
    allowed = {
        "voice": {".mp3", ".m4a", ".wav", ".amr"},
        "image": {".jpg", ".jpeg", ".png", ".webp"},
    }[kind]
    if suffix not in allowed:
        raise PushError(f"{kind} 媒体扩展名不支持：{path.name}")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise PushError(f"{kind} 媒体读取失败：{path.name}（{exc}）") from exc
    if len(payload) != size:
        raise PushError(f"{kind} 媒体读取大小变化：{path.name}")
    return MediaPart(field="", kind=kind, filename=path.name, payload=payload)


def prepare_group(group: str, date_text: str, messages: Sequence[Any], client: Any) -> PreparedGroup:
    """把一群消息预检成云端 manifest 行和实际附件；失败时不产生上传请求。"""
    if not messages:
        return PreparedGroup([], [])
    used: set[str] = set()
    rows: list[dict[str, Any]] = []
    media: list[MediaPart] = []
    for msg in messages:
        msg_id = stable_msg_id(group, date_text, getattr(msg, "msg_id", ""), used)
        msg_type = _cloud_type(getattr(msg, "msg_type", "text"))
        row: dict[str, Any] = {
            "msg_id": msg_id,
            "time": getattr(msg, "timestamp").strftime("%Y-%m-%d %H:%M:%S"),
            "sender": str(getattr(msg, "sender_name", "") or "未知"),
            "content": str(getattr(msg, "content", "") or getattr(msg, "raw_content", "") or ""),
            "type": msg_type,
        }
        row_media: list[MediaPart] = []
        for attachment in _message_attachments(msg):
            kind = str(attachment.get("kind") or "").strip().lower()
            if kind == "article":
                continue  # URL 已在 content/note 中，不是本端文件。
            if kind not in MEDIA_KINDS:
                raise PushError(f"消息 {getattr(msg, 'msg_id', '')} 含不支持的附件类型：{kind or '空'}")
            if any(part.kind == kind for part in row_media):
                raise PushError(f"消息 {getattr(msg, 'msg_id', '')} 含多个 {kind}，当前协议一条消息只允许一个")
            key = attachment.get("key") or getattr(msg, "raw_content", "") or getattr(msg, "msg_id", "")
            part = _read_media(client, msg, kind, key)
            part = MediaPart(
                field=f"{msg_id}.{kind}", kind=part.kind, filename=part.filename, payload=part.payload
            )
            row_media.append(part)
        if row_media:
            row["attachments"] = [
                {
                    "kind": part.kind,
                    "field": part.field,
                    "sha256": hashlib.sha256(part.payload).hexdigest(),
                }
                for part in row_media
            ]
            media.extend(row_media)
        rows.append(row)
    return PreparedGroup(rows, media)


def build_multipart(
    rows: Sequence[dict[str, Any]],
    media: Sequence[MediaPart],
    *,
    group: str = "",
    date_text: str = "",
    boundary: str = "qunshitong-boundary",
) -> bytes:
    """构造服务端 /api/upload-media 所需 multipart，并返回实际请求字节。"""
    files = {part.field: part for part in media}
    manifest = {
        "group": group,
        "date": date_text,
        "messages": list(rows),
    }
    chunks: list[bytes] = []
    marker = boundary.encode("ascii")
    chunks.append(b"--" + marker + b"\r\n")
    chunks.append(b'Content-Disposition: form-data; name="manifest"\r\n')
    chunks.append(b"Content-Type: application/json; charset=utf-8\r\n\r\n")
    chunks.append(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    chunks.append(b"\r\n")
    for part in media:
        filename = Path(part.filename).name
        if not filename or "\x00" in filename:
            raise PushError("媒体文件名无效")
        chunks.append(b"--" + marker + b"\r\n")
        chunks.append(
            f'Content-Disposition: form-data; name="{part.field}"; filename="{filename}"\r\n'.encode("utf-8")
        )
        chunks.append(b"Content-Type: application/octet-stream\r\n\r\n")
        chunks.append(part.payload)
        chunks.append(b"\r\n")
    chunks.append(b"--" + marker + b"--\r\n")
    return b"".join(chunks)


def make_batches(group: str, date_text: str, prepared: PreparedGroup) -> list[tuple[list[dict[str, Any]], list[MediaPart], bytes]]:
    """按附件数和完整 multipart 字节数切分；所有批次都走媒体端点。"""
    if not prepared.rows:
        return []
    media_by_field = {part.field: part for part in prepared.media}
    batches: list[tuple[list[dict[str, Any]], list[MediaPart], bytes]] = []
    current_rows: list[dict[str, Any]] = []
    current_media: list[MediaPart] = []

    def candidate(rows: list[dict[str, Any]], media: list[MediaPart]) -> bytes:
        return build_multipart(rows, media, group=group, date_text=date_text, boundary="qst-fixed-boundary")

    for row in prepared.rows:
        row_media = [media_by_field[a["field"]] for a in row.get("attachments", [])]
        if len(row_media) > MAX_MEDIA_FILES:
            raise PushError("单批媒体附件数量超过 20")
        test_rows = current_rows + [row]
        test_media = current_media + row_media
        body = candidate(test_rows, test_media)
        if current_rows and (len(test_media) > MAX_MEDIA_FILES or len(body) > MAX_MEDIA_REQUEST_BYTES):
            final_body = candidate(current_rows, current_media)
            batches.append((current_rows, current_media, final_body))
            current_rows, current_media = [row], row_media
            body = candidate(current_rows, current_media)
            test_rows, test_media = current_rows, current_media
        if len(body) > MAX_MEDIA_REQUEST_BYTES:
            raise PushError(f"单条消息无法装入 50MiB 请求：{row.get('msg_id')}")
        current_rows, current_media = test_rows, test_media
    if current_rows:
        batches.append((current_rows, current_media, candidate(current_rows, current_media)))
    return batches


def post_batch(cloud: str, body: bytes, timeout: int = 60) -> dict[str, Any]:
    boundary = "qst-fixed-boundary"
    url = cloud.rstrip("/") + "/api/upload-media"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Content-Length", str(len(body)))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise PushError(f"云端返回 HTTP {exc.code}：{exc.read().decode('utf-8', 'replace')[:300]}") from exc
    except urllib.error.URLError as exc:
        raise PushError(f"连不上云端 {cloud}：{exc.reason}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise PushError(f"云端响应无效：{exc}") from exc
    if not result.get("ok"):
        raise PushError(f"云端拒绝请求：{result}")
    return result


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = str(value).strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把本机某天一个或多个群的聊天记录推送到云端")
    parser.add_argument("--group", "-g", action="append", help="群名；可重复指定")
    parser.add_argument("--all", action="store_true", help="推送数据源返回的全部群（上限由数据源决定，当前 chatlog 为 500）")
    parser.add_argument("--date", "-d", default="today", help="today / yesterday / 2026-10-25")
    parser.add_argument("--cloud", default=DEFAULT_CLOUD, help=f"云端地址，默认 {DEFAULT_CLOUD}")
    parser.add_argument("--dry-run", action="store_true", help="只预检和打印统计，不上传、不打印聊天正文")
    args = parser.parse_args(argv)
    if args.all and args.group:
        parser.error("--all 不能与 --group 同时使用")
    if not args.all and not args.group:
        parser.error("必须指定 --group（可重复）或 --all")

    build_client_from_config, load_settings, parse_date = _load_runtime()
    cfg = load_settings()
    client = build_client_from_config(cfg)
    if not client.health():
        print("✗ 本机数据源不可用，请先确认老项目的数据源")
        try:
            client.close()
        except Exception:
            pass
        return 1

    day = parse_date(args.date)
    start = day
    end = day.replace(hour=23, minute=59, second=59)
    if args.all:
        groups = _dedupe(str(item.get("name")) for item in (client.get_groups() or []) if isinstance(item, Mapping))
        print(f"--all：使用数据源返回的全部群（当前 chatlog 列表接口上限 500），共 {len(groups)} 个")
    else:
        groups = _dedupe(args.group or [])

    failures = 0
    try:
        for group in groups:
            try:
                messages = client.get_messages(group, start, end, leaders=None)
                if not messages:
                    print(f"○ {group}：无消息")
                    continue
                prepared = prepare_group(group, day.strftime("%Y-%m-%d"), messages, client)
                batches = make_batches(group, day.strftime("%Y-%m-%d"), prepared)
                total_bytes = sum(len(body) for _, _, body in batches)
                print(f"· {group}：{len(messages)} 条消息，{len(prepared.media)} 个附件，{total_bytes} 字节，{len(batches)} 批")
                if args.dry_run:
                    continue
                sent = 0
                try:
                    for _, _, body in batches:
                        post_batch(args.cloud, body)
                        sent += 1
                except PushError as exc:
                    failures += 1
                    if sent:
                        print(f"△ {group}：部分成功，已上传 {sent}/{len(batches)} 批；未自动重试：{exc}")
                    else:
                        print(f"✗ {group}：失败：{exc}")
                    continue
                print(f"✓ {group}：上传成功，{len(messages)} 条消息，{len(prepared.media)} 个附件，{sent} 批")
            except Exception as exc:
                # 数据源单群错误必须隔离；不自动重试，避免掩盖部分成功。
                failures += 1
                print(f"✗ {group}：失败：{exc}")
                continue
    finally:
        try:
            client.close()
        except Exception:
            pass
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
