import json
import time
import urllib.request

from botapp.config import AppConfig
from botapp.console import console


class LLMResult:


    def __init__(
        self,
        content: str = "",
        reasoning_content: str = "",
        tool_calls: list[dict] | None = None,
        raw: dict | None = None,
    ) -> None:
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_calls = tool_calls or []
        self.raw = raw or {}

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    def _build_request_body(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        body: dict = {
            "model": self._config.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
        # V4 的 thinking 默认启用，必须显式传 enabled/disabled 才能控制开关
        body["thinking"] = {"type": "enabled" if self._config.thinking else "disabled"}
        if self._config.thinking:
            body["reasoning_effort"] = self._config.reasoning_effort
        return body

    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_chunk=None,
    ) -> LLMResult:

        body = json.dumps(self._build_request_body(messages, tools)).encode()
        req = urllib.request.Request(
            self._config.base_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._config.api_key}",
            },
            method="POST",
        )

        reply_parts: list[str] = []
        thinking_parts: list[str] = []
        # tool_calls 按 index 分片累积：{index: {"id","name","arguments"}}
        tool_calls: dict[int, dict] = {}
        # 原始 SSE 行（逐行原样保留，不格式化）
        raw_chunks: list[dict] = []
        raw_lines: list[str] = []
        t_start = time.perf_counter()
        ttfb: float | None = None
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw in resp:
                if ttfb is None:
                    ttfb = time.perf_counter() - t_start
                line = raw.decode().strip()
                raw_lines.append(line)
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    raw_chunks.append(chunk)
                    choice = chunk["choices"][0]
                    delta = choice.get("delta") or {}
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue

                # 实时回调（在流式过程中逐块通知）
                if on_chunk is not None:
                    on_chunk(chunk)

                content = delta.get("content")
                if content:
                    reply_parts.append(content)

                rc = delta.get("reasoning_content")
                if rc:
                    thinking_parts.append(rc)

                for tc in delta.get("tool_calls") or []:
                    index = tc.get("index", 0)
                    slot = tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    fn = tc.get("function") or {}
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]

        calls: list[dict] = []
        for index in sorted(tool_calls):
            slot = tool_calls[index]
            try:
                args = json.loads(slot["arguments"]) if slot["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            calls.append({"id": slot["id"], "name": slot["name"], "arguments": args})

        total = time.perf_counter() - t_start
        console.llm_stats(ttfb or total, total - (ttfb or total), total)
        return LLMResult(
            content="".join(reply_parts),
            reasoning_content="".join(thinking_parts),
            tool_calls=calls,
            raw={
                "request_body": self._build_request_body(messages, tools),
                "raw_lines": raw_lines,
                "chunks": raw_chunks,
                "stream_duration_s": round(total, 3),
                "ttfb_s": round(ttfb or total, 3),
            },
        )

    def make_messages(self, user_text: str) -> list[dict]:
        #构造对话
        return [
            {"role": "system", "content": self._config.system_prompt},
            {"role": "user", "content": user_text},
        ]
