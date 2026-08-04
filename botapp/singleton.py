import atexit
import ctypes
import os
import subprocess
import sys
from pathlib import Path

from botapp.console import console

_LOCK_PATH = Path(__file__).resolve().parent.parent / "data" / "bot.lock"

# 注意：Windows 上 os.kill(pid, 0) 会真的终止进程（TerminateProcess），
# 绝不能用来探活。改用 Win32 OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)。
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_kernel32 = ctypes.windll.kernel32


def _pid_alive(pid: int) -> bool:

    if pid <= 0:
        return False
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_uint32()
        if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == _STILL_ACTIVE
    finally:
        _kernel32.CloseHandle(handle)


def _kill_tree(pid: int) -> None:
    #必须 /T 递归清理：MCP stdio 子进程（revive/OB/event_logger 等）是
    #独立进程，只杀主进程会让它们残留成为孤儿进程。然后就会发生一些奇怪的bug 比如变成回声桶
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _release() -> None:
    #释放锁
    try:
        if int(_LOCK_PATH.read_text(encoding="utf-8").strip()) == os.getpid():
            _LOCK_PATH.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def acquire_singleton_lock() -> None:
    #获取锁
    if _LOCK_PATH.exists():
        old_pid = 0
        try:
            old_pid = int(_LOCK_PATH.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            old_pid = 0
        if old_pid > 0 and _pid_alive(old_pid):
            console.warn(f"检测到已有 bot 正在运行 (PID {old_pid})")
            answer = input("是否杀掉旧进程并启动新的 bot？[y/N] ").strip().lower()
            if answer in ("y", "yes"):
                console.info(f"正在终止旧 bot 进程 (PID {old_pid}) ...")
                _kill_tree(old_pid)
            else:
                console.info("已选择不覆盖，退出")
                sys.exit(0)
        # 残留锁（进程已死）或旧进程已终止 → 清理后重建
        try:
            _LOCK_PATH.unlink(missing_ok=True)
        except OSError:
            pass

    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        # 与另一实例并发启动的竞争：对方刚拿到锁
        console.warn("检测到另一 bot 实例正在启动，本实例退出")
        sys.exit(0)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    atexit.register(_release)
