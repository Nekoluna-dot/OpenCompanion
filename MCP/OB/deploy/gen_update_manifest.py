#!/usr/bin/env python3
"""发布侧：生成 update_manifest.json（热更新完整性清单）。

背景（安全加固 #1 / B1）：`/api/do-update` 已经内置「若仓库含 update_manifest.json
就逐文件核对 sha256/size，不符则整体中止、不落盘」的校验（见 web/meta._plan_update_files）。
但这只有当仓库里**真的带**这份清单时才生效。本脚本在发布时生成它，对用户完全零感知——
用户端热更新会自动多一道防篡改/防下坏的保险。

清单只覆盖热更新会覆盖的 src/ 与 frontend/。路径用 repo 相对（如 "src/server.py"），
与 _plan_update_files 的候选键一致。

用法（发布流程里跑一次，把产物一并提交/发布）：
    python deploy/gen_update_manifest.py               # 写到 <repo>/update_manifest.json
    python deploy/gen_update_manifest.py --check        # 只校验现有清单是否与当前代码一致（CI 用）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TRACKED_DIRS = ("src", "frontend")
_MANIFEST_PATH = os.path.join(_REPO_ROOT, "update_manifest.json")


def _iter_files(repo_root: str):
    for top in _TRACKED_DIRS:
        base = os.path.join(repo_root, top)
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            # 跳过缓存/编译产物，别把 __pycache__ 写进清单
            if "__pycache__" in root.split(os.sep):
                continue
            for fn in files:
                if fn.endswith((".pyc", ".pyo")):
                    continue
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, repo_root).replace(os.sep, "/")
                yield rel, full


def build_manifest(repo_root: str = _REPO_ROOT) -> dict:
    version = "unknown"
    vpath = os.path.join(repo_root, "VERSION")
    if os.path.isfile(vpath):
        with open(vpath, "r", encoding="utf-8") as f:
            version = f.read().strip() or "unknown"
    entries = []
    for rel, full in sorted(_iter_files(repo_root)):
        with open(full, "rb") as f:
            data = f.read()
        entries.append({
            "path": rel,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })
    return {
        "version": version,
        "rollout_strategy": "single-node",
        "files": entries,
    }


def _write(manifest: dict, path: str = _MANIFEST_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="生成 / 校验 update_manifest.json")
    ap.add_argument("--check", action="store_true", help="只校验现有清单是否与当前代码一致（不写文件）")
    args = ap.parse_args(argv[1:])

    fresh = build_manifest()
    if args.check:
        if not os.path.isfile(_MANIFEST_PATH):
            print("update_manifest.json 不存在，请先生成。", file=sys.stderr)
            return 1
        with open(_MANIFEST_PATH, "r", encoding="utf-8") as f:
            current = json.load(f)
        if current.get("files") != fresh["files"]:
            print("update_manifest.json 与当前 src/frontend 不一致，请重新生成。", file=sys.stderr)
            return 1
        print("update_manifest.json 与当前代码一致 ✓")
        return 0

    _write(fresh)
    print(f"已生成 {_MANIFEST_PATH}（{len(fresh['files'])} 个文件，version={fresh['version']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
