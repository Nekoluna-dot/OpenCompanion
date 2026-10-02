"""weilink 微信平台插件包。

导入本包时自动注册 "wechat" 平台适配器（见 adapter.py）。
"""

from botapp.platform.registry import register_platform

from .adapter import WeChatAdapter

register_platform("wechat", WeChatAdapter)
