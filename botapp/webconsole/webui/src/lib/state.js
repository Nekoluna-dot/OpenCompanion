import { reactive } from "vue";

export const TOKEN_KEY = "wc_token";

export const app = reactive({
  token: localStorage.getItem(TOKEN_KEY) || "",
  tokenRequired: false,
  bot: null,
  ports: {},
  logs: [], // 全局日志环形数组（上限 2000）
  logSeq: 0,
  sseOk: false,
});

export function setToken(t) {
  app.token = t || "";
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}
