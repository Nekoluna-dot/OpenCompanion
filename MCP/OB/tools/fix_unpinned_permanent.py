#!/usr/bin/env python3
"""
Audit unpinned permanent buckets.

type=permanent is now a first-class bucket type. A permanent bucket does not
need pinned=True to be valid, visible, or readable by breath. For safety this
script is read-only by default.

Use --force-demote only when you have manually confirmed that the listed files
are legacy buckets that should be moved back to dynamic/.
"""

import argparse
import asyncio
import os
import sys

import frontmatter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from utils import load_config             # noqa: E402
from bucket_manager import BucketManager  # noqa: E402


async def audit(force_demote: bool) -> None:
    config = load_config()
    mgr = BucketManager(config)

    perm_dir = mgr.permanent_dir
    if not os.path.exists(perm_dir):
        print(f"permanent/ does not exist: {perm_dir}")
        return

    candidates = []
    for root, _, files in os.walk(perm_dir):
        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            try:
                post = frontmatter.load(fpath)
            except Exception as e:
                print(f"skip unreadable bucket {fpath}: {e}")
                continue
            meta = post.metadata
            pinned = bool(meta.get("pinned"))
            protected = bool(meta.get("protected"))
            if meta.get("type") == "permanent" and not pinned and not protected:
                candidates.append((fpath, post))

    print(
        "permanent/ scan complete: "
        f"{len(candidates)} explicit permanent buckets without pinned/protected."
    )
    if candidates:
        print("These are valid permanent buckets in the current data model:")
    for fpath, post in candidates:
        bid = post.metadata.get("id") or os.path.splitext(os.path.basename(fpath))[0]
        name = post.metadata.get("name") or ""
        print(f"  - {bid} {name} ({fpath})")

    if not force_demote:
        print("\nNo changes made. Pass --force-demote only for manually verified legacy data.")
        return

    moved = 0
    for fpath, post in candidates:
        domain = post.metadata.get("domain") or ["未分类"]
        post.metadata["type"] = "dynamic"
        post.metadata["pinned"] = False
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(frontmatter.dumps(post))
            mgr._move_bucket(fpath, mgr.dynamic_dir, domain)
            moved += 1
        except OSError as e:
            print(f"demote failed {fpath}: {e}")

    print(f"\nDemoted {moved} manually confirmed buckets to dynamic/.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="accepted for compatibility; no changes are made")
    ap.add_argument("--force-demote", action="store_true", help="explicitly move listed buckets to dynamic/")
    args = ap.parse_args()
    asyncio.run(audit(force_demote=args.force_demote))


if __name__ == "__main__":
    main()
