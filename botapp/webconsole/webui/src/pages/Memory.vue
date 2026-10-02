<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from "vue";
import { Button, Input, Tag, Tabs, Drawer, Empty } from "animal-island-ui-vue";
import { api, toast, esc } from "../lib/api.js";

let active = true;
const statusText = ref("检测中…");
const obStatus = ref(null);
const dataVisible = ref(false);
const view = ref("buckets");
const type = ref("");
const buckets = ref([]);
const letters = ref([]);
const listError = ref("");
const loading = ref(false);

const drawer = reactive({ visible: false, title: "", sub: "", bodyHtml: "" });

const obPassword = ref("");

const typeChips = computed(() => {
  if (view.value === "letters") return [["", "全部"], ["user", "对方"], ["ai", "你"]];
  return [["", "全部"], ["permanent", "永久"], ["dynamic", "动态"], ["letter", "信件"], ["plan", "计划"], ["feel", "情绪"]];
});

const tabItems = computed(() => [
  { key: "buckets", label: "记忆桶" },
  { key: "letters", label: "信件" },
]);

async function checkConn() {
  let st = null;
  try {
    st = await api("/api/ob/status");
    obStatus.value = st;
    statusText.value = st.ok ? (st.authenticated ? "已连接" : "未登录") : "未连接";
  } catch (e) {
    statusText.value = "出错";
    obStatus.value = { ok: false, error: e.message };
  }
  if (st && st.ok && st.authenticated) {
    dataVisible.value = true;
    if (!buckets.value.length && !letters.value.length) loadAll();
  } else {
    dataVisible.value = false;
  }
  return st;
}

async function obSetup() {
  try {
    const r = await api("/api/ob/setup", "POST", { password: obPassword.value });
    if (!r.ok) { toast(r.error || "设置失败", "err"); return; }
    toast("已设置，进入记忆页", "ok");
    obPassword.value = "";
    checkConn(); loadAll();
  } catch (e) { toast(e.message, "err"); }
}

async function obLogin() {
  try {
    const r = await api("/api/ob/login", "POST", { password: obPassword.value });
    if (!r.ok) { toast(r.error || "登录失败", "err"); return; }
    toast("已登录", "ok");
    obPassword.value = "";
    checkConn(); loadAll();
  } catch (e) { toast(e.message, "err"); }
}

async function loadAll() {
  if (!active) return;
  loading.value = true;
  listError.value = "";
  try {
    if (view.value === "letters") await loadLetters();
    else await loadBuckets();
  } finally {
    loading.value = false;
  }
}

async function loadBuckets() {
  try {
    const r = await api("/api/ob/buckets?type=" + encodeURIComponent(type.value));
    if (!r.ok) { listError.value = r.error; buckets.value = []; return; }
    buckets.value = r.buckets || [];
  } catch (e) { listError.value = e.message; buckets.value = []; }
}

async function loadLetters() {
  try {
    const r = await api("/api/ob/letters" + (type.value ? "?author=" + type.value : ""));
    if (!r.ok) { listError.value = r.error; letters.value = []; return; }
    letters.value = r.letters || [];
  } catch (e) { listError.value = e.message; letters.value = []; }
}

function switchView(v) {
  if (view.value === v) return;
  view.value = v;
  type.value = "";
  loadAll();
}

function setType(v) {
  type.value = v;
  loadAll();
}

function openBucket(b) {
  const btype = b.type || "dynamic";
  drawer.title = "记忆桶详情";
  drawer.sub = b.name || b.id;
  drawer.bodyHtml = `
    <div style="display:grid;grid-template-columns:120px 1fr;gap:6px 14px;font-size:13px">
      <div class="muted">ID</div><div class="mono">${esc(b.id)}</div>
      <div class="muted">类型</div><div>${esc(btype)}</div>
      <div class="muted">重要度 / 得分</div><div>${b.importance != null ? b.importance : "—"} / ${b.score != null ? b.score.toFixed(2) : "—"}</div>
      <div class="muted">创建 / 活跃</div><div>${esc(b.created || "—")} / ${esc(b.last_active || "—")}</div>
      <div class="muted">激活次数</div><div>${b.activation_count || 0}</div>
      <div class="muted">标签</div><div>${esc((b.tags || []).join("、") || "—")}</div>
      ${b.why_remembered ? `<div class="muted">为何记住</div><div>${esc(b.why_remembered)}</div>` : ""}
    </div>
    <div class="hr"></div>
    <div class="card-title">内容</div>
    <div style="white-space:pre-wrap;font-size:13px">${esc(b.content_preview || "(无内容)")}</div>
    <div class="muted" style="margin-top:10px">完整内容请在 OmbreBrain 后台（18001）查看</div>`;
  drawer.visible = true;
}

