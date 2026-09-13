<script setup>
import { reactive, ref, onMounted, onUnmounted } from "vue";
import { api } from "../lib/api.js";

let es = null;
const waitVisible = ref(true);
const waitText = ref("等待 LLM 请求…");

const liveVisible = ref(false);
const history = ref([]); // 已完成的卡片（HTML 字符串）
const cur = reactive({
  time: "", user: "", status: "思考中…",
  thinkVisible: false, think: "",
  replyVisible: false, reply: "",
  toolsVisible: false, tools: [],
  contextVisible: false, contextHtml: "",
});

function resetLive() {
  cur.time = ""; cur.user = ""; cur.status = "思考中…";
  cur.thinkVisible = false; cur.think = "";
  cur.replyVisible = false; cur.reply = "";
  cur.toolsVisible = false; cur.tools = [];
  cur.contextVisible = false; cur.contextHtml = "";
}

function onBegin(d, isSync) {
  resetLive();
  waitVisible.value = false;
  liveVisible.value = true;
  cur.time = d.time || "";
  cur.user = d.user_id || "";
  if (d.context_html) { cur.contextVisible = true; cur.contextHtml = d.context_html; }
  if (!isSync) return;
  const s = d.live;
  if (!s) return;
  (s.thinking || []).forEach(t => { cur.thinkVisible = true; cur.think += t; });
  (s.reply || []).forEach(r => { cur.replyVisible = true; cur.reply += r; });
  (s.tool_calls || []).forEach(tc => {
    if (!tc.name) return;
    cur.toolsVisible = true;
    cur.tools.push({ name: tc.name, args: tc.args || "" });
  });
}

function snapshotCard() {
  const chips = cur.tools.map(t => `<span class="dbg-chip">${escapeHtml(t.name)}</span>`).join("");
  let body = "";
  if (cur.thinkVisible) body += `<div class="dbg-sec"><div class="dbg-lbl">思考内容</div><pre class="dbg-think-text">${escapeHtml(cur.think)}</pre></div>`;
  if (cur.replyVisible) body += `<div class="dbg-sec"><div class="dbg-lbl">最终回复</div><pre class="dbg-reply-text">${escapeHtml(cur.reply)}</pre></div>`;
  if (cur.toolsVisible) {
    body += `<div class="dbg-sec"><div class="dbg-lbl">工具调用</div>`;
    cur.tools.forEach(t => { body += `<div class="dbg-tool-item"><b>${escapeHtml(t.name)}</b><pre>${escapeHtml(t.args)}</pre></div>`; });
    body += `</div>`;
  }
  if (cur.contextVisible) {
    body += `<details><summary>系统提示 · 工具定义 · 对话消息</summary><div class="dbg-context-body">${cur.contextHtml}</div></details>`;
  }
  return `<div class="card"><div class="dbg-header"><span><b>${escapeHtml(cur.time)}</b> <b>${escapeHtml(cur.user)}</b></span><span>${chips}</span><span class="dbg-status">完成</span></div><div class="dbg-body">${body}</div></div>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function connectSSE() {
  if (es) { es.close(); es = null; }
  waitVisible.value = true; waitText.value = "等待 LLM 请求…";
  es = new EventSource("/api/debug/events");
  es.onmessage = (ev) => {
    let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
    switch (d.type) {
      case "begin": onBegin(d, false); break;
      case "sync": onBegin(d, true); break;
      case "thinking": cur.thinkVisible = true; cur.think += d.text || ""; break;
      case "reply": cur.replyVisible = true; cur.reply += d.text || ""; break;
      case "tool_name":
        cur.toolsVisible = true;
        cur.tools.push({ name: d.text, args: "" });
        break;
      case "tool_args":
        if (cur.tools.length) cur.tools[cur.tools.length - 1].args += d.text || "";
        break;
      case "end":
        cur.status = "完成";
        history.value.unshift(snapshotCard());
        resetLive();
        liveVisible.value = false;
        waitVisible.value = true; waitText.value = "等待 LLM 请求…";
        break;
    }
  };
  es.onerror = () => {
    waitText.value = "连接中断，重连中…";
  };
}

onMounted(() => {
  connectSSE();
  api("/api/debug/snapshot").then(d => {
    if (!d.bot_running) { waitText.value = "机器人未运行（启动机器人后自动连接）"; }
    else if (d.has_live) { waitText.value = "有进行中的 LLM 请求，正在同步…"; }
  }).catch(() => {});
});
onUnmounted(() => { if (es) { es.close(); es = null; } });
</script>

<template>
  <div class="debug-layout">
    <div class="debug-main">
      <div v-if="liveVisible" class="card" id="dbg-live-card">
        <div class="dbg-header">
          <span><b>{{ cur.time }}</b> <b>{{ cur.user }}</b></span>
          <span><span v-for="(t, i) in cur.tools" :key="i" class="dbg-chip">{{ t.name }}</span></span>
          <span class="dbg-status">{{ cur.status }}</span>
        </div>
        <div class="dbg-body">
          <div v-if="cur.thinkVisible" class="dbg-sec">
            <div class="dbg-lbl">思考内容</div>
            <pre class="dbg-think-text">{{ cur.think }}</pre>
          </div>
          <div v-if="cur.replyVisible" class="dbg-sec">
            <div class="dbg-lbl">最终回复</div>
            <pre class="dbg-reply-text">{{ cur.reply }}</pre>
          </div>
          <div v-if="cur.toolsVisible" class="dbg-sec">
            <div class="dbg-lbl">工具调用</div>
            <div v-for="(t, i) in cur.tools" :key="i" class="dbg-tool-item"><b>{{ t.name }}</b><pre>{{ t.args }}</pre></div>
          </div>
          <details v-if="cur.contextVisible">
            <summary>系统提示 · 工具定义 · 对话消息</summary>
            <div class="dbg-context-body" v-html="cur.contextHtml"></div>
          </details>
        </div>
      </div>

      <div v-if="waitVisible" class="card dbg-wait">
        <span>{{ waitText }}</span>
      </div>

      <div id="dbg-history">
        <div v-for="(h, i) in history" :key="i" v-html="h"></div>
      </div>
    </div>
  </div>
</template>
