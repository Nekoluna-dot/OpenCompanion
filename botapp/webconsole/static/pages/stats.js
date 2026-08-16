"use strict";
/* 统计页：提醒事件 / 对话存档 / 日志活动 / OB 记忆桶 */
import { api, esc, fmtSize } from "../app.js";

let statsTimer = null;

export function mountStatsPage(root) {
  root.innerHTML = `
  <div class="grid cols-4" id="st-cards"></div>
  <div class="grid cols-2">
    <div class="card">
      <div class="card-title">提醒事件趋势 <span class="hint">最近 14 天新增</span></div>
      <div class="daily-chart" id="st-events-daily"></div>
    </div>
    <div class="card">
      <div class="card-title">对话活跃 <span class="hint">最近 14 天有更新的用户数</span></div>
      <div class="daily-chart" id="st-conv-daily"></div>
    </div>
    <div class="card">
      <div class="card-title">提醒事项分类</div>
      <div id="st-actions"></div>
    </div>
    <div class="card">
      <div class="card-title">日志活动 <span class="hint">缓冲内最近约 4000 行</span></div>
      <div id="st-tags"></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">记忆桶分布 <span class="hint">OmbreBrain 后台</span></div>
    <div id="st-buckets"><div class="empty">加载中…</div></div>
  </div>`;

  const dailyChart = (el, data, suffix) => {
    const max = Math.max(1, ...data.map(d => d.count));
    el.innerHTML = "";
    data.forEach(d => {
      const col = document.createElement("div");
      col.className = "dc-col";
      col.innerHTML = `<span class="muted" style="font-size:10px">${d.count || ""}</span>
        <div class="dc-bar" style="height:${Math.max(2, (d.count / max) * 90)}%"></div>
        <div class="dc-date">${d.date}</div>`;
      el.appendChild(col);
    });
  };
  const barList = (el, items) => {
    if (!items || !items.length) { el.innerHTML = `<div class="empty">暂无数据</div>`; return; }
    const max = Math.max(1, ...items.map(i => i.count));
    el.innerHTML = "";
    items.forEach(i => {
      const row = document.createElement("div");
      row.className = "bar-row";
      row.innerHTML = `<div class="bl" title="${esc(i.name)}">${esc(i.name)}</div>
        <div class="bar-wrap"><div class="bar" style="width:${(i.count / max) * 100}%"></div></div>
        <div class="bv">${i.count}</div>`;
      el.appendChild(row);
    });
  };

  async function refresh() {
    try {
      const st = await api("/api/stats");
      const e = st.events, c = st.conversation, l = st.logs, t = st.tokens || {};
      const hitPart = t.cache_hit ? ` · 缓存命中 ${t.cache_hit.toLocaleString()}` : "";
      const cards = [
        ["LLM 调用", t.calls || 0, `输入 ${(t.prompt || 0).toLocaleString()} · 输出 ${(t.completion || 0).toLocaleString()}`],
        ["LLM Token 总量", (t.total || 0).toLocaleString(), `输入 ${(t.prompt || 0).toLocaleString()} + 输出 ${(t.completion || 0).toLocaleString()}${hitPart}`],
        ["提醒事件", e.total, `待提醒 ${e.upcoming} · ${e.users} 个用户`],
        ["对话用户", c.users, `${c.messages} 条消息 · ${fmtSize(c.total_bytes)}`],
        ["对话存档文件", c.files, c.users ? `${c.users} 个用户` : "未启用对话存档"],
        ["近 1 小时日志", l.last_hour, `${Object.keys(l.by_tag || {}).length} 类活动`],
      ];
      root.querySelector("#st-cards").innerHTML = cards.map(([lbl, num, sub]) =>
        `<div class="stat-card"><div class="lbl">${lbl}</div><div class="num">${num}</div><div class="sub">${sub}</div></div>`
      ).join("");
      dailyChart(root.querySelector("#st-events-daily"), e.daily || []);
      dailyChart(root.querySelector("#st-conv-daily"), c.daily || []);
      barList(root.querySelector("#st-actions"), e.by_action || []);
      const tags = Object.entries(l.by_tag || {}).map(([name, count]) => ({ name, count }));
      barList(root.querySelector("#st-tags"), tags.sort((a, b) => b.count - a.count).slice(0, 10));
      loadBuckets();
    } catch (err) {
      root.querySelector("#st-cards").innerHTML = `<div class="empty">统计加载失败：${esc(err.message)}</div>`;
    }
  }

  async function loadBuckets() {
    const el = root.querySelector("#st-buckets");
    try {
      const r = await api("/api/ob/buckets");
      if (!r.ok) { el.innerHTML = `<div class="empty">${esc(r.error)}</div>`; return; }
      const buckets = r.buckets || [];
      const dist = {};
      buckets.forEach(b => { const t = b.type || "dynamic"; dist[t] = (dist[t] || 0) + 1; });
      if (!buckets.length) { el.innerHTML = `<div class="empty">暂无记忆桶</div>`; return; }
      el.innerHTML = `<div class="bar-row"><div class="bl">总数</div><div class="bar-wrap"><div class="bar" style="width:100%"></div></div><div class="bv">${buckets.length}</div></div>`;
      const items = Object.entries(dist).map(([name, count]) => ({ name, count }));
      const max = Math.max(1, ...items.map(i => i.count));
      items.forEach(({ name, count }) => {
        const row = document.createElement("div");
        row.className = "bar-row";
        row.innerHTML = `<div class="bl">${esc(name)}</div>
          <div class="bar-wrap"><div class="bar" style="width:${(count / max) * 100}%"></div></div>
          <div class="bv">${count}</div>`;
        el.appendChild(row);
      });
    } catch (err) {
      el.innerHTML = `<div class="empty">${esc(err.message)}</div>`;
    }
  }

  refresh();
  statsTimer = setInterval(refresh, 30000);
}

export function unmountStatsPage() {
  if (statsTimer) { clearInterval(statsTimer); statsTimer = null; }
}