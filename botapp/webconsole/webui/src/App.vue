<script setup>
import { ref, computed, onMounted } from "vue";
import { useRoute } from "vue-router";
import {
  Button,
  Input,
  Tag,
  Empty,
} from "animal-island-ui-vue";
import { api } from "./lib/api.js";
import { app, setToken } from "./lib/state.js";
import { toast, toastState } from "./lib/toast.js";
import { setUnauthorizedHandler } from "./lib/authBus.js";
import { startSse, stopSse } from "./lib/logs.js";
import { NAV } from "./router.js";

const route = useRoute();
const view = ref("loading"); // loading | setup | login | app
const setupPassword = ref("");
const setupPassword2 = ref("");
const setupError = ref("");
const loginPassword = ref("");
const loginError = ref("");

const pageTitle = computed(() => (route.meta && route.meta.title) || "概览");
const botRunning = computed(() => !!(app.bot && app.bot.running));
const obVisible = computed(() => !!(app.ports && app.ports[18001] && app.ports[18001].in_use));

function showApp() {
  view.value = "app";
  startSse();
  if (!location.hash || location.hash === "#/" || location.hash === "#") {
    location.hash = "#/overview";
  }
  refreshState();
}

async function checkAuth() {
  try {
    const st = await api("/api/auth/status");
    if (st.need_setup) { view.value = "setup"; return; }
    if (!st.authed) { view.value = "login"; return; }
    showApp();
  } catch (e) {
    view.value = "login";
  }
}

function showLogin() {
  view.value = "login";
  stopSse();
  loginPassword.value = "";
  loginError.value = "";
}

async function doLogin() {
  loginError.value = "";
  const password = loginPassword.value.trim();
  try {
    const r = await api("/api/auth/login", "POST", { password });
    if (!r.ok) { loginError.value = r.error || "登录失败"; return; }
    setToken(r.session);
    showApp();
    toast("登录成功", "ok");
  } catch (e) {
    loginError.value = e.message;
  }
}

async function doSetup() {
  setupError.value = "";
  const p1 = setupPassword.value, p2 = setupPassword2.value;
  if (p1.length < 6) { setupError.value = "密码至少 6 位"; return; }
  if (p1 !== p2) { setupError.value = "两次输入的密码不一致"; return; }
  try {
    const r = await api("/api/auth/setup", "POST", { password: p1 });
    if (!r.ok) { setupError.value = r.error || "设置失败"; return; }
    setToken(r.session);
    toast("密码设置成功", "ok");
    showApp();
  } catch (e) {
    setupError.value = e.message;
  }
}

async function logout() {
  try { await api("/api/auth/logout", "POST", {}); } catch (e) {}
  setToken("");
  stopSse();
  showLogin();
}

let stateTimer = null;
async function refreshState() {
  try {
    const st = await api("/api/state");
    app.bot = st.bot;
    app.ports = st.ports;
  } catch (e) { return; }
}

setUnauthorizedHandler(showLogin);

onMounted(() => {
  checkAuth();
  stateTimer = setInterval(() => { if (view.value === "app") refreshState(); }, 5000);
});
</script>

<template>
  <div v-if="view === 'setup'" class="login-wrap">
    <div class="login-card">
      <div class="login-logo"><img src="/logo-square.png" alt="logo"></div>
      <h1>首次使用</h1>
      <p class="muted">请设置后台登录密码（至少 6 位）</p>
      <div class="login-form">
        <Input v-model="setupPassword" type="password" placeholder="新密码" size="large" allow-clear
               @keydown.enter="doSetup" />
        <Input v-model="setupPassword2" type="password" placeholder="确认密码" size="large" allow-clear
               @keydown.enter="doSetup" />
        <Button type="primary" size="large" block @click="doSetup">设置并进入</Button>
        <div class="login-error">{{ setupError }}</div>
      </div>
      <div class="login-foot">
        <a href="https://github.com/Nekoluna-dot/OpenCompanion" target="_blank" rel="noopener">GitHub</a>
      </div>
    </div>
  </div>

  <div v-else-if="view === 'login'" class="login-wrap">
    <div class="login-card">
      <div class="login-logo"><img src="/logo-square.png" alt="logo"></div>
      <h1>OpenCompanion 控制台</h1>
      <div class="login-form">
        <Input v-model="loginPassword" type="password" placeholder="登录密码" size="large" allow-clear
               @keydown.enter="doLogin" />
        <Button type="primary" size="large" block @click="doLogin">登 录</Button>
        <div class="login-error">{{ loginError }}</div>
      </div>
      <div class="login-foot">
        <a href="https://github.com/Nekoluna-dot/OpenCompanion" target="_blank" rel="noopener">GitHub</a>
      </div>
    </div>
  </div>

  <div v-else-if="view === 'loading'" class="login-wrap">
    <Empty title="正在加载…" description="正在校验登录状态" />
  </div>

  <div v-else-if="view === 'app'" class="app">
    <aside class="sidebar">
      <div class="sidebar-brand"><img src="/logo-horizontal.png" alt="logo"></div>
      <nav class="nav">
        <router-link v-for="item in NAV" :key="item.path" :to="item.path" custom v-slot="{ isActive, navigate }">
          <button :class="{ active: isActive }" @click="navigate">{{ item.title }}</button>
        </router-link>
      </nav>
      <div class="sidebar-foot">
        <span class="dot" :class="app.sseOk ? 'on' : 'off'"></span>
        <span>{{ app.sseOk ? '在线' : '日志流重连中…' }}</span>
      </div>
    </aside>

    <div class="main-col">
      <header class="topbar">
        <div class="page-title">{{ pageTitle }}</div>
        <div class="topbar-right">
          <Tag :color="botRunning ? 'mint' : 'pink'">{{ botRunning ? '机器人运行中' : '机器人未运行' }}</Tag>
          <a v-if="obVisible" class="pill link" target="_blank" href="http://127.0.0.1:18001">OmbreBrain 后台</a>
          <Button type="default" size="small" @click="logout">退出</Button>
        </div>
      </header>
      <main class="content">
        <router-view></router-view>
      </main>
      <footer class="page-foot">
        <a href="https://github.com/Nekoluna-dot/OpenCompanion" target="_blank" rel="noopener">GitHub</a>
      </footer>
    </div>
  </div>

  <div id="toast">
    <div v-for="t in toastState.items" :key="t.id" class="toast" :class="t.type">{{ t.msg }}</div>
  </div>
</template>
