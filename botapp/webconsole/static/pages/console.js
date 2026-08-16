"use strict";
/* 日志控制台页：实时日志 + 搜索过滤 + 批量渲染。
   登录二维码/账号相关已移至「账号管理」页。 */
import { api, toast, subscribeLogs, app } from "../app.js";

const LOG_LIMIT = 2000;
let activeUnsub = null;

/* 通用：在指定容器渲染最近日志（快照 + 实时增量）。
   返回取消订阅函数。overview 页面也复用本函数。 */
export function renderRecentLogs(container, limit = 500) {
  const frag = document.createDocumentFragment();
  for (const line of app.logs.slice(-limit)) {
    const div = document.createElement("div");
    div.className = "line";
    div.textContent = line;
    frag.appendChild(div);
  }
  container.appendChild(frag);
  container.scrollTop = container.scrollHeight;

  return subscribeLogs(line => {
    const div = document.createElement("div");
    div.className = "line";
    div.textContent = line;
    container.appendChild(div);
    while (container.childElementCount > limit) container.removeChild(container.firstElementChild);
    container.scrollTop = container.scrollHeight;
  });
}

export function mountConsolePage(root) {
  root.innerHTML = `
  <div class="card">
    <div class="card-title">运行日志</div>
    <div class="log-tools">
      <button id="c-clear" class="btn ghost sm">清空日志窗口</button>
      <label style="display:flex;align-items:center;gap:5px;font-size:12px;color:var(--muted)">
        <input type="checkbox" id="c-auto" checked> 自动滚动
      </label>
      <input type="text" id="c-filter" placeholder="过滤关键词…" style="width:200px">
    </div>
    <div id="logview"></div>
  </div>`;

  const logview = root.querySelector("#logview");

  let logBuffer = [];
  let ticking = false;
  let filterText = "";

  function matches(line) {
    if (!filterText) return true;
    return line.toLowerCase().includes(filterText.toLowerCase());
  }

  function flush() {
    if (!logview.isConnected) { ticking = false; logBuffer = []; return; }
    if (!logBuffer.length) { ticking = false; return; }
    const atBottom = logview.scrollHeight - logview.scrollTop - logview.clientHeight < 60;
    const auto = root.querySelector("#c-auto").checked;
    const frag = document.createDocumentFragment();
    for (const line of logBuffer.splice(0)) {
      if (!matches(line)) continue;
      const div = document.createElement("div");
      div.className = "line";
      div.textContent = line;
      frag.appendChild(div);
    }
    logview.appendChild(frag);
    while (logview.childElementCount > LOG_LIMIT) logview.removeChild(logview.firstElementChild);
    if (auto && atBottom) logview.scrollTop = logview.scrollHeight;
    ticking = false;
  }

  function append(line, fromReplay) {
    logBuffer.push(line);
    if (fromReplay) { flush(); return; }
    if (!ticking) { ticking = true; setTimeout(flush, 50); }
  }

  const unsub = subscribeLogs(line => append(line, false));
  activeUnsub = unsub;

  // 快照：拉一次全量（tail=500）
  api("/api/logs?tail=500").then(d => {
    logview.innerHTML = "";
    logBuffer = [];
    (d.lines || []).forEach(l => append(l, true));
  }).catch(() => {});

  root.querySelector("#c-clear").onclick = async () => {
    try { await api("/api/logs/clear", "POST", {}); logview.innerHTML = ""; logBuffer = []; toast("已清空日志缓冲", "ok"); }
    catch (e) { toast(e.message, "err"); }
  };
  root.querySelector("#c-filter").oninput = e => {
    filterText = e.target.value.trim();
    logview.innerHTML = "";
    app.logs.forEach(l => append(l, true));
  };
}

export function unmountConsolePage() {
  if (activeUnsub) { activeUnsub(); activeUnsub = null; }
}