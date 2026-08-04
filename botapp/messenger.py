from botapp.platform.base import PlatformAdapter


class MessageSender:
    def __init__(self, platform: PlatformAdapter) -> None:
        self._platform = platform

    def send(self, to: str, text: str) -> None:
        """发送一条文本消息。

        Args:
            to: 目标用户完整 ID。
            text: 消息内容。
        """
        self._platform.send(to, text)
