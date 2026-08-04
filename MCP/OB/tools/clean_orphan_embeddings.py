#!/usr/bin/env python3
"""
clean_orphan_embeddings — 对账并清理孤儿 embedding（iter 1.6 §4）

孤儿 = SQLite 里仍然存着 embedding 行，但桶文件已经在 buckets/ 里找不到。
通常出现在：早期版本删桶没同步删向量；手动删除 markdown；iCloud 冲突。

用法：
    python clean_orphan_embeddings.py            # 仅扫描，dry-run
    python clean_orphan_embeddings.py --apply    # 真的删
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from utils import load_config, setup_logging
from bucket_manager import BucketManager
from embedding_engine import EmbeddingEngine


async def _scan() -> tuple[set[str], set[str]]:
    config = load_config()
    embedding = EmbeddingEngine(config)
    bucket_mgr = BucketManager(config, embedding_engine=embedding)

    if not embedding.enabled:
        print("embedding 未启用 (config.embedding.enabled=false)，无需对账。")
        return set(), set()

    bucket_ids = {b["id"] for b in await bucket_mgr.list_all(include_archive=True)}
    embedding_ids = set(embedding.list_all_ids())

    orphan_ids = embedding_ids - bucket_ids
    return orphan_ids, embedding_ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="真的删除孤儿；不传只 dry-run")
    args = parser.parse_args()

    setup_logging("INFO")
    orphan_ids, embedding_ids = asyncio.run(_scan())

    if not embedding_ids:
        return 0

    print(f"embedding 表共 {len(embedding_ids)} 条；其中孤儿 {len(orphan_ids)} 条。")

    if not orphan_ids:
        print("✓ 没有孤儿 embedding，无需清理。")
        return 0

    for bid in sorted(orphan_ids):
        print(f"  孤儿: {bid}")

    if not args.apply:
        print("\n[dry-run] 加 --apply 才会真的删。")
        return 0

    config = load_config()
    embedding = EmbeddingEngine(config)
    for bid in orphan_ids:
        embedding.delete_embedding(bid)
    print(f"\n✓ 已清理 {len(orphan_ids)} 条孤儿 embedding。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
