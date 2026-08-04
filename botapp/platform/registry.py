"""平台插件注册表：注册具体平台适配器，按配置创建实例。

第三方平台插件可在此注册，或使用入口模块的
``platforms[name] = adapter_class`` 约定（见 :func:`discover`）。
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from botapp.platform.base import PlatformAdapter

#: 平台注册表：{平台名: 适配器类}。插件用 register_platform() 注册。
_PLATFORMS: dict[str, type["PlatformAdapter"]] = {}

#: 平台类构造签名：def __init__(self, config) -> None
AdapterFactory = Callable[..., "PlatformAdapter"]


def register_platform(name: str, adapter_class: type["PlatformAdapter"]) -> None:
    """注册一个平台适配器类。

    Args:
        name: 平台名（config.ini [platform] name 使用，如 wechat）。
        adapter_class: PlatformAdapter 子类。
    """
    if name in _PLATFORMS:
        raise ValueError(f"平台 {name!r} 已注册，不能重复注册。")
    _PLATFORMS[name] = adapter_class


def _import_builtin_plugins() -> None:
    """惰性导入 botapp.platform 包内建的平台插件模块。"""
    import botapp.platform as pkg

    for _mod in pkgutil.iter_modules(pkg.__path__):
        # wechat.py 等模块在 import 时自注册（通过 register_platform 或
        # 模块级 _PLATFORM_NAME/_PLATFORM_CLASS 约定）
        try:
            importlib.import_module(f"{pkg.__name__}.{_mod.name}")
        except Exception:
            # 平台插件导入失败不影响其他功能
            from botapp.console import console

            console.error(f"平台插件 {_mod.name} 加载失败")
            continue


def list_platforms() -> list[str]:
    """返回已注册的平台名列表。"""
    _import_builtin_plugins()
    return sorted(_PLATFORMS)


def create_platform(config) -> "PlatformAdapter":
    """按配置创建平台适配器实例。

    Args:
        config: AppConfig，读取 config.platform 作为平台名。

    Returns:
        PlatformAdapter 实例。

    Raises:
        ValueError: 平台名未注册或未安装。
    """
    _import_builtin_plugins()
    name = getattr(config, "platform", "") or "wechat"
    adapter_class = _PLATFORMS.get(name)
    if adapter_class is None:
        raise ValueError(
            f"平台 {name!r} 未注册。可用平台: {', '.join(list_platforms())}。"
        )
    return adapter_class(config)
