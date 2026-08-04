"""独立的 bot 功能测试脚本（无需微信登录/启动服务）。

模拟用户发消息，走完整 on_message → LLM agent → 工具调用 → 发送流程，
拦截发送与输入状态，打印输入上下文（含 systime）、思考、回复、工具与耗时。

用法：
    python test_bot.py              # 交互模式，逐条输入消息
    python test_bot.py "你好"        # 单条模式，发完即退出
    python test_bot.py --list        # 列出 conversation 目录的用户
"""

import os
import sys
import time

# 直接命令行运行时的路径（脚本在 <项目根>/testtool/test_bot.py）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import urllib.request

from botapp.config import AppConfig

config = AppConfig()

if not config.use_proxy:
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
    )
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

from botapp import OpenCompanion
from botapp.console import console

# ── 拦截：不真正发送微信、不启动 MCP / 调试视图 ──────────────────
from botapp.platform.base import BotMessage, PlatformAdapter


class _FakePlatform(PlatformAdapter):
    """假平台适配器：拦截发送，不连接真实微信。"""

    name = "fake"

    def __init__(self) -> None:
        self._handler = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def send(self, to, text):  # noqa: ARG002
        console.reply(to, text)

    def send_typing(self, user_id: str) -> None:  # noqa: ARG002
        pass

    def stop_typing(self, user_id: str) -> None:  # noqa: ARG002
        pass

    def on_message(self, handler) -> None:
        self._handler = handler

    def resolve_user_id(self, user_id: str) -> str:
        return user_id if "@" in user_id else f"{user_id}@im.wechat"

    def clear_chat_history(self) -> str:
        return "已清空全部历史聊天记录（测试平台）。"


def _silent(rawview):
    """关闭 rawview 的页面输出，专注控制台。"""
    from botapp.rawview import RawViewServer

    class _Silent(RawViewServer):
        def start(self):
            pass

    return _Silent


def build_bot(user_id: str) -> OpenCompanion:
    platform = _FakePlatform()
    # 替换 rawview 为静默版（测试时不开页面端口 8080）
    import botapp.rawview as _rv

    _rv.RawViewServer = _silent(_rv.RawViewServer)
    bot = OpenCompanion(platform, config)
    bot.typing.start = lambda uid: None
    bot.typing.stop = lambda uid: None
    return bot


def make_message(user_id: str, text: str) -> BotMessage:
    return BotMessage(from_user=user_id, text=text, msg_type="text")


def show_reply_and_thinking(bot: OpenCompanion, user_id: str, text: str) -> None:
    console.info(f"── 用户: {text} ──")
    bot.on_message(make_message(user_id, text))
    rec = None
    if bot.rawview is not None and bot.rawview._records:
        rec = bot.rawview._records[-1]
    thinking = "".join((rec or {}).get("thinking") or []).strip()
    if thinking:
        console.info(f"[思考] {thinking[:800]}")
    if rec and rec.get("raw"):
        body = rec["raw"].get("request_body") or {}
        usage = rec["raw"].get("usage")
        console.config(
            f"thinking={body.get('thinking')} effort={body.get('reasoning_effort')} "
            f"usage={usage}"
        )


def interactive(user_id: str) -> None:
    bot = build_bot(user_id)
    console.info(f"测试会话开始（用户 {user_id}），输入空行退出。")
    while True:
        try:
            text = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break
        show_reply_and_thinking(bot, user_id, text)


def main() -> None:
    if "--list" in sys.argv:
        from botapp.store import ConversationStore

        store = ConversationStore(config.conversation_dir)
        for uid in store.list_users():
            print(uid)
        return

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    user_id = "test@im.wechat"
    if args:
        if len(args) >= 2 and "@" in args[0]:
            user_id = args[0]
            text = args[1]
        else:
            text = args[0]
        bot = build_bot(user_id)
        show_reply_and_thinking(bot, user_id, text)
    else:
        interactive(user_id)


if __name__ == "__main__":
    main()
