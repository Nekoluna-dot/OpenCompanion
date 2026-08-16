"use strict";
/* 记忆与日记页：OmbreBrain 记忆桶 / 信件（经网页控制台代理）。
   首次使用需在 OB 后台 18001 完成密码初始化，或在本页直接设置。 */
import { api, toast, esc } from "../app.js";

let active = false;

export function mountMemoryPage(root) {
  active = true;
  root.innerHTML = `
  <div class="card" id="mem-conn">
    <div class="card-title">OmbreBrain 连接 <span id="mem-status" class="hint">检测中…</span></div>
    <div id="mem-conn-body"></div>
  </div>
  <div class="card" id="mem-data" style="display:none">
    <div class="card-title">
      记忆与信件
      <div class="chips" style="margin:0 0 0 16px">
        <span class="chip active" data-view="buckets">记忆桶</span>
        <span class="chip" data-view="letters">信件</span>
      </div>
      <div class="chips" id="mem-types" style="margin:0 0 0 8px"></div>
    </div>
    <div id="mem-list"></div>
  </div>
  <div class="drawer-backdrop" id="mem-drawer" style="display:none">
    <div class="drawer">
      <div class="row" style="justify-content:space-between">
        <h3 id="drawer-title">详情</h3>
        <button class="btn ghost sm" id="drawer-close">关闭</button>
      </div>
      <div id="drawer-body"></div>
    </div>
  </div>`;

  const statusEl = root.querySelector("#mem-status");
  const connBody = root.querySelector("#mem-conn-body");
  const dataCard = root.querySelector("#mem-data");
  const listEl = root.querySelector("#mem-list");
  const typeChips = root.querySelector("#mem-types");
  let view = "buckets";
  let type = "";
  let letters = [];

  async function checkConn() {
    let st = null;
    try {
      st = await api("/api/ob/status");
      statusEl.textContent = st.ok ? (st.authenticated ? "已连接" : "未登录") : "未连接";
      renderConnBody(st);
    } catch (e) {
      statusEl.textContent = "出错";
      connBody.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
    if (st && st.ok && st.authenticated) {
      dataCard.style.display = "";
      if (!listEl.childElementCount) loadAll();
    } else {
      dataCard.style.display = "none";
    }
    return st;
  }

  function renderConnBody(st) {
    if (!st.ok) {
      connBody.innerHTML = `
        <div class="empty">OmbreBrain 后台（18001）未启动。机器人启动后会自动拉起，或手动启动后刷新本页。</div>`;
      return;
    }
    if (st.setup_needed) {
      connBody.innerHTML = `
        <div class="row">
          <span>后台尚未设置登录密码（首次使用），在此设置：</span>
          <input type="password" id="ob-pwd" placeholder="新密码（至少 6 位）">
          <button class="btn" id="ob-setup">设置并进入</button>
        </div>`;
      root.querySelector("#ob-setup").onclick = async () => {
        const pwd = root.querySelector("#ob-pwd").value;
        try {
          const r = await api("/api/ob/setup", "POST", { password: pwd });
          if (!r.ok) { toast(r.error || "设置失败", "err"); return; }
          toast("已设置，进入记忆页", "ok");
          checkConn(); loadAll();
        } catch (e) { toast(e.message, "err"); }
      };
      return;
    }
    connBody.innerHTML = `
      <div class="row">
        <span>已设置密码，输入后台密码登录以查看记忆：</span>
        <input type="password" id="ob-pwd" placeholder="OmbreBrain 后台密码">
        <button class="btn" id="ob-login">登录</button>
      </div>`;
    root.querySelector("#ob-login").onclick = async () => {
      const pwd = root.querySelector("#ob-pwd").value;
      try {
        const r = await api("/api/ob/login", "POST", { password: pwd });
        if (!r.ok) { toast(r.error || "登录失败", "err"); return; }
        toast("已登录", "ok");
        checkConn(); loadAll();
      } catch (e) { toast(e.message, "err"); }
    };
  }

  function renderTypeChips() {
    typeChips.innerHTML = "";
    const types = view === "letters" ? [["", "全部"], ["user", "对方"], ["ai", "你"]] :
      [["", "全部"], ["permanent", "永久"], ["dynamic", "动态"], ["letter", "信件"], ["plan", "计划"], ["feel", "情绪"]];
    types.forEach(([v, label]) => {
      const c = document.createElement("span");
      c.className = "chip" + (type === v ? " active" : "");
      c.textContent = label;
      c.onclick = () => { type = v; loadAll(); };
      typeChips.appendChild(c);
    });
  }

  async function loadAll() {
    if (!active) return;
    renderTypeChips();
    if (view === "letters") await loadLetters();
    else await loadBuckets();
  }

  async function loadBuckets() {
    try {
      const r = await api("/api/ob/buckets?type=" + encodeURIComponent(type));
      if (!r.ok) { listEl.innerHTML = `<div class="empty">${esc(r.error)}</div>`; return; }
      const buckets = r.buckets || [];
      if (!buckets.length) { listEl.innerHTML = `<div class="empty">暂无记忆桶${type ? "（此类型）" : ""}</div>`; return; }
      listEl.innerHTML = "";
      buckets.forEach(b => {
        const item = document.createElement("div");
        item.className = "bucket-item";
        const btype = b.type || "dynamic";
        const tags = [
          `<span class="tag ${btype}">${esc(btype)}</span>`,
          b.pinned ? `<span class="tag perm">已置顶</span>` : "",
          b.resolved ? `<span class="tag">已解决</span>` : "",
          `<span class="tag">重要度 ${b.importance != null ? b.importance : "—"}</span>`,
          `<span class="tag">得分 ${b.score != null ? b.score.toFixed(2) : "—"}</span>`,
          `<span class="tag">触发 ${b.activation_count || 0} 次</span>`,
        ].filter(Boolean).join("");
        item.innerHTML = `<div class="meta">
            <div class="bname">${esc(b.name || b.id)}</div>
            <div class="bdesc">${esc(b.content_preview || "(无内容)")}</div>
            <div class="btags">${tags}</div>
            <div class="muted" style="margin-top:4px">创建 ${esc(b.created || "—")}　活跃 ${esc(b.last_active || "—")}</div>
          </div>`;
        item.onclick = () => openDrawer("记忆桶详情", b.name || b.id, `
          <table class="tbl">
            <tr><td>ID</td><td class="mono">${esc(b.id)}</td></tr>
            <tr><td>类型</td><td>${esc(btype)}</td></tr>
            <tr><td>重要度 / 得分</td><td>${b.importance != null ? b.importance : "—"} / ${b.score != null ? b.score.toFixed(2) : "—"}</td></tr>
            <tr><td>创建 / 活跃</td><td>${esc(b.created || "—")} / ${esc(b.last_active || "—")}</td></tr>
            <tr><td>激活次数</td><td>${b.activation_count || 0}</td></tr>
            <tr><td>标签</td><td>${esc((b.tags || []).join("、") || "—")}</td></tr>
            ${b.why_remembered ? `<tr><td>为何记住</td><td>${esc(b.why_remembered)}</td></tr>` : ""}
          </table>
          <div class="hr"></div>
          <div class="card-title">内容</div>
          <div style="white-space:pre-wrap;font-size:13px">${esc(b.content_preview || "(无内容)")}</div>
          <div class="muted" style="margin-top:10px">完整内容请在 OmbreBrain 后台（18001）查看</div>`);
        listEl.appendChild(item);
      });
    } catch (e) {
      listEl.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  async function loadLetters() {
    try {
      const r = await api("/api/ob/letters" + (type ? "?author=" + type : ""));
      if (!r.ok) { listEl.innerHTML = `<div class="empty">${esc(r.error)}</div>`; return; }
      letters = r.letters || [];
      if (!letters.length) { listEl.innerHTML = `<div class="empty">暂无信件${type ? "（此作者）" : ""}</div>`; return; }
      listEl.innerHTML = "";
      letters.forEach(l => {
        const item = document.createElement("div");
        item.className = "letter-item";
        item.innerHTML = `<div class="ltitle">${esc(l.title || "(无标题)")} <span class="tag ${l.author === "user" ? "letter" : "perm"}">${esc(l.author || "?")}</span></div>
          <div class="muted">${esc(l.date || "")}　→ ${esc(l.user_name || "—")}</div>
          <div class="lbody">${esc(l.content || "")}</div>`;
        item.onclick = () => openDrawer("信件详情", l.title || "(无标题)", `
          <table class="tbl">
            <tr><td>作者</td><td>${esc(l.author || "?")}</td></tr>
            <tr><td>日期</td><td>${esc(l.date || "—")}</td></tr>
            <tr><td>收件人</td><td>${esc(l.user_name || "—")}</td></tr>
          </table>
          <div class="hr"></div>
          <div style="white-space:pre-wrap;font-size:13px;line-height:1.7">${esc(l.content || "")}</div>`);
        listEl.appendChild(item);
      });
    } catch (e) {
      listEl.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  function openDrawer(title, sub, bodyHtml) {
    root.querySelector("#drawer-title").textContent = title;
    root.querySelector("#drawer-body").innerHTML = `<div class="muted" style="margin-bottom:10px">${esc(sub)}</div>` + bodyHtml;
    root.querySelector("#mem-drawer").style.display = "flex";
  }
  root.querySelector("#drawer-close").onclick = () => { root.querySelector("#mem-drawer").style.display = "none"; };
  root.querySelector("#mem-drawer").onclick = e => { if (e.target === e.currentTarget) e.currentTarget.style.display = "none"; };

  root.querySelectorAll("#mem-data .chip").forEach(chip => { /* 视图切换 chip 已绑定下方事件 */ });
  const viewChips = root.querySelectorAll("#mem-data > .card-title .chip");
  viewChips[0].onclick = () => {
    if (view === "letters") {
      view = "buckets"; type = "";
      viewChips.forEach((c, i) => c.classList.toggle("active", i === 0));
      loadAll();
    }
  };
  viewChips[1].onclick = () => {
    if (view === "buckets") {
      view = "letters"; type = "";
      viewChips.forEach((c, i) => c.classList.toggle("active", i === 1));
      loadAll();
    }
  };

  checkConn();
}

export function unmountMemoryPage() {
  active = false;
}