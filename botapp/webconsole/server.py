"""网页控制台 HTTP 服务器（标准库实现，零新依赖，Windows/容器通用）。

功能覆盖 scripts/launcher.py 的全部能力，并新增：
  启动器页（状态/启停/自动重启/端口/实时日志）→ /api/bot/*、/api/logs/*
  机器人配置页（config.ini 结构化编辑 + mcpsources 勾选 + 原始文本）→ /api/config/ini
  OmbreBrain 配置页（config.yaml）→ /api/config/yaml
  数据管理页（路径/大小/删除/恢复出厂）→ /api/data/*
  记忆查看页（OB 记忆桶/信件，经本服务代理避免跨端口与凭据暴露）→ /api/ob/*
  统计页（提醒事件/对话存档/日志活动）→ /api/stats
  聊天模拟测试页（注入消息到 bot 进程）→ /api/test/message、/api/ob 鉴权
鉴权：config.ini [webconsole] token 或环境变量 BOT_WEBCONSOLE_TOKEN；留空则不鉴权。
"""

from __future__ import annotations

import hashlib
import json
import io
import os
import platform
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from botapp.console import console
from botapp.webconsole import config_edit, dataops, obproxy, prompts, stats
from botapp.webconsole.manager import (
    TEST_HTTP_PORT,
    BotProcessManager,
    LogRing,
    pid_alive,
)
from botapp.webconsole.prompts import PromptsManager

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}

# 平台适配器的展示名（未知平台回退用其 id；新增适配器只需在此补一行）
_PLATFORM_NAMES = {
    "wechat": "微信 (weilink)",
}

# 需要关注的端口（8080 调试面板已集成到 webconsole，不再独立监听）
WATCH_PORTS = [
    (8000, "MCP 服务器"),
    (18001, "OmbreBrain 后台"),
    (9000, "网页控制台"),
]


def _in_docker() -> bool:
    """是否运行在容器内：/.dockerenv 或 cgroup 含 docker/containerd/kubepods。"""
    try:
        if os.path.exists("/.dockerenv"):
            return True
        with open("/proc/1/cgroup", "r", encoding="utf-8", errors="ignore") as f:
            cg = f.read()
        return ("docker" in cg) or ("containerd" in cg) or ("/kubepods" in cg)
    except Exception:
        return False


