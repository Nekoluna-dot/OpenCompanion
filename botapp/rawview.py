import html
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from botapp.config import AppConfig
from botapp.console import console

# 上下文总结记录标记（与 robot._COMPACT_MARK 对应）：
# 历史中以此为前缀的 system 消息是压缩时生成的总结数据，
# 在对话消息区用 Summary 样式标记展示。
_SUMMARY_MARK = "[对话总结]"

_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Bot 调试视图</title>
<style>
  body { font-family: "Consolas", "Microsoft YaHei", monospace; background:#0d1117; color:#c9d1d9; margin:0; padding:16px; }
  h1 { font-size:18px; color:#58a6ff; }
  .card { border:1px solid #30363d; border-radius:8px; margin:12px 0; overflow:hidden; }
  .card-head { padding:8px 12px; background:#161b22; font-size:13px; color:#8b949e; display:flex; justify-content:space-between; }
  .card-head b { color:#e6edf3; }
  .card-body { padding:10px 12px; font-size:13px; }
  .sec { margin:10px 0; }
  .lbl { display:inline-block; color:#79c0ff; font-weight:bold; margin-bottom:4px; }
  pre { margin:4px 0; background:#161b22; border:1px solid #30363d; border-radius:6px;
        padding:8px; overflow-x:auto; white-space:pre-wrap; word-break:break-word; font-size:12px; }
  .msg { border:1px solid #30363d; border-radius:6px; margin:6px 0; }
  .msg-head { padding:4px 10px; font-size:11px; border-bottom:1px solid #30363d; }
  .msg-body { padding:6px 10px; }
  .role-user .msg-head { color:#58a6ff; background:rgba(88,166,255,.08); }
  .role-assistant .msg-head { color:#3fb950; background:rgba(63,185,80,.08); }
  .role-tool .msg-head { color:#d29922; background:rgba(210,153,34,.08); }
  .role-system .msg-head { color:#8b949e; }
  .role-summary .msg-head { color:#f778ba; background:rgba(247,120,186,.12); }
  .sum-tag { display:inline-block; background:#f778ba; color:#0d1117; border-radius:4px;
             padding:0 6px; font-size:11px; font-weight:bold; margin-left:8px; }
  details { background:#161b22; border:1px solid #30363d; border-radius:6px; padding:6px 10px; }
  summary { cursor:pointer; color:#8b949e; font-size:12px; }
  .think { color:#c678dd; white-space:pre-wrap; }
  .tool { border:1px solid #d29922; border-radius:6px; margin:6px 0; padding:8px 10px; }
  .tool b { color:#d29922; }
  .empty { color:#8b949e; font-style:italic; }
  .muted { color:#8b949e; font-size:11px; }
  .tool-list { display:flex; flex-wrap:wrap; gap:6px; }
  .tool-chip { background:#1f2430; border:1px solid #30363d; color:#79c0ff; border-radius:4px; padding:2px 8px; font-size:11px; }
  .tool-type { color:#8b949e; font-size:11px; margin-left:8px; }
  .tool-desc { color:#c9d1d9; margin:6px 0; white-space:pre-wrap; font-size:12px; }
  #live-card { border:1px solid #388bfd; box-shadow:0 0 0 1px #388bfd inset; }
  #live-status { color:#d29922; }
</style>
</head>
<body>
<h1>Bot 调试视图 <span class="muted">（实时流式）</span></h1>
<div id="wait" class="empty">等待 LLM 请求…（等用户发消息即可实时看到流式数据）</div>
<div id="live-card" class="card" style="display:none">
  <div class="card-head">
    <span>[<b id="live-time"></b>] <b id="live-user"></b></span>
    <span>
      <span id="live-tools-chips"></span>
      <span id="live-status" class="muted">思考中…</span>
    </span>
  </div>
  <div class="card-body">
    <div id="live-think-sec" class="sec" style="display:none">
      <span class="lbl">思考内容</span><pre id="live-think" class="think"></pre>
    </div>
    <div id="live-reply-sec" class="sec" style="display:none">
      <span class="lbl">最终回复</span><pre id="live-reply"></pre>
    </div>
    <div id="live-tools-sec" class="sec" style="display:none">
      <span class="lbl">工具调用</span><div id="live-tools"></div>
    </div>
    <div id="live-context-sec" class="sec" style="display:none">
      <details>
        <summary id="live-context-summary">系统提示 · 工具定义 · 对话消息（本轮上下文）</summary>
        <div id="live-context"></div>
      </details>
    </div>
  </div>
</div>
<div id="last-card">{cards}</div>
<script>
const es = new EventSource('/events');
const $ = id => document.getElementById(id);
const wait = $('wait');
const live = {
  card: $('live-card'), time: $('live-time'), user: $('live-user'), status: $('live-status'),
  contextSec: $('live-context-sec'), context: $('live-context'),
  thinkSec: $('live-think-sec'), think: $('live-think'),
  replySec: $('live-reply-sec'), reply: $('live-reply'),
  toolsSec: $('live-tools-sec'), tools: $('live-tools'),
  toolsChips: $('live-tools-chips'),
  curArgs: null
};
function addChipEl(name) {
  const s = document.createElement('span');
  s.className = 'tool-chip';
  s.textContent = name;
  live.toolsChips.appendChild(s);
}
function renderChips(calls) {
  live.toolsChips.innerHTML = '';
  const seen = new Set();
  for (const tc of (calls || [])) {
    if (tc.name && !seen.has(tc.name)) { seen.add(tc.name); addChipEl(tc.name); }
  }
}
function resetLive() {
  wait.style.display = 'none';
  const lastCard = $('last-card');
  if (lastCard) lastCard.style.display = 'none';
  live.card.style.display = '';
  live.time.textContent = '';
  live.user.textContent = '';
  live.status.textContent = '思考中…';
  live.contextSec.style.display = 'none';
  live.context.innerHTML = '';
  live.think.textContent = '';
  live.reply.textContent = '';
  live.tools.innerHTML = '';
  live.thinkSec.style.display = 'none';
  live.replySec.style.display = 'none';
  live.toolsSec.style.display = 'none';
  live.toolsChips.innerHTML = '';
  live.curArgs = null;
}
function addTool(name) {
  live.toolsSec.style.display = '';
  const d = document.createElement('div');
  d.className = 'tool';
  const b = document.createElement('b');
  b.textContent = name;
  const pre = document.createElement('pre');
  d.appendChild(b); d.appendChild(pre);
  live.tools.appendChild(d);
  return pre;
}
function onBegin(d, sync) {
  resetLive();
  live.time.textContent = d.time;
  live.user.textContent = d.user_id;
  if (d.context_html) {
    live.contextSec.style.display = '';
    live.context.innerHTML = d.context_html;
  }
  if (!sync) return;
  const s = d.live;
  renderChips(s.tool_calls || []);
  for (const t of (s.thinking || [])) { live.thinkSec.style.display=''; live.think.textContent += t; }
  for (const r of (s.reply || [])) { live.replySec.style.display=''; live.reply.textContent += r; }
  for (const tc of (s.tool_calls || [])) {
    const pre = addTool(tc.name);
    if (tc.args) pre.textContent = tc.args;
    live.curArgs = pre;
  }
}
es.onmessage = function(ev) {
  let d; try { d = JSON.parse(ev.data); } catch(e) { return; }
  switch (d.type) {
    case 'begin': onBegin(d, false); break;
    case 'sync': onBegin(d, true); break;
    case 'thinking': live.thinkSec.style.display=''; live.think.textContent += d.text; break;
    case 'reply': live.replySec.style.display=''; live.reply.textContent += d.text; break;
    case 'tool_name': live.curArgs = addTool(d.text); addChipEl(d.text); break;
    case 'tool_args': if (live.curArgs) live.curArgs.textContent += d.text; break;
    case 'end': live.status.textContent = '完成'; break;
  }
};
es.onerror = function(){ /* 断线自动重连 */ };
</script>
</body>
</html>
"""


class RawViewServer:
    """捕获并展示每次 LLM 请求的原始数据（支持 SSE 实时流式展示）。"""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._records: deque[dict[str, Any]] = deque(maxlen=config.web_max_records)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # 当前进行中的流式会话（LLM 生成期间实时更新）
        self._live: dict[str, Any] | None = None
        # SSE 订阅者队列
        self._subscribers: list["queue.Queue"] = []

    # ------------------------------------------------------------------
    # 流式记录：begin_stream → on_chunk → finish_stream
    # ------------------------------------------------------------------
    def begin_stream(self, user_id: str, messages: list[dict], tool_defs: list[dict] | None = None) -> None:
        """开始一次流式记录：创建 live 会话并通知订阅者。"""
        with self._lock:
            self._live = {
                "time": time.strftime("%H:%M:%S"),
                "user_id": user_id,
                "messages": messages,
                "tool_defs": tool_defs or [],
                "raw_chunks": [],
                "thinking": [],
                "reply": [],
                "tool_calls": [],
            }
            context_html = self._render_context(messages, self._live["tool_defs"])
            self._emit_locked(
                {
                    "type": "begin",
                    "user_id": user_id,
                    "time": self._live["time"],
                    "context_html": context_html,
                }
            )

    def on_chunk(self, chunk: dict) -> None:
        """流式过程中每收到一个 chunk 时调用，实时更新 live 会话。"""
        with self._lock:
            live = self._live
            if live is None:
                return
            live["raw_chunks"].append(chunk)
            try:
                delta = chunk["choices"][0]["delta"]
            except (KeyError, IndexError, TypeError):
                return
            rc = delta.get("reasoning_content")
            if rc:
                live["thinking"].append(rc)
                self._emit_locked({"type": "thinking", "text": rc})
                return
            c = delta.get("content")
            if c:
                live["reply"].append(c)
                self._emit_locked({"type": "reply", "text": c})
                return
            tcs = delta.get("tool_calls")
            if tcs:
                for tc in tcs:
                    if tc.get("function", {}).get("name"):
                        live["tool_calls"].append({"name": tc["function"]["name"], "args": ""})
                        self._emit_locked({"type": "tool_name", "text": tc["function"]["name"]})
                    elif tc.get("function", {}).get("arguments"):
                        if live["tool_calls"]:
                            arg = tc["function"]["arguments"]
                            live["tool_calls"][-1]["args"] += arg
                            self._emit_locked({"type": "tool_args", "text": arg})

    def finish_stream(self, raw: dict) -> None:
        """结束流式记录：把 live 会话（含完整 raw）写入历史。"""
        with self._lock:
            live = self._live
            self._live = None
        if live is not None:
            live["raw"] = raw
            live.pop("raw_chunks", None)
            self.record_from_live(live)
            self._emit_locked({"type": "end", "count": len(self._records)})

    def record_from_live(self, live: dict) -> None:
        """把已完成的 live 会话转存为历史记录。"""
        with self._lock:
            self._records.append(live)

    # ------------------------------------------------------------------
    def record(
        self,
        user_id: str,
        messages: list[dict],
        raw: dict[str, Any],
    ) -> None:
        """记录一次已完成的请求（非流式场景）。"""
        with self._lock:
            self._records.append(
                {
                    "time": time.strftime("%H:%M:%S"),
                    "user_id": user_id,
                    "messages": messages,
                    "raw": raw,
                    "thinking": [],
                    "reply": [],
                    "tool_calls": [],
                }
            )

    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动 HTTP 服务器（后台线程）。"""
        if self._server is not None:
            return
        host, port = self._config.web_host, self._config.web_port
        handler = self._make_handler()
        try:
            self._server = ThreadingHTTPServer((host, port), handler)
        except OSError as e:
            console.error(f"调试视图启动失败 {host}:{port}: {e}")
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="raw-view"
        )
        self._thread.start()
        console.mcp(f"调试视图: http://{host}:{port}")

    # ------------------------------------------------------------------
    # SSE 推送
    # ------------------------------------------------------------------
    def _emit_locked(self, event: dict) -> None:
        """向所有 SSE 订阅者推送增量事件（调用方需持有锁）。"""
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    def _sse_events(self) -> "queue.Queue":
        """注册一个 SSE 订阅者，返回接收队列。"""
        import queue

        q: "queue.Queue" = queue.Queue(maxsize=1024)
        with self._lock:
            # 订阅时若已有进行中的会话，先同步全量状态
            if self._live is not None:
                context_html = self._render_context(
                    self._live["messages"], self._live.get("tool_defs") or []
                )
                payload = json.dumps(
                    {
                        "type": "sync",
                        "user_id": self._live["user_id"],
                        "time": self._live["time"],
                        "live": self._live,
                        "context_html": context_html,
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                q.put_nowait(payload)
            self._subscribers.append(q)
        return q

    # ------------------------------------------------------------------
    def _make_handler(self):
        def _run(self_: BaseHTTPRequestHandler, *_) -> None:
            if self_.path.startswith("/events"):
                self_.send_response(200)
                self_.send_header("Content-Type", "text/event-stream")
                self_.send_header("Cache-Control", "no-cache")
                self_.send_header("Connection", "keep-alive")
                self_.end_headers()
                q = server._sse_events()
                try:
                    while True:
                        try:
                            payload = q.get(timeout=20)
                            self_.wfile.write(b"data: " + payload + b"\n\n")
                            self_.wfile.flush()
                        except Exception:
                            pass
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    with server._lock:
                        if q in server._subscribers:
                            server._subscribers.remove(q)
                return
            if self_.path == "/" or self_.path.startswith("/?"):
                self_.send_response(200)
                self_.send_header("Content-Type", "text/html; charset=utf-8")
                self_.end_headers()
                self_.wfile.write(server.snapshot_html().encode("utf-8"))
            else:
                self_.send_response(404)
                self_.end_headers()
        server = self
        return type(
            "RawHandler",
            (BaseHTTPRequestHandler,),
            {
                "do_GET": _run,
                "log_message": lambda self_, *_: None,
            },
        )

    # ------------------------------------------------------------------
    def snapshot_html(self) -> str:
        """渲染页面 HTML。

        - 进行中（_live 非空）：live 卡片由 SSE 增量驱动，页面只给骨架。
        - 空闲时：渲染最近一条已完成记录（含思考/回复/工具/上下文），
          让生成完成后仍能看到内容，不再退回空白等待页。
        """
        with self._lock:
            if self._live is not None:
                return _PAGE
            last = self._records[-1] if self._records else None
        if last is None:
            return _PAGE
        card = self._render_record(last)
        return _PAGE.replace("{n}", str(len(self._records))).replace(
            "{cards}", card
        )

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _render_record(self, rec: dict) -> str:
        """把一条已完成记录渲染成静态卡片（思考/回复/工具/上下文）。"""
        messages = rec.get("messages") or []
        tool_defs = rec.get("tool_defs") or []
        thinking = "".join(rec.get("thinking") or []).strip()
        reply_text = "".join(rec.get("reply") or []).strip()
        tool_used = rec.get("tool_calls") or []

        parts: list[str] = [
            '<div class="card">'
            f'<div class="card-head"><span>'
            f'[{html.escape(rec.get("time", ""))}] <b>{html.escape(rec.get("user_id", ""))}</b></span>'
            f'<span>{self._render_tool_chips(rec.get("tool_calls") or [])}'
            '<span class="muted">完成</span></span></div>'
            '<div class="card-body">'
        ]

        if thinking:
            parts.append(
                '<div class="sec"><span class="lbl">思考内容</span>'
                f'<pre class="think">{html.escape(thinking)}</pre></div>'
            )
        if reply_text:
            parts.append(
                '<div class="sec"><span class="lbl">最终回复</span>'
                f'<pre>{html.escape(reply_text)}</pre></div>'
            )
        for tc in tool_used:
            args = html.escape(tc.get("args", tc.get("arguments", "{}")))
            name = tc.get("name", "?")
            # 归档类工具（任何 namespace 的 *-add_record）显示 Summary 徽标，
            # 不再精确匹配单个工具名（支持换用其他档案插件）
            tag = (
                '<span class="sum-tag">Summary</span>'
                if name.endswith("-add_record")
                else ""
            )
            parts.append(
                f'<div class="tool">[Tool] <b>{html.escape(name)}</b>{tag} '
                f'调用参数：<pre>{args}</pre></div>'
            )

        parts.append(self._render_context(messages, tool_defs))
        parts.append("</div></div>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    @staticmethod
    def _render_tool_chips(tool_calls: list[dict]) -> str:
        """本次请求实际调用的工具名徽标（去重）。"""
        names: list[str] = []
        for tc in tool_calls:
            name = tc.get("name")
            if name and name not in names:
                names.append(name)
        if not names:
            return ""
        return "".join(
            f'<span class="tool-chip">{html.escape(n)}</span> ' for n in names
        )

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _render_context(self, messages: list[dict], tool_defs: list[dict]) -> str:
        """渲染系统提示 + 工具定义 + 对话消息，供历史卡片与 live 事件共用。"""
        parts: list[str] = []

        # 系统提示（仅提示词正文）
        system_text = self._extract_system_text(messages)
        parts.append('<div class="sec"><span class="lbl">系统提示</span>')
        if system_text:
            parts.append(f"<pre>{html.escape(system_text)}</pre>")
        else:
            parts.append('<div class="muted">（无系统提示词）</div>')
        parts.append("</div>")

        # 工具定义（来自请求 body 的 tools 参数 = MCP tools/list 结果）
        parts.append('<div class="sec"><span class="lbl">工具定义（tools 参数 · MCP tools/list）</span>')
        if tool_defs:
            parts.append(self._render_tools(tool_defs))
        else:
            parts.append('<div class="muted">（未启用工具）</div>')
        parts.append("</div>")

        # 对话消息（总结数据用 Summary 标记展示）
        parts.append('<div class="sec"><span class="lbl">对话消息（本轮上下文）</span>')
        for m in messages:
            if m.get("role") == "system":
                # 普通系统提示在「系统提示」区展示；带总结标记的单独用 Summary 展示
                content = m.get("content")
                if isinstance(content, str) and content.startswith(_SUMMARY_MARK):
                    parts.append(self._render_message(m, is_summary=True))
                continue
            parts.append(self._render_message(m))
        parts.append("</div>")

        return "\n".join(parts)

    def _render_tools(self, tool_defs: list[dict]) -> str:
        """把 tools 参数里的每个工具渲染成详细卡片（名称/描述/参数 JSON Schema）。"""
        cards: list[str] = []
        for td in tool_defs:
            fn = (td.get("function") or {}) if isinstance(td, dict) else {}
            name = fn.get("name") or "?"
            desc = fn.get("description") or ""
            params = fn.get("parameters") or {}
            head = html.escape(name)
            body: list[str] = []
            if desc:
                body.append(
                    f'<div class="tool-desc">{html.escape(desc)}</div>'
                )
            body.append(
                '<details><summary>参数 JSON Schema</summary>'
                '<pre>' + html.escape(json.dumps(params, ensure_ascii=False, indent=2)) + "</pre>"
                "</details>"
            )
            cards.append(
                f'<div class="tool"><b>{head}</b>'
                f'<span class="tool-type">{html.escape(str(fn.get("type", "function")))}</span>'
                + "".join(body)
                + "</div>"
            )
        return "\n".join(cards)

    def _render_message(self, m: dict, is_summary: bool = False) -> str:
        role = m.get("role", "?")
        content = m.get("content")
        head = role
        if is_summary:
            head = "summary"
        elif role == "assistant" and m.get("tool_calls"):
            head += f' · 工具调用 {len(m["tool_calls"])} 个'
        elif role == "tool":
            head = f'tool → {m.get("tool_call_id", "")[:16]}'
        tag = '<span class="sum-tag">Summary</span>' if is_summary else ""
        body = html.escape(str(content)) if content else '<span class="muted">(空)</span>'
        return (
            f'<div class="msg role-{"summary" if is_summary else html.escape(role)}">'
            f'<div class="msg-head">{html.escape(head)}{tag}</div>'
            f'<div class="msg-body">{body}</div></div>'
        )

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_system_text(messages: list[dict]) -> str:
        for m in messages:
            if m.get("role") == "system" and m.get("content"):
                return str(m["content"])
        return ""
