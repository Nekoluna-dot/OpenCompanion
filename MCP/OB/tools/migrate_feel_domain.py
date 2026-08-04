"""一次性迁移：把旧 feel 桶 domain=[] 修成 domain=["feel"]。

背景：iter 1.6 之前 hold(feel=True) 创建桶时 domain 留空，
导致 dashboard 显示「未分类」，分组与新 feel 桶不一致。

用法：
    python tools/migrate_feel_domain.py          # 仅扫描，不写盘
    python tools/migrate_feel_domain.py --apply  # 明确执行迁移

这是旧 vault 兼容工具；保留只读默认值，避免误运行改变记忆元数据。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from utils import load_config  # noqa: E402
from bucket_manager import BucketManager  # noqa: E402


async def main(apply: bool = False) -> None:
    config = load_config()
    mgr = BucketManager(config)
    all_buckets = await mgr.list_all(include_archive=True)
    fixed = 0
    skipped = 0
    for b in all_buckets:
        meta = b.get("metadata", {})
        if meta.get("type") != "feel":
            continue
        domain = meta.get("domain", []) or []
        if domain == ["feel"]:
            skipped += 1
            continue
        bid = b["id"]
        print(f"  [fix] {bid}: domain={domain!r} -> ['feel']")
        if apply:
            await mgr.update(bid, domain=["feel"])
        fixed += 1
    print(f"\n完成：修复 {fixed} 个 feel 桶，跳过 {skipped} 个已正确的。")
    if not apply:
        print("（只读预演，未写盘；确认后用 --apply）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="明确执行迁移；默认仅扫描")
    ap.add_argument("--dry", action="store_true", help="兼容旧命令；默认本来就是只读")
    args = ap.parse_args()
    asyncio.run(main(apply=args.apply and not args.dry))
