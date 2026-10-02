import os
import signal
import threading
import time
import urllib.request

from botapp.config import AppConfig
from botapp.console import console

config = AppConfig()

if not config.use_proxy:
    # Clash等代理软件即使是直连也会导致延迟飙升 不适合轮询 也不建议使用代理
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
    )
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

# ── 依赖 weilink 的模块在代理策略确定后再导入 ────────────────────
from botapp import McpServer, OpenCompanion  # noqa: E402
from botapp.diagnostics import install as install_diagnostics  # noqa: E402
from botapp.event_trigger import EventTrigger  # noqa: E402
from botapp.platform import create_platform  # noqa: E402
from botapp.ritual import DailyRitual  # noqa: E402
from botapp.singleton import acquire_singleton_lock  # noqa: E402
install_diagnostics()


def main() -> None:
    acquire_singleton_lock()    #锁检测

    platform = create_platform(config)

    bot = OpenCompanion(platform, config)
    bot.register()
    bot.plugins.start()
    EventTrigger(bot, interval=60).start()
    DailyRitual(bot, hour=4).start()

    if config.mcp_enabled:
        McpServer(platform, config).start()

    # 网页控制台聊天测试：由控制台以环境变量 BOT_TEST_HTTP_PORT 拉起时启用
    _test_port = os.environ.get("BOT_TEST_HTTP_PORT", "").strip()
    if _test_port.isdigit():
        from botapp.test_http import start_test_server

        if start_test_server(bot, int(_test_port)):
            console.config(f"聊天测试服务已启动（127.0.0.1:{_test_port}）")

    stop_flag = threading.Event()

    def _on_sigint(signum: int, frame) -> None:
        console.info("正在停止，请稍等...")
        stop_flag.set()
        platform.stop()

    signal.signal(signal.SIGINT, _on_sigint)
    signal.signal(signal.SIGTERM, _on_sigint)

    console.config(f"平台 = {platform.name}")
    platform.start()

    # 等待轮询 重连线程关闭
    while not stop_flag.is_set():
        time.sleep(1.0)

    # 清理
    try:
        bot.close()
    finally:
        platform.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.info("已退出")
