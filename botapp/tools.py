import asyncio
import json
from pathlib import Path

from botapp.capabilities import CapabilityRegistry
from botapp.config import AppConfig
from botapp.console import console

_BASE_DIR = Path(__file__).resolve().parent.parent


def _strip_titles(schemas: list[dict]) -> list[dict]:
    """递归删除 schema 中的冗余 title 字段（Pydantic 自动生成），节省 token。"""

    def clean(obj):
        if isinstance(obj, dict):
            obj.pop("title", None)
            for v in obj.values():
                clean(v)
        elif isinstance(obj, list):
            for v in obj:
                clean(v)
        return obj

    return clean(schemas)


class McpTools:
    """标准工具：列表查询与调用执行（含外部 MCP 源接入）。"""

    def __init__(self, platform, config: AppConfig) -> None:
        self._platform = platform
        self._config = config
        self._registry = None
        # 对 LLM 隐藏的 namespace（由插件系统动态加入）：工具仍可被 invoke，
        # 但不出现在 list_openai_tools() 的 LLM 可见列表。
        self._hidden_namespaces: set[str] = set()
        # 能力注册表：从 mcp_sources 的 capability 声明构建，主代码据此
        # 调用"记忆/档案/事件"等能力，不硬编码具体 namespace 名。
        self.capabilities = CapabilityRegistry(config.mcp_sources)

    def hide_namespace(self, namespace: str) -> None:
        """把某 namespace 的全部工具从 LLM 可见列表隐藏（调用不受影响）。"""
        self._hidden_namespaces.add(namespace)

    # ------------------------------------------------------------------
    def _get_registry(self):
        if self._registry is None:
            from toolregistry import ToolRegistry

            # 平台内建工具（weilink send/recv 等）不暴露给 LLM：
            # 收/发消息由适配器自动处理，媒体发送走 send_media 代码路径。
            # 外部 MCP 工具源照常接入。
            self._registry = ToolRegistry(name="base")
            for src in self._config.mcp_sources:
                self._register_external(src)
        return self._registry

    def register_external(self, src: dict) -> None:
        """对外暴露：注册一个外部 MCP 源（插件系统调用）。"""
        self._get_registry()
        self._register_external(src)

    def _register_external(self, src: dict) -> None:
        """把一个外部 MCP 源注册进注册表；失败不影响其他工具。"""
        try:
            self._registry.register_from_mcp(
                src["transport"],
                namespace=src["namespace"],
            )
            desc = dict(src["transport"])
            desc.pop("env", None)
            console.mcp(
                f"已接入外部 MCP 工具源: {src['name']} "
                f"({desc}) namespace={src['namespace']}"
            )
            # 源声明了 warmup（常驻连接预热）时，注册成功后立即预热
            self._warm_connections()
        except (Exception, asyncio.CancelledError) as e:
            console.warn(f"接入外部 MCP 工具源 {src['name']} 失败: {e}")

    def _warm_connections(self) -> None:
        #这里是声明MCP插件是否需要尝试在后台运行
        for tool in self.capabilities.warmup_tools():
            if tool not in self._registry:
                continue
            try:
                self._registry.invoke(tool, {})
            except (Exception, asyncio.CancelledError) as e:
                console.warn(f"常驻连接预热失败 {tool}: {e}")

    # storage_info 是内部元数据协议工具（插件声明自己的数据存储位置），
    # 不暴露给 LLM，避免模型误调。
    _META_SUFFIX = "-storage_info"

    def list_openai_tools(self) -> list[dict]:

        schemas = self._get_registry().get_schemas(api_format="openai-chat")
        out: list[dict] = []
        for s in schemas:
            fn = s.get("function") or {}
            name = str(fn.get("name") or s.get("name") or "")
            if name.endswith(self._META_SUFFIX):
                continue
            ns = name.split("-", 1)[0] if "-" in name else ""
            if ns in self._hidden_namespaces:
                continue
            out.append(s)
        return _strip_titles(out)

    def get_storage_declarations(self, user_id: str) -> list[dict]:

        registry = self._get_registry()
        out: list[dict] = []
        for src in self._config.mcp_sources:
            ns = src["namespace"]
            tool_name = f"{ns}{self._META_SUFFIX}"
            item = {
                "name": src["name"],
                "namespace": ns,
                "declared": False,
                "declaration": None,
                "error": "",
            }
            if registry.get_tool(tool_name) is None:
                out.append(item)
                continue
            item["declared"] = True
            try:
                result = registry.invoke(tool_name, {"user_id": user_id})
                result = self._normalize_result(result)
                if isinstance(result, str):
                    result = json.loads(result)
                item["declaration"] = result
            except (Exception, asyncio.CancelledError) as e:
                item["error"] = str(e)
            out.append(item)
        return out

    def call_tool(self, name: str, arguments: dict) -> str:
        #执行工具调用，返回 JSON 字符串。
        try:
            result = self._get_registry().invoke(name, arguments or {})
            result = self._normalize_result(result)
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False)
            return str(result)
        except (Exception, asyncio.CancelledError) as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @staticmethod
    def _normalize_result(result):
        """把 MCP 返回值归一化为可 JSON 化的 dict/list/str。"""
        import json as _json

        # MCP CallToolResult / CallToolResultDict：优先取 structuredContent
        sc = getattr(result, "structuredContent", None)
        if sc is None and isinstance(result, dict):
            sc = result.get("structuredContent")
        if sc is not None:
            if isinstance(sc, dict) and "result" in sc:
                return sc["result"]
            return sc

        # TextContent 列表：[{"type":"text","text":"..."}]（text 可能是完整 JSON）
        if isinstance(result, list) and result and all(
            isinstance(i, dict) and i.get("type") == "text" for i in result
        ):
            parsed = []
            for i in result:
                text = str(i.get("text", ""))
                try:
                    parsed.append(_json.loads(text))
                except (_json.JSONDecodeError, TypeError):
                    parsed.append(text)
            # 单条 text → 直接返回其解析值；多条 → 合并（事件数组等场景）
            if len(parsed) == 1:
                return parsed[0]
            # 若所有条目都能合并为列表（如多条事件 JSON），尝试合并
            merged = []
            for item in parsed:
                if isinstance(item, list):
                    merged.extend(item)
                else:
                    merged.append(item)
            return merged

        return result
