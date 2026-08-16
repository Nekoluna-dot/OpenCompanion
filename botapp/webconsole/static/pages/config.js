"use strict";
/* 机器人配置页：config.ini（结构化 + 工具源勾选 + 原始文本）与 OmbreBrain config.yaml */
import { api, toast, esc } from "../app.js";

export function mountConfigPage(root) {
  root.innerHTML = `
  <div class="grid cols-2">
    <div class="card">
      <div class="card-title">机器人配置（config.ini）</div>
      <div class="row">
        <button id="ini-reload" class="btn ghost sm">重新读取</button>
        <button id="ini-save" class="btn sm">保存</button>
        <button id="ini-save-restart" class="btn sm">保存并重启机器人</button>
        <label style="display:flex;align-items:center;gap:6px;font-size:13px">
          <input type="checkbox" id="ini-raw-toggle"> 编辑原始文本
        </label>
      </div>
      <div id="ini-form"></div>
      <textarea id="ini-raw" style="display:none" spellcheck="false"></textarea>
    </div>
    <div class="card">
      <div class="card-title">OmbreBrain 配置（MCP/OB/config.yaml）</div>
      <div class="row">
        <button id="yaml-reload" class="btn ghost sm">重新读取</button>
        <button id="yaml-save" class="btn sm">保存</button>
        <button id="yaml-save-restart" class="btn sm">保存并重启机器人</button>
        <label style="display:flex;align-items:center;gap:6px;font-size:13px">
          <input type="checkbox" id="yaml-raw-toggle"> 编辑原始文本
        </label>
      </div>
      <div id="yaml-form"></div>
      <textarea id="yaml-raw" style="display:none" spellcheck="false"></textarea>
    </div>
  </div>`;

  // ---- 通用表单构建 ----
  function buildForm(container, data) {
    container.innerHTML = "";
    const values = data.values || {}, schema = data.schema || {};
    const combo = data.combo || {};
    const descs = data.descs || {};
    const els = {};
    for (const sec of Object.keys(schema)) {
      const f = document.createElement("fieldset");
      f.innerHTML = `<legend>${esc(sec)}</legend>`;
      for (const key of Object.keys(schema[sec])) {
        const type = schema[sec][key];
        const val = (values[sec] || {})[key];
        const lab = document.createElement("label");
        lab.className = "fld";
        const desc = (descs[sec] || {})[key];
        lab.innerHTML = `<span>${esc(key)}${desc ? `<i class="hint" title="${esc(desc)}">${esc(desc)}</i>` : ""}</span>`;
        let input;
        if (type === "bool") {
          input = document.createElement("input"); input.type = "checkbox";
          input.checked = String(val).toLowerCase() === "true" || val === "1" || val === "on";
          input.style.justifySelf = "start";
        } else if (type === "combo") {
          input = document.createElement("select");
          (combo[key] || []).forEach(o => {
            const op = document.createElement("option");
            op.value = o; op.textContent = o;
            input.appendChild(op);
          });
          input.value = val;
        } else {
          input = document.createElement("input");
          input.type = type === "password" ? "password" : "text";
          input.value = val || "";
        }
        lab.appendChild(input);
        f.appendChild(lab);
        (els[sec] = els[sec] || {})[key] = input;
      }
      container.appendChild(f);
    }
    if (data.sources) {
      const f = document.createElement("fieldset");
      f.innerHTML = `<legend>[mcpsources] 外部 MCP 工具源（勾选 = 启用）</legend>`;
      els.__sources = [];
      data.sources.forEach(s => {
        const lab = document.createElement("label");
        lab.className = "fld";
        const cb = document.createElement("input");
        cb.type = "checkbox"; cb.checked = s.enabled;
        lab.innerHTML = `<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.name)} = ${esc(s.raw)}</span>`;
        lab.appendChild(cb);
        f.appendChild(lab);
        els.__sources.push({ name: s.name, raw: s.raw, cb });
      });
      container.appendChild(f);
    }
    return els;
  }
  function collectValues(els) {
    const values = {};
    for (const sec of Object.keys(els)) {
      if (sec === "__sources") continue;
      values[sec] = {};
      for (const key of Object.keys(els[sec])) {
        const el = els[sec][key];
        values[sec][key] = el.type === "checkbox" ? (el.checked ? "true" : "false") : el.value.trim();
      }
    }
    return values;
  }

  // ---- ini ----
  let iniEls = null, iniData = null;
  async function loadIni() {
    try {
      iniData = await api("/api/config/ini");
      if (!root.querySelector("#ini-raw-toggle").checked)
        iniEls = buildForm(root.querySelector("#ini-form"), iniData);
      root.querySelector("#ini-raw").value = iniData.raw || "";
    } catch (e) { toast(e.message, "err"); }
  }
  async function saveIni(restart) {
    try {
      const rawMode = root.querySelector("#ini-raw-toggle").checked;
      await api("/api/config/ini", "POST", rawMode
        ? { raw: root.querySelector("#ini-raw").value }
        : { values: collectValues(iniEls), sources: (iniEls.__sources || []).map(s => ({ name: s.name, raw: s.raw, enabled: s.cb.checked })) });
      toast("config.ini 已保存", "ok");
      if (restart) await restartBot();
    } catch (e) { toast(e.message, "err"); }
  }
  root.querySelector("#ini-reload").onclick = loadIni;
  root.querySelector("#ini-save").onclick = () => saveIni(false);
  root.querySelector("#ini-save-restart").onclick = () => saveIni(true);
  root.querySelector("#ini-raw-toggle").onchange = () => {
    const raw = root.querySelector("#ini-raw-toggle").checked;
    root.querySelector("#ini-form").style.display = raw ? "none" : "";
    root.querySelector("#ini-raw").style.display = raw ? "" : "none";
    if (raw && !iniData) loadIni();
  };

  // ---- yaml ----
  let yamlEls = null, yamlData = null;
  async function loadYaml() {
    try {
      yamlData = await api("/api/config/yaml");
      if (!root.querySelector("#yaml-raw-toggle").checked)
        yamlEls = buildForm(root.querySelector("#yaml-form"), yamlData);
      root.querySelector("#yaml-raw").value = yamlData.raw || "";
    } catch (e) { toast(e.message, "err"); }
  }
  async function saveYaml(restart) {
    try {
      const rawMode = root.querySelector("#yaml-raw-toggle").checked;
      await api("/api/config/yaml", "POST", rawMode
        ? { raw: root.querySelector("#yaml-raw").value }
        : { values: collectValues(yamlEls) });
      toast("config.yaml 已保存", "ok");
      if (restart) await restartBot();
    } catch (e) { toast(e.message, "err"); }
  }
  root.querySelector("#yaml-reload").onclick = loadYaml;
  root.querySelector("#yaml-save").onclick = () => saveYaml(false);
  root.querySelector("#yaml-save-restart").onclick = () => saveYaml(true);
  root.querySelector("#yaml-raw-toggle").onchange = () => {
    const raw = root.querySelector("#yaml-raw-toggle").checked;
    root.querySelector("#yaml-form").style.display = raw ? "none" : "";
    root.querySelector("#yaml-raw").style.display = raw ? "" : "none";
    if (raw && !yamlData) loadYaml();
  };

  async function restartBot() {
    try {
      const r = await api("/api/bot/restart", "POST", {});
      toast(r.result, r.result === "ok" ? "ok" : "err");
    } catch (e) { toast(e.message, "err"); }
  }

  loadIni();
  loadYaml();
}

export function unmountConfigPage() {}