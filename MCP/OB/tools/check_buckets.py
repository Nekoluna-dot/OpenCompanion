"""Read-only vault integrity check used for operations and restore drills."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from utils import load_config
from vault_health import inspect_vault


def _pending_ids(buckets_dir: str) -> set[str]:
    path = os.path.join(buckets_dir, ".embedding_outbox.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        items = payload.get("items", {}) if isinstance(payload, dict) else {}
        return {str(item) for item in items} if isinstance(items, dict) else set()
    except (OSError, ValueError):
        return set()


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Ombre Brain Markdown and vector integrity")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    config = load_config()
    buckets_dir = str(config.get("buckets_dir") or "")
    embed_cfg = config.get("embedding", {}) or {}
    db_path = str(embed_cfg.get("db_path") or os.path.join(buckets_dir, "embeddings.db"))
    report = inspect_vault(buckets_dir, db_path, _pending_ids(buckets_dir))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        markdown = report["markdown"]
        sqlite = report["sqlite"]
        print(f"Vault health: {report['status'].upper()}")
        print(
            f"Markdown: {markdown['file_count']} files, "
            f"{markdown['parse_error_count']} parse errors, "
            f"{markdown['duplicate_id_count']} duplicate IDs"
        )
        print(
            f"Vectors: {sqlite['vector_count']} rows, "
            f"{sqlite['orphan_count']} orphaned, "
            f"{sqlite['missing_unqueued_count']} missing and unqueued, "
            f"SQLite quick_check={'ok' if sqlite['quick_check_ok'] else 'failed'}"
        )
        for item in markdown["parse_errors"]:
            print(f"ERROR {item['path']}: {item['error']}")
        for bucket_id, paths in markdown["duplicate_ids"].items():
            print(f"ERROR duplicate id {bucket_id}: {', '.join(paths)}")
        if sqlite["error"]:
            print(f"ERROR embeddings.db: {sqlite['error']}")
    return 1 if report["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
