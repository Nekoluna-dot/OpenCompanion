import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("todo-list")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
_lock = threading.Lock()

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _sanitize_user_id(user_id: str) -> str:
    uid = (user_id or "").split("@", 1)[0].strip()
    uid = _INVALID_CHARS.sub("_", uid)
    if not uid or uid in (".", ".."):
        raise ValueError(f"Invalid user ID: {user_id!r}")
    return uid


def _user_file(user_id: str) -> Path:
    return DATA_DIR / "todos" / f"{_sanitize_user_id(user_id)}.json"


def _load(user_id: str) -> list[dict]:
    path = _user_file(user_id)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(user_id: str, records: list[dict]) -> None:
    path = _user_file(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _validate_priority(priority: int) -> int:
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        raise ValueError(f"priority must be int (1-5), got: {priority!r}")
    if not 1 <= priority <= 5:
        raise ValueError(f"priority must be in 1-5, got: {priority}")
    return priority


def _to_output(record: dict) -> dict:
    return {k: record[k] for k in ("id", "content", "priority", "created_at", "updated_at")}


def _sorted(records: list[dict]) -> list[dict]:
    return sorted(records, key=lambda r: (r.get("priority", 3), r.get("created_at", "")))


@mcp.tool()
def add_todo(user_id: str, content: str, priority: int = 3) -> dict:
    """Add a todo item for the user (e.g. "buy milk", "交房租").

    Use when the user asks you to remember a task for later. The todo list
    is per-user; items can be listed, completed or deleted afterwards.

    Args:
        user_id: The current conversation user ID.
        content: Task description, e.g. "buy milk".
        priority: 1 = highest, 5 = lowest. Default 3.
    """
    record = {
        "id": uuid.uuid4().hex[:12],
        "content": content.strip(),
        "priority": _validate_priority(priority),
        "created_at": _now(),
        "updated_at": _now(),
    }
    if not record["content"]:
        raise ValueError("content cannot be empty")
    with _lock:
        records = _load(user_id)
        records.append(record)
        _save(user_id, records)
    return _to_output(record)


@mcp.tool()
def delete_todo(user_id: str, todo_id: str) -> str:
    """Delete a todo by ID. Returns "已删除" or "没数据" (not found)."""
    with _lock:
        records = _load(user_id)
        remaining = [r for r in records if r["id"] != todo_id]
        if len(remaining) == len(records):
            return "没数据"
        _save(user_id, remaining)
    return "已删除"


@mcp.tool()
def complete_todo(user_id: str, todo_id: str) -> str:
    """Mark a todo done: it is removed from the list. "已完成并删除" or "没数据".

    Args:
        user_id: The current conversation user ID.
        todo_id: Todo ID.
    """
    with _lock:
        records = _load(user_id)
        remaining = [r for r in records if r["id"] != todo_id]
        if len(remaining) == len(records):
            return "没数据"
        _save(user_id, remaining)
    return "已完成并删除"


@mcp.tool()
def update_todo_priority(user_id: str, todo_id: str, priority: int) -> dict | str:
    """Change a todo's priority. Returns the updated item or "没数据".

    Args:
        user_id: The current conversation user ID.
        todo_id: Todo ID.
        priority: New priority 1-5 (1 = highest).
    """
    p = _validate_priority(priority)
    with _lock:
        records = _load(user_id)
        for r in records:
            if r["id"] != todo_id:
                continue
            r["priority"] = p
            r["updated_at"] = _now()
            _save(user_id, records)
            return _to_output(r)
    return "没数据"


@mcp.tool()
def next_todo(user_id: str) -> dict | str:
    """Get the single highest-priority pending todo (token-saving). "没数据" if none.

    Args:
        user_id: The current conversation user ID.
    """
    with _lock:
        records = _sorted(_load(user_id))
    if not records:
        return "没数据"
    return _to_output(records[0])


@mcp.tool()
def storage_info(user_id: str) -> dict:
    """Declare where this plugin stores data for the given user (internal use).

    Returns the concrete file paths that belong to `user_id`, so the bot can
    delete them when clearing the user's data. Plugins without this tool are
    treated as "compatibility mode": their data cannot be removed.
    """
    return {
        "user_data": [
            {"kind": "file", "path": str(_user_file(user_id))},
        ]
    }


@mcp.resource("todos://stats/{user_id}")
def todos_stats(user_id: str) -> str:
    """Todo stats for a user: total pending count. Use when the user asks how many todos they have."""
    with _lock:
        records = _load(user_id)
    return f"待办 {len(records)} 条"


if __name__ == "__main__":
    mcp.run(transport="stdio")
