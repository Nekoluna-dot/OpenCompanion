"""网页控制台：跨平台 bot 进程管理（对应 scripts/launcher.py 的进程管理部分）。

- 用 subprocess 拉起 bot 主进程（解释器 = 本进程的 sys.executable，
  Windows 上使用 runtime/python/python.exe，容器里就是容器内 python）
- 捕获 stdout/stderr → 环形日志缓冲 + SSE 订阅者分发
- 自动重启（异常退出后拉起，手动停止不触发）
- 二维码行识别（终端块字符），供网页原样显示扫码
"""

from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# 终端二维码用到的 Unicode 块字符
_QR_BLOCK_RE = re.compile(r"[█▀▄▐▌▪▫▬■□▮▯⣿⣠⣤⣦⣧⣩⣫⣭⣮⣯⣰⣱⣲⣳⣴⣵⣶⣷]")
# MCP SDK 会为每个工具调用在日志里刷一行 "Processing request of type ..."，
# 已经在 bot 侧压低日志级别，这里再做一道捕获层兜底过滤（仅精确匹配，
# 避免误吞真正的错误信息）。
_MCP_NOISE = {
    "Processing request of type CallToolRequest",
    "Processing request of type ListToolsRequest",
    "Processing request of type InitializeRequest",
    "Processing request of type PingRequest",
    "Processing request of type SendNotificationRequest",
}

_ROOT = Path(__file__).resolve().parent.parent.parent
_SETTINGS_PATH = _ROOT / "data" / "webconsole_settings.json"
_LOCK_PATH = _ROOT / "data" / "bot.lock"

# 聊天模拟测试服务端口（bot 子进程内监听 127.0.0.1）
TEST_HTTP_PORT = 19001


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def is_qr_line(line: str) -> bool:
    """二维码行：包含大量块字符且几乎无其他文本（去空格后全是块字符）。"""
    stripped = line.strip()
    if len(stripped) < 4:
        return False
    blocks = _QR_BLOCK_RE.findall(stripped)
    return len(blocks) >= 4 and len(blocks) >= len(stripped) * 0.5


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_uint32()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class LogRing:
    """环形日志缓冲：新行进缓冲 + 分发到订阅队列。"""

    def __init__(self, maxlen: int = 4000) -> None:
        self._buf: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue] = []

    def append(self, line: str) -> None:
        with self._lock:
            self._buf.append(line)
            for q in list(self._subscribers):
                try:
                    q.put(line, timeout=0.1)
                except Exception:
                    pass

    def snapshot(self, tail: int | None = None) -> list[str]:
        with self._lock:
            lines = list(self._buf)
        return lines[-tail:] if tail else lines

    def subscribe(self) -> queue.Queue:
        with self._lock:
            q: queue.Queue = queue.Queue(maxsize=2000)
            self._subscribers.append(q)
            return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()


