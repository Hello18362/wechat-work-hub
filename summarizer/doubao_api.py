"""豆包 / OpenAI 兼容 API 直连总结（预留，用于自动化阶段）。

默认走火山方舟的 OpenAI 兼容接口：

    POST {base_url}/chat/completions
    Authorization: Bearer ${DOUBAO_API_KEY}

没有密钥时 `available` 返回 False，工厂会自动回落到 file_output，不会报错。
"""

from __future__ import annotations

import time
from typing import Any, Dict

import requests

from core.log import get_logger
from summarizer.base import Summarizer

logger = get_logger("doubao_api")


class DoubaoSummarizer(Summarizer):
    """调用在线大模型完成总结。

    Args:
        api_key: API Key（来自 .env）。
        base_url: 服务地址，形如 `https://ark.cn-beijing.volces.com/api/v3`。
        model: 模型接入点 ID 或模型名。
        timeout: 单次请求超时秒数（总结通常较慢，默认给到 120s）。
        temperature: 采样温度，总结任务建议压低以保证稳定。
        max_tokens: 单次最大输出 token。
    """

    name = "doubao"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        model: str = "doubao-seed-1904",
        timeout: int = 120,
        temperature: float = 0.3,
        max_tokens: int = 3000,
    ) -> None:
        super().__init__()
        self.api_key = (api_key or "").strip()
        self.base_url = str(base_url).rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._session = requests.Session()
        self._session.trust_env = False

    @property
    def available(self) -> bool:
        """有密钥才算可用。"""
        return bool(self.api_key)

    def summarize(self, chat_content: str, prompt_template: str) -> str:
        """调用模型生成总结。

        Args:
            chat_content: 合并后的聊天文本。
            prompt_template: prompt 模板原文。

        Returns:
            模型返回的 Markdown 总结；失败时返回带错误说明的 Markdown。
        """
        if not self.available:
            self.last_meta["error"] = "missing_api_key"
            return self._error_block("未配置 DOUBAO_API_KEY，已跳过在线总结。")

        prompt = self.render_prompt(
            prompt_template,
            chat_content=chat_content,
            leaders_list=self.last_meta.get("leaders_text", "（未指定）"),
            group_name=self.last_meta.get("group_name", "未命名群"),
            date=self.last_meta.get("date", ""),
        )

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是严谨的工作助手，只依据给定聊天记录作答，不臆造信息。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        try:
            logger.info("调用在线总结模型：%s", self.model)
            resp = self._session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            logger.error("在线总结请求失败：%s", exc)
            self.last_meta["error"] = "request_failed"
            return self._error_block(f"在线总结请求失败：{exc}")

        if resp.status_code != 200:
            logger.error("在线总结返回 %s：%s", resp.status_code, resp.text[:300])
            self.last_meta["error"] = f"http_{resp.status_code}"
            return self._error_block(f"在线总结失败（HTTP {resp.status_code}）：{resp.text[:200]}")

        try:
            body = resp.json()
            choices = body.get("choices") or []
            message = choices[0].get("message", {}) if choices else {}
            content = str(message.get("content") or "").strip()
            # 容错：部分模型（如开启思维链的 deepseek-flash）会把回答放在
            # reasoning_content，而 content 为空。此时降级用 reasoning_content，
            # 避免「模型返回空内容」的误判。
            if not content:
                content = str(message.get("reasoning_content") or "").strip()
            usage = body.get("usage") or {}
            self.last_meta["tokens"] = usage
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.error("在线总结响应解析失败：%s", exc)
            self.last_meta["error"] = "bad_response"
            return self._error_block("在线总结响应解析失败，请查看日志。")

        if not content:
            self.last_meta["error"] = "empty_response"
            return self._error_block("模型返回了空内容。")

        logger.info("在线总结完成（%d 字）", len(content))
        return content

    @staticmethod
    def _error_block(reason: str) -> str:
        """统一的失败占位区块，保证报告结构不被破坏。"""
        return (
            "## 总结\n\n"
            f"> ⚠️ {reason}\n>\n"
            "> 聊天记录已完整保留在下方，可改用 `file_output` 模式离线处理。"
        )


