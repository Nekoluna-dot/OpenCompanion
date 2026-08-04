"""自动接入日志桥：被 bot 以 stdio 子进程拉起的进程（带 BOT_LOGBRIDGE_PASSTHROUGH=1
环境标记）启动时自动把标准 logging 输出转发进 bot 的 logs/bot.log。

不碰 stdout/stderr，保证 MCP JSON-RPC 管道零污染。bot 主进程无该标记，不受影响。
"""

import os

if os.environ.get("BOT_LOGBRIDGE_PASSTHROUGH") == "1":
    try:
        from botapp.logbridge import install_passthrough

        install_passthrough()
    except Exception:
        pass
