# OpenCompanion 网页控制台（Vue 3）

后端静态网页已从手写 vanilla JS 迁移到 **Vite + Vue 3 (SFC)**。
**功能与外观保持不变**，后端 API 与 `botapp/webconsole/server.py` 未改动。

## 目录

```
webui/
├── index.html            # Vite 入口（挂载 #app）
├── vite.config.js        # 构建产物输出到 ../static/
├── package.json
├── public/               # logo（构建时复制到 static/）
└── src/
    ├── main.js           # createApp + router
    ├── App.vue           # 登录/首次设置/应用壳/Toast
    ├── router.js         # hash 路由（与旧版一致）+ 导航表
    ├── assets/theme.css  # Animal Island 主题样式（库样式由 dist 自动注入）
    ├── lib/              # api / state / logs(SSE) / toast / authBus
    ├── components/       # LogView（实时日志）
    └── pages/            # 11 个页面组件
        Overview / Console / Accounts / Chat / Debug / Memory
        Config / Prompts / Stats / Data / Feedback
```

## 构建

```bash
cd botapp/webconsole/webui
npm install          # 首次
npm run build        # 产物写入 ../static/（index.html + assets/*）
```

> `../static/` 已加入 `.gitignore`，**不再入库**。Docker 镜像由 `Dockerfile` 的
> node 构建阶段自动编译（见仓库根 `Dockerfile`），CI 无需额外步骤。
> 从源码直接跑 `python webconsole.py` 时需先手动 `npm run build`，
> 否则控制台会显示"网页控制台尚未构建"的提示页。

构建后由 `botapp/webconsole/server.py` 的静态服务器托管（`/`、`/assets/*`、`/logo-*.png`），
无需改动后端。

## 开发（可选）

```bash
npm run dev          # Vite dev server，需自行把 /api 代理到 127.0.0.1:9000
```

## 说明

- 使用 **hash 路由**（`#/overview`），与旧版行为一致，服务端无需 catch-all。
- SSE 日志流（`/api/logs/stream`）与调试流（`/api/debug/events`）逻辑照搬旧版。
- 全局日志缓冲、401 跳登录、登录/首次设置流程与旧版等价。
