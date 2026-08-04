#平台通讯协议抽象层：定义通用消息模型与平台适配器接口。
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class BotMessage:

    #: 发送者唯一 ID（完整 ID，如 xxx@im.wechat）
    from_user: str
    #: 文本内容（无文本时可为空字符串）
    text: str = ""
    #: 消息类型：text / image / voice / file / video（供扩展，目前只处理文本）
    msg_type: str = "text"
    #: 平台原始消息对象（如需扩展媒体处理时可取用）
    raw: Any = None
    #: 被引用/回复的原文内容（用户引用某条消息回复时非空）
    replied_text: str = ""
    #: 被引用消息的类型（text / image / voice / file / video）
    replied_type: str = ""
    #: 图片消息下载后的本地路径（无图片为空串）
    image_path: str = ""
    #: 视频消息下载后的本地路径（无视频为空串）
    video_path: str = ""
    #: 附加信息（平台特有，如 context_token 等）
    extra: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.text)


@dataclass
class PlatformStatus:
    """平台连接状态摘要（供 /info 或日志展示）。"""

    name: str
    connected: bool
    detail: str = ""


MessageHandler = Callable[[BotMessage], None]


class SendQuotaExhausted(Exception):
    """平台发送配额已耗尽（如每轮最多 N 条出站消息）。

    机器人核心捕获此异常优雅停止发送，而不是让发送线程崩溃。
    平台插件在遇到各自的配额限制时，应转换为本异常抛出。
    """


class PlatformAdapter(ABC):
    """平台通讯适配器统一接口。

    机器人通过本接口完成「收发消息 + 输入态 + 用户解析」，不关心底层
    是 weilink 还是别的平台。平台插件需实现全部抽象方法；生命周期
    由 :meth:`start` / :meth:`stop` 管理，会话过期重连也在此层完成。
    """

    #: 平台名（注册名，如 "wechat"），用于配置 [platform] name 指定
    name = "base"

    # ── 生命周期 ─────────────────────────────────────────────
    @abstractmethod
    def start(self) -> None:
        """启动平台连接与消息轮询（后台）。"""

    @abstractmethod
    def stop(self) -> None:
        """停止平台连接与消息轮询。"""

    def close(self) -> None:
        """完全释放平台资源（进程退出时调用）。默认等价于 stop。"""
        self.stop()

    # ── 收发 ─────────────────────────────────────────────────
    @abstractmethod
    def send(self, to: str, text: str) -> None:
        """发送一条文本消息给指定用户。"""

    @abstractmethod
    def send_typing(self, user_id: str) -> None:
        """向用户显示「正在输入中」。"""

    @abstractmethod
    def stop_typing(self, user_id: str) -> None:
        """取消「正在输入中」状态。"""

    @abstractmethod
    def on_message(self, handler: MessageHandler) -> None:
        """注册入站消息处理器（由机器人核心调用）。"""

    # ── 用户/消息库 ──────────────────────────────────────────
    @abstractmethod
    def resolve_user_id(self, user_id: str) -> str:
        """把短用户 ID（去 @ 后缀）还原为完整可发送的 ID。

        事件存档等场景只存短 ID，发送时需还原为完整 ID 才能命中
        会话上下文（如 weilink 的 xxx@im.wechat）。
        """

    @abstractmethod
    def clear_chat_history(self) -> str:
        """清空平台侧的历史聊天记录（消息库），返回给用户的提示文本。"""

    def clear_user_data(self, user_id: str) -> str:
        """清除指定用户在本平台侧的所有数据（消息库等），返回提示文本。

        默认不做任何事（返回空提示）；wechat 等平台可覆写按用户清理。
        """
        return ""

    # ── 状态 ─────────────────────────────────────────────────
    def status(self) -> PlatformStatus:
        """平台连接状态摘要，默认实现仅返回 name/connected=True。"""
        return PlatformStatus(name=self.name, connected=True)

    def context_tokens(self) -> dict[str, str]:
        """返回 {用户完整ID: context_token} 映射（需发送会话 token 的平台）。

        默认返回空 dict；weilink 等平台可覆写。
        """
        return {}

    def mcp_client(self):
        """返回平台底层连接对象（供 MCP 服务器等共享实例使用）。

        默认返回 None；wechat 插件返回 weilink 实例。平台插件需保证
        重连复用同一实例，使已绑定的外部引用持续有效。
        """
        return None

    # ── 媒体发送 / 平台内建工具 ────────────────────────────────
    def send_media(self, user_id: str, kind: str, path: str) -> tuple[bool, str]:
        """向用户发送媒体文件，返回 (是否成功, 结果文本)。

        kind 为平台约定值（如 image/voice/file/video）。平台内部负责
        格式转换（如语音转 SILK）、路径校验与发送。默认实现返回
        「平台不支持自动发送媒体」。
        """
        return False, f"平台 {self.name} 不支持自动发送媒体"

    def platform_tool_registry(self):
        """构建并返回平台内建工具注册表（含 send/recv 等平台工具）。

        默认返回 None（平台不提供内建工具）；wechat 返回
        weilink build_registry() 的结果。机器人核心据此把平台工具
        与外部 MCP 源一起注册给 LLM。平台内部可在此应用自己的工具
        可见性过滤（如账号管理工具开关）。
        """
        return None

    def run_mcp_server(
        self,
        transport: str,
        host: str,
        port: int,
        token: str | None,
    ) -> None:
        """启动平台提供的 MCP 服务器（后台线程中调用，阻塞直到退出）。

        默认什么都不做；wechat 平台覆写为运行 weilink 的 MCP 服务器，
        使外部 MCP 客户端可调用平台内建工具。
        """
        return None