class BotProcessManager:
    """bot 主进程生命周期管理。"""

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root else _ROOT
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._logs = LogRing()
        self._manual_stop = False
        self._restart_pending = False
        self._start_time: float | None = None
        self._pump_thread: threading.Thread | None = None
        self._watch_thread: threading.Thread | None = None
        self._closing = False
        self.auto_restart = bool(self._load_settings().get("auto_restart_bot", True))
        self._watch_thread = threading.Thread(
            target=self._watch_loop, name="wc-watch", daemon=True
        )
        self._watch_thread.start()

    # ------------------------------------------------------------------
    # 设置持久化
    # ------------------------------------------------------------------
    def _load_settings(self) -> dict:
        try:
            return json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            data = self._load_settings()
            data["auto_restart_bot"] = bool(self.auto_restart)
            self._settings_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    @property
    def _settings_path(self) -> Path:
        return _SETTINGS_PATH

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def state(self) -> dict:
        proc = self._proc
        running = proc is not None and proc.poll() is None
        uptime = None
        if running and self._start_time is not None:
            uptime = max(0, int(time.time() - self._start_time))
        pid = proc.pid if running else None
        lock_pid = None
        if not running and _LOCK_PATH.exists():
            try:
                lock_pid = int(_LOCK_PATH.read_text(encoding="utf-8").strip() or 0)
            except (OSError, ValueError):
                lock_pid = None
            if lock_pid and not pid_alive(lock_pid):
                lock_pid = None
        return {
            "running": running,
            "pid": pid,
            "uptime": uptime,
            "auto_restart": bool(self.auto_restart),
            "manual_stop": self._manual_stop,
            "started_by_console": self._start_time is not None,
            "stale_lock_pid": lock_pid,
        }

    def logs(self, tail: int | None = None) -> list[str]:
        return self._logs.snapshot(tail)

    def subscribe_logs(self):
        return self._logs.subscribe()

    def unsubscribe_logs(self, q) -> None:
        self._logs.unsubscribe(q)

    def clear_logs(self) -> None:
        self._logs.clear()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> str:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return "机器人已在运行。"
            if not (self._root / "main.py").exists():
                return "未找到 main.py（项目根目录不对）"
            # 清理残留运行锁（进程已死时）
            self._cleanup_stale_lock()
            try:
                self._proc = subprocess.Popen(
                    [sys.executable, "main.py"],
                    cwd=str(self._root),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env={
                        **os.environ,
                        "PYTHONIOENCODING": "utf-8",
                        "PYTHONUNBUFFERED": "1",
                        "BOT_TEST_HTTP_PORT": str(TEST_HTTP_PORT),
                    },
                )
            except OSError as e:
                return f"启动失败: {e}"
            self._manual_stop = False
            self._restart_pending = False
            self._start_time = time.time()
            self._pump_thread = threading.Thread(
                target=self._pump, name="wc-pump", daemon=True
            )
            self._pump_thread.start()
            self._logs.append("[控制台] 机器人启动中...")
            return "ok"

    def stop(self) -> str:
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                return "机器人未在运行。"
            self._manual_stop = True
            pid = proc.pid
        self._kill_tree(pid)
        self._logs.append(f"[控制台] 已发送停止信号 PID {pid}")
        return "ok"

    def restart(self) -> str:
        if self._proc is not None and self._proc.poll() is None:
            with self._lock:
                self._manual_stop = True
                pid = self._proc.pid
            self._kill_tree(pid)
            time.sleep(1.5)
        with self._lock:
            self._manual_stop = False
        return self.start()

    def set_auto_restart(self, enabled: bool) -> None:
        self.auto_restart = bool(enabled)
        self._save_settings()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _cleanup_stale_lock(self) -> None:
        if not _LOCK_PATH.exists():
            return
        try:
            pid = int(_LOCK_PATH.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            pid = 0
        if pid > 0 and pid_alive(pid):
            return
        try:
            _LOCK_PATH.unlink(missing_ok=True)
        except OSError:
            pass

    def _pump(self) -> None:
        """逐行读取子进程输出：低延迟，不等待缓冲区填满。"""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            # 用 readline 而非 read(1024)：日志是行式的，不需要等缓冲区填满
            # PYTHONUNBUFFERED=1 已在启动时设置，确保子进程 stdout 无缓冲
            import io as _io
            buf = _io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace", newline=None)
            while True:
                line = buf.readline()
                if not line:
                    break
                stripped = strip_ansi(line.rstrip("\r\n"))
                if not stripped:
                    continue
                if stripped in _MCP_NOISE:
                    continue
                self._logs.append(stripped)
        except Exception:
            pass
        finally:
            self._logs.append("--- 进程退出 ---")

    def _kill_tree(self, pid: int) -> None:
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
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            if sig == signal.SIGTERM:
                try:
                    time.sleep(1.0)
                except Exception:
                    pass

    def _watch_loop(self) -> None:
        """进程退出后若开启自动重启则拉起（手动停止不触发）。"""
        while not self._closing:
            time.sleep(2.0)
            proc = self._proc
            if proc is None:
                continue
            if proc.poll() is None:
                continue
            if self._manual_stop or not self.auto_restart:
                continue
            if self._restart_pending:
                continue
            self._restart_pending = True
            self._logs.append("[控制台] 检测到机器人进程已退出，3 秒后自动重启...")
            time.sleep(3.0)
            self._restart_pending = False
            if self._closing:
                return
            if self._manual_stop or not self.auto_restart:
                continue
            self.start()

    def close(self) -> None:
        self._closing = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            self._kill_tree(proc.pid)
