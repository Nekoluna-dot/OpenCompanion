import re
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("event-logger")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
DB_PATH = DATA_DIR / "events.db"
_lock = threading.Lock()

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
TIME_FORMAT = "%Y-%m-%d %H:%M"
_TIME_NOW = "%Y-%m-%d %H:%M:%S"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    time        TEXT NOT NULL,
    time_type   TEXT NOT NULL DEFAULT '精确',
    action      TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_user_time ON events (user_id, time);
"""


def _now() -> str:
    return datetime.now().strftime(_TIME_NOW)


def _validate_time(time_str: str) -> str:
    try:
        parsed = datetime.strptime(time_str, TIME_FORMAT)
    except (ValueError, TypeError):
        raise ValueError(f"时间格式必须为「YYYY-MM-DD HH:MM」，如 2026-07-31 22:30，收到: {time_str!r}")
    return parsed.strftime(TIME_FORMAT)


def _sanitize_user_id(user_id: str) -> str:
    # 所有用户 id 后缀相同（@im.wechat 等），只取 @ 之前的前缀
    uid = (user_id or "").split("@", 1)[0].strip()
    uid = _INVALID_CHARS.sub("_", uid)
    if not uid or uid in (".", ".."):
        raise ValueError(f"非法用户 ID: {user_id!r}")
    return uid


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _rows_to_output(rows) -> list[dict]:
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "time": r["time"],
                "time_type": r["time_type"],
                "action": r["action"],
                "content": r["content"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
        )
    return out


@mcp.tool()
def add_event(user_id: str, time: str, action: str, content: str = "", time_type: str = "精确") -> dict:
    """安排定时提醒，到点后你会被拉起提醒对方。对方有需要提醒的情景时必须调用，光在聊天里答应不算数。时间要换算成绝对时间 YYYY-MM-DD HH:MM（如 2026-08-01 22:30）。time_type 精确=准点提醒，粗略=前后约 20 分钟内提醒。提醒名（action）相同且还没到期的提醒会被视为同一条：对方改时间/改内容时直接更新原来那条，不会新建重复的；完全相同的提醒（同时间同提醒名）直接返回已有那条。不同的事请用不同的提醒名（action）。"""
    if time_type not in ("精确", "粗略"):
        raise ValueError("time_type 只能为「精确」或「粗略」")
    uid = _sanitize_user_id(user_id)
    event_time = _validate_time(time)
    now_str = datetime.now().strftime(TIME_FORMAT)
    event = {
        "id": uuid.uuid4().hex[:12],
        "time": event_time,
        "time_type": time_type,
        "action": action,
        "content": content,
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _lock, _connect() as conn:
        # 1) 完全相同的提醒（同用户+同时间+同 action）：直接返回已有那条，
        #    防止重复触发 / 提醒触发后又被当成"重新设置"再建一条导致无限循环。
        exact = conn.execute(
            "SELECT * FROM events WHERE user_id = ? AND time = ? AND action = ? "
            "ORDER BY created_at ASC LIMIT 1",
            (uid, event_time, action),
        ).fetchall()
        if exact:
            return _rows_to_output([exact[0]])[0]
        # 2) 同 action 且未到期（时间还没到）：视为对方在改时间/内容，
        #    直接更新原来那条，避免 LLM 不调 update_event 而是新建导致重复提醒。
        upcoming = conn.execute(
            "SELECT * FROM events WHERE user_id = ? AND action = ? AND time >= ? "
            "ORDER BY created_at ASC LIMIT 1",
            (uid, action, now_str),
        ).fetchall()
        if upcoming:
            old = upcoming[0]
            conn.execute(
                "UPDATE events SET time = ?, time_type = ?, content = ?, updated_at = ? "
                "WHERE id = ?",
                (event_time, time_type, content, _now(), old["id"]),
            )
            row = conn.execute(
                "SELECT * FROM events WHERE id = ?", (old["id"],)
            ).fetchone()
            return _rows_to_output([row])[0]
        conn.execute(
            "INSERT INTO events (id, user_id, time, time_type, action, content, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event["id"], uid, event["time"], event["time_type"], event["action"], event["content"], event["created_at"], event["updated_at"]),
        )
    return event


@mcp.tool()
def query_events(
    user_id: str,
    keyword: str = "",
    time: str = "",
    time_from: str = "",
    time_to: str = "",
    action: str = "",
    time_type: str = "",
    order: str = "asc",
    offset: int = 0,
    limit: int = 50,
) -> list[dict]:
    """查对方现有的提醒（按时间/关键词/提醒名）。承诺新提醒前先查查有没有重复、确认的时候用。"""
    if time_type and time_type not in ("精确", "粗略"):
        raise ValueError("time_type 只能为「精确」或「粗略」")
    if order not in ("asc", "desc"):
        raise ValueError("order 只能为「asc」或「desc」")
    if time_from:
        _validate_time(time_from)
    if time_to:
        _validate_time(time_to)
    if time_from and time_to and time_from > time_to:
        raise ValueError("time_from 不能晚于 time_to")

    uid = _sanitize_user_id(user_id)
    clauses = ["user_id = ?"]
    params: list = [uid]
    if time:
        clauses.append("time = ?")
        params.append(time)
    if time_from:
        clauses.append("time >= ?")
        params.append(time_from)
    if time_to:
        clauses.append("time <= ?")
        params.append(time_to)
    if action:
        clauses.append("action = ?")
        params.append(action)
    if time_type:
        clauses.append("time_type = ?")
        params.append(time_type)
    if keyword:
        clauses.append("(action LIKE ? OR content LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw])

    sql = (
        f"SELECT * FROM events WHERE {' AND '.join(clauses)} "
        f"ORDER BY time {'DESC' if order == 'desc' else 'ASC'} "
        "LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])
    with _lock, _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return _rows_to_output(rows)


@mcp.tool()
def get_event(user_id: str, event_id: str) -> dict | None:
    """按 ID 查一条提醒，没有返回 None。"""
    uid = _sanitize_user_id(user_id)
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM events WHERE user_id = ? AND id = ?", (uid, event_id)
        ).fetchone()
    return _rows_to_output([row])[0] if row else None


@mcp.tool()
def update_event(user_id: str, event_id: str, time: str = "", action: str = "", content: str = "", time_type: str = "") -> dict | None:
    """改提醒的时间/内容/提醒名（留空不变）。对方改主意了用这个。"""
    uid = _sanitize_user_id(user_id)
    sets = []
    params: list = []
    if time:
        sets.append("time = ?")
        params.append(_validate_time(time))
    if time_type:
        if time_type not in ("精确", "粗略"):
            raise ValueError("time_type 只能为「精确」或「粗略」")
        sets.append("time_type = ?")
        params.append(time_type)
    if action:
        sets.append("action = ?")
        params.append(action)
    if content:
        sets.append("content = ?")
        params.append(content)
    if not sets:
        return get_event(user_id, event_id)
    sets.append("updated_at = ?")
    params.append(_now())
    params.extend([uid, event_id])

    with _lock, _connect() as conn:
        cur = conn.execute(
            f"UPDATE events SET {', '.join(sets)} WHERE user_id = ? AND id = ?",
            params,
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM events WHERE user_id = ? AND id = ?", (uid, event_id)
        ).fetchone()
    return _rows_to_output([row])[0]


@mcp.tool()
def delete_event(user_id: str, event_id: str) -> bool:
    """删一条提醒。"""
    uid = _sanitize_user_id(user_id)
    with _lock, _connect() as conn:
        cur = conn.execute(
            "DELETE FROM events WHERE user_id = ? AND id = ?", (uid, event_id)
        )
    return cur.rowcount > 0


@mcp.tool()
def list_actions(user_id: str) -> list[str]:
    """列出该用户用过的提醒名（如"睡觉"、"喝水"）。"""
    uid = _sanitize_user_id(user_id)
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT action FROM events WHERE user_id = ? ORDER BY action",
            (uid,),
        ).fetchall()
    return [r["action"] for r in rows if r["action"]]


@mcp.tool()
def list_users() -> list[str]:
    """列出有提醒记录的用户 ID（系统调度器内部使用）。"""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM events ORDER BY user_id"
        ).fetchall()
    return [r["user_id"] for r in rows]


@mcp.tool()
def storage_info(user_id: str) -> dict:
    """（内部）声明本插件为该用户存储的数据位置，清除用户数据时用。"""
    return {
        "user_data": [
            {
                "kind": "db",
                "path": str(DB_PATH),
                "table": "events",
                "user_column": "user_id",
                "user_value": _sanitize_user_id(user_id),
            }
        ]
    }


@mcp.resource("events://stats/{user_id}")
def events_stats(user_id: str) -> str:
    """用户待提醒数量统计。"""
    uid = _sanitize_user_id(user_id)
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE user_id = ?", (uid,)
        ).fetchone()
    return f"事件总数 {row['c']}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
