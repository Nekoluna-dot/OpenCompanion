import json
import re
import threading
from pathlib import Path

from botapp.console import console

# 用户 ID 中含 @、- 等字符，转换为安全的文件名
_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _user_filename(user_id: str) -> str:
    return _SAFE_RE.sub("_", user_id) + ".json"


def _restore_user_id(stem: str) -> str:

    idx = stem.rfind("_im.wechat")
    if idx >= 0:
        return stem[:idx] + "@" + stem[idx + 1:]
    return stem


class ConversationStore:
    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    @property
    def directory(self) -> Path:
        return self._dir

    def load(self, user_id: str) -> list[dict]:
        """加载该用户的对话历史；文件不存在或损坏时返回空列表。"""
        path = self._path_for(user_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [m for m in data if isinstance(m, dict)]
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError) as e:
            console.warn(f"对话存档读取失败 {path.name}: {e}")
        return []

    def save(self, user_id: str, messages: list[dict]) -> None:
        """把对话历史原子写入存档文件。"""
        path = self._path_for(user_id)
        tmp = path.with_suffix(".tmp")
        try:
            with self._lock:
                tmp.write_text(
                    json.dumps(messages, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                tmp.replace(path)
        except OSError as e:
            console.warn(f"对话存档写入失败 {path.name}: {e}")

    def delete(self, user_id: str) -> None:
        """删除该用户的对话存档（/清除上下文 时调用）。"""
        path = self._path_for(user_id)
        try:
            with self._lock:
                path.unlink(missing_ok=True)
        except OSError:
            pass

    def list_users(self) -> list[str]:
        """列出当前有存档的用户 ID 列表（跳过非对话文件如 proactive_schedule.json）。"""
        users = []
        for path in sorted(self._dir.glob("*.json")):
            if path.name.endswith(".tmp"):
                continue
            if "@" not in _restore_user_id(path.stem):
                continue
            users.append(path.stem)
        return users

    def list_real_users(self) -> list[str]:
        return [
            _restore_user_id(p.stem)
            for p in sorted(self._dir.glob("*.json"))
            if not p.name.endswith(".tmp") and "@" in _restore_user_id(p.stem)
        ]

    # ------------------------------------------------------------------
    def _path_for(self, user_id: str) -> Path:
        return self._dir / _user_filename(user_id)
