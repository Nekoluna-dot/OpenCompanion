"""
这个是快捷清空ombrebrain的数据库文件的 小心使用
"""
import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent / "MCP" / "OB" / "buckets"

_CLEAR_DIRS = [
    "dynamic",
    "permanent",
    "feel",
    "plans",
    "letters",
    "archive",
    "_ledger",
]
_DELETE_FILES = [
    "embeddings.db",
    "embeddings.db.backup",
    "dehydration_cache.db",
    ".embedding_outbox.json",
    ".embedding_outbox.lock",
    ".logs/_pending_migration_status.json",
]


def main() -> int:
    if not _BASE.is_dir():
        print(f"找不到数据目录: {_BASE}")
        return 1
    if "--yes" not in sys.argv:
        print(f"即将清空全部记忆数据: {_BASE}")
        answer = input("继续? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消")
            return 0
    removed = 0
    for rel in _CLEAR_DIRS:
        d = _BASE / rel
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file():
                p.unlink()
                removed += 1
        for p in sorted(d.rglob("*"), reverse=True):
            if p.is_dir():
                try:
                    p.rmdir()
                except OSError:
                    pass
    for rel in _DELETE_FILES:
        p = _BASE / rel
        if p.exists():
            p.unlink()
            removed += 1
    print(f"已清空 {removed} 个文件。OB 全部记忆已重置。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
