<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue";
import {
  Button,
  Switch,
  Tag,
} from "animal-island-ui-vue";
import { api, toast, fmtUptime, esc } from "../lib/api.js";
import { app } from "../lib/state.js";
import LogView from "../components/LogView.vue";

const refreshing = ref(false);
const detail = ref("");
let stateTimer = null;

const ports = computed(() => app.ports || {});
const bot = computed(() => app.bot || {});

function renderState() {
  const b = app.bot;
  if (!b) { refresh(); return; }
  const running = !!b.running;
  detail.value = running
    ? `<span class="dot on"></span>运行中 · PID ${esc(b.pid)} · 运行时长 ${fmtUptime(b.uptime || 0)}`
    : (b.stale_lock_pid
      ? `<span class="dot mid"></span>未运行（检测到残留运行锁 PID ${esc(b.stale_lock_pid)}，启动时会自动清理）`
      : `<span class="dot off"></span>未运行`);
}

async function refresh() {
  if (refreshing.value) return;
  refreshing.value = true;
  try {
    const st = await api("/api/state");
    app.bot = st.bot;
    app.ports = st.ports;
  } catch (e) {}
  refreshing.value = false;
  renderState();
}

async function start() {
  try { const r = await api("/api/bot/start", "POST", {}); toast(r.result, r.result === "ok" ? "ok" : "err"); refresh(); }
  catch (e) { toast(e.message, "err"); }
}
async function stop() {
  try { await api("/api/bot/stop", "POST", {}); toast("已发送停止信号", "ok"); refresh(); }
  catch (e) { toast(e.message, "err"); }
}
async function restart() {
  try { const r = await api("/api/bot/restart", "POST", {}); toast(r.result, r.result === "ok" ? "ok" : "err"); refresh(); }
  catch (e) { toast(e.message, "err"); }
}
async function toggleAuto(v) {
  try { await api("/api/bot/auto_restart", "POST", { enabled: v }); toast("已保存", "ok"); }
  catch (err) { toast(err.message, "err"); }
}
async function killPort(port, pids) {
  if (!confirm(`确定杀死端口 ${port} 的占用进程？\nPID: ${pids.join(", ")}`)) return;
  try { await api("/api/ports/kill", "POST", { pids }); toast("已杀死", "ok"); refresh(); }
  catch (e) { toast(e.message, "err"); }
}

onMounted(() => {
  stateTimer = setInterval(refresh, 5000);
  refresh();
});
onUnmounted(() => { if (stateTimer) clearInterval(stateTimer); });
</script>

<template>
  <div class="grid cols-2">
    <div class="card">
      <div class="card-title">机器人控制</div>
      <div class="row">
        <Button type="primary" :disabled="bot.running" @click="start">启动机器人</Button>
        <Button :disabled="!bot.running" @click="stop">停止机器人</Button>
        <Button @click="restart">重启机器人</Button>
        <Switch :checked="!!bot.auto_restart" @update:checked="toggleAuto" checked-children="自动重启"
                un-checked-children="自动重启" />
      </div>
      <div class="muted" style="margin-top:10px" v-html="detail"></div>
    </div>
    <div class="card">
      <div class="card-title">快捷入口</div>
      <div class="grid cols-2" style="gap:10px">
        <div class="stat-card">
          <div class="lbl">调试视图</div>
          <div class="num" style="font-size:18px;font-weight:700"><a href="#/debug">调试</a></div>
          <div class="sub">查看每次 LLM 请求的实时流式输出（思考/回复/工具）</div>
        </div>
        <div class="stat-card">
          <div class="lbl">OmbreBrain 后台</div>
          <div class="num" style="font-size:18px;font-weight:700"><a href="http://127.0.0.1:18001" target="_blank">:18001</a></div>
          <div class="sub">{{ ports[18001] && ports[18001].in_use ? '运行中' : '未运行' }}</div>
          <div class="sub">长期记忆：日记、信件、记忆桶</div>
        </div>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">端口占用</div>
    <table class="tbl">
      <thead><tr><th>服务</th><th>端口</th><th>状态</th><th>占用进程</th><th></th></tr></thead>
      <tbody>
        <tr v-for="(s, port) in ports" :key="port">
          <td>{{ s.desc }}</td>
          <td class="mono">{{ port }}</td>
          <td>
            <Tag :color="s.in_use ? 'mint' : 'default'">{{ s.in_use ? '被占用' : '空闲' }}</Tag>
          </td>
          <td class="mono">{{ s.pids && s.pids.length ? 'PID ' + s.pids.join(', ') : '—' }}</td>
          <td class="actions">
            <Button v-if="s.pids && s.pids.length" type="primary" danger size="small" @click="killPort(port, s.pids)">杀死</Button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-title">最近日志</div>
    <LogView :limit="300" />
  </div>
</template>
