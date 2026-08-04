import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("record-server")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
_lock = threading.Lock()

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _sanitize_user_id(user_id: str) -> str:
    uid = _INVALID_CHARS.sub("_", user_id.strip())
    if not uid or uid in (".", ".."):
        raise ValueError(f"Invalid user ID: {user_id!r}")
    return uid


def _user_file(user_id: str) -> Path:
    return DATA_DIR / "records" / f"{_sanitize_user_id(user_id)}.json"


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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _user_file(user_id)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _match_keyword(record: dict, keyword: str) -> bool:
    if not keyword:
        return True
    kw = keyword.lower()
    text = " ".join(
        str(record.get(k, "")) for k in ("contact", "category", "title", "content")
    ).lower()
    return kw in text


def _to_output(record: dict) -> dict:
    return {k: record[k] for k in ("id", "contact", "category", "title", "content", "created_at", "updated_at")}


@mcp.tool()
def add_record(user_id: str, contact: str, content: str, category: str = "备忘", title: str = "") -> dict:
    """记下关于对方的重要信息（名字、喜好、计划、重要日期等），跨会话保存，以后聊天能想起来。觉得对方的事值得记住就用这个。"""
    record = {
        "id": uuid.uuid4().hex[:12],
        "contact": contact,
        "category": category,
        "title": title or content[:20],
        "content": content,
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _lock:
        records = _load(user_id)
        records.append(record)
        _save(user_id, records)
    return _to_output(record)


@mcp.tool()
def query_records(user_id: str, keyword: str = "", contact: str = "", category: str = "", limit: int = 20) -> list[dict]:
    """查找以前记过的对方信息（按关键词/称呼/分类）。对方问起以前的事、或你想确认自己记过什么时用。"""
    with _lock:
        records = _load(user_id)
    result = []
    for r in records:
        if contact and r.get("contact") != contact:
            continue
        if category and r.get("category") != category:
            continue
        if not _match_keyword(r, keyword):
            continue
        result.append(_to_output(r))
    return result[:limit]


@mcp.tool()
def get_record(user_id: str, record_id: str) -> dict | None:
    """按 ID 查一条存档记录，没有返回 None。"""
    with _lock:
        records = _load(user_id)
    for r in records:
        if r["id"] == record_id:
            return _to_output(r)
    return None


@mcp.tool()
def update_record(user_id: str, record_id: str, content: str = "", category: str = "", title: str = "") -> dict | None:
    """更新一条已存记录（内容/分类/标题，留空不变）。对方信息变了（比如换了喜好）用这个改。"""
    with _lock:
        records = _load(user_id)
        for r in records:
            if r["id"] != record_id:
                continue
            if content:
                r["content"] = content
            if category:
                r["category"] = category
            if title:
                r["title"] = title
            r["updated_at"] = _now()
            _save(user_id, records)
            return _to_output(r)
    return None


@mcp.tool()
def delete_record(user_id: str, record_id: str) -> bool:
    """按 ID 删除一条存档记录。"""
    with _lock:
        records = _load(user_id)
        remaining = [r for r in records if r["id"] != record_id]
        if len(remaining) == len(records):
            return False
        _save(user_id, remaining)
    return True


@mcp.tool()
def list_contacts(user_id: str) -> list[str]:
    """列出该用户存档里的所有称呼。"""
    with _lock:
        records = _load(user_id)
    return sorted({r.get("contact", "") for r in records if r.get("contact")})


@mcp.tool()
def list_categories(user_id: str) -> list[str]:
    """列出存档用过的全部分类（性格/待办/背景/备忘）。"""
    with _lock:
        records = _load(user_id)
    return sorted({r.get("category", "") for r in records if r.get("category")})


@mcp.tool()
def storage_info(user_id: str) -> dict:
    """（内部）声明本插件为该用户存储的数据位置，清除用户数据时用。"""
    return {
        "user_data": [
            {"kind": "file", "path": str(_user_file(user_id))},
        ]
    }


@mcp.resource("record://stats/{user_id}")
def record_stats(user_id: str) -> str:
    """用户档案统计：总记录数、对象数、分类数。"""
    with _lock:
        records = _load(user_id)
    contacts = len({r.get("contact") for r in records})
    categories = len({r.get("category") for r in records})
    return f"记录总数 {len(records)}，对象数 {contacts}，分类数 {categories}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
