"""后台启动 OB：stdio 主服务 + Dashboard Web 后台。

路径全部由本文件位置推导，不硬编码：
    python scripts/ob_dashboard.py      # 启动（后台进程，PID 写入 MCP/OB/.dashboard_pid）
    python scripts/ob_dashboard.py --stop   # 停止

启动后浏览器访问 http://127.0.0.1:18001 （端口见 MCP/OB/config.yaml 的 host_port）。
注意：与 bot 同时跑时端口会冲突，二选一。
"""

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OB_DIR = ROOT / "MCP" / "OB"
if os.name == "nt":
    VENV_REL = Path("Scripts") / "python.exe"
else:
    VENV_REL = Path("bin") / "python"
VENV_PY = OB_DIR / ".venv" / VENV_REL
LOG_PATH = OB_DIR / "ob_stdout.log"
PID_PATH = OB_DIR / ".dashboard_pid"


def stop() -> None:
    if not PID_PATH.exists():
        print("OmbreBrain没有在运行")
        return
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        print(f"PID 文件损坏：{PID_PATH}")
        return
    import signal

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"已发送停止信号  PID {pid}，等待…")
        for _ in range(20):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except OSError:
                PID_PATH.unlink(missing_ok=True)
                print("已停止。")
                return
        print("退出失败。")
    except OSError as e:
        print(f"停止失败：{e}")
        PID_PATH.unlink(missing_ok=True)


def start() -> None:
    if not VENV_PY.exists():
        sys.exit(f"找不到 Ombre 虚拟环境：{VENV_PY}")
    with open(LOG_PATH, "a", encoding="utf-8", errors="replace") as logf:
        proc = subprocess.Popen(
            [str(VENV_PY), "src/server.py"],
            cwd=str(OB_DIR),
            stdin=subprocess.PIPE,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
    PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    print(f"OmbreBrain已启动（PID {proc.pid}），日志：{LOG_PATH}")
    print("Dashboard: http://127.0.0.1:18001")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            proc.kill()
        except Exception:
            pass


if __name__ == "__main__":
    if "--stop" in sys.argv:
        stop()
    else:
        start()
