"use strict";
import { api, toast, esc } from "../app.js";

const FEEDBACK_ENDPOINT = "https://columbina.duckdns.org:800/feedback";
const TID_KEY = "oc_fb_tickets";

const STATUS_LABEL = { open: "处理中", replied: "已回复", resolved: "已解决", closed: "已关闭" };
const TYPE_LABEL = { bug: "BUG 上报", suggestion: "功能建议", feedback: "意见反馈" };

let files = [];
let metaData = {};

function loadTids() {
  try {
    const v = JSON.parse(localStorage.getItem(TID_KEY) || "[]");
    return Array.isArray(v) ? v.filter(t => typeof t === "string") : [];
  } catch (e) { return []; }
}

function saveTids(tids) {
  try { localStorage.setItem(TID_KEY, JSON.stringify(tids)); } catch (e) {}
}

function addTid(tid) {
  const list = loadTids();
  if (!list.includes(tid)) {
    list.unshift(tid);
    saveTids(list.slice(0, 50));
  }
}

function removeTid(tid) {
  saveTids(loadTids().filter(t => t !== tid));
}

function fmtTime(s) {
  const t = String(s || "").replace("T", " ").replace(/\.\d+/, "");
  return t.length > 19 ? t.slice(0, 19) : t;
}

export function mountFeedbackPage(root) {
  root.innerHTML = `
  <div class="grid" style="max-width:780px">
    <div class="card">
      <div class="card-title">我的反馈</div>
      <div id="fb-mine" class="fb-mine"></div>
    </div>

    <div class="card">
      <div class="card-title">意见 / BUG 反馈</div>
      <p class="muted" style="margin-bottom:12px">
        也可以通过 <a href="https://github.com/Nekoluna-dot/OpenCompanion/issues" target="_blank" rel="noopener">GitHub Issues</a> 反馈问题
      </p>
      <div class="fb-form">
        <label class="fld">
          <span>反馈类型</span>
          <select id="fb-type">
            <option value="bug">BUG 上报</option>
            <option value="suggestion">功能建议</option>
            <option value="feedback">意见反馈</option>
          </select>
        </label>
        <label class="fld">
          <span>标题</span>
          <input id="fb-title" type="text" maxlength="120" placeholder="一句话概括（选填，与内容至少填一项）">
        </label>
        <label class="fld">
          <span>详细描述</span>
          <textarea id="fb-content" style="min-height:140px" maxlength="8000"
            placeholder="问题现象 / 复现步骤 / 期望行为；功能出错时请尽量说明「出错的位置/功能」"></textarea>
        </label>
        <label class="fld">
          <span>联系方式</span>
          <input id="fb-contact" type="text" maxlength="200" placeholder="邮箱 / QQ / 微信（选填，便于跟进）">
        </label>
        <label class="fld">
          <span>截图</span>
          <span style="display:flex;flex-direction:column;gap:8px">
            <label class="btn ghost sm fb-file-btn">
              选择截图 <input id="fb-images" type="file" hidden
                accept="image/png,image/jpeg,image/gif,image/webp" multiple>
            </label>
            <span class="hint">PNG/JPG/GIF/WebP，最多 3 张，单张不超过 4MB（选填）</span>
            <span id="fb-previews" class="fb-previews"></span>
          </span>
        </label>
        <div class="hr"></div>
        <label class="fb-consent" id="fb-consent-label">
          <input type="checkbox" id="fb-consent" required>
          <span><em class="fb-req">*</em> 我同意上传系统信息（不包含您的个人信息），必选项</span>
        </label>
        <div class="row" style="margin-top:14px">
          <button id="fb-submit" class="btn primary">提交反馈</button>
          <button id="fb-reset" class="btn ghost" type="button">清空</button>
          <span id="fb-status" class="fb-status muted"></span>
        </div>
      </div>
    </div>
  </div>`;

  const mineEl = root.querySelector("#fb-mine");
  const typeEl = root.querySelector("#fb-type");
  const titleEl = root.querySelector("#fb-title");
  const contentEl = root.querySelector("#fb-content");
  const contactEl = root.querySelector("#fb-contact");
  const filesEl = root.querySelector("#fb-images");
  const previewsEl = root.querySelector("#fb-previews");
  const consentEl = root.querySelector("#fb-consent");
  const submitBtn = root.querySelector("#fb-submit");
  const resetBtn = root.querySelector("#fb-reset");
  const statusEl = root.querySelector("#fb-status");

  async function loadMeta() {
    try {
      const d = await api("/api/feedback/meta");
      metaData = d.meta || {};
      try {
        const logs = await api("/api/logs?tail=40");
        if (logs && Array.isArray(logs.lines) && logs.lines.length) {
          metaData.recent_logs = logs.lines.filter(l => typeof l === "string").slice(0, 40)
            .map(l => l.length > 240 ? l.slice(0, 240) + "…" : l);
        }
      } catch (e) { /* 可选 */ }
    } catch (e) {
      metaData = {};
    }
  }

  function renderPreviews() {
    previewsEl.innerHTML = "";
    files.forEach((f, idx) => {
      const wrap = document.createElement("div");
      wrap.className = "fb-preview";
      const img = document.createElement("img");
      img.alt = f.name;
      const reader = new FileReader();
      reader.onload = () => { img.src = reader.result; };
      reader.readAsDataURL(f);
      const info = document.createElement("div");
      info.className = "fb-preview-info";
      info.textContent = `${f.name}（${(f.size / 1024).toFixed(1)} KB）`;
      const rm = document.createElement("button");
      rm.className = "btn ghost sm";
      rm.textContent = "移除";
      rm.onclick = () => { files.splice(idx, 1); renderPreviews(); };
      wrap.appendChild(img);
      wrap.appendChild(info);
      wrap.appendChild(rm);
      previewsEl.appendChild(wrap);
    });
  }

  function ticketCard(tid, data) {
    const card = document.createElement("div");
    card.className = "fb-ticket";

    const top = document.createElement("div");
    top.className = "fb-ticket-top";
    const tidEl = document.createElement("span");
    tidEl.className = "fb-tid";
    tidEl.textContent = tid;
    const typeEl2 = document.createElement("span");
    typeEl2.className = "fb-chip fb-chip-type";
    typeEl2.textContent = TYPE_LABEL[data.type] || "意见反馈";
    const titleEl2 = document.createElement("span");
    titleEl2.className = "fb-title";
    titleEl2.textContent = data.title || "(无标题)";
    const chip = document.createElement("span");
    chip.className = "fb-chip st-" + (data.status || "open");
    chip.textContent = STATUS_LABEL[data.status] || "处理中";
    const timeEl = document.createElement("span");
    timeEl.className = "fb-time";
    timeEl.textContent = fmtTime(data.created_at);
    const chev = document.createElement("span");
    chev.className = "fb-chev";
    chev.textContent = "▾";
    top.appendChild(tidEl);
    top.appendChild(typeEl2);
    top.appendChild(titleEl2);
    top.appendChild(chip);
    top.appendChild(timeEl);
    top.appendChild(chev);
    top.onclick = () => card.classList.toggle("open");

    const body = document.createElement("div");
    body.className = "fb-ticket-body";
    const contentDiv = document.createElement("div");
    contentDiv.className = "fb-desc";
    contentDiv.textContent = data.content || "(无内容)";

    const actions = document.createElement("div");
    actions.className = "fb-actions";
    const del = document.createElement("button");
    del.className = "btn ghost sm";
    del.textContent = "移除此单";
    del.onclick = (e) => {
      e.stopPropagation();
      removeTid(tid);
      renderMine();
    };
    actions.appendChild(del);

    body.appendChild(contentDiv);
    body.appendChild(actions);

    const repliesBox = document.createElement("div");
    repliesBox.className = "fb-replybox";
    const repQ = document.createElement("div");
    repQ.className = "fb-replybox-title";
    repQ.textContent = "回复";
    repliesBox.appendChild(repQ);
    if (data.replies && data.replies.length) {
      data.replies.forEach(r => {
        const rep = document.createElement("div");
        rep.className = "fb-reply";
        const head = document.createElement("div");
        head.className = "fb-reply-head";
        head.textContent = "开发方 · " + fmtTime(r.created_at);
        const txt = document.createElement("div");
        txt.textContent = r.body;
        rep.appendChild(head);
        rep.appendChild(txt);
        repliesBox.appendChild(rep);
      });
    } else {
      const none = document.createElement("div");
      none.className = "fb-note";
      none.textContent = "暂无回复";
      repliesBox.appendChild(none);
    }
    body.appendChild(repliesBox);

    if (data.attachments && data.attachments.length) {
      const att = document.createElement("div");
      att.className = "fb-attach";
      data.attachments.forEach(a => {
        const img = document.createElement("img");
        img.loading = "lazy";
        img.alt = a.path;
        img.title = a.path;
        img.onclick = () => window.open(
          FEEDBACK_ENDPOINT + "/file.php?tid=" + encodeURIComponent(tid) + "&f=" + encodeURIComponent(a.path), "_blank");
        img.src = FEEDBACK_ENDPOINT + "/file.php?tid=" + encodeURIComponent(tid) + "&f=" + encodeURIComponent(a.path);
        att.appendChild(img);
      });
      body.appendChild(att);
    }

    card.appendChild(top);
    card.appendChild(body);
    return card;
  }

  function errorCard(tid, msg) {
    const card = document.createElement("div");
    card.className = "fb-ticket";
    const top = document.createElement("div");
    top.className = "fb-ticket-top";
    const t = document.createElement("span");
    t.className = "fb-tid";
    t.textContent = tid;
    const err = document.createElement("span");
    err.className = "fb-error";
    err.textContent = msg;
    const del = document.createElement("button");
    del.className = "btn ghost sm";
    del.textContent = "移除";
    del.onclick = (e) => { e.stopPropagation(); removeTid(tid); renderMine(); };
    top.appendChild(t);
    top.appendChild(err);
    top.appendChild(del);
    card.appendChild(top);
    return card;
  }

  async function renderMine() {
    const tids = loadTids();
    if (!tids.length) {
      mineEl.innerHTML = '<div class="fb-note">暂无反馈记录。</div>';
      return;
    }
    mineEl.innerHTML = '<div class="fb-note">加载中…</div>';
    const results = await Promise.all(tids.map(async tid => {
      try {
        const resp = await fetch(FEEDBACK_ENDPOINT + "/status.php?tid=" + encodeURIComponent(tid));
        const data = await resp.json().catch(() => null);
        if (!resp.ok || !data || !data.ok) {
          throw new Error((data && data.error) || ("HTTP " + resp.status));
        }
        const t = Object.assign({}, data.ticket || {}, {
          replies: data.replies || [],
          attachments: data.attachments || [],
        });
        return { tid, card: ticketCard(tid, t) };
      } catch (e) {
        return { tid, card: errorCard(tid, (e && e.message) || "查询失败") };
      }
    }));
    mineEl.innerHTML = "";
    results.forEach(r => mineEl.appendChild(r.card));
  }

  filesEl.onchange = () => {
    files = Array.from(filesEl.files || []).slice(0, 3);
    renderPreviews();
  };

  submitBtn.onclick = async () => {
    const type = typeEl.value;
    const title = titleEl.value.trim();
    const content = contentEl.value.trim();
    const contact = contactEl.value.trim();
    if (!consentEl.checked) {
      consentEl.closest(".fb-consent").classList.add("fb-invalid");
      setTimeout(() => consentEl.closest(".fb-consent").classList.remove("fb-invalid"), 1600);
      toast("必选项：请先勾选同意上传系统信息", "err");
      consentEl.focus();
      return;
    }
    if (!title && !content) { toast("请填写标题或内容", "err"); return; }

    statusEl.innerHTML = "提交中…";
    submitBtn.disabled = true;
    try {
      const csrfResp = await fetch(FEEDBACK_ENDPOINT + "/csrf.php");
      let token = "";
      try {
        const cd = await csrfResp.json();
        token = cd.token || "";
      } catch (e) {}
      if (!token) throw new Error("无法获取安全令牌：请检查反馈后端地址是否可访问");

      const fd = new FormData();
      fd.append("csrf", token);
      fd.append("type", type);
      fd.append("title", title);
      fd.append("content", content);
      fd.append("contact", contact);
      fd.append("meta", JSON.stringify(metaData));
      files.forEach(f => fd.append("screenshots[]", f, f.name));

      const resp = await fetch(FEEDBACK_ENDPOINT + "/submit.php", { method: "POST", body: fd });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok && data.ok) {
        const tid = data.tid || "";
        if (tid) addTid(tid);
        toast("反馈已提交", "ok");
        statusEl.innerHTML = "";
        if (tid) {
          const okDiv = document.createElement("span");
          okDiv.innerHTML = '已提交成功，您的反馈单号：<b class="fb-tid">' + esc(tid) + '</b> '
            + '<button class="btn ghost sm" id="fb-copy">复制</button>';
          statusEl.appendChild(okDiv);
          const cp = okDiv.querySelector("#fb-copy");
          cp.onclick = async () => {
            try { await navigator.clipboard.writeText(tid); toast("单号已复制", "ok"); }
            catch (e) { toast(tid, "err"); }
          };
        }
        if (data.warnings && data.warnings.length) {
          const wdiv = document.createElement("span");
          wdiv.style.color = "#b7271c";
          wdiv.style.display = "block";
          wdiv.style.marginTop = "6px";
          wdiv.textContent = data.warnings.join("；");
          statusEl.appendChild(wdiv);
          toast(data.warnings[0], "err");
        }
        files = [];
        filesEl.value = "";
        previewsEl.innerHTML = "";
        consentEl.checked = false;
        typeEl.value = "bug";
        titleEl.value = "";
        contentEl.value = "";
        contactEl.value = "";
        renderMine();
      } else {
        throw new Error(data.error || ("HTTP " + resp.status));
      }
    } catch (e) {
      statusEl.innerHTML = "";
      toast(e.message, "err");
    } finally {
      submitBtn.disabled = false;
    }
  };

  resetBtn.onclick = () => {
    files = [];
    filesEl.value = "";
    previewsEl.innerHTML = "";
    consentEl.checked = false;
    typeEl.value = "feedback";
    titleEl.value = "";
    contentEl.value = "";
    contactEl.value = "";
    statusEl.innerHTML = "";
  };

  loadMeta();
  renderMine();
}

export function unmountFeedbackPage() {}