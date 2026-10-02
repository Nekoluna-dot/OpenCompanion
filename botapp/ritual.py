import threading
from datetime import date, datetime

from botapp.console import console

_POLL_SECONDS = 30


class DailyRitual:
    def __init__(self, bot, hour: int = 4) -> None:
        self._bot = bot
        self._hour = hour
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_fired: date | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        console.config(f"每日 {self._hour}:00 睡前仪式检查已启动")

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._stop.wait(_POLL_SECONDS):
                break
            now = datetime.now()
            if now.hour != self._hour:
                continue
            today = now.date()
            if self._last_fired == today:
                continue
            self._last_fired = today
            try:
                self._bot.run_daily_ritual()
            except Exception as e:
                console.warn(f"睡前仪式检查异常: {e}")
