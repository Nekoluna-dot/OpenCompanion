#!/bin/bash
# ============================================================
# Ombre Brain 健壮部署 / 更新脚本（交互式，自动纠错）
# ============================================================
# 在项目根目录运行：  bash deploy/deploy.sh
#
# 它做什么：
#   1) git pull 更新代码（若是 git 仓库）
#   2) 检测对外端口是否被占用 → 终端交互让你换端口（写入 deploy/.env）
#   3) 检测老数据布局（./data）→ 交互迁移到标准 ./buckets，或保持挂载 ./data
#   4) docker compose 构建并启动
#   5) 健康检查，失败时打印日志与排查指引
#
# 设计目标：让任何机器（含本仓库作者的 VPS）走同一套标准流程，不需要任何
# 机器专属的手改（端口/挂载）。配置都落在 deploy/.env，重建/更新不丢。
# ============================================================
set -e
cd "$(dirname "$0")/.."
PROJ="$(pwd)"
ENVFILE="deploy/.env"
COMPOSE="deploy/docker-compose.yml"

echo "=== Ombre Brain 部署（$PROJ）==="
mkdir -p deploy
touch "$ENVFILE"

port_in_use() {
  if command -v ss >/dev/null 2>&1; then ss -tlnp 2>/dev/null | grep -q ":$1 "
  else netstat -tlnp 2>/dev/null | grep -q ":$1 "; fi
}
set_env() {  # set_env KEY VALUE
  if grep -q "^$1=" "$ENVFILE"; then sed -i "s#^$1=.*#$1=$2#" "$ENVFILE"
  else echo "$1=$2" >> "$ENVFILE"; fi
}

# --- 1) 更新代码 ---
if [ -d .git ]; then
  echo "[git] 拉取最新代码..."
  git pull --ff-only 2>/dev/null || echo "[git] pull 跳过（非快进/无 remote），用当前代码继续"
fi

# --- 2) 端口检测 + 交互纠错 ---
PORT="$(grep -oE '^OMBRE_HOST_PORT=[0-9]+' "$ENVFILE" 2>/dev/null | cut -d= -f2)"
PORT="${PORT:-18001}"
while port_in_use "$PORT"; do
  echo "⚠️  对外端口 $PORT 已被占用："
  ( ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null ) | grep ":$PORT " | sed 's/^/     /'
  read -r -p "   输入一个新端口（回车=强制仍用 $PORT）: " NEW
  [ -z "$NEW" ] && break
  PORT="$NEW"
done
echo "[port] 对外端口 = $PORT"
set_env OMBRE_HOST_PORT "$PORT"

# --- 3) 数据目录健壮化（兼容老的 ./data 布局）---
if [ -d ./data/permanent ] && [ ! -d ./buckets/permanent ]; then
  echo "⚠️  检测到老布局：记忆库在 ./data，标准位置是 ./buckets。"
  read -r -p "   迁移 ./data → ./buckets？(y=迁移 / N=保持挂载 ./data 不动数据): " MIG
  if [ "$MIG" = "y" ] || [ "$MIG" = "Y" ]; then
    cp -a ./data/. ./buckets/ && echo "[data] 已复制 data → buckets（原 data 保留作备份）"
  else
    set_env OMBRE_HOST_VAULT_DIR "$PROJ/data"
    echo "[data] 保持挂载 ./data（已写入 deploy/.env）"
  fi
fi

# --- 4) 构建并启动 ---
echo "[docker] 构建并启动 ombre-brain..."
docker compose -f "$COMPOSE" up -d --build ombre-brain

# --- 5) 健康检查 ---
sleep 10
echo "[health] GET http://localhost:$PORT/health ..."
if curl -s -m 10 "http://localhost:$PORT/health" 2>/dev/null | grep -q '"status":"ok"'; then
  echo "✅ 部署成功：$(curl -s -m5 http://localhost:$PORT/health)"
else
  echo "❌ 健康检查未通过。最近日志："
  docker logs ombre-brain 2>&1 | tail -20
  echo "   手动排查：docker logs ombre-brain"
  exit 1
fi
