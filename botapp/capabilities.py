#通过能力名而非具体工具名调用外部 MCP 源。举例 dream可以匹配不同工具 而不是硬编码


from __future__ import annotations

from typing import Iterable

# 内置能力定义：能力名 → 该能力通常涉及的工具（简称）。
# capability 字段可用 dict 覆盖：{"capability": {"memory": ["breath","hold"]}}
_CAPABILITY_TOOLS: dict[str, list[str]] = {
    "memory": ["breath", "dream", "hold", "letter_read", "letter_write", "plan", "trace"],
    "archive": ["add_record"],
    "event": ["list_users", "query_events"],
}


class CapabilityRegistry:
    """从 MCP 源描述符解析能力声明，提供工具名解析。"""

    def __init__(self, sources: Iterable[dict]) -> None:
        # {capability: {tool_short: "namespace-tool"}}
        self._providers: dict[str, dict[str, str]] = {}
        self._warmups: list[str] = []
        for src in sources:
            self.register_source(src)

    # ------------------------------------------------------------------
    def register_source(self, src: dict) -> None:

        cap = src.get("capability")
        if not cap:
            return
        ns = src.get("namespace", "")
        if isinstance(cap, str):
            caps = {cap: _CAPABILITY_TOOLS.get(cap, [])}
        elif isinstance(cap, dict):
            caps = cap
        else:
            return
        for name, tools in caps.items():
            self._providers.setdefault(name, {})
            for tool in tools:
                self._providers[name][tool] = f"{ns}-{tool}" if ns else tool
        # 预热工具（启动时建立常驻连接）
        warmup = src.get("warmup")
        if warmup:
            tool = warmup if isinstance(warmup, str) else ""
            if tool:
                self._warmups.append(f"{ns}-{tool}" if ns else tool)

    # ------------------------------------------------------------------
    def names(self) -> list[str]:
        """已注册的能力名列表（升序）。"""
        return sorted(self._providers)

    def has(self, capability: str) -> bool:
        """是否有提供者。"""
        return capability in self._providers and bool(self._providers[capability])

    def tool(self, capability: str, tool: str) -> str | None:
        """返回能力下某工具的全名（namespace-tool）；未注册返回 None。"""
        return self._providers.get(capability, {}).get(tool)

    def tools(self, capability: str) -> list[str]:
        """返回能力下已注册的全部工具全名（升序）。"""
        return sorted(self._providers.get(capability, {}).values())

    def warmup_tools(self) -> list[str]:
        """返回所有声明了 warmup 的工具全名（启动时逐个预热）。"""
        return list(self._warmups)
