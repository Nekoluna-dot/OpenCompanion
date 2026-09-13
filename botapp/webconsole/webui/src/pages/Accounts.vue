<script setup>
import { ref, reactive, onMounted, onUnmounted, computed } from "vue";
import {
  Button,
  Input,
  Tag,
} from "animal-island-ui-vue";
import { api, toast } from "../lib/api.js";
import { app } from "../lib/state.js";
import { subscribeLogs } from "../lib/logs.js";

const URL_RE = /(https?:\/\/[^\s"'<>，。]+)/;
const HINT_RE = /(Scan this QR|扫码|登录|login|qrcode|二维码|session|过期|expired|refresh|Waiting for|Bot ID|已退出|logout)/i;
const LOG_FILTER_RE = /(Scan|QR|二维码|登录|login|session|过期|expired|refresh|Waiting|Bot ID|logout|账号)/i;

const PHASE_META = {
  waiting: { color: "warning", text: "等待扫码" },
  scanned: { color: "blue", text: "已扫码，请在手机上确认" },
  logged: { color: "mint", text: "已登录" },
  expired: { color: "pink", text: "二维码已过期，正在刷新" },
  logged_out: { color: "pink", text: "已退出登录" },
  unknown: { color: "default", text: "状态未知（暂无登录活动）" },
};

function derivePhase(text) {
  const s = (text || "").toLowerCase();
  if (/(login successful|登录成功|扫码登录完成|已登录|bot id)/.test(s)) return "logged";
  if (/logout|已退出|退出登录/.test(s)) return "logged_out";
  if (/scanned, confirm|已扫描/.test(s)) return "scanned";
  if (/expired|过期/.test(s)) return "expired";
  if (/refresh|刷新|重新/.test(s)) return "waiting";
  if (/waiting for scan|scan this qr|scan the qr|等待扫码|等待扫描|请用.*扫码|扫码登录/.test(s)) return "waiting";
  return null;
}

const platformData = reactive({ platforms: [], current: "", running: false, friendly: {} });
const selected = ref(null);
const currentQr = ref("");
const phase = ref("unknown");
const phaseSet = ref(false);
const logLines = ref([]);
const manualUrl = ref("");

let unsub = null;
let refreshTimer = null;
let lastHintAt = 0;

const currentName = computed(() => (platformData.friendly && platformData.friendly[platformData.current]) || platformData.current || "(未配置)");
const phaseMeta = computed(() => PHASE_META[phase.value] || PHASE_META.unknown);

function setQr(url) {
  if (!url || url === currentQr.value) return;
  currentQr.value = url;
}

function setPhase(text) {
  const p = derivePhase(text);
  if (!p) return;
  phase.value = p;
  phaseSet.value = true;
}

function onLogLine(line) {
  const m = URL_RE.exec(line);
  const isUrlLine = !!(m && line.trim().startsWith("http"));
  if (!LOG_FILTER_RE.test(line) && !isUrlLine) return;
  const now = Date.now();
  if (HINT_RE.test(line)) {
    lastHintAt = now;
    setPhase(line);
    if (m) setQr(m[1].replace(/[)\]}>"'.,;]+$/, ""));
  } else if (m) {
    if (now - lastHintAt < 10000) setQr(m[1].replace(/[)\]}>"'.,;]+$/, ""));
  }
  logLines.value.push(line);
  if (logLines.value.length > 120) logLines.value.splice(0, logLines.value.length - 120);
}

async function loadPlatforms() {
  try {
    const d = await api("/api/platforms");
    Object.assign(platformData, d);
  } catch (e) {
    toast("读取平台信息失败: " + e.message, "err");
  }
}

async function switchPlatform() {
  try {
    const r = await api("/api/platform/switch", "POST", { name: selected.value });
    toast(`已切换平台，${r.restart_required ? "请重启机器人生效" : "已保存"}`, "ok");
    selected.value = null;
    loadPlatforms();
  } catch (e) {
    toast(e.message, "err");
  }
}

function genManual() {
  const v = manualUrl.value.trim();
  if (!/^https?:\/\/\S+/.test(v)) { toast("请输入合法链接（http/https 开头）", "err"); return; }
  setQr(v);
  toast("二维码已生成", "ok");
}

const qrSrc = computed(() => (currentQr.value ? "/api/qr?content=" + encodeURIComponent(currentQr.value) : ""));

onMounted(() => {
  unsub = subscribeLogs(onLogLine);
  app.logs.forEach(onLogLine);
  loadPlatforms();
  refreshTimer = setInterval(loadPlatforms, 5000);
});
onUnmounted(() => {
  if (unsub) unsub();
  if (refreshTimer) clearInterval(refreshTimer);
});
</script>

<template>
  <div class="acc-grid">
    <div>
      <div class="card">
        <div class="card-title">平台适配器</div>
        <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
          <span class="muted">当前启用：</span>
          <Tag :color="platformData.current ? 'mint' : 'default'">{{ currentName }}</Tag>
          <span class="muted">机器人进程：</span>
          <Tag :color="platformData.running ? 'mint' : 'pink'">{{ platformData.running ? '运行中' : '已停止' }}</Tag>
        </div>
        <div class="platform-pills">
          <button v-for="id in platformData.platforms" :key="id"
            :class="{ on: selected === id }" :disabled="id === platformData.current"
            @click="selected = id">{{ (platformData.friendly && platformData.friendly[id]) || id }}</button>
        </div>
        <div class="row" style="margin-top:12px">
          <Button type="primary" :disabled="!selected || selected === platformData.current" @click="switchPlatform">切换到所选平台</Button>
        </div>
      </div>
      <div class="card">
        <div class="card-title">登录状态</div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
          <Tag :color="phaseMeta.color">{{ phaseSet ? phaseMeta.text : '分析中…' }}</Tag>
        </div>
        <div class="acc-log">
          <div v-for="(l, i) in logLines" :key="i" class="line">{{ l }}</div>
        </div>
      </div>
    </div>
    <div class="card qr-card">
      <div class="card-title">登录二维码</div>
      <div class="qr-box">
        <img v-if="qrSrc" :src="qrSrc" alt="二维码" class="qr-img" />
        <div v-else class="muted" style="font-size:12px;text-align:center;padding:44px 6px;line-height:1.9">暂无登录二维码</div>
        <a v-if="currentQr" :href="currentQr" target="_blank" rel="noopener" class="qr-link">{{ currentQr }}</a>
      </div>
      <div style="border-top:1px dashed var(--pg-border);margin-top:14px;padding-top:12px">
        <div class="muted" style="margin-bottom:6px">手动生成（粘贴任意登录链接）：</div>
        <Input v-model="manualUrl" placeholder="https://…" @keydown.enter="genManual" />
        <div class="row" style="margin-top:8px">
          <Button block @click="genManual">生成二维码</Button>
        </div>
      </div>
    </div>
  </div>
</template>
