<script setup>
import { ref, reactive, onMounted } from "vue";
import { Button, Input, Textarea, Select, Checkbox, Tag, Empty } from "animal-island-ui-vue";
import { api, toast, esc } from "../lib/api.js";

const FEEDBACK_ENDPOINT = "https://columbina.duckdns.org:800/feedback";
const TID_KEY = "oc_fb_tickets";

const STATUS_LABEL = { open: "处理中", replied: "已回复", resolved: "已解决", closed: "已关闭" };
const TYPE_LABEL = { bug: "BUG 上报", suggestion: "功能建议", feedback: "意见反馈" };

const TYPE_OPTIONS = [
  { label: "BUG 上报", value: "bug" },
  { label: "功能建议", value: "suggestion" },
  { label: "意见反馈", value: "feedback" },
];

const form = reactive({ type: "bug", title: "", content: "", contact: "", consent: false });
const fileInput = ref(null);
const files = ref([]);          // [{file, name, size, dataUrl}]
const submitting = ref(false);
const statusHtml = ref("");
const tickets = ref([]);        // [{tid, data|null, error|null, open}]
const loadingTickets = ref(false);
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
  if (!list.includes(tid)) { list.unshift(tid); saveTids(list.slice(0, 50)); }
}
function removeTid(tid) {
  saveTids(loadTids().filter(t => t !== tid));
  renderMine();
}

function fmtTime(s) {
  const t = String(s || "").replace("T", " ").replace(/\.\d+/, "");
  return t.length > 19 ? t.slice(0, 19) : t;
}

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
    } catch (e) {}
  } catch (e) { metaData = {}; }
}

function onFilesChange(e) {
  const list = Array.from(e.target.files || []).slice(0, 3);
  files.value = list.map(f => ({ file: f, name: f.name, size: f.size, dataUrl: "" }));
  files.value.forEach(item => {
    const reader = new FileReader();
    reader.onload = () => { item.dataUrl = reader.result; };
    reader.readAsDataURL(item.file);
  });
}

function removeFile(idx) { files.value.splice(idx, 1); }

async function renderMine() {
  const tids = loadTids();
  if (!tids.length) { tickets.value = []; return; }
  loadingTickets.value = true;
  const results = await Promise.all(tids.map(async tid => {
    try {
      const resp = await fetch(FEEDBACK_ENDPOINT + "/status.php?tid=" + encodeURIComponent(tid));
      const data = await resp.json().catch(() => null);
      if (!resp.ok || !data || !data.ok) throw new Error((data && data.error) || ("HTTP " + resp.status));
      const t = Object.assign({}, data.ticket || {}, { replies: data.replies || [], attachments: data.attachments || [] });
      return { tid, data: t, error: null, open: false };
    } catch (e) {
      return { tid, data: null, error: (e && e.message) || "查询失败", open: false };
    }
  }));
  tickets.value = results;
  loadingTickets.value = false;
}

function attUrl(tid, path) {
  return FEEDBACK_ENDPOINT + "/file.php?tid=" + encodeURIComponent(tid) + "&f=" + encodeURIComponent(path);
}

function openAtt(tid, path) {
  window.open(attUrl(tid, path), "_blank");
}

async function submit() {
  if (!form.consent) { toast("必选项：请先勾选同意上传系统信息", "err"); return; }
  if (!form.title.trim() && !form.content.trim()) { toast("请填写标题或内容", "err"); return; }
  submitting.value = true;
  statusHtml.value = "提交中…";
  try {
    const csrfResp = await fetch(FEEDBACK_ENDPOINT + "/csrf.php");
    let token = "";
    try { const cd = await csrfResp.json(); token = cd.token || ""; } catch (e) {}
    if (!token) throw new Error("无法获取安全令牌：请检查反馈后端地址是否可访问");

    const fd = new FormData();
    fd.append("csrf", token);
    fd.append("type", form.type);
    fd.append("title", form.title.trim());
    fd.append("content", form.content.trim());
    fd.append("contact", form.contact.trim());
    fd.append("meta", JSON.stringify(metaData));
    files.value.forEach(f => fd.append("screenshots[]", f.file, f.name));

    const resp = await fetch(FEEDBACK_ENDPOINT + "/submit.php", { method: "POST", body: fd });
    const data = await resp.json().catch(() => ({}));
    if (!(resp.ok && data.ok)) throw new Error(data.error || ("HTTP " + resp.status));
    const tid = data.tid || "";
    if (tid) addTid(tid);
    toast("反馈已提交", "ok");
    if (tid) {
      statusHtml.value = '已提交成功，您的反馈单号：<b class="fb-tid">' + esc(tid) + '</b> <button class="fb-copy-btn" id="fb-copy" type="button">复制</button>';
      requestAnimationFrame(() => {
        const cp = document.getElementById("fb-copy");
        if (cp) cp.onclick = async () => {
          try { await navigator.clipboard.writeText(tid); toast("单号已复制", "ok"); }
          catch (e) { toast(tid, "err"); }
        };
      });
    } else { statusHtml.value = ""; }
    if (data.warnings && data.warnings.length) {
      statusHtml.value += `<span style="color:var(--pg-red);display:block;margin-top:6px">${esc(data.warnings.join("；"))}</span>`;
      toast(data.warnings[0], "err");
    }
    files.value = [];
    resetForm();
    renderMine();
  } catch (e) {
    statusHtml.value = "";
    toast(e.message, "err");
  } finally {
    submitting.value = false;
  }
}

