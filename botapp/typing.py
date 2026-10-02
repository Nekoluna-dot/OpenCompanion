"""平台「正在输入中」状态控制：基于 PlatformAdapter 抽象接口。"""

from botapp.platform.base import PlatformAdapter


class TypingIndicator:
    def __init__(self, platform: PlatformAdapter) -> None:
        self._platform = platform

    def start(self, user_id: str) -> None:
        """向用户显示「正在输入中」。"""
        self._platform.send_typing(user_id)

    def stop(self, user_id: str) -> None:
        """取消「正在输入中」状态。"""
        self._platform.stop_typing(user_id)
