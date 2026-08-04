#已废弃 但是prompt里面可能使用 暂时不删 后续干掉
import re

from botapp.console import console


class ReplyMarkers:
    """特殊标记处理器：解析回复 → 执行动作 → 剥掉标记。"""

    def __init__(self, tools=None) -> None:
        self._tools = tools
        self._handlers: dict[str, callable] = {}
        self._content_markers: set[str] = set()
        self.last_results: list[str] = []

    def register(self, name: str, handler, with_content: bool = False) -> None:
        """绑定标记名 → 处理函数。

        with_content=False：无参调用 handler(user_id="")。
        with_content=True：匹配 <name>正文</name>，调用 handler(正文, user_id="")。
        """
        self._handlers[name] = handler
        if with_content:
            self._content_markers.add(name)

    def names(self) -> list[str]:
        """当前已注册的标记名（供提示词/帮助文档引用）。"""
        return sorted(self._handlers)

    def find(self, reply: str) -> list[str]:
        """找出回复里出现的、已注册的标记名（保持出现顺序）。"""
        return [name for name, _ in self._parse(reply)]

    def _parse(self, reply: str) -> list[tuple[str, str | None]]:
        """解析出 [(标记名, 正文或 None)]，按出现顺序。"""
        if not reply:
            return []
        out: list[tuple[str, str | None]] = []
        # 内容型：<name>正文</name>
        for name in sorted(self._content_markers, key=len, reverse=True):
            pattern = re.compile(rf"<{name}>\s*([\s\S]*?)\s*</{name}>")
            for m in pattern.finditer(reply):
                out.append((name, m.group(1)))
        # 无内容型：<name>
        plain = [n for n in self._handlers if n not in self._content_markers]
        if plain:
            pattern = re.compile(
                "|".join(rf"<({n})>" for n in sorted(plain, key=len, reverse=True))
            )
            for m in pattern.finditer(reply):
                out.append((m.group(1), None))
        return out

    def process(self, reply: str, user_id: str = "") -> str:
        """执行回复中所有已注册标记的动作，并剥掉标记返回干净文本。

        单个标记执行失败只记日志，不影响回复本身；last_results 记录
        本轮各标记的执行结果，供调用方（如 rawview）展示。
        """
        self.last_results = []
        found = self._parse(reply)
        if not found:
            return reply
        for name, content in found:
            try:
                if content is None:
                    result = self._handlers[name](user_id=user_id)
                else:
                    result = self._handlers[name](content, user_id=user_id)
                self.last_results.append(f"<{name}>: {result}")
                console.mcp(f"标记 <{name}> 触发: {str(result)[:200]}")
            except Exception as e:
                self.last_results.append(f"<{name}>: 失败 {e}")
                console.warn(f"标记 <{name}> 执行失败: {e}")
        for name, _ in found:
            if name in self._content_markers:
                # 内容型：标签 + 正文一起剥掉（正文是系统动作的私有输入）
                reply = re.sub(rf"<{name}>\s*[\s\S]*?\s*</{name}>", "", reply)
            else:
                reply = reply.replace(f"<{name}>", "")
        return reply
