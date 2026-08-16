"""OpenCompanion 网页控制台入口。

在浏览器里管理机器人：启停/自动重启/实时日志（含微信扫码登录）/
config.ini 与 OmbreBrain config.yaml 编辑 / 数据管理 / 端口检测。

用法:
    python webconsole.py            # 默认 127.0.0.1:9000
    BOT_WEBCONSOLE_HOST=0.0.0.0 BOT_WEBCONSOLE_PORT=9000 BOT_WEBCONSOLE_TOKEN=xxx python webconsole.py

也可在 config.ini 的 [webconsole] 节配置 host / port / token。
"""

import configparser
import os
import signal
import threading
import time
from pathlib import Path

from botapp.console import console
from botapp.webconsole import WebConsoleServer

_BASE_DIR = Path(__file__).resolve().parent
_CONFIG_INI = _BASE_DIR / "config.ini"


def _load_webconsole_config() -> dict:
    host = os.environ.get("BOT_WEBCONSOLE_HOST", "127.0.0.1")
    port = os.environ.get("BOT_WEBCONSOLE_PORT", "9000")
    token = os.environ.get("BOT_WEBCONSOLE_TOKEN", "").strip()
    if _CONFIG_INI.exists():
        cp = configparser.ConfigParser()
        cp.read(_CONFIG_INI, encoding="utf-8")
        if cp.has_section("webconsole"):
            host = host or cp.get("webconsole", "host", fallback="127.0.0.1").strip()
            port = port or cp.get("webconsole", "port", fallback="9000").strip()
            token = token or cp.get("webconsole", "token", fallback="").strip()
    return {
        "host": host,
        "port": int(port),
        "token": token,
    }


def main() -> None:
    cfg = _load_webconsole_config()
    server = WebConsoleServer(
        host=cfg["host"], port=cfg["port"], token=cfg["token"]
    )
    try:
        server.start()
    except RuntimeError as e:
        console.error(str(e))
        return

    # 判断实际鉴权状态（优先新密码系统，其次旧 token）
    _auth_file = os.path.join("data", "webconsole_auth.json")
    _has_password = False
    if os.path.isfile(_auth_file):
        try:
            import json
            with open(_auth_file, "r", encoding="utf-8") as _f:
                _d = json.load(_f)
            _has_password = bool(_d.get("password_hash"))
        except Exception:
            pass
    if cfg["token"]:
        _auth_note = "  (Bearer token 鉴权)"
    elif _has_password:
        _auth_note = "  (密码鉴权)"
    else:
        _auth_note = "  (未开启鉴权)"

    console.config(
        f"网页控制台: http://{cfg['host']}:{cfg['port']}" + _auth_note
    )
    console.info("在浏览器打开后，可在「状态与日志」页启动机器人并扫码登录微信。")

    stop_flag = threading.Event()

    def _on_signal(signum, frame) -> None:
        console.info("正在停止网页控制台...")
        stop_flag.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    while not stop_flag.is_set():
        time.sleep(1.0)
    server.stop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.info("已退出")
