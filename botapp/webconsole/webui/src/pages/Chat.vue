<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue";
import { Button, Input, Checkbox, Select } from "animal-island-ui-vue";
import { api, toast } from "../lib/api.js";
import { app } from "../lib/state.js";
import { subscribeLogs } from "../lib/logs.js";

const TAG_RE = /^\[(\d{2}:\d{2}:\d{2})\] \[([^\]]+)\] (.*)$/;
const USERS_KEY = "wc_chat_users";

const EVENT_STYLE = {
  Receive: { cls: "ev-user", label: "用户" },
  Reply: { cls: "ev-bot", label: "AI" },
  Controller: { cls: "ev-ctrl", label: "控制" },
  Agent: { cls: "ev-agent", label: "LLM" },
  Tool: { cls: "ev-tool", label: "工具" },
  MCP: { cls: "ev-mcp", label: "MCP" },
  LLM: { cls: "ev-llm", label: "耗时" },
  Token: { cls: "ev-token", label: "Token" },
  Output: { cls: "ev-output", label: "输出" },
  Warning: { cls: "ev-warn", label: "警告" },
  Error: { cls: "ev-err", label: "错误" },
  Info: { cls: "ev-info", label: "信息" },
};

const savedUsers = JSON.parse(localStorage.getItem(USERS_KEY) || "[]");
const allUsers = ref([...savedUsers]);
const userId = ref(savedUsers.length ? savedUsers[savedUsers.length - 1] : "");
const userOptions = computed(() => allUsers.value.map(u => ({ label: u, value: u })));
const onlyMe = ref(true);
const showAll = ref(true);
const inputText = ref("");
const events = ref([]);
const histUser = ref("");
const histMsgs = ref([]);
const histState = ref("empty"); // empty | loading | none | done

let unsub = null;
const streamEl = ref(null);

function parseLine(line) {
  const m = TAG_RE.exec(line);
  if (!m) return null;
  return { ts: m[1], tag: m[2], text: m[3] };
}

function pickUser(v) {
  if (!v) return;
  userId.value = v;
  renderHistory();
}

function pickHistUser(v) {
  if (!v) return;
  histUser.value = v;
  loadHistory();
}

const userSelectValue = computed({
  get: () => userId.value,
  set: (v) => pickUser(v),
});

const histSelectValue = computed({
  get: () => histUser.value,
  set: (v) => pickHistUser(v),
});

function isMatchUser(p) {
  if (!userId.value.trim()) return true;
  const uid = userId.value.trim();
  if (["Receive", "Reply", "Controller"].includes(p.tag)) {
    const idx = p.text.indexOf(": ");
    if (idx > 0) return p.text.slice(0, idx).trim() === uid;
  }
  return true;
}

function makeEvent(p) {
  const style = EVENT_STYLE[p.tag] || { cls: "ev-other", label: p.tag };
  let content = p.text;
  let user = "";
  if (["Receive", "Reply", "Controller"].includes(p.tag)) {
    const idx = content.indexOf(": ");
    if (idx > 0) { user = content.slice(0, idx); content = content.slice(idx + 2); }
  }
  if (p.tag === "Tool" && content.length > 300) content = content.slice(0, 300) + "...";
  const collapsible = p.tag === "MCP" && content.startsWith("思考过程");
  return {
    ts: p.ts, tag: p.tag, cls: style.cls, label: style.label,
    user, content, collapsible, expanded: false,
  };
}

function isMain(tag) {
  return ["Receive", "Reply", "Controller"].includes(tag);
}

function visible(ev) {
  if (onlyMe.value && !isMatchUser({ tag: ev.tag, text: ev.user ? ev.user + ": " + ev.content : ev.content })) return false;
  if (!showAll.value && !isMain(ev.tag)) return false;
  return true;
}

function appendLine(line, scroll) {
  if (!app.bot || !app.bot.running) return;
  const p = parseLine(line);
  if (!p) return;
  if (onlyMe.value && !isMatchUser(p)) return;
  if (!showAll.value && !isMain(p.tag)) return;
  events.value.push(makeEvent(p));
  if (events.value.length > 800) events.value.splice(0, events.value.length - 800);
  if (scroll !== false) {
    requestAnimationFrame(() => {
      if (streamEl.value) streamEl.value.scrollTop = streamEl.value.scrollHeight;
    });
  }
}

function renderHistory() {
  events.value = [];
  app.logs.forEach(line => {
    const p = parseLine(line);
    if (!p) return;
    if (onlyMe.value && !isMatchUser(p)) return;
    events.value.push(makeEvent(p));
  });
  requestAnimationFrame(() => {
    if (streamEl.value) streamEl.value.scrollTop = streamEl.value.scrollHeight;
  });
}