def test_connection(
    api_key: str,
    base_url: str,
    model: str,
    timeout: int = 25,
) -> Dict[str, Any]:
    """用一次极小的请求验证「Key + 地址 + 模型名」三者是否都对。

    控制台的「测试连接」按钮调这个函数。它刻意做到三件事：

    1. **发真实请求**——只校验格式没有意义，用户要的是「能不能出结果」；
    2. **消耗极小**——max_tokens=8，一次测试的成本可以忽略；
    3. **把网络错误的种类翻译成人话**——401/404/超时对应的问题完全不同，
       直接抛原始异常用户看不懂。

    Args:
        api_key: 明文 Key。
        base_url: OpenAI 兼容地址（不需要带 /chat/completions）。
        model: 模型名或接入点 ID。
        timeout: 超时秒数。

    Returns:
        `{"ok": bool, "message": str, "detail": str, "latency_ms": int}`
        其中 `message` 是可以直接显示给用户的中文结论。
    """
    api_key = (api_key or "").strip()
    base_url = (base_url or "").strip().rstrip("/")
    model = (model or "").strip()

    if not api_key:
        return {
            "ok": False,
            "message": "还没填 API Key",
            "detail": "本地模型（Ollama / LM Studio）不校验 Key，但也要随便填一个占位值，例如 ollama。",
            "latency_ms": 0,
        }
    if not base_url.startswith(("http://", "https://")):
        return {
            "ok": False,
            "message": "Base URL 格式不对",
            "detail": "要以 http:// 或 https:// 开头，并且填到版本号那一层，例如 https://api.deepseek.com 或 https://xxx.com/v1。",
            "latency_ms": 0,
        }
    if not model:
        return {
            "ok": False,
            "message": "还没填模型名",
            "detail": "例如 deepseek-chat / qwen-plus / moonshot-v1-8k。豆包要填推理接入点 ID（ep-xxxxxx）。",
            "latency_ms": 0,
        }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    started = time.time()
    try:
        with requests.Session() as session:
            session.trust_env = False  # 绕开系统代理，避免「本机代理挂了导致全部失败」
            resp = session.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=timeout,
            )
    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "message": "连接超时",
            "detail": f"{timeout} 秒内没有响应。可能是网络问题，或 Base URL 写错（例如把 https 写成了 http）。",
            "latency_ms": int((time.time() - started) * 1000),
        }
    except requests.exceptions.SSLError as exc:
        return {
            "ok": False,
            "message": "SSL 握手失败",
            "detail": f"地址可达但证书校验没通过：{exc}",
            "latency_ms": int((time.time() - started) * 1000),
        }
    except requests.exceptions.ConnectionError as exc:
        return {
            "ok": False,
            "message": "连不上这个地址",
            "detail": f"检查 Base URL 是否写错、服务是否在运行。原始错误：{exc}",
            "latency_ms": int((time.time() - started) * 1000),
        }
    except requests.exceptions.RequestException as exc:
        return {
            "ok": False,
            "message": "请求失败",
            "detail": str(exc),
            "latency_ms": int((time.time() - started) * 1000),
        }

    latency = int((time.time() - started) * 1000)
    snippet = (resp.text or "")[:400]

    if resp.status_code == 200:
        try:
            body = resp.json()
            choices = body.get("choices") or []
            content = ""
            if choices:
                message = choices[0].get("message", {}) or {}
                content = str(message.get("content") or message.get("reasoning_content") or "")
            if choices:
                return {
                    "ok": True,
                    "message": f"连接成功，模型有响应（{latency} ms）",
                    "detail": (content or "（模型返回空内容，但接口调用正常）")[:200],
                    "latency_ms": latency,
                }
            return {
                "ok": False,
                "message": "接口能通，但返回结构不对",
                "detail": f"没有 choices 字段，可能这个地址不是 OpenAI 兼容接口。响应片段：{snippet}",
                "latency_ms": latency,
            }
        except ValueError:
            return {
                "ok": False,
                "message": "接口返回的不是 JSON",
                "detail": f"可能 Base URL 指到了网页而不是 API。响应片段：{snippet}",
                "latency_ms": latency,
            }

    hints = {
        400: "请求被拒绝。最常见的原因是模型名写错，或这个模型不支持 max_tokens 参数。",
        401: "Key 无效或已失效。去服务商控制台重新复制一次，注意不要带空格和引号。",
        403: "Key 没有访问这个模型的权限，可能需要在控制台开通对应模型。",
        404: "地址或模型不存在。检查 Base URL 是否需要带 /v1，以及模型名拼写。",
        429: "请求太频繁，或者账户余额/额度不足。",
        500: "服务端出错，通常是服务商侧的问题，稍后重试。",
        502: "网关错误，多为代理或中转服务的问题。",
        503: "服务暂时不可用，稍后重试。",
    }
    return {
        "ok": False,
        "message": f"失败（HTTP {resp.status_code}）",
        "detail": hints.get(resp.status_code, "服务端返回了错误。") + f"\n原始响应：{snippet}",
        "latency_ms": latency,
    }
