"use strict";
/* 调试视图页：实时 LLM 流式输出（思考/回复/工具/上下文）

数据链路：rawview._ingest → HTTP POST /api/debug/ingest（回环）
→ webconsole 独立缓冲 → /api/debug/events SSE → 本页面渲染

不写入 bot stdout，日志流保持干净；没有独立的 8080 端口。
*/
import { api, toast, esc } from "../app.js";

let es = null;

export function mountDebugPage(root) {
  root.innerHTML = `
  <div class="debug-layout">
    <div class="debug-main">
      <!-- 实时流式卡片 -->
      <div class="card" id="dbg-live-card" style="display:none">
        <div class="dbg-header">
          <span><b id="dbg-time"></b> <b id="dbg-user"></b></span>
          <span id="dbg-tools-chips"></span>
          <span id="dbg-status" class="dbg-status">思考中…</span>
        </div>
        <div class="dbg-body">
          <div id="dbg-think-sec" class="dbg-sec" style="display:none">
            <div class="dbg-lbl">思考内容</div>
            <pre id="dbg-think" class="dbg-think-text"></pre>
          </div>
          <div id="dbg-reply-sec" class="dbg-sec" style="display:none">
            <div class="dbg-lbl">最终回复</div>
            <pre id="dbg-reply" class="dbg-reply-text"></pre>
          </div>
          <div id="dbg-tools-sec" class="dbg-sec" style="display:none">
            <div class="dbg-lbl">工具调用</div>
            <div id="dbg-tools"></div>
          </div>
          <details id="dbg-context-details" style="display:none">
            <summary>系统提示 · 工具定义 · 对话消息</summary>
            <div id="dbg-context" class="dbg-context-body"></div>
          </details>
        </div>
      </div>

      <!-- 等待提示 -->
      <div id="dbg-wait" class="card dbg-wait">
        <span id="dbg-wait-icon">⏳</span> <span id="dbg-wait-text">等待 LLM 请求…</span>
      </div>

      <!-- 历史记录（end 事件时从 live 卡片复制） -->
      <div id="dbg-history"></div>
    </div>
  </div>`;

  const waitEl = root.querySelector("#dbg-wait");
  const waitText = root.querySelector("#dbg-wait-text");
  const waitIcon = root.querySelector("#dbg-wait-icon");
  const liveCard = root.querySelector("#dbg-live-card");
  const historyEl = root.querySelector("#dbg-history");

  // DOM 引用
  const dom = {
    time: root.querySelector("#dbg-time"),
    user: root.querySelector("#dbg-user"),
    status: root.querySelector("#dbg-status"),
    thinkSec: root.querySelector("#dbg-think-sec"),
    think: root.querySelector("#dbg-think"),
    replySec: root.querySelector("#dbg-reply-sec"),
    reply: root.querySelector("#dbg-reply"),
    toolsSec: root.querySelector("#dbg-tools-sec"),
    tools: root.querySelector("#dbg-tools"),
    toolsChips: root.querySelector("#dbg-tools-chips"),
    contextDetails: root.querySelector("#dbg-context-details"),
    context: root.querySelector("#dbg-context"),
  };
  let curArgs = null;

  function resetLive() {
    waitEl.style.display = "none";
    liveCard.style.display = "";
    dom.time.textContent = "";
    dom.user.textContent = "";
    dom.status.textContent = "思考中…";
    dom.thinkSec.style.display = "none";
    dom.think.textContent = "";
    dom.replySec.style.display = "none";
    dom.reply.textContent = "";
    dom.toolsSec.style.display = "none";
    dom.tools.innerHTML = "";
    dom.toolsChips.innerHTML = "";
    dom.contextDetails.style.display = "none";
    dom.context.innerHTML = "";
    curArgs = null;
  }

  function addChip(name) {
    const s = document.createElement("span");
    s.className = "dbg-chip";
    s.textContent = name;
    dom.toolsChips.appendChild(s);
  }

  function addTool(name) {
    dom.toolsSec.style.display = "";
    const d = document.createElement("div");
    d.className = "dbg-tool-item";
    d.innerHTML = `<b>${esc(name)}</b><pre></pre>`;
    dom.tools.appendChild(d);
    return d.querySelector("pre");
  }

  function onBegin(d, isSync) {
    resetLive();
    dom.time.textContent = d.time || "";
    dom.user.textContent = d.user_id || "";
    if (d.context_html) {
      dom.contextDetails.style.display = "";
      dom.context.innerHTML = d.context_html;
    }
    if (!isSync) return;
    const s = d.live;
    if (!s) return;
    (s.tool_calls || []).forEach(tc => { if (tc.name) addChip(tc.name); });
    (s.thinking || []).forEach(t => {
      dom.thinkSec.style.display = "";
      dom.think.textContent += t;
    });
    (s.reply || []).forEach(r => {
      dom.replySec.style.display = "";
      dom.reply.textContent += r;
    });
    (s.tool_calls || []).forEach(tc => {
      const pre = addTool(tc.name);
      if (tc.args) pre.textContent = tc.args;
      curArgs = pre;
    });
  }

  function connectSSE() {
    if (es) { es.close(); es = null; }
    waitEl.style.display = "";
    waitIcon.textContent = "⏳";
    waitText.textContent = "等待 LLM 请求…";

    es = new EventSource("/api/debug/events");
    es.onmessage = (ev) => {
      let d;
      try { d = JSON.parse(ev.data); } catch(e) { return; }

      switch (d.type) {
        case "begin":
          onBegin(d, false);
          break;
        case "sync":
          onBegin(d, true);
          break;
        case "thinking":
          dom.thinkSec.style.display = "";
          dom.think.textContent += d.text || "";
          break;
        case "reply":
          dom.replySec.style.display = "";
          dom.reply.textContent += d.text || "";
          break;
        case "tool_name":
          curArgs = addTool(d.text);
          addChip(d.text);
          break;
        case "tool_args":
          if (curArgs) curArgs.textContent += d.text || "";
          break;
        case "end":
          dom.status.textContent = "完成";
          // 把当前 live 卡片复制到历史顶部
          historyEl.insertAdjacentHTML("afterbegin", liveCard.outerHTML);
          // 重置 live 卡片为空白等待下次
          resetLive();
          liveCard.style.display = "none";
          waitEl.style.display = "";
          waitIcon.textContent = "⏳";
          waitText.textContent = "等待 LLM 请求…";
          break;
      }
    };

    es.onerror = () => {
      // EventSource 自动重连，只更新 UI
      waitIcon.textContent = "⊘";
      waitText.textContent = "连接中断，重连中…";
    };
  }

  connectSSE();

  // 检查机器人是否在运行、是否有活跃会话
  api("/api/debug/snapshot").then(d => {
    if (!d.bot_running) {
      waitIcon.textContent = "⊝";
      waitText.textContent = "机器人未运行（启动机器人后自动连接）";
    } else if (d.has_live) {
      waitText.textContent = "有进行中的 LLM 请求，正在同步…";
    }
  }).catch(() => {});
}

export function unmountDebugPage() {
  if (es) { es.close(); es = null; }
}
