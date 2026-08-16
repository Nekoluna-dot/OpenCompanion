"use strict";
/* OpenCompanion 控制台核心：鉴权、路由、SSE 日志分发、全局状态 */

const $ = s => document.querySelector(s);
const TOKEN_KEY = "wc_token";

export const app = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  tokenRequired: false,
  bot: null,
  ports: {},
  logs: [],            // 全局日志环形数组（上限 2000）
  logSeq: 0,
  sseOk: false,
};

// ---------------- API ----------------
export async function api(path, method = "GET", body) {
  const opt = { method, headers: {} };
  if (app.token) opt.headers["Authorization"] = "Bearer " + app.token;
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  if (r.status === 401 && !path.startsWith("/api/auth/")) {
    showLogin();
    throw new Error("未授权");
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}

// ---------------- Toast ----------------
export function toast(msg, type = "") {
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = msg;
  $("#toast").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

// ---------------- 格式化 ----------------
export function fmtUptime(s) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0") + ":" + String(sec).padStart(2, "0");
}
export function fmtSize(n) {
  if (!n && n !== 0) return "—";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}
export const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------------- 登录 / 首次设置 ----------------
export async function checkAuth() {
  try {
    const st = await api("/api/auth/status");
    if (st.need_setup) { showSetup(); return; }
    if (!st.authed) { showLogin(); return; }
    showApp();
  } catch (e) {
    showLogin();
  }
}
export function showLogin() {
  const appEl = $("#app");
  if (appEl) appEl.style.display = "none";
  const setupEl = $("#view-setup");
  if (setupEl) setupEl.style.display = "none";
  const loginEl = $("#view-login");
  if (!loginEl) return;
  loginEl.style.display = "flex";
  stopSse();
  const inp = $("#login-token");
  if (inp) { inp.value = ""; inp.focus(); }
}
function showSetup() {
  const appEl = $("#app");
  if (appEl) appEl.style.display = "none";
  const loginEl = $("#view-login");
  if (loginEl) loginEl.style.display = "none";
  const setupEl = $("#view-setup");
  if (!setupEl) return;
  setupEl.style.display = "flex";
  stopSse();
  const inp = $("#setup-password");
  if (inp) inp.focus();
}
function showApp() {
  const setupEl = $("#view-setup");
  if (setupEl) setupEl.style.display = "none";
  $("#view-login").style.display = "none";
  $("#app").style.display = "flex";
  startSse();
  if (!location.hash || location.hash === "#/") location.hash = "#/overview";
  render();
  refreshState();
}
// ---------------- 登录/设置绑定（仅 index.html 存在时） ----------------
if ($("#login-btn")) {
  $("#login-btn").onclick = async () => {
    const password = $("#login-token").value.trim();
    $("#login-error").textContent = "";
    try {
      const r = await api("/api/auth/login", "POST", { password });
      if (!r.ok) { $("#login-error").textContent = r.error || "登录失败"; return; }
      app.token = r.session;
      localStorage.setItem(TOKEN_KEY, r.session);
      showApp();
      toast("登录成功", "ok");
    } catch (e) { $("#login-error").textContent = e.message; }
  };
  $("#login-token").addEventListener("keydown", e => { if (e.key === "Enter") $("#login-btn").click(); });
  $("#logout-btn").onclick = async () => {
    try { await api("/api/auth/logout", "POST", {}); } catch (e) {}
    localStorage.removeItem(TOKEN_KEY);
    app.token = "";
    stopSse();
    showLogin();
  };
}
if ($("#setup-btn")) {
  $("#setup-btn").onclick = async () => {
    const p1 = $("#setup-password").value, p2 = $("#setup-password2").value;
    const errEl = $("#setup-error");
    errEl.textContent = "";
    if (p1.length < 6) { errEl.textContent = "密码至少 6 位"; return; }
    if (p1 !== p2) { errEl.textContent = "两次输入的密码不一致"; return; }
    try {
      const r = await api("/api/auth/setup", "POST", { password: p1 });
      if (!r.ok) { errEl.textContent = r.error || "设置失败"; return; }
      app.token = r.session;
      localStorage.setItem(TOKEN_KEY, r.session);
      toast("密码设置成功", "ok");
      showApp();
    } catch (e) { errEl.textContent = e.message; }
  };
  $("#setup-password2").addEventListener("keydown", e => { if (e.key === "Enter") $("#setup-btn").click(); });
}

// ---------------- 顶部状态 ----------------
export async function refreshState() {
  try {
    const st = await api("/api/state");
    app.bot = st.bot;
    app.ports = st.ports;
  } catch (e) { return; }
  const badge = $("#badge");
  const running = app.bot && app.bot.running;
  badge.textContent = running ? "● 机器人运行中" : "○ 机器人未运行";
  badge.className = "pill " + (running ? "on" : "off");
  const link = $("#ob-link");
  const ob = app.ports && app.ports[18001];
  link.style.display = (ob && ob.in_use) ? "" : "none";
}

// ---------------- SSE 全局日志流 ----------------
let es = null;
const logSubs = new Set();
export function subscribeLogs(cb) { logSubs.add(cb); return () => logSubs.delete(cb); }
function pushLog(line) {
  app.logs.push(line);
  if (app.logs.length > 2000) app.logs.splice(0, app.logs.length - 2000);
  app.logSeq++;
  logSubs.forEach(cb => { try { cb(line); } catch (e) {} });
}
function startSse() {
  if (es) return;
  const q = app.token ? "?token=" + encodeURIComponent(app.token) : "";
  es = new EventSource("/api/logs/stream" + q);
  es.onmessage = ev => {
    app.sseOk = true;
    const el = $("#sse-dot");
    if (el) { el.className = "dot on"; $("#sse-text").textContent = "日志流已连接"; }
    try { pushLog(JSON.parse(ev.data)); } catch (e) { pushLog(ev.data); }
  };
  es.onerror = () => {
    app.sseOk = false;
    const el = $("#sse-dot");
    if (el) { el.className = "dot off"; $("#sse-text").textContent = "日志流重连中…"; }
    es.close();
    es = null;
    if ($("#app").style.display !== "none") setTimeout(startSse, 2000);
  };
}
function stopSse() {
  if (es) { es.close(); es = null; }
}

// ---------------- 路由 ----------------
import { pages } from "./pages/index.js";

function render() {
  const hash = location.hash.slice(1) || "/overview";
  const page = pages[hash] || pages["/overview"];
  const root = $("#page-root");
  const active = $("#nav button.active");
  if (active) active.classList.remove("active");
  const navBtn = document.querySelector(`#nav button[data-page="${page.path}"]`);
  if (navBtn) navBtn.classList.add("active");
  $("#page-title").textContent = page.title;
  $("#crumb").textContent = "控制台 / " + page.title;
  root.innerHTML = "";
  if (page.unmount) page.unmount();
  page.mount(root);
}
window.addEventListener("hashchange", render);

// 导航
const NAV = [
  ["/overview", "◉", "概览"],
  ["/console", "▤", "日志控制台"],
  ["/accounts", "◎", "账号管理"],
  ["/chat", "✉", "聊天测试"],
  ["/debug", "◇", "调试视图"],
  ["/memory", "◈", "记忆与日记"],
  ["/config", "⚙", "机器人配置"],
  ["/prompts", "◑", "人设预设"],
  ["/stats", "▥", "统计"],
  ["/data", "□", "数据管理"],
  ["/feedback", "✎", "意见反馈"],
];
const navEl = $("#nav");
if (navEl) {
  navEl.innerHTML = "";
  NAV.forEach(([path, icon, name]) => {
    const b = document.createElement("button");
    b.dataset.page = path;
    b.innerHTML = `<span class="icon">${icon}</span><span>${name}</span>`;
    b.onclick = () => { if (location.hash !== "#" + path) location.hash = path; };
    navEl.appendChild(b);
  });
}

// ---------------- 启动（仅 index.html 包含登录/设置视图时执行，smoke 测试页会跳过） ----------------
if ($("#view-login") || $("#view-setup")) {
  checkAuth();
  setInterval(() => { if ($("#app").style.display !== "none") refreshState(); }, 5000);
}
