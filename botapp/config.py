import configparser
import json
import os
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent
_REASONING_LEVELS = ("low", "high", "max")
_MCP_TRANSPORTS = ("sse", "streamable-http")

# prompt_extra.txt 缺失时的内置兜底（内容应与 prompt_extra.txt 保持一致）
_DEFAULT_PROMPT_EXTRA = (
    "none"
)

# prompt.txt 缺失时 __init__ 阶段的临时占位，随后由 _load_prompt() 覆盖
_DEFAULT_PROMPT = ""


class AppConfig:
    """读取 config.ini 与 prompt.txt 的全部运行配置。"""

    def __init__(
        self,
        config_path: str | Path | None = None,
        prompt_path: str | Path | None = None,
        prompt_extra_path: str | Path | None = None,
    ) -> None:
        self.config_path = Path(config_path) if config_path else _BASE_DIR / "config.ini"
        self.prompt_path = Path(prompt_path) if prompt_path else _BASE_DIR / "prompt.txt"
        self.prompt_extra_path = (
            Path(prompt_extra_path)
            if prompt_extra_path
            else _BASE_DIR / "prompt_extra.txt"
        )

        # platform 节
        # 通讯平台名（对应 botapp/platform/ 下注册的插件，如 wechat）
        self.platform = "wechat"

        # llmapi 节
        self.base_url = ""
        self.api_key = ""
        self.model = ""
        self.thinking = False
        self.reasoning_effort = "low"
        self.use_proxy = False
        # 是否接收图片消息并送入 LLM（需模型支持图片输入）
        self.enable_image = False
        # 是否接收视频消息并送入 LLM（需模型支持视频输入，视频须 <50MB）
        self.enable_video = False
        # 文本清洗：发送前删除括号内神态/动作描写（中文（）与英文()）
        self.clean_paren = True
        # 是否把 \n\n 和 \n 视为气泡分隔符（true=每个换行拆一条气泡）
        self.split_newline = False
        # 上下文压缩触发阈值（token 估算，1 字符≈1 token）这里不管中英文的 可能会导致计算错误 但是是最简单的计算方法了喵
        self.compact_token_limit = 250000

        # mcp 节
        self.mcp_enabled = False
        self.mcp_transport = "streamable-http"
        self.mcp_host = "127.0.0.1"
        self.mcp_port = 8000
        self.mcp_token = ""
        # 是否启用 weilink 内建账号管理工具（sessions/login/logout/rename_session/set_default），
        # 默认 False：禁用，仅暴露 recv/send/download/history
        #这些工具其实没啥用 反而浪费上下文
        self.mcp_account_tools_enabled = False

        # 外部 MCP 工具源（[mcpsources] 节，可多个）
        # 每项: {"name", "transport", "namespace"}
        self.mcp_sources: list[dict] = []

        # conversation 节
        self.conversation_enabled = False
        self.conversation_dir = str(_BASE_DIR / "conversation")

        # web 节
        #调试用的
        self.web_enabled = False
        self.web_host = "127.0.0.1"
        self.web_port = 8080
        self.web_max_records = 50

        self.system_prompt = _DEFAULT_PROMPT
        self.prompt_extra = _DEFAULT_PROMPT_EXTRA

        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"未找到配置文件 {self.config_path}，请参照 config.ini 创建。"
            )

        parser = configparser.ConfigParser()
        parser.read(self.config_path, encoding="utf-8")

        if parser.has_section("platform"):
            self._load_platform(parser)
        if parser.has_section("llmapi"):
            self._load_llmapi(parser)
        if parser.has_section("mcp"):
            self._load_mcp(parser)
        if parser.has_section("mcpsources"):
            self._load_mcp_sources(parser)
        if parser.has_section("conversation"):
            self._load_conversation(parser)
        if parser.has_section("web"):
            self._load_web(parser)

        if not self.base_url or not self.api_key or not self.model:
            raise ValueError(
                "config.ini 的 [llmapi] 节必须填写 base_url、api_key、model。"
            )
        self._load_prompt()

    def _load_platform(self, parser: configparser.ConfigParser) -> None:
        self.platform = (
            parser.get("platform", "name", fallback="wechat").strip().lower()
        )
        if not self.platform:
            self.platform = "wechat"

    def _load_llmapi(self, parser: configparser.ConfigParser) -> None:
        self.base_url = parser.get("llmapi", "base_url", fallback="").strip().rstrip("/")
        self.api_key = parser.get("llmapi", "api_key", fallback="").strip()
        self.model = parser.get("llmapi", "model", fallback="").strip()
        self.thinking = parser.getboolean("llmapi", "thinking", fallback=False)
        self.reasoning_effort = (
            parser.get("llmapi", "reasoning_effort", fallback="low").strip().lower()
        )
        self.use_proxy = parser.getboolean("llmapi", "use_proxy", fallback=False)
        self.enable_image = parser.getboolean("llmapi", "enable_image", fallback=False)
        self.enable_video = parser.getboolean("llmapi", "enable_video", fallback=False)
        self.clean_paren = parser.getboolean("llmapi", "clean_paren", fallback=True)
        self.split_newline = parser.getboolean("llmapi", "split_newline", fallback=False)
        self.compact_token_limit = parser.getint(
            "llmapi", "compact_token_limit", fallback=200000
        )

        if self.reasoning_effort not in _REASONING_LEVELS:
            raise ValueError(
                f"reasoning_effort 必须是 {', '.join(_REASONING_LEVELS)} 之一。"
            )

    def _load_mcp(self, parser: configparser.ConfigParser) -> None:
        self.mcp_enabled = parser.getboolean("mcp", "enabled", fallback=False)
        self.mcp_transport = parser.get(
            "mcp", "transport", fallback="streamable-http"
        ).strip()
        self.mcp_host = parser.get("mcp", "host", fallback="127.0.0.1").strip()
        self.mcp_port = parser.getint("mcp", "port", fallback=8000)
        self.mcp_token = parser.get("mcp", "token", fallback="").strip()
        self.mcp_account_tools_enabled = parser.getboolean(
            "mcp", "account_tools_enabled", fallback=False
        )

        if self.mcp_transport not in _MCP_TRANSPORTS:
            raise ValueError(
                "MCP transport 仅支持 sse 或 streamable-http（stdio 会污染 stdout 日志）。"#这里其实是STDIO MCP服务器注册到web 然后整体暴露服务给客户端连接 这样stdio的返回的内容不会污染日志 是个很不错的方法
            )

    def _load_mcp_sources(self, parser: configparser.ConfigParser) -> None:

        for name, raw in parser.items("mcpsources"):
            name = name.strip().lower()
            raw = raw.strip()
            if not name or not raw or name.startswith("#"):
                continue
            transport: str | dict = raw
            extra: dict = {}
            if raw.startswith("{"):
                try:
                    transport = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"[mcpsources] {name} 的 stdio 配置不合法: {e}"
                    )
                # 能力声明与预热工具属于 bot 端配置，不入子进程 env
                extra = {
                    k: transport.pop(k)
                    for k in ("capability", "warmup")
                    if k in transport
                }
                transport = self._resolve_stdio_paths(transport)
            self.mcp_sources.append(
                {
                    "name": name,
                    "transport": transport,
                    "namespace": name,
                    **extra,
                }
            )

    @staticmethod
    def _resolve_stdio_paths(transport: dict) -> dict:
        if not isinstance(transport, dict):
            return transport
        out = dict(transport)

        def _resolve(p: str) -> str:
            if p and not os.path.isabs(p) and ("/" in p or "\\" in p):
                return str(_BASE_DIR / p)
            return p

        if isinstance(out.get("command"), str):
            out["command"] = _resolve(out["command"])
        args = out.get("args")
        if isinstance(args, list):
            out["args"] = [_resolve(a) if isinstance(a, str) else a for a in args]
        # 注入 PYTHONPATH 指向项目根，使 stdio 子进程可
        # from botapp.logbridge import emit（日志桥，防止污染 MCP stdout）。
        # toolregistry 会把 env 原样传给子进程（不自动合并系统环境），
        # 因此这里基于 os.environ 快照合并，避免子进程丢失 PATH 等变量。
        # 注入 PYTHONPATH 指向项目根，使 stdio 子进程可
        # from botapp.logbridge import emit（日志桥，防止污染 MCP stdout）。
        # 注意：toolregistry 会把 env 原样传给子进程（env 非 None 时整体替换，
        # 不自动继承系统环境），因此必须带上子进程运行所需的系统变量；
        # 但只取最小必要集合，绝不 dump 整个 os.environ（会随工具源打印刷屏）。
        env = {
            k: v
            for k, v in os.environ.items()
            if v
            and k
            in (
                "PATH",
                "SYSTEMROOT",
                "SYSTEMDRIVE",
                "TEMP",
                "TMP",
                "COMSPEC",
                "PATHEXT",
                "APPDATA",
                "LOCALAPPDATA",
                "USERPROFILE",
                "PROGRAMDATA",
                "PROGRAMFILES",
                "PROGRAMFILES(X86)",
                "PROGRAMW6432",
                "HOMEDRIVE",
                "HOMEPATH",
                "OS",
                "NUMBER_OF_PROCESSORS",
                "PROCESSOR_ARCHITECTURE",
                "LANG",
                "LC_ALL",
            )
        }
        env["PYTHONPATH"] = str(_BASE_DIR)
        # 标记子进程：sitecustomize.py 检测到后自动挂日志桥 passthrough，
        # 让子进程全部标准 logging 输出落盘 logs/bot.log（不污染 MCP stdout）
        env["BOT_LOGBRIDGE_PASSTHROUGH"] = "1"
        out["env"] = env
        return out

    def _load_web(self, parser: configparser.ConfigParser) -> None:
        self.web_enabled = parser.getboolean("web", "enabled", fallback=False)
        self.web_host = parser.get("web", "host", fallback="127.0.0.1").strip()
        self.web_port = parser.getint("web", "port", fallback=8080)
        self.web_max_records = parser.getint("web", "max_records", fallback=50)

    def _load_conversation(self, parser: configparser.ConfigParser) -> None:
        self.conversation_enabled = parser.getboolean(
            "conversation", "enabled", fallback=False
        )
        dir_value = parser.get(
            "conversation", "dir", fallback=str(_BASE_DIR / "conversation")
        ).strip()
        # 相对路径基于项目根目录解析，避免受启动工作目录影响
        self.conversation_dir = str(Path(dir_value) if Path(dir_value).is_absolute() else _BASE_DIR / dir_value)

    def _load_prompt(self) -> None:
        if not self.prompt_path.exists():
            raise FileNotFoundError(f"未找到系统提示词文件 {self.prompt_path}。")
        self.system_prompt = self.prompt_path.read_text(encoding="utf-8").strip()

    def reload_prompt(self) -> str:
        """按需重读 prompt.txt：仅当文件修改时间变化时读盘。

        每次对话时调用；文件未变化时直接返回内存缓存，
        变化时重读，使 prompt.txt 修改后无需重启即可生效。
        """
        try:
            mtime = self.prompt_path.stat().st_mtime
        except OSError:
            return self.system_prompt
        if getattr(self, "_prompt_mtime", None) != mtime:
            self._load_prompt()
            self._prompt_mtime = mtime
        return self.system_prompt

    def _load_prompt_extra(self) -> None:
        """读取 prompt_extra.txt；文件缺失时回退内置默认值。"""
        if not self.prompt_extra_path.exists():
            return
        self.prompt_extra = self.prompt_extra_path.read_text(encoding="utf-8").strip()

    def reload_prompt_extra(self) -> str:
        """按需重读 prompt_extra.txt（仅文件修改时间变化时读盘）。

        独立于 prompt.txt，可单独编辑调试；无需重启即生效。
        """
        try:
            mtime = self.prompt_extra_path.stat().st_mtime
        except OSError:
            return self.prompt_extra
        if getattr(self, "_prompt_extra_mtime", None) != mtime:
            self._load_prompt_extra()
            self._prompt_extra_mtime = mtime
        return self.prompt_extra

    # ------------------------------------------------------------------
    # 运行时修改 llmapi 配置（通过对话指令，立即生效 + 持久化）
    # ------------------------------------------------------------------
    _LLMAPI_EDITABLE = {
        "model": str,
        "thinking": bool,
        "reasoning_effort": str,
        "compact_token_limit": int,
    }

    @staticmethod
    def _parse_size(text: str) -> int:
        """解析大小数值：支持纯数字及 k/万/w 后缀（200k、20万、20w）。"""
        t = text.strip().lower()
        mult = 1
        if t.endswith(("万", "w")):
            mult, t = 10000, t[:-1]
        elif t.endswith("k"):
            mult, t = 1000, t[:-1]
        return int(float(t) * mult)

    def set_llmapi(self, key: str, value: str) -> str:
        """修改一个 llmapi 配置项，立即生效并写回 config.ini。

        支持 model / thinking / reasoning_effort / compact_token_limit。
        返回给用户的确认文本；非法值抛 ValueError。
        """
        key = key.strip().lower()
        if key not in self._LLMAPI_EDITABLE:
            raise ValueError(f"仅支持修改：{', '.join(self._LLMAPI_EDITABLE)}。")

        if key == "thinking":
            v = value.strip().lower() in ("1", "true", "yes", "on")
            self.thinking = v
            text = "true" if v else "false"
        elif key == "reasoning_effort":
            v = value.strip().lower()
            if v not in _REASONING_LEVELS:
                raise ValueError(f"reasoning_effort 必须是 {', '.join(_REASONING_LEVELS)} 之一。")
            self.reasoning_effort = v
            text = v
        elif key == "compact_token_limit":
            v = self._parse_size(value)
            if v <= 0:
                raise ValueError("compact_token_limit 必须是正整数。")
            self.compact_token_limit = v
            text = str(v)
        else:  # model
            v = value.strip()
            if not v:
                raise ValueError("model 不能为空。")
            self.model = v
            text = v

        self._persist_llmapi(key, text)
        return f"已设置 {key} = {text}（立即生效，已写入 config.ini）"

    def _persist_llmapi(self, key: str, value: str) -> None:
        """把单个 llmapi 键值写回 config.ini（保留注释与其他节）。"""
        path = self.config_path
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        in_llmapi = False
        replaced = False
        out: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                in_llmapi = stripped.lower() == "[llmapi]"
                out.append(line)
                continue
            if in_llmapi and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=", 1)[0].strip().lower()
                if k == key and not replaced:
                    out.append(f"{key} = {value}")
                    replaced = True
                    continue
            out.append(line)
        if not replaced:
            # 节内未找到该键：追加到 [llmapi] 节末尾
            last_idx = -1
            for i, l in enumerate(out):
                if l.strip().lower() == "[llmapi]":
                    last_idx = i
            if last_idx >= 0:
                j = last_idx + 1
                while j < len(out) and not (
                    out[j].strip().startswith("[") and out[j].strip().endswith("]")
                ):
                    j += 1
                out.insert(j, f"{key} = {value}")
            else:
                out.append("")
                out.append("[llmapi]")
                out.append(f"{key} = {value}")
        try:
            path.write_text("\n".join(out) + "\n", encoding="utf-8")
        except OSError:
            pass