function resetForm() {
  form.type = "feedback";
  form.title = "";
  form.content = "";
  form.contact = "";
  form.consent = false;
  files.value = [];
  statusHtml.value = "";
}

onMounted(() => { loadMeta(); renderMine(); });
</script>

<template>
  <div class="grid" style="max-width:780px">
    <div class="card">
      <div class="card-title">我的反馈</div>
      <div class="fb-mine">
        <div v-if="loadingTickets" class="fb-note">加载中…</div>
        <Empty v-else-if="!tickets.length" title="暂无反馈记录" />
        <div v-for="t in tickets" :key="t.tid" class="fb-ticket" :class="{ open: t.open }">
          <div class="fb-ticket-top" @click="t.open = !t.open">
            <span class="fb-tid">{{ t.tid }}</span>
            <template v-if="t.data">
              <Tag color="default">{{ TYPE_LABEL[t.data.type] || '意见反馈' }}</Tag>
              <span class="fb-title">{{ t.data.title || '(无标题)' }}</span>
              <Tag :color="(t.data.status === 'replied' || t.data.status === 'resolved') ? 'mint' : 'yellow'">{{ STATUS_LABEL[t.data.status] || '处理中' }}</Tag>
              <span class="fb-time">{{ fmtTime(t.data.created_at) }}</span>
            </template>
            <span v-else class="fb-error">{{ t.error }}</span>
            <span class="fb-chev"></span>
          </div>
          <div class="fb-ticket-body">
            <template v-if="t.data">
              <div class="fb-desc">{{ t.data.content || '(无内容)' }}</div>
              <div class="fb-replybox">
                <div class="fb-replybox-title">回复</div>
                <div v-if="t.data.replies && t.data.replies.length">
                  <div v-for="(r, i) in t.data.replies" :key="i" class="fb-reply">
                    <div class="fb-reply-head">开发方 · {{ fmtTime(r.created_at) }}</div>
                    <div>{{ r.body }}</div>
                  </div>
                </div>
                <div v-else class="fb-note">暂无回复</div>
              </div>
              <div v-if="t.data.attachments && t.data.attachments.length" class="fb-attach">
                <img v-for="(a, i) in t.data.attachments" :key="i" loading="lazy" :alt="a.path" :title="a.path" :src="attUrl(t.tid, a.path)" @click="openAtt(t.tid, a.path)">
              </div>
            </template>
            <div class="row" style="justify-content:flex-end">
              <Button size="small" @click.stop="removeTid(t.tid)">移除此单</Button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">意见 / BUG 反馈</div>
      <p class="muted" style="margin-bottom:12px">
        也可以通过 <a href="https://github.com/Nekoluna-dot/OpenCompanion/issues" target="_blank" rel="noopener">GitHub Issues</a> 反馈问题
      </p>
      <div class="fb-form">
        <div class="fld">
          <span>反馈类型</span>
          <Select v-model="form.type" :options="TYPE_OPTIONS" />
        </div>
        <div class="fld">
          <span>标题</span>
          <Input v-model="form.title" maxlength="120" placeholder="一句话概括（选填，与内容至少填一项）" />
        </div>
        <div class="fld">
          <span>详细描述</span>
          <Textarea v-model="form.content" :rows="6" maxlength="8000" placeholder="问题现象 / 复现步骤 / 期望行为；功能出错时请尽量说明「出错的位置/功能」" />
        </div>
        <div class="fld">
          <span>联系方式</span>
          <Input v-model="form.contact" maxlength="200" placeholder="邮箱 / QQ / 微信（选填，便于跟进）" />
        </div>
        <div class="fld">
          <span>截图</span>
          <div style="display:flex;flex-direction:column;gap:8px">
            <input ref="fileInput" type="file" hidden accept="image/png,image/jpeg,image/gif,image/webp" multiple @change="onFilesChange">
            <Button style="width:fit-content" @click="fileInput && fileInput.click()">选择截图</Button>
            <span class="hint">PNG/JPG/GIF/WebP，最多 3 张，单张不超过 4MB（选填）</span>
            <span class="fb-previews">
              <div v-for="(f, i) in files" :key="i" class="fb-preview">
                <img :src="f.dataUrl" :alt="f.name">
                <div class="fb-preview-info">{{ f.name }}（{{ (f.size / 1024).toFixed(1) }} KB）</div>
                <Button size="small" @click.prevent="removeFile(i)">移除</Button>
              </div>
            </span>
          </div>
        </div>
        <div class="hr"></div>
        <label class="fb-consent">
          <Checkbox v-model:checked="form.consent" />
          <span><em class="fb-req">*</em> 我同意上传系统信息（不包含您的个人信息），必选项</span>
        </label>
        <div class="row" style="margin-top:14px">
          <Button type="primary" :disabled="submitting" @click="submit">提交反馈</Button>
          <Button type="default" @click="resetForm">清空</Button>
          <span class="fb-status muted" v-html="statusHtml"></span>
        </div>
      </div>
    </div>
  </div>
</template>
