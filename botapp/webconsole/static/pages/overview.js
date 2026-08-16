"use strict";
/* 概览页：机器人控制 + 快捷入口 + 端口 + 最近日志预览 */
import { api, toast, fmtUptime, esc, app } from "../app.js";
import { renderRecentLogs } from "./console.js";

let unsubLogs = null;
let stateTimer = null;
let refreshing = false;

export function mountOverview(root) {
  root.innerHTML = `
  <div class="grid cols-2">
    <div class="card">
      <div class="card-title">机器人控制</div>
      <div class="row">
        <button id="ov-start" class="btn">启动机器人</button>
        <button id="ov-stop" class="btn ghost" disabled>停止机器人</button>
        <button id="ov-restart" class="btn ghost">重启机器人</button>
        <label style="display:flex;align-items:center;gap:6px;font-size:13px">
          <input type="checkbox" id="ov-auto"> 异常退出后自动重启
        </label>
      </div>
      <div id="ov-detail" class="muted" style="margin-top:8px"></div>
    </div>
    <div class="card">
      <div class="card-title">快捷入口</div>
      <div id="ov-links" class="grid cols-2" style="gap:10px"></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">端口占用</div>
    <table class="tbl">
      <thead><tr><th>服务</th><th>端口</th><th>状态</th><th>占用进程</th><th></th></tr></thead>
      <tbody id="ov-ports"></tbody>
    </table>
  </div>
  <div class="card">
    <div class="card-title">最近日志</div>
    <div id="ov-logs" style="background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:10px;font-family:Consolas,monospace;font-size:12px;line-height:1.45;height:340px;overflow:auto"></div>
  </div>`;

  const start = root.querySelector("#ov-start");
  const stop = root.querySelector("#ov-stop");
  const restart = root.querySelector("#ov-restart");
  const auto = root.querySelector("#ov-auto");
  const detail = root.querySelector("#ov-detail");
  const portsEl = root.querySelector("#ov-ports");
  const linksEl = root.querySelector("#ov-links");

  stateTimer = setInterval(() => { if (root.isConnected) refresh(); }, 5000);

  function renderPorts() {
    const ports = app.ports;
    portsEl.innerHTML = "";
    Object.entries(ports || {}).forEach(([port, s]) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${esc(s.desc)}</td><td class="mono">${port}</td>
        <td><span class="dot ${s.in_use ? "on" : "off"}"></span>${s.in_use ? "被占用" : "空闲"}</td>
        <td class="mono">${s.pids && s.pids.length ? "PID " + s.pids.join(", ") : "—"}</td>`;
      const td = document.createElement("td"); td.className = "actions";
      if (s.pids && s.pids.length) {
        const b = document.createElement("button");
        b.className = "btn danger sm"; b.textContent = "杀死";
        b.onclick = async () => {
          if (!confirm(`确定杀死端口 ${port} 的占用进程？\nPID: ${s.pids.join(", ")}`)) return;
          try { await api("/api/ports/kill", "POST", { pids: s.pids }); toast("已杀死", "ok"); }
          catch (e) { toast(e.message, "err"); }
        };
        td.appendChild(b);
      }
      tr.appendChild(td); portsEl.appendChild(tr);
    });
  }

  function renderLinks() {
    const ports = app.ports;
    linksEl.innerHTML = "";
    [["调试视图", "/debug", "查看每次 LLM 请求的实时流式输出（思考/回复/工具）"],
     ["OmbreBrain 后台", 18001, "长期记忆：日记、信件、记忆桶"]].forEach(([name, portOrPath, desc]) => {
      const isInternal = typeof portOrPath === "string" && portOrPath.startsWith("/");
      const s = isInternal ? null : ports[portOrPath];
      const d = document.createElement("div");
      d.className = "stat-card";
      if (isInternal) {
        d.innerHTML = `<div class="lbl">${esc(name)}</div>
          <div class="num" style="font-size:18px;font-weight:700"><a href="#${portOrPath}">调试</a></div>
          <div class="sub">集成</div>
          <div class="sub">${desc}</div>`;
      } else {
        d.innerHTML = `<div class="lbl">${esc(name)}</div>
          <div class="num" style="font-size:18px;font-weight:700"><a href="http://127.0.0.1:${portOrPath}" target="_blank">:${portOrPath}</a></div>
          <div class="sub">${s && s.in_use ? "运行中" : "未运行"}</div>
          <div class="sub">${desc}</div>`;
      }
      linksEl.appendChild(d);
    });
  }

  function renderState() {
    const bot = app.bot;
    if (!bot) { refresh(); return; }
    const running = !!bot.running;
    start.disabled = running;
    stop.disabled = !running;
    auto.checked = !!bot.auto_restart;
    detail.innerHTML = running
      ? `<span class="dot on"></span>运行中　PID ${bot.pid}　运行时长 ${fmtUptime(bot.uptime || 0)}`
      : (bot.stale_lock_pid
        ? `<span class="dot mid"></span>未运行（检测到残留运行锁 PID ${bot.stale_lock_pid}，启动时会自动清理）`
        : `<span class="dot off"></span>未运行`);
    renderPorts();
    renderLinks();
  }

  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      const st = await api("/api/state");
      app.bot = st.bot;
      app.ports = st.ports;
    } catch (e) {}
    refreshing = false;
    if (root.isConnected) renderState();
  }

  start.onclick = async () => {
    try { const r = await api("/api/bot/start", "POST", {}); toast(r.result, r.result === "ok" ? "ok" : "err"); refresh(); }
    catch (e) { toast(e.message, "err"); }
  };
  stop.onclick = async () => {
    try { await api("/api/bot/stop", "POST", {}); toast("已发送停止信号", "ok"); refresh(); }
    catch (e) { toast(e.message, "err"); }
  };
  restart.onclick = async () => {
    try { const r = await api("/api/bot/restart", "POST", {}); toast(r.result, r.result === "ok" ? "ok" : "err"); refresh(); }
    catch (e) { toast(e.message, "err"); }
  };
  auto.onchange = async () => {
    try { await api("/api/bot/auto_restart", "POST", { enabled: auto.checked }); toast("已保存", "ok"); }
    catch (e) { toast(e.message, "err"); }
  };

  unsubLogs = renderRecentLogs(root.querySelector("#ov-logs"), 300);
  renderState();
}

export function unmountOverview() {
  if (stateTimer) { clearInterval(stateTimer); stateTimer = null; }
  if (unsubLogs) { unsubLogs(); unsubLogs = null; }
}