function openLetter(l) {
  drawer.title = "信件详情";
  drawer.sub = l.title || "(无标题)";
  drawer.bodyHtml = `
    <div style="display:grid;grid-template-columns:120px 1fr;gap:6px 14px;font-size:13px">
      <div class="muted">作者</div><div>${esc(l.author || "?")}</div>
      <div class="muted">日期</div><div>${esc(l.date || "—")}</div>
      <div class="muted">收件人</div><div>${esc(l.user_name || "—")}</div>
    </div>
    <div class="hr"></div>
    <div style="white-space:pre-wrap;font-size:13px;line-height:1.7">${esc(l.content || "")}</div>`;
  drawer.visible = true;
}

function bucketTags(b) {
  const btype = b.type || "dynamic";
  return [
    { text: btype, color: "default" },
    b.pinned ? { text: "已置顶", color: "yellow" } : null,
    b.resolved ? { text: "已解决", color: "default" } : null,
    { text: "重要度 " + (b.importance != null ? b.importance : "—"), color: "default" },
    { text: "得分 " + (b.score != null ? b.score.toFixed(2) : "—"), color: "default" },
    { text: "触发 " + (b.activation_count || 0) + " 次", color: "default" },
  ].filter(Boolean);
}

onMounted(() => { active = true; checkConn(); });
onUnmounted(() => { active = false; });
</script>

<template>
  <div class="card">
    <div class="card-title">OmbreBrain 连接 <span class="hint">{{ statusText }}</span></div>
    <Empty v-if="obStatus && !obStatus.ok"
           title="OmbreBrain 未连接"
           description="OmbreBrain 后台（18001）未启动。机器人启动后会自动拉起，或手动启动后刷新本页。" />
    <div v-else-if="obStatus && obStatus.setup_needed" class="row">
      <span>后台尚未设置登录密码（首次使用），在此设置：</span>
      <Input v-model="obPassword" type="password" placeholder="新密码（至少 6 位）" style="width:220px" />
      <Button type="primary" @click="obSetup">设置并进入</Button>
    </div>
    <div v-else-if="obStatus && obStatus.ok && !obStatus.authenticated" class="row">
      <span>已设置密码，输入后台密码登录以查看记忆：</span>
      <Input v-model="obPassword" type="password" placeholder="OmbreBrain 后台密码" style="width:220px" />
      <Button type="primary" @click="obLogin">登录</Button>
    </div>
  </div>

  <div v-if="dataVisible" class="card">
    <div class="card-title" style="flex-wrap:wrap;gap:10px">
      <span>记忆与信件</span>
      <Tabs :items="tabItems" :active-key="view" @update:active-key="switchView" />
      <span class="chip-row">
        <span v-for="[v, label] in typeChips" :key="v">
          <Tag :color="type === v ? 'mint' : 'default'" @click="setType(v)" style="cursor:pointer">{{ label }}</Tag>
        </span>
      </span>
    </div>

    <Empty v-if="listError" :title="listError" />
    <template v-else-if="view === 'buckets'">
      <Empty v-if="!buckets.length" :title="'暂无记忆桶' + (type ? '（此类型）' : '')" />
      <div v-for="b in buckets" :key="b.id" class="bucket-item" @click="openBucket(b)">
        <div class="meta">
          <div class="bname">{{ b.name || b.id }}</div>
          <div class="bdesc">{{ b.content_preview || "(无内容)" }}</div>
          <div class="btags">
            <Tag v-for="(t, i) in bucketTags(b)" :key="i" :color="t.color">{{ t.text }}</Tag>
          </div>
          <div class="muted" style="margin-top:4px">创建 {{ b.created || "—" }} · 活跃 {{ b.last_active || "—" }}</div>
        </div>
      </div>
    </template>

    <template v-else>
      <Empty v-if="!letters.length" :title="'暂无信件' + (type ? '（此作者）' : '')" />
      <div v-for="(l, i) in letters" :key="i" class="letter-item" @click="openLetter(l)">
        <div class="ltitle">{{ l.title || "(无标题)" }}
          <Tag :color="l.author === 'user' ? 'blue' : 'yellow'">{{ l.author || "?" }}</Tag>
        </div>
        <div class="muted">{{ l.date || "" }} · {{ l.user_name || "—" }}</div>
        <div class="lbody">{{ l.content || "" }}</div>
      </div>
    </template>
  </div>

  <Drawer v-model:open="drawer.visible" :title="drawer.title" placement="right" width="460px">
    <div class="muted" style="margin-bottom:10px">{{ drawer.sub }}</div>
    <div v-html="drawer.bodyHtml"></div>
  </Drawer>
</template>
