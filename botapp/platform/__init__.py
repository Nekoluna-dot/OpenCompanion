"""平台通讯协议抽象层包。

- base.py:    通用消息模型 BotMessage + 平台适配器接口 PlatformAdapter
- registry.py: 平台插件注册表（register_platform / create_platform）
- wechat.py:   微信平台插件（WeChatAdapter，封装 weilink）

新增平台：在 botapp/platform/ 下新建模块，实现 PlatformAdapter 子类，
并在模块级调用 register_platform("平台名", AdapterClass)。
"""

from botapp.platform.base import BotMessage, PlatformAdapter, PlatformStatus
from botapp.platform.registry import (
    create_platform,
    list_platforms,
    register_platform,
)

__all__ = [
    "BotMessage",
    "PlatformAdapter",
    "PlatformStatus",
    "create_platform",
    "list_platforms",
    "register_platform",
]
