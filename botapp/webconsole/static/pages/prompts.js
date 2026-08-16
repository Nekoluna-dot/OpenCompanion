"use strict";
/* 人设预设管理 */
import { api, toast, esc } from "../app.js";

export function mountPromptsPage(root) {
  root.innerHTML = `
  <div class="presets-layout">
    <div class="card">
      <div class="card-title">预设</div>
      <div class="new-row">
        <input id="new-name" placeholder="名称" maxlength="64">
        <button id="btn-new" class="btn sm primary">新建</button>
      </div>
      <div id="presets-list"></div>
    </div>
    <div class="card editor-card">
      <div class="editor-header">
        <span id="editing-name" class="muted"></span>
        <input id="ed-desc" placeholder="描述（可选）">
        <button id="btn-activate" class="btn sm primary">激活</button>
        <button id="btn-save" class="btn sm ghost">保存</button>
      </div>
      <textarea id="ed-prompt" spellcheck="false" placeholder="prompt.txt"></textarea>
      <textarea id="ed-extra" spellcheck="false" placeholder="prompt_extra.txt"></textarea>
    </div>
  </div>`;

  const $ = s => root.querySelector(s);
  let editing = "";

  function renderList(presets, active) {
    const tb = $("#presets-list");
    if (!presets.length) { tb.innerHTML = `<div class="empty">暂无</div>`; return; }
    tb.innerHTML = presets.map(p => `
      <div class="preset-row${p.active ? " active" : ""}" data-name="${esc(p.name)}">
        <div class="preset-info">
          <span class="preset-name">${esc(p.name)}</span>
          ${p.description ? `<span class="preset-desc">${esc(p.description)}</span>` : ""}
          ${p.active ? '<span class="pill on sm">当前</span>' : ""}
        </div>
        <div class="preset-actions">
          <button class="btn sm ghost btn-load">编辑</button>
          <button class="btn sm primary btn-swtch"${p.active ? " disabled" : ""}>激活</button>
          <button class="btn sm danger btn-del"${(p.name === "default" || p.active) ? " disabled" : ""}>删除</button>
        </div>
      </div>
    `).join("");
    // bind events
    tb.querySelectorAll(".preset-row").forEach(row => {
      const name = row.dataset.name;
      row.querySelector(".btn-load").onclick = () => loadPreset(name);
      row.querySelector(".btn-swtch").onclick = () => activatePreset(name);
      row.querySelector(".btn-del").onclick = () => deletePreset(name);
    });
  }

  async function refreshList() {
    try {
      const d = await api("/api/prompts");
      editing = d.active || "";
      renderList(d.presets || [], editing);
      await loadPreset(editing);
    } catch (e) { toast(e.message, "err"); }
  }

  async function loadPreset(name) {
    if (!name) { $("#editing-name").textContent = ""; $("#ed-prompt").value = ""; $("#ed-extra").value = ""; return; }
    try {
      const p = await api(`/api/prompts/${encodeURIComponent(name)}`);
      editing = name;
      $("#editing-name").textContent = name;
      $("#ed-desc").value = p.description || "";
      $("#ed-prompt").value = p.prompt || "";
      $("#ed-extra").value = p.extra || "";
    } catch (e) { toast(e.message, "err"); }
  }

  async function savePreset() {
    if (!editing) { toast("未选择", "err"); return; }
    try {
      const r = await api(`/api/prompts/${encodeURIComponent(editing)}`, "POST", {
        prompt: $("#ed-prompt").value,
        extra: $("#ed-extra").value,
        description: $("#ed-desc").value,
      });
      toast(`已保存`, "ok");
      await refreshList();
    } catch (e) { toast(e.message, "err"); }
  }

  async function activatePreset(name) {
    try {
      const r = await api(`/api/prompts/${encodeURIComponent(name)}/activate`, "POST", {});
      toast(`已切换到 ${name}`, "ok");
      await refreshList();
    } catch (e) { toast(e.message, "err"); }
  }

  async function deletePreset(name) {
    if (!confirm(`删除 ${name}?`)) return;
    try {
      const r = await api(`/api/prompts/${encodeURIComponent(name)}/delete`, "POST", {});
      toast(`已删除`, "ok");
      await refreshList();
    } catch (e) { toast(e.message, "err"); }
  }

  async function newPreset() {
    const name = $("#new-name").value.trim();
    if (!name) { toast("输入名称", "err"); return; }
    try {
      const r = await api("/api/prompts", "POST", { name, description: "", prompt: "", extra: "" });
      $("#new-name").value = "";
      await refreshList();
      loadPreset(r.name);
    } catch (e) { toast(e.message, "err"); }
  }

  $("#btn-save").onclick = savePreset;
  $("#btn-activate").onclick = () => activatePreset(editing);
  $("#btn-new").onclick = newPreset;

  refreshList();
}

export function unmountPromptsPage() {}
