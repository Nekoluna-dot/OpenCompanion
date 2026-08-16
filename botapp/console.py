import ctypes
import os
import sys
import time

# ANSI 颜色
_BOLD = "\033[1m"
_RESET = "\033[0m"
_GRAY = "\033[90m"
_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_BLUE = "\033[94m"
_MAGENTA = "\033[95m"
_CYAN = "\033[96m"
_WHITE = "\033[97m"


def _supports_color(stream) -> bool:

    try:
        if not stream.isatty():
            return False
    except Exception:
        return False
    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass
    return True


class Console:
    def __init__(self, use_color: bool | None = None, stream=None) -> None:
        self._stream = stream or sys.stdout
        if use_color is None:
            use_color = _supports_color(self._stream)
        self.use_color = use_color

    # ------------------------------------------------------------------
    def _paint(self, text: str, color: str | None) -> str:
        if not self.use_color or not color:
            return text
        return f"{color}{text}{_RESET}"

    def _emit(self, tag: str, color: str | None, message: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] [{tag}] {message}"
        if self.use_color:
            # 整个行按类别着色，标签加粗
            tag_s = f"{_BOLD}[{tag}]{_RESET}"
            line = f"{color}[{ts}]{_RESET} {tag_s} {self._paint(message, color)}"
        print(line, file=self._stream, flush=True)

    # ------------------------------------------------------------------
    # 通用
    # ------------------------------------------------------------------
    def info(self, message: str) -> None:
        self._emit("Info", _GREEN, message)

    def warn(self, message: str) -> None:
        self._emit("Warning", _YELLOW, message)

    def error(self, message: str) -> None:
        self._emit("Error", _RED, message)

    def config(self, message: str) -> None:
        self._emit("Config", _CYAN, message)

    def mcp(self, message: str) -> None:
        """向后兼容别名，实际输出 [Plugins] 标签。"""
        self._emit("Plugins", _MAGENTA, message)

    def plugins(self, message: str) -> None:
        self._emit("Plugins", _CYAN, message)

    def thinking(self, message: str) -> None:
        self._emit("Thinking", _CYAN, message)

    # ------------------------------------------------------------------
    # 机器人事件
    # ------------------------------------------------------------------
    def recv(self, user: str, text: str) -> None:
        self._emit("Receive", _GREEN, f"{user}: {text}")

    def reply(self, user: str, text: str) -> None:
        self._emit("Reply", _CYAN, f"{user}: {text[:60]}...")

    def control(self, user: str, text: str) -> None:
        self._emit("Controller", _YELLOW, f"{user}: {text[:40]}...")

    def generated(self, length: int) -> None:
        self._emit("Output", _BLUE, f"完成，{length} 字")

    def timing(self, items: dict) -> None:
        parts = "  ".join(f"{k}={v:.2f}s" for k, v in items.items())
        self._emit("Used Time", _YELLOW, parts)

    def merge(self, wait: float, count: int) -> None:
        self._emit("合并文本", _BLUE, f"等待 {wait:.2f}s，共 {count} 条消息")

    # ------------------------------------------------------------------
    # LLM / 工具
    # ------------------------------------------------------------------
    def agent_round(self, n: int) -> None:
        self._emit("Agent", _MAGENTA, f"第 {n} 轮调用 LLM...")

    def tool_call(self, name: str, args: str) -> None:
        self._emit("Tool", _MAGENTA, f"LLM调用了工具 {name}({args})")

    def tool_result(self, name: str, dur: float, output: str) -> None:
        self._emit("Tool", _BLUE, f"{name} 返回（{dur:.2f}s）: {output[:120]}")

    def auto_send(self, user: str, kind: str, path: str) -> None:
        self._emit("Send", _GREEN, f"auto_send {kind} → {user} ({path})")

    def llm_stats(self, ttfb: float, out: float, total: float) -> None:
        self._emit(
            "LLM",
            _CYAN,
            f"等待={ttfb:.2f}s 输出={out:.2f}s 合计={total:.2f}s",
        )

    def token(self, prompt: int, completion: int, cache_hit: int = 0) -> None:
        if cache_hit:
            self._emit(
                "Token",
                _BLUE,
                f"输入={prompt}(缓存命中{cache_hit}) 输出={completion} 总计={prompt + completion}",
            )
        else:
            self._emit("Token", _BLUE, f"输入={prompt} 输出={completion} 总计={prompt + completion}")
    # 协议诊断
    def proto(self, method: str, endpoint: str, ms: float) -> None:
        self._emit(f"{method} {endpoint}", _GRAY, f"{ms:.0f} ms")

    # ------------------------------------------------------------------
    # RawView 调试事件（特殊前缀，供 webconsole /api/debug/events 过滤）
    # ------------------------------------------------------------------
    def rawview_event(self, data: str) -> None:
        # begin 事件包含完整系统提示+工具定义（几万字），日志只显示摘要
        if '"type":"begin"' in data or '"type": "begin"' in data:
            try:
                import json as _j
                obj = _j.loads(data)
                obj.pop("context_html", None)
                data = _j.dumps(obj, ensure_ascii=False)
            except Exception:
                pass
        self._emit("RawView", _MAGENTA, data)


console = Console()
