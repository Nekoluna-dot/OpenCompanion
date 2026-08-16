import json
import time
import urllib.error
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
    # 请求端点: 完全由 config.ini 的 base_url 决定, 不做任何自动改写。
    #   chat      模式: base_url 填 https://api.deepseek.com/chat/completions
    #   responses 模式: base_url 填 https://api.deepseek.com/responses
    # ------------------------------------------------------------------
    def _endpoint(self) -> str:
        return self._config.base_url

    # ------------------------------------------------------------------
    # 配置一致性校验: api_type 与 base_url 必须匹配, 否则请求会打到
    # 错误端点返回 400 (如 responses 格式 body 发到 /chat/completions)。
    # 给出明确中文提示, 而不是裸的 HTTP 400。
    # ------------------------------------------------------------------
    def _check_endpoint_match(self) -> None:
        base = (self._config.base_url or "").rstrip("/")
        at = self._config.api_type
        if at == "responses" and base.endswith("/chat/completions"):
            raise ValueError(
                "api_type=responses 但 base_url 仍是 /chat/completions。"
                "请在 config.ini 把 base_url 改为 https://api.deepseek.com/responses"
            )
        if at == "chat" and base.endswith("/responses"):
            raise ValueError(
                "api_type=chat 但 base_url 是 /responses。"
                "请在 config.ini 把 base_url 改为 https://api.deepseek.com/chat/completions"
            )

    # ------------------------------------------------------------------
    # Chat Completions 请求体
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

    # ------------------------------------------------------------------
    # 入口: 按 api_type 分流
    # ------------------------------------------------------------------
    def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_chunk=None,
    ) -> LLMResult:
        self._check_endpoint_match()
        if self._config.api_type == "responses":
            return self._stream_responses(messages, tools, on_chunk)
        return self._stream_chat_completions(messages, tools, on_chunk)

    # ------------------------------------------------------------------
    # Chat Completions 流式
    # ------------------------------------------------------------------
    def _stream_chat_completions(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_chunk=None,
    ) -> LLMResult:

        body = json.dumps(self._build_request_body(messages, tools)).encode()
        req = urllib.request.Request(
            self._endpoint(),
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
        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            raise RuntimeError(
                f"LLM API HTTP {e.code}: {err_body or e.reason}"
            ) from e
        with resp:
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

        # 输出思考内容到日志（供 webconsole 调试视图查看）
        if thinking_parts:
            thinking_text = "".join(thinking_parts)
            console.thinking(f"({len(thinking_text)}字) {thinking_text[:500]}{'...' if len(thinking_text) > 500 else ''}")

        # 提取流式响应中的 usage（OpenAI 兼容：通常在最后一个 chunk 的 usage 字段）
        usage: dict | None = None
        for chunk in raw_chunks:
            u = chunk.get("usage")
            if isinstance(u, dict):
                usage = u
                break
        if usage:
            _log_usage(usage)

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
                "usage": usage,
            },
        )

    # ------------------------------------------------------------------
    # Responses API 流式
    # ------------------------------------------------------------------
    @staticmethod
    def _to_responses_input(messages: list[dict]) -> tuple[str, list[dict]]:
        """OpenAI messages → (instructions, responses input items)。

        注意：Responses API 无法使用 system 身份 —— 所有原本用 system
        发送的消息（系统提示、主动问候/提醒指令、压缩总结等）一律改为
        user 身份写入 input，否则生成类请求会因 input items 为空而报错
        （如 HTTP 400 "Input items array must not be empty"）。
        assistant 的 reasoning_content 不回传(Responses API 无状态,
        思考由服务端管理)。
        """
        items: list[dict] = []

        for m in messages:
            role = m.get("role")
            content = m.get("content")
            if role in ("system", "developer"):
                # 以 user 身份发送，保证 input 永不为空
                if isinstance(content, str):
                    items.append(
                        {"type": "message",
                         "role": "user",
                         "content": [{"type": "input_text", "text": content}]}
                    )
                elif isinstance(content, list):
                    text_parts: list[str] = []
                    for p in content:
                        if p.get("type") == "text":
                            text_parts.append(str(p.get("text", "")))
                    if text_parts:
                        items.append(
                            {"type": "message",
                             "role": "user",
                             "content": [{"type": "input_text", "text": " ".join(text_parts)}]}
                        )
            elif role == "user":
                if isinstance(content, str):
                    items.append(
                        {"type": "message",
                         "role": "user",
                         "content": [{"type": "input_text", "text": content}]}
                    )
                elif isinstance(content, list):
                    parts: list[dict] = []
                    for p in content:
                        t = p.get("type")
                        if t == "text":
                            parts.append(
                                {"type": "input_text", "text": p.get("text", "")})
                        elif t == "image_url":
                            parts.append(
                                {"type": "input_image",
                                 "image_url": p.get("image_url", {}).get("url", "")})
                        elif t == "video_url":
                            parts.append(
                                {"type": "input_video",
                                 "video_url": p.get("video_url", {}).get("url", "")})
                    if parts:
                        items.append({"role": "user", "content": parts})
            elif role == "assistant":
                # deepseek Responses 兼容实现要求思考模式回传 reasoning item
                if m.get("reasoning_content"):
                    items.append({
                        "type": "reasoning",
                        "content": [{"type": "reasoning_text", "text": m["reasoning_content"]}],
                    })
                tool_calls = m.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        fn = tc.get("function") or {}
                        cid = tc.get("id") or f"call_{len(items)}"
                        items.append({
                            "type": "function_call",
                            "id": cid,
                            "call_id": cid,
                            "name": fn.get("name", ""),
                            "arguments": fn.get("arguments") or "{}",
                        })
                else:
                    items.append(
                        {"type": "message",
                         "role": "assistant",
                         "content": [{"type": "output_text", "text": content or ""}]}
                    )
            elif role == "tool":
                items.append(
                    {"type": "function_call_output",
                     "call_id": m.get("tool_call_id", ""),
                     "output": content or ""}
                )
        return "", items

    @staticmethod
    def _to_responses_tools(tool_defs: list[dict]) -> list[dict]:
        """OpenAI chat 格式工具定义 → Responses API function tool。"""
        out: list[dict] = []
        for t in tool_defs:
            fn = t.get("function") or {}
            name = fn.get("name") or t.get("name", "")
            if not name:
                continue
            out.append({
                "type": "function",
                "name": name,
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            })
        return out

    def _build_responses_body(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> dict:
        instructions, items = self._to_responses_input(messages)
        body: dict = {
            "model": self._config.model,
            "stream": True,
        }
        if instructions:
            body["instructions"] = instructions
        body["input"] = items

        rtools: list[dict] = []
        if tools:
            rtools.extend(self._to_responses_tools(tools))
        # 联网搜索(仅 responses 模式; DeepSeek 按次计费)
        if self._config.search_enabled:
            rtools.append({"type": "web_search"})
        if rtools:
            body["tools"] = rtools

        # 思考开关: Responses API 用 reasoning.effort
        if self._config.thinking:
            body["reasoning"] = {"effort": self._config.reasoning_effort}
        else:
            body["reasoning"] = {"effort": "none"}
        return body

    def _stream_responses(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_chunk=None,
    ) -> LLMResult:
        body = json.dumps(self._build_responses_body(messages, tools)).encode()
        req = urllib.request.Request(
            self._endpoint(),
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._config.api_key}",
            },
            method="POST",
        )

        reply_parts: list[str] = []
        thinking_parts: list[str] = []
        # 工具调用按 item_id 累积
        tool_calls: dict[str, dict] = {}
        web_search_queries: list[str] = []
        raw_chunks: list[dict] = []
        raw_lines: list[str] = []
        finish_reason: str | None = None
        error_msg: str = ""
        usage: dict | None = None
        t_start = time.perf_counter()
        ttfb: float | None = None

        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            raise RuntimeError(
                f"LLM API HTTP {e.code}: {err_body or e.reason}"
            ) from e
        with resp:
            cur_event = ""
            for raw in resp:
                if ttfb is None:
                    ttfb = time.perf_counter() - t_start
                line = raw.decode().strip()
                raw_lines.append(line)
                if line.startswith("event:"):
                    cur_event = line[len("event:"):].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if not data_str:
                    continue
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                raw_chunks.append(data)

                if on_chunk is not None:
                    # 把 SSE event 名注入 data，让下游（rawview）能按类型分发
                    if isinstance(data, dict) and not data.get("type"):
                        data["type"] = cur_event
                    on_chunk(data)

                if cur_event == "response.output_text.delta":
                    d = data.get("delta")
                    if d:
                        reply_parts.append(d)
                elif cur_event == "response.reasoning_text.delta":
                    d = data.get("delta")
                    if d:
                        thinking_parts.append(d)
                elif cur_event == "response.output_item.added":
                    it = data.get("item") or {}
                    if it.get("type") == "function_call":
                        iid = it.get("id") or it.get("call_id") or str(len(tool_calls))
                        tool_calls.setdefault(iid, {
                            "id": iid, "name": it.get("name", ""), "arguments": "",
                        })
                elif cur_event == "response.function_call_arguments.delta":
                    iid = data.get("item_id") or data.get("call_id")
                    if iid and iid in tool_calls:
                        d = data.get("delta")
                        if d:
                            tool_calls[iid]["arguments"] += d
                elif cur_event == "response.output_item.done":
                    it = data.get("item") or {}
                    if it.get("type") == "function_call":
                        iid = it.get("id") or it.get("call_id")
                        slot = tool_calls.setdefault(iid, {
                            "id": iid, "name": it.get("name", ""), "arguments": "",
                        })
                        if not slot["arguments"]:
                            slot["arguments"] = it.get("arguments") or ""
                elif cur_event == "response.web_search_call.searching":
                    for q in (data.get("queries") or []):
                        qq = q.get("query") if isinstance(q, dict) else q
                        if qq and qq not in web_search_queries:
                            web_search_queries.append(qq)
                    if web_search_queries:
                        console.mcp("联网搜索: " + " / ".join(web_search_queries))
                elif cur_event == "response.completed":
                    finish_reason = data.get("status") or "completed"
                    resp_obj = data.get("response") or {}
                    u = resp_obj.get("usage")
                    if isinstance(u, dict):
                        usage = u
                    break
                elif cur_event == "response.incomplete":
                    finish_reason = "incomplete"
                    error_msg = str(data)[:300]
                    break
                elif cur_event == "response.failed":
                    finish_reason = "failed"
                    error_msg = str(data.get("error") or data)[:500]
                    break

        calls: list[dict] = []
        for iid in tool_calls:
            slot = tool_calls[iid]
            try:
                args = json.loads(slot["arguments"]) if slot["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            calls.append({"id": slot["id"], "name": slot["name"], "arguments": args})

        if error_msg:
            console.warn(f"Responses API 异常: {finish_reason} {error_msg}")

        total = time.perf_counter() - t_start
        console.llm_stats(ttfb or total, total - (ttfb or total), total)

        # 输出思考内容到日志（供 webconsole 调试视图查看）
        if thinking_parts:
            thinking_text = "".join(thinking_parts)
            console.thinking(f"({len(thinking_text)}字) {thinking_text[:500]}{'...' if len(thinking_text) > 500 else ''}")

        if usage:
            _log_usage(usage)
        return LLMResult(
            content="".join(reply_parts),
            reasoning_content="".join(thinking_parts),
            tool_calls=calls,
            raw={
                "request_body": self._build_responses_body(messages, tools),
                "raw_lines": raw_lines,
                "chunks": raw_chunks,
                "stream_duration_s": round(total, 3),
                "ttfb_s": round(ttfb or total, 3),
                "finish_reason": finish_reason,
                "error": error_msg,
                "web_search_queries": web_search_queries,
                "usage": usage,
            },
        )

    def make_messages(self, user_text: str) -> list[dict]:
        #构造对话（Responses API 不支持 system 身份，用 user 顶替）
        return [
            {"role": "user", "content": self._config.system_prompt},
            {"role": "user", "content": user_text},
        ]


def _log_usage(usage: dict) -> None:
    """提取并打印 token 用量（兼容 Chat Completions 与 Responses 两种字段名）。"""
    try:
        # Responses API: input_tokens/output_tokens；Chat Completions: prompt_tokens/completion_tokens
        p = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        c = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        hit = int(
            usage.get("prompt_cache_hit_tokens")
            or (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
            or (usage.get("input_tokens_details") or {}).get("cached_tokens")
            or 0
        )
    except (TypeError, ValueError):
        p = c = hit = 0
    if p or c:
        console.token(p, c, hit)
