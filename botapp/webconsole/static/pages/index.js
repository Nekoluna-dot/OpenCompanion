"use strict";
/* 页面路由聚合 */
import { mountOverview, unmountOverview } from "./overview.js";
import { mountConsolePage, unmountConsolePage } from "./console.js";
import { mountAccountsPage, unmountAccountsPage } from "./accounts.js";
import { mountChatPage, unmountChatPage } from "./chat.js";
import { mountMemoryPage, unmountMemoryPage } from "./memory.js";
import { mountConfigPage, unmountConfigPage } from "./config.js";
import { mountStatsPage, unmountStatsPage } from "./stats.js";
import { mountDataPage } from "./data.js";
import { mountPromptsPage } from "./prompts.js";
import { mountDebugPage, unmountDebugPage } from "./debug.js";
import { mountFeedbackPage, unmountFeedbackPage } from "./feedback.js";

export const pages = {
  "/overview": { path: "/overview", title: "概览", mount: mountOverview, unmount: unmountOverview },
  "/console": { path: "/console", title: "日志控制台", mount: mountConsolePage, unmount: unmountConsolePage },
  "/accounts": { path: "/accounts", title: "账号管理", mount: mountAccountsPage, unmount: unmountAccountsPage },
  "/chat": { path: "/chat", title: "聊天测试", mount: mountChatPage, unmount: unmountChatPage },
  "/memory": { path: "/memory", title: "记忆与日记", mount: mountMemoryPage, unmount: unmountMemoryPage },
  "/config": { path: "/config", title: "机器人配置", mount: mountConfigPage, unmount: unmountConfigPage },
  "/stats": { path: "/stats", title: "统计", mount: mountStatsPage, unmount: unmountStatsPage },
  "/data": { path: "/data", title: "数据管理", mount: mountDataPage },
  "/prompts": { path: "/prompts", title: "人设预设", mount: mountPromptsPage },
  "/debug":  { path: "/debug",  title: "调试视图", mount: mountDebugPage, unmount: unmountDebugPage },
  "/feedback": { path: "/feedback", title: "意见反馈", mount: mountFeedbackPage, unmount: unmountFeedbackPage },
};