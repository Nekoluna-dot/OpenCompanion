"""微信 iLink 机器人应用包。

拆分后的模块：
    config.py      AppConfig       配置读取（config.ini + prompt.txt）
    console.py     Console         统一控制台显示层
    diagnostics.py install()       iLink 协议请求耗时打点
    llm.py         LLMClient       流式调用 OpenAI 兼容 API（含 tools/tool_calls）
    typing.py      TypingIndicator 微信「正在输入中」提示
    messenger.py   MessageSender   消息发送
    tools.py       McpTools        标准工具层（toolregistry 封装，供 LLM 调用）
    mcp_server.py  McpServer       MCP 协议服务器（暴露 weilink 工具）
    store.py       ConversationStore 对话上下文持久化（conversation/ 目录）
    rawview.py     RawViewServer  RAW 调试视图（网页展示原始请求/响应）
    robot.py       OpenCompanion       机器人主逻辑（组合以上组件）
"""

from botapp.config import AppConfig
from botapp.console import Console, console
from botapp.llm import LLMClient, LLMResult
from botapp.mcp_server import McpServer
from botapp.messenger import MessageSender
from botapp.rawview import RawViewServer
from botapp.robot import OpenCompanion
from botapp.store import ConversationStore
from botapp.tools import McpTools
from botapp.typing import TypingIndicator

__all__ = [
    "AppConfig",
    "Console",
    "ConversationStore",
    "LLMClient",
    "LLMResult",
    "McpServer",
    "McpTools",
    "MessageSender",
    "RawViewServer",
    "TypingIndicator",
    "OpenCompanion",
    "console",
]
