"use strict";
/* 数据管理页：数据路径/大小/删除 + 恢复出厂 */
import { api, toast, fmtSize, esc } from "../app.js";

export function mountDataPage(root) {
  root.innerHTML = `
  <div class="card">
    <div class="card-title">数据路径</div>
    <table class="tbl">
      <thead><tr><th>说明</th><th>路径</th><th>大小</th><th></th></tr></thead>
      <tbody id="data-paths"></tbody>
    </table>
    <div class="muted" style="margin-top:8px">删除后不可恢复；平台数据删除后需重新扫码登录。</div>
  </div>
  <div class="card">
    <div class="card-title" style="color:var(--red)">危险操作</div>
    <div class="row">
      <button id="btn-reset" class="btn danger">恢复出厂设置</button>
      <span class="muted">清空全部用户数据（weilink / 对话 / OB 记忆 / 日志 / 运行锁），并把 API 密钥替换为占位符</span>
    </div>
    <div class="row" style="margin-top:10px">
      <button id="btn-reset-full" class="btn danger" style="border-style:dashed">彻底恢复出厂</button>
      <span class="muted">在恢复出厂基础上，再清空 data/ 目录（登录密码 / webconsole 设置 / 事件库等）并把 config.ini 重置为初始默认配置</span>
    </div>
  </div>`;

  async function loadData() {
    try {
      const d = await api("/api/data/paths");
      const tb = root.querySelector("#data-paths");
      tb.innerHTML = "";
      d.paths.forEach(p => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${esc(p.label)}</td><td class="mono" style="font-size:12px">${esc(p.path)}</td><td>${fmtSize(p.size)}</td>`;
        const td = document.createElement("td"); td.className = "actions";
        const b = document.createElement("button");
        b.className = "btn danger sm"; b.textContent = "删除";
        b.onclick = async () => {
          if (!confirm("确定删除？\n\n" + p.path)) return;
          try {
            const r = await api("/api/data/delete", "POST", { target: p.path });
            toast(r.result, "ok");
            loadData();
          } catch (e) { toast(e.message, "err"); }
        };
        td.appendChild(b);
        tr.appendChild(td);
        tb.appendChild(tr);
      });
      if (!d.paths.length) tb.innerHTML = `<tr><td colspan="4" class="empty">暂无数据</td></tr>`;
    } catch (e) { toast(e.message, "err"); }
  }

  root.querySelector("#btn-reset").onclick = async () => {
    if (!confirm("恢复出厂设置\n\n将清空全部用户数据并重置 API 密钥，此操作不可恢复！")) return;
    if (!confirm("最后确认：真的要恢复出厂设置吗？")) return;
    try {
      const r = await api("/api/data/factory_reset", "POST", {});
      toast(r.result, "ok");
      loadData();
      location.hash = "#/config";
    } catch (e) { toast(e.message, "err"); }
  };

  root.querySelector("#btn-reset-full").onclick = async () => {
    const msg = "彻底恢复出厂设置\n\n" +
      "1) 清空全部用户数据(weilink/对话/OB记忆/日志)\n" +
      "2) 清空 data/ 目录(登录密码、webconsole 设置、事件库等)\n" +
      "3) config.ini 重置为初始默认配置(需重新填 API 密钥、重新设登录密码)\n\n" +
      "此操作不可恢复！";
    if (!confirm(msg)) return;
    const code = prompt("请键入 RESET 以最终确认：");
    if (code !== "RESET") { toast("已取消", "err"); return; }
    if (!confirm("最后确认：真的要彻底恢复出厂吗？")) return;
    try {
      const r = await api("/api/data/factory_reset_full", "POST", {});
      toast(r.result, "ok");
      loadData();
      location.hash = "#/config";
    } catch (e) { toast(e.message, "err"); }
  };

  loadData();
}

export function unmountDataPage() {}