class WebConsoleServer:
    # 登录密码哈希存储(独立文件, 加盐 SHA-256; 不写入 config.ini)
    _AUTH_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "webconsole_auth.json"
    _SESSION_TTL = 24 * 3600  # 登录会话有效期 24h

    def __init__(self, host: str = "127.0.0.1", port: int = 9000, token: str = "") -> None:
        self.host = host
        self.port = port
        self.token = token
        self.manager = BotProcessManager(webconsole_port=self.port)
        self._rawview = LogRing(maxlen=200)  # RawView 调试事件独立缓冲（不经日志流）
        self.ob = obproxy.ObProxy()
        self.prompts = PromptsManager(_PROJECT_ROOT)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._qr_cache: dict[str, bytes] = {}
        self.password_hash = self._load_password_hash()
        self.sessions: dict[str, float] = {}  # session token -> 过期时间戳
        self.feedback_url = self._load_feedback_url()

    # -- 登录密码与会话 ------------------------------------------------
    def _load_feedback_url(self) -> str:
        """意见反馈后端地址：config.ini [webconsole] feedback_url 或环境变量覆盖。"""
        url = os.environ.get("BOT_WEBCONSOLE_FEEDBACK_URL", "").strip()
        try:
            import configparser

            cp = configparser.ConfigParser()
            cp.read(_PROJECT_ROOT / "config.ini", encoding="utf-8-sig")
            if cp.has_option("webconsole", "feedback_url"):
                url = url or cp.get("webconsole", "feedback_url", fallback="").strip()
        except Exception:
            pass
        return url.rstrip("/") or ""
    def _load_password_hash(self) -> str:
        try:
            d = json.loads(self._AUTH_FILE.read_text(encoding="utf-8"))
            return str(d.get("password_hash", "") or "")
        except Exception:
            return ""

    def _save_password_hash(self, h: str) -> None:
        self._AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._AUTH_FILE.write_text(
            json.dumps({"password_hash": h}, ensure_ascii=False), encoding="utf-8"
        )

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_hex(8)
        h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return f"{salt}:{h}"

    @staticmethod
    def _verify_password(password: str, stored: str) -> bool:
        if not stored or ":" not in stored:
            return False
        salt, h = stored.split(":", 1)
        return h == hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

    def _new_session(self) -> str:
        t = secrets.token_urlsafe(32)
        self.sessions[t] = time.time() + self._SESSION_TTL
        return t

    def _session_valid(self, t: str) -> bool:
        if not t:
            return False
        exp = self.sessions.get(t)
        if exp is None:
            return False
        if time.time() > exp:
            self.sessions.pop(t, None)
            return False
        return True

    def _revoke_session(self, t: str) -> None:
        if t:
            self.sessions.pop(t, None)

    def qr_png(self, content: str) -> bytes | None:
        """把链接/文本生成二维码 PNG（内存缓存，最多 20 个）。"""
        content = (content or "").strip()
        if not content or len(content) > 512 or "\x00" in content:
            return None
        cached = self._qr_cache.get(content)
        if cached is not None:
            return cached
        try:
            import qrcode

            img = qrcode.make(content, box_size=9, border=2)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png = buf.getvalue()
        except Exception:
            return None
        if len(self._qr_cache) >= 20 and content not in self._qr_cache:
            self._qr_cache.pop(next(iter(self._qr_cache)))
        self._qr_cache[content] = png
        return png

    def start(self) -> None:
        handler = self._make_handler()
        try:
            self._server = ThreadingHTTPServer((self.host, self.port), handler)
        except OSError as e:
            raise RuntimeError(f"网页控制台端口 {self.port} 启动失败: {e}") from e
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="webconsole")
        self._thread.start()
        self._auto_start_bot()

    def _auto_start_bot(self) -> None:
        """webconsole 启动后自动拉起机器人（无需手动点启动）。

        config.ini [webconsole] auto_start_bot = false 或环境变量
        BOT_WEBCONSOLE_AUTO_START=0 可关闭；默认自动启动。
        """
        auto = True
        try:
            import configparser
            cp = configparser.ConfigParser()
            cp.read(_PROJECT_ROOT / "config.ini", encoding="utf-8-sig")
            if cp.has_section("webconsole") and cp.has_option("webconsole", "auto_start_bot"):
                auto = cp.getboolean("webconsole", "auto_start_bot")
        except Exception:
            pass
        env = os.environ.get("BOT_WEBCONSOLE_AUTO_START", "").strip().lower()
        if env in ("1", "true", "yes", "on"):
            auto = True
        elif env in ("0", "false", "no", "off"):
            auto = False
        if not auto:
            console.info("已配置不自动启动机器人（auto_start_bot=false）")
            return

        def _do_start() -> None:
            time.sleep(1.0)  # 等 HTTP 就绪，机器人日志能流入控制台
            try:
                r = self.manager.start()
                if r != "ok":
                    console.warn(f"自动启动机器人: {r}")
            except Exception as e:
                console.error(f"自动启动机器人失败: {e}")

        threading.Thread(target=_do_start, daemon=True, name="wc-autostart").start()

    def stop(self) -> None:
        self.manager.close()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # 静默访问日志
                pass

            def handle_one_request(self):
                # 浏览器刷新/关闭页面时客户端会断开连接(10053/10054/EPIPE),
                # 这是轮询 API 的正常现象, 静默忽略, 不打印异常堆栈。
                try:
                    super().handle_one_request()
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    pass

            # -- 工具 -----------------------------------------------------
            def _credential(self) -> str:
                """从 Authorization 头或 ?token= 查询参数提取凭据。"""
                auth = self.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    return auth[len("Bearer "):].strip()
                m = re.search(r"[?&]token=([^&]*)", self.path)
                if m:
                    return urllib.parse.unquote(m.group(1))
                return ""

            def _authed(self) -> bool:
                # 未设置登录密码: 放行(前端会强制进入"设置密码"流程)
                if not server.password_hash:
                    return True
                given = self._credential()
                if given and (
                    server._session_valid(given)
                    or (server.token and given == server.token)
                ):
                    return True
                return False

            def _json(self, obj, code: int = 200) -> None:
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    pass  # 客户端已断开, 无需再写

            def _read_body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    return {}
                try:
                    return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                except (ValueError, UnicodeDecodeError):
                    return {}

            def _send_static(self, rel: str) -> None:
                path = (_STATIC_DIR / rel.lstrip("/")).resolve()
                try:
                    path.relative_to(_STATIC_DIR.resolve())
                except ValueError:
                    self.send_error(403)
                    return
                if not path.is_file():
                    self.send_error(404)
                    return
                body = path.read_bytes()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", _MIME.get(path.suffix.lower(), "application/octet-stream"))
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.send_header("Pragma", "no-cache")
                    self.end_headers()
                    self.wfile.write(body)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    pass  # 客户端已断开, 无需再写

            # -- 路由 -----------------------------------------------------
            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    self._send_static("index.html")
                    return
                if path.startswith("/static/"):
                    self._send_static(path[len("/static/"):])
                    return
                # 非 API 路径：按相对路径尝试 static 目录（style.css/app.js/pages/*）
                if not path.startswith("/api/"):
                    self._send_static(path.lstrip("/"))
                    return
                if path == "/api/auth/status":  # 无需鉴权: 供前端判断 设置/登录/已进入
                    self._json(self._api_auth_status())
                    return
                if path == "/api/prompts":  # 列出所有预设(含当前激活)
                    self._json({"presets": server.prompts.list_presets(),
                                "active": server.prompts.active_name()})
                    return
                if path.startswith("/api/prompts/"):
                    rest = path[len("/api/prompts/"):]
                    # 排除 activate/delete(那些是 POST)
                    if "/" not in rest and rest:
                        self._json(server.prompts.read_preset(rest))
                        return
                    self._json({"error": "not found"}, 404)
                    return
                # 调试视图端点：SSE 流和快照免鉴权（和日志流一样，登录前可见）
                if path == "/api/debug/events" or path == "/api/debug/snapshot":
                    pass  # 继续到下面的路由匹配
                elif not self._authed():
                    self._json({"error": "未授权"}, 401)
                    return
                if path == "/api/state":
                    self._json(self._api_state())
                elif path == "/api/logs":
                    # 只返回最近 N 条（默认 500，上限 2000），避免大 JSON 阻塞
                    qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                    tail = 500
                    m = re.search(r"[?&]tail=(\d+)", "?" + qs)
                    if m:
                        try:
                            tail = min(max(int(m.group(1)), 0), 2000)
                        except ValueError:
                            pass
                    self._json({"lines": server.manager.logs(tail)})
                elif path == "/api/logs/stream":
                    self._sse_logs()
                # -- 调试视图（代理 rawview 8080）--------------------------------
                elif path == "/api/debug/events":
                    self._sse_debug()
                elif path == "/api/debug/snapshot":
                    self._debug_snapshot()
                elif path == "/api/config/ini":
                    self._json(config_edit.read_ini())
                elif path == "/api/config/yaml":
                    self._json(config_edit.read_yaml())
                elif path == "/api/data/paths":
                    self._json({"paths": dataops.data_paths()})
                elif path == "/api/ports":
                    self._json(port_status())
                elif path == "/api/ob/status":
                    self._json(self._ob_status())
                elif path == "/api/ob/buckets":
                    qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                    params = dict(
                        re.findall(r"[?&]([^=]+)=([^&]*)", "?" + qs)
                    )
                    self._json(server.ob.buckets(
                        bucket_type=params.get("type", ""),
                        limit=int(params.get("limit", "200") or 200),
                    ))
                elif path.startswith("/api/ob/bucket/"):

                    bucket_id = path[len("/api/ob/bucket/"):]
                    self._json(server.ob.bucket(bucket_id))
                elif path == "/api/ob/letters":
                    qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                    m = re.search(r"author=([^&]*)", qs)
                    self._json(server.ob.letters(author=m.group(1) if m else ""))
                elif path == "/api/stats":
                    self._json(stats.collect_stats(server.manager.logs()))
                elif path == "/api/qr":
                    qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                    m = re.search(r"content=([^&]*)", qs)
                    content = urllib.parse.unquote(m.group(1)) if m else ""
                    png = server.qr_png(content)
                    if png is None:
                        self._json({"error": "无效的二维码内容"}, 400)
                    else:
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(png)))
                        self.send_header("Cache-Control", "no-cache, no-store")
                        self.end_headers()
                        self.wfile.write(png)
                elif path == "/api/platforms":
                    self._json(self._api_platforms())
                elif path == "/api/users":
                    self._json(self._api_users())
                elif path == "/api/history":
                    qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                    m = re.search(r"user=([^&]*)", qs)
                    user = urllib.parse.unquote(m.group(1)) if m else ""
                    self._json(self._api_history(user))
                elif path == "/api/feedback/config":
                    self._json({"endpoint": server.feedback_url,
                                "enabled": bool(server.feedback_url)})
                elif path == "/api/feedback/meta":
                    self._json(self._api_feedback_meta())
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self) -> None:
                path = self.path.split("?", 1)[0]
                if path not in ("/api/auth/login", "/api/auth/setup", "/api/debug/ingest") and not self._authed():
                    self._json({"error": "未授权"}, 401)
                    return
                body = self._read_body()
                try:
                    if path == "/api/debug/ingest":
                        # bot 进程回环上报 RawView 调试事件（仅接受本机来源）
                        client_ip = self.client_address[0] if self.client_address else ""
                        if client_ip not in ("127.0.0.1", "::1"):
                            self._json({"error": "只接受本机上报"}, 403)
                            return
                        raw = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
                        server._rawview.append(raw)
                        self._json({"ok": True})
                    elif path == "/api/auth/login":
                        self._json(self._api_login(body))
                    elif path == "/api/auth/setup":
                        self._json(self._api_setup(body))
                    elif path == "/api/auth/logout":
                        server._revoke_session(self._credential())
                        self._json({"ok": True})
                    elif path == "/api/bot/start":
                        self._json({"result": server.manager.start()})
                    elif path == "/api/bot/stop":
                        self._json({"result": server.manager.stop()})
                    elif path == "/api/bot/restart":
                        self._json({"result": server.manager.restart()})
                    elif path == "/api/bot/auto_restart":
                        server.manager.set_auto_restart(bool(body.get("enabled", False)))
                        self._json({"result": "ok"})
                    elif path == "/api/logs/clear":
                        server.manager.clear_logs()
                        self._json({"result": "ok"})
                    elif path == "/api/config/ini":
                        config_edit.save_ini(
                            body.get("values"), body.get("sources"), body.get("raw")
                        )
                        self._json({"result": "ok"})
                    elif path == "/api/config/yaml":
                        config_edit.save_yaml(body.get("values"), body.get("raw"))
                        self._json({"result": "ok"})
                    elif path == "/api/data/delete":
                        result = dataops.delete_path(str(body.get("target", "")))
                        self._json({"result": result})
                    elif path == "/api/data/factory_reset":
                        self._json({"result": dataops.factory_reset()})
                    elif path == "/api/data/factory_reset_full":
                        self._json({"result": dataops.factory_reset_full()})
                    elif path == "/api/ports/kill":
                        pids = body.get("pids") or []
                        killed = []
                        for pid in pids:
                            try:
                                pid = int(pid)
                            except (TypeError, ValueError):
                                continue
                            if pid > 0 and pid_alive(pid):
                                kill_pid(pid)
                                killed.append(pid)
                        self._json({"result": "ok", "killed": killed})
                    elif path == "/api/ob/login":
                        self._json(server.ob.login(str(body.get("password", ""))))
                    elif path == "/api/ob/setup":
                        self._json(server.ob.setup(str(body.get("password", ""))))
                    elif path == "/api/ob/logout":
                        server.ob.logout()
                        self._json({"ok": True})
                    elif path == "/api/test/message":
                        self._json(self._api_test_message(body))
                    elif path == "/api/platform/switch":
                        self._json(self._api_platform_switch(body))
                    elif path == "/api/prompts":
                        # 新建预设(body: name/description/prompt/extra)
                        self._json({"result": "ok", **server.prompts.save_preset(
                            str(body.get("name", "")),
                            str(body.get("prompt", "")),
                            str(body.get("extra", "")),
                            str(body.get("description", "")),
                        )})
                    elif path.startswith("/api/prompts/"):
                        rest = path[len("/api/prompts/"):]
                        if rest.endswith("/activate"):
                            name = rest[: -len("/activate")].rstrip("/")
                            self._json({"result": server.prompts.activate(name)})
                            return
                        if rest.endswith("/delete"):
                            name = rest[: -len("/delete")].rstrip("/")
                            self._json({"result": server.prompts.delete_preset(name)})
                            return
                        # 保存预设编辑: 路径即预设名
                        self._json({"result": "ok", **server.prompts.save_preset(
                            rest,
                            str(body.get("prompt", "")),
                            str(body.get("extra", "")),
                            str(body.get("description", "")),
                        )})
                    else:
                        self._json({"error": "not found"}, 404)
                except Exception as e:  # noqa: BLE001
                    self._json({"error": str(e)}, 500)

            # -- SSE 日志流 ------------------------------------------------
            def _sse_logs(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                q = server.manager.subscribe_logs()
                try:
                    # 连接时只重放最近 200 行，避免重连/刷新时刷屏
                    for line in server.manager.logs(200):
                        try:
                            self.wfile.write(
                                b"data: " + json.dumps(line, ensure_ascii=False).encode("utf-8") + b"\n\n"
                            )
                        except OSError:
                            return
                        self.wfile.flush()
                    while True:
                        try:
                            line = q.get(timeout=15)
                        except Exception:
                            try:
                                self.wfile.write(b": keepalive\n\n")
                                self.wfile.flush()
                            except OSError:
                                return
                            continue
                        try:
                            self.wfile.write(
                                b"data: " + json.dumps(line, ensure_ascii=False).encode("utf-8") + b"\n\n"
                            )
                            self.wfile.flush()
                        except OSError:
                            return
                finally:
                    server.manager.unsubscribe_logs(q)

            # -- 调试视图 SSE（订阅独立 RawView 缓冲，不再过滤日志流）--------
            def _sse_debug(self) -> None:
                """把 bot 经 /api/debug/ingest 上报的 RawView 事件以 SSE 推送。

                数据链路：rawview._ingest → HTTP POST /api/debug/ingest
                → 本端点（独立缓冲）→ SSE
                """
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                q = server._rawview.subscribe()
                try:
                    for line in server._rawview.snapshot(200):
                        try:
                            self.wfile.write(
                                b"data: " + line.encode("utf-8") + b"\n\n"
                            )
                        except OSError:
                            return
                        self.wfile.flush()
                    while True:
                        try:
                            line = q.get(timeout=25)
                        except Exception:
                            # 心跳保持连接
                            try:
                                self.wfile.write(b": ping\n\n")
                                self.wfile.flush()
                            except OSError:
                                return
                            continue
                        try:
                            self.wfile.write(
                                b"data: " + line.encode("utf-8") + b"\n\n"
                            )
                            self.wfile.flush()
                        except OSError:
                            return
                finally:
                    server._rawview.unsubscribe(q)

            def _debug_snapshot(self) -> None:
                """从独立 RawView 缓冲提取最近事件，判断是否有活跃会话。"""
                lines = server._rawview.snapshot()
                events = []
                for line in lines:
                    try:
                        events.append(json.loads(line))
                    except (json.JSONDecodeError, TypeError):
                        pass
                # 判断最近是否有 begin 事件（无对应 end）
                has_live = False
                for ev in reversed(events):
                    if ev.get("type") == "end":
                        break
                    if ev.get("type") in ("begin", "sync"):
                        has_live = True
                        break
                self._json({
                    "ok": True,
                    "has_live": has_live,
                    "event_count": len(events),
                    "bot_running": server.manager.state().get("running", False),
                })

            def _api_state(self) -> dict:
                st = server.manager.state()
                ports = port_status()
                return {
                    "bot": st,
                    "token_required": bool(server.password_hash) or bool(server.token),
                    "need_setup": not server.password_hash,
                    "ports": ports,
                }

            def _api_feedback_meta(self) -> dict:
                """意见反馈随附的环境信息: 操作系统 / 运行路径 / 是否 Docker / 启用的 MCP 源 / 启动的插件。"""
                sys_name = platform.system()
                meta = {
                    "platform": sys.platform,
                    "system": f"{sys_name} {platform.release()}" if sys_name else sys.platform,
                    "machine": platform.machine(),
                    "python": sys.version.splitlines()[0] if sys.version else sys.version,
                    "hostname": socket.gethostname(),
                    "run_path": str(_PROJECT_ROOT),
                    "cwd": os.getcwd(),
                    "user": os.path.expanduser("~"),
                    "in_docker": _in_docker(),
                    "docker_compose_exists": os.path.isfile(str(_PROJECT_ROOT / "docker-compose.yml")),
                    "config_exists": os.path.isfile(str(_PROJECT_ROOT / "config.ini")),
                    "mcp_enabled": self._mcp_enabled(),
                    "mcp_servers": self._enabled_mcp_servers(),
                    "plugins": self._loaded_plugins(),
                }
                return {"meta": meta}

            def _mcp_enabled(self) -> bool:
                """config.ini [mcp] enabled（内建 MCP 服务是否开启）。"""
                try:
                    v = config_edit.read_ini()
                    return (v["values"].get("mcp", {}) or {}).get("enabled", "").strip().lower() in ("1", "true", "on", "yes")
                except Exception:  # noqa: BLE001
                    return False

            def _enabled_mcp_servers(self) -> list:
                """[mcpsources] 中启用的外部 MCP 源：只列名字与传输类型，不含 URL/密钥。"""
                out = []
                try:
                    v = config_edit.read_ini()
                    for s in v.get("sources", []):
                        if not s.get("enabled"):
                            continue
                        raw = str(s.get("raw", ""))
                        if raw.startswith("{"):
                            kind = "stdio"
                        elif raw.lower().startswith(("http://", "https://")):
                            kind = "http"
                        elif raw.startswith("mcp://"):
                            kind = "mcp"
                        else:
                            kind = "other"
                        out.append({"name": str(s.get("name", "")), "transport": kind})
                except Exception:  # noqa: BLE001
                    return []
                return out

            def _loaded_plugins(self) -> list:
                """扫描 plugins/*/manifest.json 得到启动的插件列表（与 bot 端 PluginManager.load_all 同源）。"""
                out = []
                try:
                    root = _PROJECT_ROOT / "plugins"
                    if root.is_dir():
                        for mp in sorted(root.glob("*/manifest.json")):
                            try:
                                m = json.loads(mp.read_text(encoding="utf-8"))
                            except Exception:  # noqa: BLE001
                                continue
                            out.append({
                                "name": str(m.get("name", mp.parent.name)),
                                "description": str(m.get("description", "") or ""),
                            })
                except Exception:  # noqa: BLE001
                    return []
                return out

            def _api_auth_status(self) -> dict:
                """鉴权状态: 前端据此决定 设置密码 / 登录 / 进入主界面。"""
                if not server.password_hash:
                    return {"need_setup": True, "authed": False, "token_required": False}
                given = self._credential()
                authed = bool(given and (
                    server._session_valid(given)
                    or (server.token and given == server.token)
                ))
                return {"need_setup": False, "authed": authed, "token_required": True}

            def _api_login(self, body: dict) -> dict:
                """登录: 密码(首选) 或 旧 token(兼容)。成功后发放会话。"""
                if not server.password_hash:
                    return {"need_setup": True, "error": "尚未设置登录密码, 请先设置"}
                pw = str(body.get("password", "") or "")
                tok = str(body.get("token", "") or "")
                if tok and server.token and tok == server.token:
                    return {"ok": True, "session": server._new_session()}
                if pw and server._verify_password(pw, server.password_hash):
                    return {"ok": True, "session": server._new_session()}
                return {"ok": False, "error": "密码错误"}

            def _api_setup(self, body: dict) -> dict:
                """首次设置登录密码(仅未设置时可用)。"""
                if server.password_hash:
                    return {"ok": False,
                            "error": "密码已设置; 如需修改请编辑 data/webconsole_auth.json 后重启"}
                pw = str(body.get("password", "") or "")
                if len(pw) < 6:
                    return {"ok": False, "error": "密码至少 6 位"}
                server.password_hash = server._hash_password(pw)
                server._save_password_hash(server.password_hash)
                return {"ok": True, "session": server._new_session()}

            def _ob_status(self) -> dict:
                """OB 后台连通性与鉴权状态（用于记忆页引导）。

                已登录过（密码已保存）时自动用保存的密码重新登录，无需
                再次输入；自动登录失败（如密码已改）则保持未登录状态。
                """
                try:
                    st = server.ob.status()
                    if st.get("ok") and not st.get("authenticated") and not st.get("setup_needed"):
                        server.ob.login_saved()
                        st = server.ob.status()
                except RuntimeError as e:
                    return {"ok": False, "error": str(e), "setup_needed": False,
                            "authenticated": False}
                return {"ok": True, **{k: st[k] for k in ("authenticated", "setup_needed")}}

            def _api_platforms(self) -> dict:
                """已注册平台列表 + 当前启用平台 + 适配器展示名。"""
                from botapp.platform.registry import list_platforms

                try:
                    ids = list_platforms()
                except Exception:  # noqa: BLE001 平台插件导入失败不影响列表
                    ids = []
                current = config_edit.read_ini()["values"].get("platform", {}).get("name", "")
                st = server.manager.state()
                return {
                    "platforms": ids,
                    "current": current or "",
                    "running": bool(st["running"]),
                    "friendly": _PLATFORM_NAMES,
                }

            def _conv_dir(self) -> Path:
                """对话存档目录（配置值，相对路径按项目根解析）。"""
                ini = config_edit.read_ini()
                dir_val = (ini["values"].get("conversation", {}) or {}).get("dir") or "conversation"
                conv_path = Path(dir_val)
                if not conv_path.is_absolute():
                    conv_path = dataops._ROOT / conv_path
                return conv_path

            def _api_users(self) -> dict:
                """存在的用户 ID：对话存档目录 + 日志中收发双方，去重排序。"""
                users: set[str] = set()
                try:
                    from botapp.store import ConversationStore

                    conv_path = self._conv_dir()
                    if conv_path.is_dir():
                        for u in ConversationStore(conv_path).list_real_users():
                            if u:
                                users.add(u)
                except Exception:  # noqa: BLE001 存档损坏不影响用户列表
                    pass
                tag_re = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] \[(?:Receive|Reply|Controller)\] (.+?): ")
                for line in server.manager.logs(4000):
                    m = tag_re.match(line)
                    if m:
                        u = m.group(1).strip()
                        if u:
                            users.add(u)
                return {"users": sorted(users)}

            def _api_history(self, user: str) -> dict:
                """读取某用户的对话存档记录（conversation/ 下按用户 JSON）。"""
                if not user:
                    return {"messages": []}
                try:
                    from botapp.store import ConversationStore

                    store = ConversationStore(self._conv_dir())
                    msgs = store.load(user)
                    return {"messages": msgs}
                except Exception as e:  # noqa: BLE001
                    return {"messages": [], "error": str(e)}

            def _api_platform_switch(self, body: dict) -> dict:
                """切换 [platform] name 并写回 config.ini（需重启机器人生效）。"""
                name = str(body.get("name") or "").strip()
                try:
                    from botapp.platform.registry import list_platforms

                    ids = list_platforms()
                except Exception:  # noqa: BLE001
                    ids = []
                if not ids:
                    raise RuntimeError("未发现任何平台适配器")
                if name not in ids:
                    raise RuntimeError(
                        f"平台 {name!r} 未注册。可用平台: {', '.join(ids)}"
                    )
                config_edit.save_ini({"platform": {"name": name}}, None, None)
                running = bool(server.manager.state()["running"])
                return {"ok": True, "restart_required": running}

            def _api_test_message(self, body: dict) -> dict:
                """代理注入消息到 bot 进程内的测试服务（19001）。"""
                user_id = str(body.get("user_id") or "").strip()
                text = str(body.get("text") or "").strip()
                if not user_id or not text:
                    return {"ok": False, "error": "user_id 和 text 不能为空"}
                st = server.manager.state()
                if not st["running"]:
                    return {"ok": False, "error": "机器人未在运行，请先在概览页启动"}
                payload = json.dumps({"user_id": user_id, "text": text}).encode("utf-8")
                req = urllib.request.Request(
                    f"http://127.0.0.1:{TEST_HTTP_PORT}/api/test/message",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        obj = json.loads(resp.read().decode("utf-8") or "{}")
                except urllib.error.HTTPError as e:
                    try:
                        obj = json.loads(e.read().decode("utf-8") or "{}")
                    except (OSError, ValueError):
                        obj = {}
                    return {"ok": False, "error": obj.get("error", f"HTTP {e.code}")}
                except OSError as e:
                    return {"ok": False, "error": f"注入服务不可达: {e}"}
                if not obj.get("ok", False) and obj.get("result") != "ok":
                    return {"ok": False, "error": obj.get("error", "未知错误")}
                return {"ok": True, "result": "消息已注入，请查看对话流或微信"}

        return Handler


# ---------------------------------------------------------------------------
# 端口检测（跨平台）
# ---------------------------------------------------------------------------
def port_status() -> dict:
    out = {}
    for port, desc in WATCH_PORTS:
        out[port] = {
            "desc": desc,
            "in_use": _tcp_check(port),
            "pids": _port_pids(port),
        }
    return out


def _tcp_check(port: int) -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
        s.close()
        return True
    except OSError:
        return False


def _port_pids(port: int) -> list[int]:
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # Windows 下 netstat 输出可能是 GBK 编码(含中文), 不能用 text=True
            out = (proc.stdout or b"").decode("utf-8", errors="ignore")
        except (OSError, subprocess.SubprocessError):
            return []
        pids = []
        for raw in out.splitlines():
            line = raw.strip()
            if "LISTENING" not in line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            addr = parts[1]
            if ":" not in addr:
                continue
            try:
                if int(addr.rsplit(":", 1)[-1]) != port:
                    continue
            except ValueError:
                continue
            try:
                pids.append(int(parts[-1]))
            except ValueError:
                continue
        return pids
    # POSIX：解析 /proc/net/tcp(+tcp6) 的 LISTEN inode → /proc/<pid>/fd
    return _posix_port_pids(port)


def _posix_port_pids(port: int) -> list[int]:
    inodes = set()
    for fn in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(fn, "r", encoding="utf-8") as f:
                lines = f.readlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 10 or parts[3] != "0A":
                continue  # 0A = LISTEN
            addr = parts[1]
            try:
                p = int(addr.rsplit(":", 1)[-1], 16)
            except ValueError:
                continue
            if p == port:
                inodes.add(parts[9])
    if not inodes:
        return []
    pids = []
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        fd_dir = entry / "fd"
        try:
            for fd in fd_dir.iterdir():
                try:
                    target = os.readlink(str(fd))
                except OSError:
                    continue
                if target.startswith("socket:["):
                    inode = target[8:-1]
                    if inode in inodes and int(entry.name) not in pids:
                        pids.append(int(entry.name))
                        if len(inodes) and len(pids) == len(inodes):
                            return pids
        except OSError:
            continue
    return pids


def kill_pid(pid: int) -> None:
    import signal

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            pass
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