async function send() {
  const uid = userId.value.trim();
  const text = inputText.value.trim();
  if (!uid) { toast("填写用户 ID", "err"); return; }
  if (!text) return;
  inputText.value = "";
  try {
    const r = await api("/api/test/message", "POST", { user_id: uid, text });
    if (!r.ok) { toast(r.error || "失败", "err"); return; }
    toast("已注入", "ok");
    const list = JSON.parse(localStorage.getItem(USERS_KEY) || "[]");
    if (!list.includes(uid)) {
      list.push(uid);
      localStorage.setItem(USERS_KEY, JSON.stringify(list.slice(-8)));
      if (!allUsers.value.includes(uid)) allUsers.value.push(uid);
    }
  } catch (e) { toast(e.message, "err"); }
}

async function loadHistory() {
  const uid = histUser.value.trim();
  if (!uid) return;
  histState.value = "loading";
  histMsgs.value = [];
  try {
    const d = await api("/api/history?user=" + encodeURIComponent(uid));
    const msgs = (d.messages || []).filter(m => m.role !== "system");
    if (!msgs.length) { histState.value = "none"; return; }
    histMsgs.value = msgs.map(m => {
      const role = m.role === "assistant" ? "bot" : "me";
      let text = String(m.content || "");
      text = text.replace(/<SEP>/g, "\n\n").replace(/\s+systime:\d{4}-\d{2}-\d{2} \d{2}:\d{2}/g, "");
      return { role, text };
    });
    histState.value = "done";
  } catch (e) {
    histState.value = "error";
    histMsgs.value = [{ role: "err", text: e.message }];
  }
}

onMounted(() => {
  api("/api/users").then(d => {
    (d.users || []).forEach(u => { if (!allUsers.value.includes(u)) allUsers.value.push(u); });
  }).catch(() => {});
  unsub = subscribeLogs(line => appendLine(line, true));
  renderHistory();
});
onUnmounted(() => { if (unsub) unsub(); });
</script>

<template>
  <div class="card" style="padding:12px 16px">
    <div class="row" style="margin:0;gap:12px">
      <span class="muted" style="font-size:12.5px">用户 ID</span>
      <Select v-model="userSelectValue" :options="userOptions" placeholder="选择用户" style="width:220px" />
      <Input v-model="userId" placeholder="或手动输入 wxid_xxxx@im.wechat" allow-clear style="width:260px" />
      <Checkbox v-model:checked="onlyMe" @update:checked="renderHistory">仅此用户</Checkbox>
      <Checkbox v-model:checked="showAll">显示全部事件</Checkbox>
    </div>
  </div>
  <div class="chat-shell">
    <div ref="streamEl" class="chat-stream">
      <div v-for="(ev, i) in events" :key="i" class="ev-row" :class="[ev.cls, { 'ev-collapsible': ev.collapsible, 'ev-expanded': ev.expanded }]">
        <span class="ev-ts">{{ ev.ts }}</span>
        <span class="ev-tag">{{ ev.label }}</span>
        <span v-if="ev.user" class="ev-user-id">{{ ev.user }}</span>
        <template v-if="ev.collapsible">
          <span class="ev-toggle" @click="ev.expanded = !ev.expanded">{{ ev.expanded ? '收起' : '展开' }}</span>
          <pre class="ev-pre">{{ ev.content }}</pre>
        </template>
        <span v-else class="ev-text">{{ ev.content }}</span>
      </div>
    </div>
    <div class="chat-input">
      <Input v-model="inputText" placeholder="发送消息给机器人（回车）" @keydown.enter="send" />
      <Button type="primary" @click="send">发送</Button>
    </div>
  </div>
  <div class="card" style="margin-top:14px;padding:12px 16px">
    <div class="card-title" style="margin-bottom:8px">历史记录</div>
    <div class="row" style="margin:0">
      <Select v-model="histSelectValue" :options="userOptions" placeholder="选择用户" style="width:220px" />
      <Input v-model="histUser" placeholder="或手动输入用户 ID" style="width:260px" @keydown.enter="loadHistory" />
      <Button @click="loadHistory">加载</Button>
    </div>
    <div style="max-height:300px;overflow:auto;margin-top:8px">
      <div v-if="histState === 'empty'" class="empty">选择用户后加载</div>
      <div v-else-if="histState === 'loading'" class="empty">加载中…</div>
      <div v-else-if="histState === 'none'" class="empty">无记录</div>
      <div v-else-if="histState === 'error'" class="empty">{{ histMsgs[0] ? histMsgs[0].text : '加载失败' }}</div>
      <div v-else class="msg" :class="m.role === 'bot' ? 'bot' : 'me'" v-for="(m, i) in histMsgs" :key="i">
        <span class="mt">{{ m.role === 'bot' ? 'AI' : '用户' }}</span>{{ m.text }}
      </div>
    </div>
  </div>
</template>
