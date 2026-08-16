# Docker 部署指南

把 OpenCompanion 跑在 Docker 容器里，数据与微信登录会话全部持久化，
重启容器、升级镜像都不丢记忆、不丢登录态。

## 前置条件

- Docker（含 Compose 插件，`docker compose version` 可查）
- Linux 主机（或 Windows/macOS 上的 Docker Desktop）

## 方式一：拉取公开镜像（推荐）

镜像发布在 GitHub Container Registry（ghcr.io），打 tag 时由 GitHub Actions
自动构建，**无需本地 Docker 构建**。镜像内置的 API key 是占位符，真实 key
通过挂载的配置文件提供：

```bash
# 1. 准备 config.ini（可从仓库下载或在容器外编辑）：
#    [llmapi] api_key = 你的 DeepSeek key

# 2. 拉取并启动（首次会先 docker pull）
docker compose up -d

# 3. 浏览器打开网页控制台
#    http://服务器IP:9000

# 4. 在「状态与日志」页点击「启动机器人」，日志里直接出现微信二维码，
#    用手机微信扫码即可登录（无需 docker attach）
```

> 拉取的镜像里 `runtime/python/python.exe` 不存在（那是 Windows 便携版），
> 代码会自动回退到容器内 Python（`botapp/config.py:resolve_python_command`），
> 无需额外设置。

## 方式二：本地构建

```bash
docker compose up -d --build
```

## 网页控制台

入口：`http://服务器IP:9000`（强烈建议在 compose 里设置 `BOT_WEBCONSOLE_TOKEN`，前端会提示输入令牌）。

| 页面 | 功能 |
| ---- | ---- |
| 状态与日志 | 机器人启停/重启/自动重启开关、运行时长、端口占用检测与清理、快捷入口（9000/18001）、实时日志（含微信扫码二维码，可放大） |
| 机器人配置 | config.ini 全部字段编辑、mcpsources 勾选启停、原始文本编辑、保存/保存并重启 |
| OmbreBrain 配置 | config.yaml 的 dehydration/embedding 字段编辑、保存/保存并重启 |
| 数据管理 | 数据路径与大小、快捷删除（weilink/对话/OB 记忆/日志/运行锁）、恢复出厂设置 |

扫码登录完成后，容器内的 `~/.weilink`（compose 里映射为命名卷 `session`）
保存了登录 token，之后重启容器/机器人**免扫码**，除非会话过期。

## 端口

| 端口 | 用途 |
| ---- | ---- |
| 9000 | 网页控制台（管理机器人/配置/数据） |
| 18001 | OmbreBrain 后台（日记/信件/记忆桶，随机器人运行） |

MCP 服务器（容器内 8000）默认回环监听，供容器内 AI 助手调用 weilink 工具，
不映射到宿主机；调试面板（8080）已删除。

如需仅本机访问，把 compose 里 `"9000:9000"` 改成 `"127.0.0.1:9000:9000"`（18001 同理）。

## 日常使用

```bash
docker compose logs -f            # 查看容器日志（控制台本身的输出）
docker compose restart             # 重启容器（控制台 + 由它管理的机器人）
docker compose down                # 停止并删除容器（数据保留）
docker compose down -v             # 停止并连登录会话一起删（下次需重扫码）
docker compose build --no-cache    # 更新镜像（代码/依赖变化时）
```

机器人的启停/重启在**网页控制台**里操作；容器级重启只在升级代码/改 compose 时需要。

> Windows 原生部署时，可用 `python webconsole.py` 启动网页控制台（替代 scripts/launcher.py 的 GUI 启动器），浏览器打开 http://127.0.0.1:9000。

## 数据都存哪

| 数据 | 位置 |
| ---- | ---- |
| 对话存档 / 用户档案 / 事件库 | `./data/` |
| 上下文存档 | `./conversation/` |
| 日志 | `./logs/` |
| 微信登录 token（免扫码） | 命名卷 `session`（`docker volume inspect opencompanion_session`） |
| 记忆引擎 OmbreBrain 数据 | `./data/`（MCP/OB/buckets） |

备份 = 拷贝 `data/`、`conversation/`、`logs/` 三个目录 + 用
`docker run --rm -v opencompanion_session:/d alpine tar -czf - -C /d . > session.tar.gz`
导出登录会话卷。

## 常用端口

| 端口 | 用途 |
| ---- | ---- |
| 9000 | 网页控制台（管理机器人/配置/数据） |
| 18001 | OmbreBrain 后台（日记/信件/记忆桶，随机器人运行） |

> MCP 服务器（容器内 8000）默认只回环监听本机，供容器内 AI 编码助手调用，
> 不映射到宿主机；曾被集成进控制台的调试面板（8080）已删除，不再监听。

## 最小化运行

不需要的工具源直接注释掉 config.ini `[mcpsources]` 对应行再 `docker compose restart`，
全部注释时机器人只保留 weilink 内置工具，几乎零额外依赖。

## 常见问题

- **控制台打不开**：确认 `docker compose ps` 状态 Up，`docker compose logs` 里应有
  `网页控制台: http://0.0.0.0:9000`；检查云服务器安全组/防火墙放行 9000 端口。
- **拉取了镜像但机器人报 api_key 无效**：镜像里是占位符 key，请确认
  `./config.ini`、`./MCP/OB/.env`、`./MCP/OB/config.yaml` 三个文件已在
  宿主机填好真实 key（compose 会把它们挂载进容器覆盖占位符）。
- **扫码登录后机器人没反应**：在控制台「状态与日志」页确认日志无错误；
  会话过期时重新点「停止」再「启动」，日志会重新出二维码。
- **会话过期需要重新扫码**：网页控制台停止再启动机器人即可；仍不行时
  `docker compose down -v` 清掉登录卷重来。
- **时区不对**：compose 里改 `TZ=Asia/Shanghai` 为你的时区后 `docker compose up -d`。
- **Windows 宿主同时跑着本机版 bot**：两边的 `data/`、`conversation/` 不要指向同一目录，
  容器内的锁机制（data/bot.lock）只能管容器内进程。

## 与 Windows 原生部署的关系

Docker 版不需要 `runtime/` 目录（Windows 嵌入式 Python 不适用于容器）。
代码做了三处跨平台适配：

1. `botapp/singleton.py`：进程探活/杀进程树按平台分支（Windows 用
   ctypes+taskkill，POSIX 用 os.kill），非交互环境自动接管旧进程不提问。
2. `botapp/config.py` / `botapp/plugins.py`：`mcpsources` 与插件 manifest 里的
   Python 路径找不到时，自动回退 `BOT_PYTHON` 环境变量 → 容器内 `sys.executable`。
3. `botapp/robot.py`：CPU 使用率采样 Windows 用 GetSystemTimes，
   Linux 用 `/proc/stat`。
