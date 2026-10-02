<script setup>
import { ref, onMounted, onUnmounted } from "vue";
import { Empty } from "animal-island-ui-vue";
import { api, fmtSize } from "../lib/api.js";

let statsTimer = null;
const cards = ref([]);
const eventsDaily = ref([]);
const convDaily = ref([]);
const actions = ref([]);
const tags = ref([]);
const buckets = ref([]);
const bucketError = ref("");

const maxDaily = (data) => Math.max(1, ...data.map(d => d.count));
const maxItems = (items) => Math.max(1, ...items.map(i => i.count));

async function refresh() {
  try {
    const st = await api("/api/stats");
    const e = st.events, c = st.conversation, l = st.logs, t = st.tokens || {};
    const hitPart = t.cache_hit ? ` · 缓存命中 ${t.cache_hit.toLocaleString()}` : "";
    cards.value = [
      { lbl: "LLM 调用", num: t.calls || 0, sub: `输入 ${(t.prompt || 0).toLocaleString()} · 输出 ${(t.completion || 0).toLocaleString()}` },
      { lbl: "LLM Token 总量", num: (t.total || 0).toLocaleString(), sub: `输入 ${(t.prompt || 0).toLocaleString()} + 输出 ${(t.completion || 0).toLocaleString()}${hitPart}` },
      { lbl: "提醒事件", num: e.total, sub: `待提醒 ${e.upcoming} · ${e.users} 个用户` },
      { lbl: "对话用户", num: c.users, sub: `${c.messages} 条消息 · ${fmtSize(c.total_bytes)}` },
      { lbl: "对话存档文件", num: c.files, sub: c.users ? `${c.users} 个用户` : "未启用对话存档" },
      { lbl: "近 1 小时日志", num: l.last_hour, sub: `${Object.keys(l.by_tag || {}).length} 类活动` },
    ];
    eventsDaily.value = e.daily || [];
    convDaily.value = c.daily || [];
    actions.value = e.by_action || [];
    tags.value = Object.entries(l.by_tag || {}).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count).slice(0, 10);
    loadBuckets();
  } catch (err) {
    cards.value = [];
    bucketError.value = err.message;
  }
}

async function loadBuckets() {
  try {
    const r = await api("/api/ob/buckets");
    if (!r.ok) { bucketError.value = r.error; buckets.value = []; return; }
    buckets.value = r.buckets || [];
    bucketError.value = "";
  } catch (err) { bucketError.value = err.message; buckets.value = []; }
}

function bucketDist() {
  const dist = {};
  buckets.value.forEach(b => { const t = b.type || "dynamic"; dist[t] = (dist[t] || 0) + 1; });
  return Object.entries(dist).map(([name, count]) => ({ name, count }));
}

onMounted(() => { refresh(); statsTimer = setInterval(refresh, 30000); });
onUnmounted(() => { if (statsTimer) clearInterval(statsTimer); });
</script>

<template>
  <div class="grid cols-4">
    <div v-for="(c, i) in cards" :key="i" class="stat-card">
      <div class="lbl">{{ c.lbl }}</div>
      <div class="num">{{ c.num }}</div>
      <div class="sub">{{ c.sub }}</div>
    </div>
    <Empty v-if="!cards.length" title="统计加载失败" />
  </div>
  <div class="grid cols-2">
    <div class="card">
      <div class="card-title">提醒事件趋势 <span class="hint">最近 14 天新增</span></div>
      <div class="daily-chart">
        <div v-for="(d, i) in eventsDaily" :key="i" class="dc-col">
          <span class="muted" style="font-size:10px">{{ d.count || "" }}</span>
          <div class="dc-bar" :style="{ height: Math.max(2, (d.count / maxDaily(eventsDaily)) * 90) + '%' }"></div>
          <div class="dc-date">{{ d.date }}</div>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">对话活跃 <span class="hint">最近 14 天有更新的用户数</span></div>
      <div class="daily-chart">
        <div v-for="(d, i) in convDaily" :key="i" class="dc-col">
          <span class="muted" style="font-size:10px">{{ d.count || "" }}</span>
          <div class="dc-bar" :style="{ height: Math.max(2, (d.count / maxDaily(convDaily)) * 90) + '%' }"></div>
          <div class="dc-date">{{ d.date }}</div>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">提醒事项分类</div>
      <Empty v-if="!actions.length" title="暂无数据" />
      <div v-for="(it, i) in actions" :key="i" class="bar-row">
        <div class="bl" :title="it.name">{{ it.name }}</div>
        <div class="bar-wrap"><div class="bar" :style="{ width: (it.count / maxItems(actions)) * 100 + '%' }"></div></div>
        <div class="bv">{{ it.count }}</div>
      </div>
    </div>
    <div class="card">
      <div class="card-title">日志活动 <span class="hint">缓冲内最近约 4000 行</span></div>
      <Empty v-if="!tags.length" title="暂无数据" />
      <div v-for="(it, i) in tags" :key="i" class="bar-row">
        <div class="bl" :title="it.name">{{ it.name }}</div>
        <div class="bar-wrap"><div class="bar" :style="{ width: (it.count / maxItems(tags)) * 100 + '%' }"></div></div>
        <div class="bv">{{ it.count }}</div>
      </div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">记忆桶分布 <span class="hint">OmbreBrain 后台</span></div>
    <Empty v-if="bucketError" :title="bucketError" />
    <Empty v-else-if="!buckets.length" title="暂无记忆桶" />
    <template v-else>
      <div class="bar-row"><div class="bl">总数</div><div class="bar-wrap"><div class="bar" style="width:100%"></div></div><div class="bv">{{ buckets.length }}</div></div>
      <div v-for="(it, i) in bucketDist()" :key="i" class="bar-row">
        <div class="bl">{{ it.name }}</div>
        <div class="bar-wrap"><div class="bar" :style="{ width: (it.count / maxItems(bucketDist())) * 100 + '%' }"></div></div>
        <div class="bv">{{ it.count }}</div>
      </div>
    </template>
  </div>
</template>
