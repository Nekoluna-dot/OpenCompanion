import json
import importlib
from pathlib import Path

from botapp.console import console

_BASE_DIR = Path(__file__).resolve().parent.parent
_PLUGINS_DIR = _BASE_DIR / "plugins"


class Plugin:
    """单个已加载的插件实例。"""

    def __init__(self, manifest: dict, base_dir: Path) -> None:
        self.manifest = manifest
        self.base_dir = base_dir
        self.name: str = manifest.get("name", "")
        self.description: str = manifest.get("description", "")
        self.mcp: dict | None = manifest.get("mcp")
        self.trigger_conf: dict | None = manifest.get("trigger")
        self.reply_hook_conf: dict | None = manifest.get("on_user_reply")
        self.trigger = None  # 后台调度器实例（start() 后非空）
        self.reply_hook = None  # 用户回复钩子实例（instantiate 后非空）

    @property
    def mcp_source(self) -> dict | None:
        """构造给 McpTools 的外部源描述（相对路径已解析为绝对路径）。"""
        if not self.mcp:
            return None
        command = self.mcp.get("command", "")
        args = self.mcp.get("args", [])
        source = {
            "name": self.name,
            "transport": {
                "command": self._resolve(command),
                "args": [self._resolve(a) for a in args],
            },
            "namespace": self.name,
        }
        # 透传 capability / warmup 声明（能力注册表据此识别该源提供的能力）
        if self.mcp.get("capability"):
            source["capability"] = self.mcp["capability"]
        if self.mcp.get("warmup"):
            source["warmup"] = self.mcp["warmup"]
        return source

    def _resolve(self, p: str) -> str:
        if not p or (Path(p).is_absolute()):
            return p
        if "/" in p or "\\" in p:
            return str(self.base_dir.parent.parent / p)
        return p


class PluginManager:
    """插件加载器：扫描 plugins/，注册 MCP 源 + 启动后台调度器 + 注册钩子。"""

    def __init__(self, tools, bot=None) -> None:
        self._tools = tools
        self._bot = bot
        self._plugins: list[Plugin] = []
        self._by_name: dict[str, Plugin] = {}

    # ------------------------------------------------------------------
    def load_all(self) -> list[Plugin]:
        """扫描 plugins/ 下所有子目录的 manifest.json 并加载。"""
        if not _PLUGINS_DIR.is_dir():
            return []
        for manifest_path in sorted(_PLUGINS_DIR.glob("*/manifest.json")):
            try:
                self.load_manifest(manifest_path)
            except Exception as e:
                console.warn(f"插件加载失败 {manifest_path}: {e}")
        return list(self._plugins)

    def load_manifest(self, path: Path) -> Plugin:
        """加载单个插件的 manifest。"""
        manifest = json.loads(path.read_text(encoding="utf-8"))
        plugin = Plugin(manifest, base_dir=path.parent)

        # 注册 MCP 源
        source = plugin.mcp_source
        if source is not None:
            self._tools.register_external(source)
            if plugin.mcp.get("expose_to_llm", True) is False:
                self._tools.hide_namespace(plugin.name)
                console.config(
                    f"MCP {plugin.name} 工具已禁用"
                )

        self._plugins.append(plugin)
        self._by_name[plugin.name] = plugin
        console.config(
            f"已加载插件: {plugin.name}"
            + (f" — {plugin.description}" if plugin.description else "")
        )
        return plugin

    # ------------------------------------------------------------------
    def instantiate_triggers(self, bot) -> None:
        """为声明了 trigger 的插件实例化调度器，挂到 bot.<name>。"""
        for plugin in self._plugins:
            conf = plugin.trigger_conf
            if not conf:
                continue
            module = importlib.import_module(conf["module"])
            cls = getattr(module, conf["class"])
            plugin.trigger = cls(bot, interval=conf.get("interval", 60))
            setattr(bot, plugin.name, plugin.trigger)
            console.config(
                f"插件 {plugin.name} 调度器已就绪"
                f"（每 {conf.get('interval', 60)}s 轮询）"
            )

    def instantiate_reply_hooks(self) -> None:
        """为声明了 on_user_reply 的插件实例化钩子，注册到 bot。

        钩子声明支持两种形态：
          - {"module": "plugins.xxx", "class": "XxxHook"}：实例化类，
            要求构造签名 __init__(self, bot)，并实现 __call__(user_id, text)。
          - {"module": "plugins.xxx", "function": "on_reply"}：模块级函数，
            支持两种签名：on_reply(bot, user_id, text) 或 on_reply(user_id, text)。
        注册后统一以 hook(user_id, text) 被主代码调用；主代码不硬编码插件名。
        """
        if self._bot is None:
            return
        for plugin in self._plugins:
            conf = plugin.reply_hook_conf
            if not conf:
                continue
            module = importlib.import_module(conf["module"])
            if conf.get("class"):
                cls = getattr(module, conf["class"])
                hook = cls(self._bot)
            else:
                fn = getattr(module, conf.get("function", ""))
                # 适配带 bot 首参的模块级函数（on_reply(bot, user_id, text)）
                try:
                    import inspect

                    sig = inspect.signature(fn)
                    has_bot = len(sig.parameters) >= 3
                except (TypeError, ValueError):
                    has_bot = False

                def _make(f, _has_bot):
                    if _has_bot:
                        return lambda uid, text: f(self._bot, uid, text)
                    return f

                hook = _make(fn, has_bot)
            plugin.reply_hook = hook
            self._bot._user_reply_hooks.append(hook)
            console.config(f"插件 {plugin.name} 用户回复钩子已注册")

    def start(self) -> None:
        """启动所有插件调度器。"""
        for plugin in self._plugins:
            if plugin.trigger is not None:
                plugin.trigger.start()

    def stop(self) -> None:
        """停止所有插件调度器。"""
        for plugin in self._plugins:
            if plugin.trigger is not None:
                try:
                    plugin.trigger.stop()
                except Exception as e:
                    console.warn(f"插件 {plugin.name} 停止失败: {e}")
