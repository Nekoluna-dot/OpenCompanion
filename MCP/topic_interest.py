import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("topic-interest")

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
    return DATA_DIR / "topics" / f"{_sanitize_user_id(user_id)}.json"


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


def _validate_score(name: str, value: int, lo: int, hi: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be int ({lo}-{hi}), got: {value!r}")
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be in {lo}-{hi}, got: {value}")
    return value


def _to_output(record: dict) -> dict:
    return {k: record[k] for k in ("id", "topic", "interest", "favorability", "note", "created_at", "updated_at")}


@mcp.tool()
def add_topic_interest(user_id: str, topic: str, interest: int, favorability: int, note: str = "") -> dict:
    """记录对方对某话题的兴趣度和好感度（兴趣 0-10，好感 -10~10）。对方明显喜欢/反感什么（爱好、食物、人）时用，方便以后聊。"""
    record = {
        "id": uuid.uuid4().hex[:12],
        "topic": topic.strip(),
        "interest": _validate_score("interest", interest, 0, 10),
        "favorability": _validate_score("favorability", favorability, -10, 10),
        "note": note,
        "created_at": _now(),
        "updated_at": _now(),
    }
    if not record["topic"]:
        raise ValueError("topic cannot be empty")
    with _lock:
        records = _load(user_id)
        records.append(record)
        _save(user_id, records)
    return _to_output(record)


@mcp.tool()
def query_topic_interests(
    user_id: str,
    keyword: str = "",
    min_interest: int | None = None,
    min_favorability: int | None = None,
    order: str = "desc",
    limit: int = 50,
) -> list[dict] | str:
    """查对方感兴趣的话题（可按关键词/最低兴趣度过滤）。找聊天话题、对方问"我喜欢啥"时用。"""
    if order not in ("asc", "desc"):
        raise ValueError('order must be "asc" or "desc"')
    with _lock:
        records = _load(user_id)
    result = []
    for r in records:
        if keyword and keyword.lower() not in " ".join((r.get("topic", ""), r.get("note", ""))).lower():
            continue
        if min_interest is not None and r.get("interest", 0) < min_interest:
            continue
        if min_favorability is not None and r.get("favorability", 0) < min_favorability:
            continue
        result.append(_to_output(r))
    result.sort(key=lambda r: r["interest"], reverse=(order == "desc"))
    if not result:
        return "没数据"
    return result[:limit]


@mcp.tool()
def get_topic_interest(user_id: str, record_id: str) -> dict | str:
    """按 ID 查一条话题记录，没有返回"没数据"。"""
    with _lock:
        records = _load(user_id)
    for r in records:
        if r["id"] == record_id:
            return _to_output(r)
    return "[none]"


@mcp.tool()
def update_topic_interest(
    user_id: str,
    record_id: str,
    interest: int | None = None,
    favorability: int | None = None,
    note: str = "",
) -> dict | str:
    """更新话题的兴趣度/好感度/备注（留空不变）。对方态度变了用这个。"""
    with _lock:
        records = _load(user_id)
        for r in records:
            if r["id"] != record_id:
                continue
            if interest is not None:
                r["interest"] = _validate_score("interest", interest, 0, 10)
            if favorability is not None:
                r["favorability"] = _validate_score("favorability", favorability, -10, 10)
            if note:
                r["note"] = note
            r["updated_at"] = _now()
            _save(user_id, records)
            return _to_output(r)
    return "没数据"


@mcp.tool()
def delete_topic_interest(user_id: str, record_id: str) -> str:
    """删一条话题记录，返回"已删除"或"没数据"。"""
    with _lock:
        records = _load(user_id)
        remaining = [r for r in records if r["id"] != record_id]
        if len(remaining) == len(records):
            return "没数据"
        _save(user_id, remaining)
    return "已删除"


@mcp.tool()
def list_topics(user_id: str, order: str = "desc") -> list[str] | str:
    """列出该用户所有话题名，按兴趣度排序。"""
    with _lock:
        records = _load(user_id)
    if order not in ("asc", "desc"):
        raise ValueError('order must be "asc" or "desc"')
    records = sorted(records, key=lambda r: r.get("interest", 0), reverse=(order == "desc"))
    if not records:
        return "没数据"
    return [r["topic"] for r in records]


@mcp.tool()
def storage_info(user_id: str) -> dict:
    """声明本插件为该用户存储的数据位置（内部使用）。返回属于该用户的文件路径，便于清除用户数据时定位。"""
    return {
        "user_data": [
            {"kind": "file", "path": str(_user_file(user_id))},
        ]
    }


@mcp.resource("topics://stats/{user_id}")
def topics_stats(user_id: str) -> str:
    """用户话题统计：数量、平均兴趣度、平均好感度。"""
    with _lock:
        records = _load(user_id)
    if not records:
        return "暂无话题记录"
    avg_interest = sum(r.get("interest", 0) for r in records) / len(records)
    avg_favor = sum(r.get("favorability", 0) for r in records) / len(records)
    return f"话题 {len(records)} 个，平均兴趣度 {avg_interest:.1f}/10，平均好感度 {avg_favor:.1f}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
