# ---------- 前端构建阶段：Vue 3 + Vite ----------
FROM node:22-slim AS webui
WORKDIR /webui
# 先只拷贝依赖清单，利用层缓存避免每次改源码都重装依赖
COPY botapp/webconsole/webui/package.json botapp/webconsole/webui/package-lock.json ./
RUN npm ci --no-audit --no-fund
# 再拷贝前端源码并构建（vite.config.js 的 outDir 为 ../static）
COPY botapp/webconsole/webui/ ./
RUN npm run build

# ---------- 运行阶段：Python 后端 ----------
FROM python:3.11-slim

# 时区数据：每日日记/写信/提醒按本地时间运行，缺失时 Python 本地时间会退化为 UTC
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# 默认中国时区，可用 docker-compose.yml 的 environment 覆盖
ENV TZ=Asia/Shanghai
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 先装依赖，利用构建缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 用前端阶段编译出的产物覆盖 static（镜像内始终是源码对应的最新界面）
COPY --from=webui /static ./botapp/webconsole/static

EXPOSE 9000 18001

CMD ["python", "main.py"]
