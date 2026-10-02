import { createRouter, createWebHashHistory } from "vue-router";

export const NAV = [
  { path: "/overview", title: "概览" },
  { path: "/console", title: "日志控制台" },
  { path: "/accounts", title: "账号管理" },
  { path: "/chat", title: "聊天测试" },
  { path: "/debug", title: "调试视图" },
  { path: "/memory", title: "记忆与日记" },
  { path: "/config", title: "机器人配置" },
  { path: "/prompts", title: "人设预设" },
  { path: "/stats", title: "统计" },
  { path: "/data", title: "数据管理" },
  { path: "/feedback", title: "意见反馈" },
];

const routes = [
  { path: "/", redirect: "/overview" },
  { path: "/overview", component: () => import("./pages/Overview.vue"), meta: { title: "概览" } },
  { path: "/console", component: () => import("./pages/Console.vue"), meta: { title: "日志控制台" } },
  { path: "/accounts", component: () => import("./pages/Accounts.vue"), meta: { title: "账号管理" } },
  { path: "/chat", component: () => import("./pages/Chat.vue"), meta: { title: "聊天测试" } },
  { path: "/debug", component: () => import("./pages/Debug.vue"), meta: { title: "调试视图" } },
  { path: "/memory", component: () => import("./pages/Memory.vue"), meta: { title: "记忆与日记" } },
  { path: "/config", component: () => import("./pages/Config.vue"), meta: { title: "机器人配置" } },
  { path: "/prompts", component: () => import("./pages/Prompts.vue"), meta: { title: "人设预设" } },
  { path: "/stats", component: () => import("./pages/Stats.vue"), meta: { title: "统计" } },
  { path: "/data", component: () => import("./pages/Data.vue"), meta: { title: "数据管理" } },
  { path: "/feedback", component: () => import("./pages/Feedback.vue"), meta: { title: "意见反馈" } },
  { path: "/:pathMatch(.*)*", redirect: "/overview" },
];

const router = createRouter({
  history: createWebHashHistory(),
  routes,
});

router.afterEach((to) => {
  const t = to.meta && to.meta.title ? to.meta.title : "概览";
  document.title = "OpenCompanion 控制台 · " + t;
});

export default router;
