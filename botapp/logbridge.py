"""日志桥：给插件 / MCP 服务器（stdio 子进程）提供一个 log 方法。

stdio 子进程的 stdout 是 MCP JSON-RPC 通道，任何日志打到 stdout 都会
污染管道、导致 client 解析失败（如 OB 的 uvicorn access log）。因此
本模块提供 emit()：子进程 import 后调用，日志只追加写 logs/bot.log
（与 bot 共用同一日志文件，带时间/级别/来源标记），完全不碰
stdout/stderr，保证 MCP 管道零污染。

子进程用法（bot 启动时已注入 PYTHONPATH 指向 BOT 根目录）：

    from botapp.logbridge import emit
    emit("info", "memory saved", "myplugin")

bot 内部代码同样可用（会额外输出到 console）：
    from botapp.logbridge import log
    log("warn", "something", "botapp")
"""

import logging
import threading
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from botapp.console import console

_BASE_DIR = Path(__file__).resolve().parent.parent
_LOG_DIR = _BASE_DIR / "logs"
_LOG_FILE = _LOG_DIR / "bot.log"

_logger = logging.getLogger("bot.logbridge")
_handler: RotatingFileHandler | None = None
_handler_lock = threading.Lock()

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_CONSOLE_EMIT = {
    logging.DEBUG: console.info,
    logging.INFO: console.info,
    logging.WARNING: console.warn,
    logging.ERROR: console.error,
    logging.CRITICAL: console.error,
}


def _ensure_handler() -> RotatingFileHandler:
    global _handler
    if _handler is None:
        with _handler_lock:
            if _handler is None:
                _LOG_DIR.mkdir(parents=True, exist_ok=True)
                _handler = RotatingFileHandler(
                    _LOG_FILE,
                    maxBytes=1_000_000,
                    backupCount=3,
                    encoding="utf-8",
                )
                _handler.setFormatter(
                    logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
                )
                _logger.addHandler(_handler)
                _logger.setLevel(logging.DEBUG)
                _logger.propagate = False
    return _handler


def emit(level: str = "info", message: str = "", source: str = "") -> str:
    """子进程安全版：只落盘 logs/bot.log，不写 stdout/stderr。

    MCP stdio 子进程专用——stdout 是协议通道不能碰，stderr 虽安全
    但不落盘。本函数以追加写文件，多进程并发安全。

    Args:
        level: debug / info / warn / error / critical，非法值回退 info。
        message: 日志正文。
        source: 来源标识（如插件名），可选。
    """
    lvl = _LEVELS.get(str(level or "").strip().lower(), logging.INFO)
    text = f"[{source}] {message}" if source else message
    _ensure_handler()
    _logger.log(lvl, text)
    return "ok"


def log(level: str = "info", message: str = "", source: str = "") -> str:
    """bot 进程内版：console 即时输出 + 落盘 logs/bot.log。

    Args:
        level: debug / info / warn / error / critical，非法值回退 info。
        message: 日志正文。
        source: 来源标识（如模块名），可选。
    """
    lvl = _LEVELS.get(str(level or "").strip().lower(), logging.INFO)
    text = f"[{source}] {message}" if source else message
    _ensure_handler()
    _logger.log(lvl, text)
    emit_fn = _CONSOLE_EMIT.get(lvl, console.info)
    emit_fn(f"[log{(':' + source) if source else ''}] {message}")
    return "ok"


class _PassthroughHandler(logging.Handler):
    """把标准 logging 记录转发进 logs/bot.log（子进程日志统一落盘）。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
            if record.exc_info:
                text += "\n" + "".join(
                    traceback.format_exception(*record.exc_info)
                )
            lvl = _LEVELS.get(str(record.levelname or "").lower(), logging.INFO)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = f"[{ts}] [{record.levelname}] [{record.name or 'child'}] {text}\n"
            _ensure_handler()
            # 直接以追加写，避免走 _logger 再次触发本 handler 的死循环
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass


def install_passthrough() -> None:
    """给 root logger 挂上转发 handler：本进程所有标准 logging 输出统一
    落盘 logs/bot.log（不碰 stdout/stderr，MCP 管道零污染）。

    供 stdio 子进程（插件 / MCP 服务器）调用；bot 启动子进程时已注入
    PYTHONPATH，配合 BOT 根目录 sitecustomize.py 自动执行本函数。
    幂等：重复调用无副作用。
    """
    root = logging.getLogger()
    if any(isinstance(h, _PassthroughHandler) for h in root.handlers):
        return
    _handler = _PassthroughHandler()
    _handler.setLevel(logging.DEBUG)
    root.addHandler(_handler)
