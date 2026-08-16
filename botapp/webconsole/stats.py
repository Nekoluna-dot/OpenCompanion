"""网页控制台：统计页数据（标准库实现，无新依赖）。

数据源：
- data/events.db        提醒事件（事件提醒工具写入）
- conversation/ 目录    对话存档（按用户 JSON，含每条消息）
- 控制台日志缓冲        近期活动（Receive/Reply/Tool 等计数）
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_EVENTS_DB = _ROOT / "data" / "events.db"
_CONV_DIR = _ROOT / "conversation"

_lock = threading.Lock()


def collect_stats(log_lines: list[str] | None = None) -> dict:
    """汇总统计：提醒事件 + 对话存档 + 日志活动 + LLM 用量 + 运行状态。"""
    lines = log_lines or []
    return {
        "events": _events_stats(),
        "conversation": _conversation_stats(),
        "logs": _log_stats(lines),
        "tokens": _token_stats(lines),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------------------------------------------------------------------------
# events.db 提醒事件
# ---------------------------------------------------------------------------
def _events_stats() -> dict:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    empty = {
        "total": 0,
        "upcoming": 0,
        "users": 0,
        "by_action": [],
        "daily": [],
    }
    if not _EVENTS_DB.exists():
        return empty
    try:
        con = sqlite3.connect(f"file:{_EVENTS_DB}?mode=ro", uri=True)
    except sqlite3.Error:
        return empty
    try:
        cur = con.cursor()
        total = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        upcoming = cur.execute(
            "SELECT COUNT(*) FROM events WHERE time >= ?", (now_str,)
        ).fetchone()[0]
        users = cur.execute("SELECT COUNT(DISTINCT user_id) FROM events").fetchone()[0]
        by_action = [
            {"name": row[0], "count": row[1]}
            for row in cur.execute(
                "SELECT action, COUNT(*) c FROM events GROUP BY action ORDER BY c DESC LIMIT 8"
            ).fetchall()
        ]
        # 最近 14 天每天的新增提醒数（按 created_at 日期）
        start = (datetime.now() - timedelta(days=13)).strftime("%Y-%m-%d")
        rows = cur.execute(
            "SELECT substr(created_at, 1, 10) d, COUNT(*) c FROM events "
            "WHERE created_at >= ? GROUP BY d",
            (start,),
        ).fetchall()
        by_day = {r[0]: r[1] for r in rows}
        daily = [
            {"date": (datetime.now() - timedelta(days=i)).strftime("%m-%d"),
             "count": by_day.get((datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d"), 0)}
            for i in range(13, -1, -1)
        ]
        return {
            "total": total,
            "upcoming": upcoming,
            "users": users,
            "by_action": by_action,
            "daily": daily,
        }
    except sqlite3.Error:
        return empty
    finally:
        con.close()


# ---------------------------------------------------------------------------
# conversation/ 对话存档
# ---------------------------------------------------------------------------
def _conversation_stats() -> dict:
    empty = {"users": 0, "files": 0, "messages": 0, "daily": [], "total_bytes": 0}
    if not _CONV_DIR.is_dir():
        return empty
    files = list(_CONV_DIR.glob("*.json"))
    files = [f for f in files if not f.name.endswith(".tmp")]
    users = 0
    total_msgs = 0
    total_bytes = 0
    per_day: dict[str, int] = {}
    for f in files:
        total_bytes += f.stat().st_size
        if "@" not in f.stem:
            continue
        users += 1
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = []
        total_msgs += len(data) if isinstance(data, list) else 0
        try:
            day = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d")
        except OSError:
            continue
        per_day[day] = per_day.get(day, 0) + 1
    start = (date.today() - timedelta(days=13)).isoformat()
    daily = []
    for i in range(13, -1, -1):
        d = (date.today() - timedelta(days=i))
        daily.append({"date": d.strftime("%m-%d"), "count": per_day.get(d.isoformat(), 0)})
    return {
        "users": users,
        "files": len(files),
        "messages": total_msgs,
        "daily": daily,
        "total_bytes": total_bytes,
    }


# ---------------------------------------------------------------------------
# LLM Token 用量（解析 [Token] 日志行，仅缓冲内）
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"\[Token\] 输入=(\d+)(?:\(缓存命中(\d+)\))? 输出=(\d+)")


def _token_stats(lines: list[str]) -> dict:
    calls = 0
    prompt = 0
    completion = 0
    cache_hit = 0
    for line in lines:
        m = _TOKEN_RE.search(line)
        if m:
            calls += 1
            prompt += int(m.group(1))
            cache_hit += int(m.group(2) or 0)
            completion += int(m.group(3))
    return {
        "calls": calls,
        "prompt": prompt,
        "completion": completion,
        "cache_hit": cache_hit,
        "cache_miss": prompt - cache_hit,
        "total": prompt + completion,
    }


# ---------------------------------------------------------------------------
# 日志活动统计（仅缓冲内，最近约 4000 行）
# ---------------------------------------------------------------------------
def _log_stats(lines: list[str]) -> dict:
    counts: dict[str, int] = {}
    last_hour = 0
    now = datetime.now()
    for line in lines:
        m = line.find("] [")
        if m <= 0:
            continue
        tag = line[m + 3: line.find("]", m + 3)]
        if not tag:
            continue
        counts[tag] = counts.get(tag, 0) + 1
        ts = line[1: m].strip()
        try:
            t = datetime.strptime(ts, "%H:%M:%S")
            t = t.replace(year=now.year, month=now.month, day=now.day)
            if (now - t).total_seconds() <= 3600 and (now - t).total_seconds() >= 0:
                last_hour += 1
        except ValueError:
            pass
    return {"by_tag": counts, "last_hour": last_hour}
