"use strict";
/* 账号管理页：平台适配器选择 + 登录二维码 + 登录状态。
   多适配器通用：二维码从日志流中自动提取（任意登录链接），也支持手动粘贴；状态由日志关键词推导。 */
import { api, toast, subscribeLogs, app } from "../app.js";

const URL_RE = /(https?:\/\/[^\s"'<>，。]+)/;
// 登录提示行关键词（兼容不同适配器/语言输出）
const HINT_RE = /(Scan this QR|扫码|登录|login|qrcode|二维码|session|过期|expired|refresh|Waiting for|Bot ID|已退出|logout)/i;
const LOG_FILTER_RE = /(Scan|QR|二维码|登录|login|session|过期|expired|refresh|Waiting|Bot ID|logout|账号)/i;

function friendlyName(id, map) {
  return (map && map[id]) || id;
}

function derivePhase(text) {
  const s = (text || "").toLowerCase();
  if (/(login successful|登录成功|扫码登录完成|已登录|bot id)/.test(s)) return "logged";
  if (/logout|已退出|退出登录/.test(s)) return "logged_out";
  if (/scanned, confirm|已扫描/.test(s)) return "scanned";
  if (/expired|过期/.test(s)) return "expired";
  if (/refresh|刷新|重新/.test(s)) return "waiting";
  if (/waiting for scan|scan this qr|scan the qr|等待扫码|等待扫描|请用.*扫码|扫码登录/.test(s)) return "waiting";
  return null;
}

const PHASE_META = {
  waiting:   { color: "var(--orange)", text: "等待扫码" },
  scanned:   { color: "var(--blue)",   text: "已扫码，请在手机上确认" },
  logged:    { color: "var(--green)",  text: "已登录" },
  expired:   { color: "var(--red)",    text: "二维码已过期，正在刷新" },
  logged_out:{ color: "var(--red)",    text: "已退出登录" },
  unknown:   { color: "var(--muted)",  text: "状态未知（暂无登录活动）" },
};

let activeUnsub = null;
let activeRefresh = null;

export function mountAccountsPage(root) {
  root.innerHTML = `
  <div style="display:grid;grid-template-columns:1fr 300px;gap:16px;align-items:start" id="acc-grid">
    <div style="display:flex;flex-direction:column;gap:16px">
      <div class="card">
        <div class="card-title">平台适配器</div>
        <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px">
          <span class="muted">当前启用：</span>
          <span id="acc-current" class="pill on">…</span>
          <span class="muted">机器人进程：</span>
          <span id="acc-bot" class="pill">…</span>
        </div>
        <div id="acc-platforms" style="display:flex;gap:8px;flex-wrap:wrap"></div>
        <button id="acc-switch" class="btn" style="margin-top:12px" disabled>切换到所选平台</button>
      </div>
      <div class="card" style="flex:1">
        <div class="card-title">登录状态</div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
          <span id="acc-dot" style="width:10px;height:10px;border-radius:50%;background:var(--muted);display:inline-block"></span>
          <span id="acc-phase" class="muted">分析中…</span>
        </div>
        <div id="acc-log" style="max-height:280px;overflow:auto;font-size:12px;line-height:1.7;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:8px 10px"></div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">登录二维码</div>
      <div style="display:flex;flex-direction:column;align-items:center">
        <img id="acc-qr" alt="二维码" style="display:none;width:250px;height:250px;border:1px solid var(--border);border-radius:8px;background:#fff">
        <div id="acc-qr-empty" class="muted" style="font-size:12px;text-align:center;padding:44px 6px;line-height:1.9">
          暂无登录二维码
        </div>
        <a id="acc-qr-link" target="_blank" rel="noopener" style="display:none;margin-top:10px;font-size:11.5px;word-break:break-all;text-align:center;color:var(--primary)"></a>
      </div>
      <div style="border-top:1px solid var(--border);margin-top:14px;padding-top:12px">
        <div class="muted" style="margin-bottom:6px">手动生成（粘贴任意登录链接）：</div>
        <input type="text" id="acc-manual" placeholder="https://…" style="width:100%;box-sizing:border-box">
        <button id="acc-gen" class="btn ghost sm" style="margin-top:8px;width:100%">生成二维码</button>
      </div>
    </div>
  </div>`;

  const qrImg = root.querySelector("#acc-qr");
  const qrEmpty = root.querySelector("#acc-qr-empty");
  const qrLink = root.querySelector("#acc-qr-link");
  const dot = root.querySelector("#acc-dot");
  const phaseEl = root.querySelector("#acc-phase");
  const accLog = root.querySelector("#acc-log");
  const currentEl = root.querySelector("#acc-current");
  const botEl = root.querySelector("#acc-bot");
  const listEl = root.querySelector("#acc-platforms");

  let platformData = { platforms: [], current: "", running: false, friendly: {} };
  let selected = null;
  let currentQr = null;

  function setQr(url) {
    if (!url) return;
    if (url === currentQr) return;
    currentQr = url;
    qrImg.src = "/api/qr?content=" + encodeURIComponent(url);
    qrImg.style.display = "";
    qrEmpty.style.display = "none";
    qrLink.href = url;
    qrLink.textContent = url;
    qrLink.style.display = "";
  }

  function setPhase(text) {
    const phase = derivePhase(text);
    if (!phase) return;
    const meta = PHASE_META[phase];
    dot.style.background = meta.color;
    phaseEl.textContent = meta.text;
    phaseEl.style.color = meta.color;
    phaseEl.classList.remove("muted");
  }

  let lastHintAt = 0;
  function onLogLine(line) {
    const m = URL_RE.exec(line);
    const isUrlLine = !!(m && line.trim().startsWith("http"));
    if (!LOG_FILTER_RE.test(line) && !isUrlLine) return;
    const now = Date.now();
    if (HINT_RE.test(line)) {
      lastHintAt = now;
      setPhase(line);
      if (m) setQr(m[1].replace(/[)\]}>"'.,;]+$/, ""));
    } else if (m) {
      if (now - lastHintAt < 10000) setQr(m[1].replace(/[)\]}>"'.,;]+$/, ""));
    }
    if (accLog.childElementCount > 120) accLog.removeChild(accLog.firstElementChild);
    const div = document.createElement("div");
    div.className = "line";
    div.textContent = line;
    accLog.appendChild(div);
    accLog.scrollTop = accLog.scrollHeight;
  }

  const unsub = subscribeLogs(onLogLine);
  activeUnsub = unsub;
  app.logs.forEach(onLogLine);

  function renderPlatforms() {
    if (!root.isConnected) return;
    const { platforms, current, running, friendly } = platformData;
    currentEl.textContent = friendlyName(current, friendly) || "(未配置)";
    currentEl.classList.remove("on", "off");
    currentEl.classList.add(current ? "on" : "off");
    botEl.textContent = running ? "运行中" : "已停止";
    botEl.classList.remove("on", "off");
    botEl.classList.add(running ? "on" : "off");
    listEl.innerHTML = "";
    platforms.forEach(id => {
      const b = document.createElement("button");
      b.className = "btn ghost sm";
      b.textContent = friendlyName(id, friendly);
      if (id === current) b.disabled = true;
      if (selected === id) b.classList.add("on");
      b.onclick = () => {
        selected = id;
        renderPlatforms();
      };
      listEl.appendChild(b);
    });
    const sw = root.querySelector("#acc-switch");
    if (sw) sw.disabled = !selected || selected === current;
  }

  async function loadPlatforms() {
    try {
      const d = await api("/api/platforms");
      if (!root.isConnected) return;
      platformData = d;
      renderPlatforms();
    } catch (e) {
      if (root.isConnected) toast("读取平台信息失败: " + e.message, "err");
    }
  }

  root.querySelector("#acc-switch").onclick = async () => {
    try {
      const r = await api("/api/platform/switch", "POST", { name: selected });
      toast(`已切换平台，${r.restart_required ? "请重启机器人生效" : "已保存"}`, "ok");
      selected = null;
      loadPlatforms();
    } catch (e) {
      toast(e.message, "err");
    }
  };

  root.querySelector("#acc-gen").onclick = () => {
    const v = root.querySelector("#acc-manual").value.trim();
    if (!/^https?:\/\/\S+/.test(v)) { toast("请输入合法链接（http/https 开头）", "err"); return; }
    setQr(v);
    toast("二维码已生成", "ok");
  };
  root.querySelector("#acc-manual").addEventListener("keydown", e => {
    if (e.key === "Enter") root.querySelector("#acc-gen").click();
  });

  loadPlatforms();
  const refreshTimer = setInterval(() => {
    if (root.isConnected) loadPlatforms();
  }, 5000);
  activeRefresh = refreshTimer;
}

export function unmountAccountsPage() {
  if (activeRefresh) { clearInterval(activeRefresh); activeRefresh = null; }
  if (activeUnsub) { activeUnsub(); activeUnsub = null; }
}