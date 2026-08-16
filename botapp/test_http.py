"""网页控制台：bot 进程内测试消息注入 HTTP 服务（标准库实现）。

作用：聊天模拟测试页通过网页控制台代理到本服务，把消息注入
bot 的消息管道（等价于平台上收到一条真实消息：正常走合并缓冲、
LLM 生成、分气泡发送，回复真实发送到微信）。

仅在环境变量 BOT_TEST_HTTP_PORT 设置时由 main.py 启动，不影响
正常使用；监听 127.0.0.1 只对本机开放，无鉴权（本机回环）。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def start_test_server(bot, port: int) -> ThreadingHTTPServer | None:
    """在后台线程启动测试消息服务；失败返回 None（已打印原因）。"""
    if port <= 0:
        return None

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def _json(self, obj, code: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/api/test/ping":
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if path != "/api/test/message":
                self._json({"error": "not found"}, 404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                body = {}
            user_id = str(body.get("user_id") or "").strip()
            text = str(body.get("text") or "").strip()
            if not user_id or not text:
                self._json({"error": "user_id 和 text 不能为空"}, 400)
                return
            try:
                from botapp.platform.base import BotMessage

                bot.on_message(BotMessage(from_user=user_id, text=text))
            except Exception as e:  # noqa: BLE001
                self._json({"error": f"消息处理失败: {e}"}, 500)
                return
            self._json({"result": "ok"})

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        return None
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="wc-test-http").start()
    return server