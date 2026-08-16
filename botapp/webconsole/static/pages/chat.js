"use strict";
/* 聊天测试页：实时流式调试视图（完整事件展示） */
import { api, toast, subscribeLogs, app, esc } from "../app.js";

const TAG_RE = /^\[(\d{2}:\d{2}:\d{2})\] \[([^\]]+)\] (.*)$/;
const USERS_KEY = "wc_chat_users";
let activeUnsub = null;

// 事件分类与样式
const EVENT_STYLE = {
  Receive:  { cls: "ev-user", icon: "→", label: "用户" },
  Reply:    { cls: "ev-bot",  icon: "←", label: "AI" },
  Controller:{ cls: "ev-ctrl", icon: "⚙", label: "控制" },
  Agent:    { cls: "ev-agent", icon: "◆", label: "LLM" },
  Tool:     { cls: "ev-tool", icon: "⬡", label: "工具" },
  MCP:      { cls: "ev-mcp", icon: "⊕", label: "MCP" },
  LLM:      { cls: "ev-llm", icon: "⏱", label: "耗时" },
  Token:    { cls: "ev-token", icon: "◈", label: "Token" },
  Output:   { cls: "ev-output", icon: "✓", label: "输出" },
  Warning:  { cls: "ev-warn", icon: "!", label: "警告" },
  Error:    { cls: "ev-err", icon: "✗", label: "错误" },
  Info:     { cls: "ev-info", icon: "·", label: "信息" },
};

export function mountChatPage(root) {
  const savedUsers = JSON.parse(localStorage.getItem(USERS_KEY) || "[]");
  root.innerHTML = `
  <div class="card" style="padding:12px 16px">
    <div class="row" style="margin:0">
      <label style="font-size:12.5px;color:var(--muted)">用户 ID</label>
      <input type="text" id="ch-user" list="ch-users" style="width:260px" placeholder="wxid_xxxx@im.wechat">
      <datalist id="ch-users"></datalist>
      <label style="display:flex;align-items:center;gap:5px;font-size:12px">
        <input type="checkbox" id="ch-only-me" checked> 仅此用户
      </label>
      <label style="display:flex;align-items:center;gap:5px;font-size:12px">
        <input type="checkbox" id="ch-show-all" checked> 显示全部事件
      </label>
    </div>
  </div>
  <div class="chat-shell">
    <div id="ch-stream" class="chat-stream"></div>
    <div class="chat-input">
      <input type="text" id="ch-text" placeholder="发送消息给机器人（回车）" autocomplete="off">
      <button id="ch-send" class="btn">发送</button>
    </div>
  </div>
  <div class="card" style="margin-top:14px;padding:12px 16px">
    <div class="card-title" style="margin-bottom:8px">历史记录</div>
    <div class="row" style="margin:0">
      <input type="text" id="ch-hist-user" list="ch-hist-users" style="width:260px" placeholder="选择用户 ID">
      <datalist id="ch-hist-users"></datalist>
      <button id="ch-hist-load" class="btn ghost sm">加载</button>
    </div>
    <div id="ch-hist-list" style="max-height:300px;overflow:auto;margin-top:8px">
      <div class="empty">选择用户后加载</div>
    </div>
  </div>`;

  const userInput = root.querySelector("#ch-user");
  const dl = root.querySelector("#ch-users");
  const histUser = root.querySelector("#ch-hist-user");
  const histDl = root.querySelector("#ch-hist-users");
  const histList = root.querySelector("#ch-hist-list");

  // 用户列表
  const allUsers = [...savedUsers];
  api("/api/users").then(d => {
    (d.users || []).forEach(u => { if (!allUsers.includes(u)) allUsers.push(u); });
    refreshOptions();
  }).catch(() => {});
  function refreshOptions() {
    [dl, histDl].forEach(d => {
      d.innerHTML = "";
      allUsers.forEach(u => { const o = document.createElement("option"); o.value = u; d.appendChild(o); });
    });
  }
  refreshOptions();
  if (savedUsers.length) userInput.value = savedUsers[savedUsers.length - 1];

  // 历史记录
  root.querySelector("#ch-hist-load").onclick = async () => {
    const uid = histUser.value.trim();
    if (!uid) return;
    histList.innerHTML = `<div class="empty">加载中…</div>`;
    try {
      const d = await api("/api/history?user=" + encodeURIComponent(uid));
      const msgs = (d.messages || []).filter(m => m.role !== "system");
      if (!msgs.length) { histList.innerHTML = `<div class="empty">无记录</div>`; return; }
      histList.innerHTML = "";
      msgs.forEach(m => {
        const div = document.createElement("div");
        const role = m.role === "assistant" ? "bot" : "me";
        let text = String(m.content || "");
        text = text.replace(/<SEP>/g, "\n\n").replace(/\s+systime:\d{4}-\d{2}-\d{2} \d{2}:\d{2}/g, "");
        div.className = "msg " + role;
        div.innerHTML = `<span class="mt">${esc(role === "bot" ? "AI" : "用户")}</span>${esc(text)}`;
        histList.appendChild(div);
      });
      histList.scrollTop = histList.scrollHeight;
    } catch (e) { histList.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  };
  histUser.addEventListener("keydown", e => { if (e.key === "Enter") root.querySelector("#ch-hist-load").click(); });

  const stream = root.querySelector("#ch-stream");
  const textInput = root.querySelector("#ch-text");
  const sendBtn = root.querySelector("#ch-send");
  const onlyMe = root.querySelector("#ch-only-me");
  const showAll = root.querySelector("#ch-show-all");

  function parseLine(line) {
    const m = TAG_RE.exec(line);
    if (!m) return null;
    return { ts: m[1], tag: m[2], text: m[3] };
  }

  function renderHistory() {
    stream.innerHTML = "";
    app.logs.forEach(line => {
      const p = parseLine(line);
      if (!p) return;
      if (onlyMe.checked && !isMatchUser(p)) return;
      appendEvent(p, false);
    });
    stream.scrollTop = stream.scrollHeight;
  }

  function isMatchUser(p) {
    if (!userInput.value.trim()) return true;
    const uid = userInput.value.trim();
    // Receive/Reply/Controller 带 user:id 前缀
    if (["Receive","Reply","Controller"].includes(p.tag)) {
      const idx = p.text.indexOf(": ");
      if (idx > 0) return p.text.slice(0, idx).trim() === uid;
    }
    // 其他事件不按用户过滤
    return true;
  }

  function appendEvent(p, scroll) {
    const div = document.createElement("div");
    const style = EVENT_STYLE[p.tag] || { cls: "ev-other", icon: "·", label: p.tag };
    div.className = `ev-row ${style.cls}`;
    div.dataset.tag = p.tag;

    // 时间 + 标签
    let html = `<span class="ev-ts">${esc(p.ts)}</span>`;
    html += `<span class="ev-tag">${style.icon} ${style.label}</span>`;

    // 内容处理
    let content = p.text;
    if (p.tag === "Receive" || p.tag === "Reply" || p.tag === "Controller") {
      const idx = content.indexOf(": ");
      if (idx > 0) {
        const user = content.slice(0, idx);
        content = content.slice(idx + 2);
        html += `<span class="ev-user-id">${esc(user)}</span>`;
      }
    }
    if (p.tag === "Tool") {
      // 工具调用/返回，截断长参数
      if (content.length > 300) content = content.slice(0, 300) + "...";
    }
    if (p.tag === "MCP" && content.startsWith("思考过程")) {
      // 思考内容可折叠
      div.classList.add("ev-collapsible");
      html += `<span class="ev-toggle">▶</span><pre class="ev-pre">${esc(content)}</pre>`;
    } else {
      html += `<span class="ev-text">${esc(content)}</span>`;
    }

    div.innerHTML = html;

    // 思考内容折叠点击
    if (div.classList.contains("ev-collapsible")) {
      div.querySelector(".ev-toggle").onclick = () => {
        div.classList.toggle("ev-expanded");
        div.querySelector(".ev-toggle").textContent = div.classList.contains("ev-expanded") ? "▼" : "▶";
      };
    }

    stream.appendChild(div);
    while (stream.childElementCount > 800) stream.removeChild(stream.firstElementChild);
    if (scroll !== false) stream.scrollTop = stream.scrollHeight;
  }

  async function send() {
    const user_id = userInput.value.trim();
    const text = textInput.value.trim();
    if (!user_id) { toast("填写用户 ID", "err"); userInput.focus(); return; }
    if (!text) return;
    textInput.value = "";
    sendBtn.disabled = true;
    try {
      const r = await api("/api/test/message", "POST", { user_id, text });
      if (!r.ok) { toast(r.error || "失败", "err"); return; }
      toast("已注入", "ok");
      const list = JSON.parse(localStorage.getItem(USERS_KEY) || "[]");
      if (!list.includes(user_id)) { list.push(user_id); localStorage.setItem(USERS_KEY, JSON.stringify(list.slice(-8))); }
    } catch (e) { toast(e.message, "err"); }
    finally { sendBtn.disabled = false; }
  }

  sendBtn.onclick = send;
  textInput.addEventListener("keydown", e => { if (e.key === "Enter") send(); });
  onlyMe.onchange = renderHistory;
  showAll.onchange = () => {
    // 切换显示模式时重新渲染
    const show = showAll.checked;
    stream.querySelectorAll(".ev-row").forEach(row => {
      const tag = row.dataset.tag;
      const isMain = ["Receive","Reply","Controller"].includes(tag);
      row.style.display = (show || isMain) ? "" : "none";
    });
  };

  activeUnsub = subscribeLogs(line => {
    if (!app.bot || !app.bot.running) return;
    const p = parseLine(line);
    if (!p) return;
    if (onlyMe.checked && !isMatchUser(p)) return;
    // 非主要事件在"仅此用户+不显示全部"时隐藏
    if (!showAll.checked && !["Receive","Reply","Controller"].includes(p.tag)) return;
    appendEvent(p, true);
  });

  renderHistory();
}

export function unmountChatPage() {
  if (activeUnsub) { activeUnsub(); activeUnsub = null; }
}
