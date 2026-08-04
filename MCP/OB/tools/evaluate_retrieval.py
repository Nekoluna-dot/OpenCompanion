#!/usr/bin/env python3
"""
tools/evaluate_retrieval.py — 只读检索质量评测 CLI

这是什么：给一份「查询 → 期望命中的真实 bucket ID」用例文件，跑一遍检索，
          算 Hit@K / Recall@K / MRR，并打印每条查询里期望桶的实际排名。
做什么：默认只评测关键词/BM25 通道（离线，不调用也不消耗 embedding API）；
        加 --with-embedding 才为每条查询算向量近邻分数、评测完整混合检索。
不做什么：绝不修改记忆——不写、不 touch、不重排。纯只读，可安全对真实 vault 跑。
对外暴露：build_parser() / main(argv)。

用法：
    python tools/evaluate_retrieval.py retrieval-cases.json --top-k 5
    python tools/evaluate_retrieval.py retrieval-cases.json --with-embedding
    python tools/evaluate_retrieval.py retrieval-cases.json --min-hit-rate 0.8   # 低于基线返回非零退出码(供 CI)

用例文件格式：
    {"cases": [{"name": "发布流程", "query": "蓝色发布通道", "domain": "work", "expected_ids": ["abc123"]}]}

评测核心逻辑在 src/retrieval_eval.py（normalize_cases / evaluate_cases），本文件只做
参数解析、构造 BucketManager、可选算向量分数、输出 JSON。参考 tools/clean_orphan_embeddings.py 的构造方式。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from utils import load_config, setup_logging  # noqa: E402
from bucket_manager import BucketManager  # noqa: E402
from embedding_engine import EmbeddingEngine  # noqa: E402
from retrieval_eval import normalize_cases, evaluate_cases  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only retrieval quality evaluation (Hit@K / Recall@K / MRR)")
    parser.add_argument("cases_file", type=Path, help="JSON file with a 'cases' list (query + expected_ids)")
    parser.add_argument("--top-k", default=5, type=int, help="Evaluate against the top-K results (default 5)")
    parser.add_argument(
        "--with-embedding",
        action="store_true",
        help="Also score the vector channel (calls the embedding API); default is keyword/BM25 only, offline",
    )
    parser.add_argument("--min-hit-rate", type=float, default=None, help="Exit non-zero if hit_rate falls below this (for CI)")
    parser.add_argument("--buckets-dir", type=Path, default=None, help="Override the vault directory (default: config)")
    parser.add_argument("--output", type=Path, help="Optional JSON output file")
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config()
    if args.buckets_dir is not None:
        config["buckets_dir"] = str(args.buckets_dir)

    raw = json.loads(args.cases_file.read_text(encoding="utf-8"))
    cases = normalize_cases(raw)

    vector_scores_by_query: dict[str, dict[str, float]] | None = None
    embedding_engine = None
    if args.with_embedding:
        # 显式请求向量通道：构造 embedding 引擎，为每条唯一 query 算 {bucket_id: score}。
        embedding_engine = EmbeddingEngine(config)
        if not embedding_engine.enabled:
            raise SystemExit(
                "--with-embedding 需要已启用的 embedding 配置（config.embedding.enabled + API key），"
                "当前为待机状态。去掉 --with-embedding 可只评测关键词通道。"
            )
        vector_scores_by_query = {}
        for query in {case["query"] for case in cases}:
            pairs = await embedding_engine.search_similar(query, top_k=max(args.top_k, 10))
            vector_scores_by_query[query] = {str(bid): float(score) for bid, score in pairs}

    # 离线模式 embedding_engine=None；search 契约保证「vector_scores 为空时不调用 embedding API」。
    bucket_mgr = BucketManager(config, embedding_engine=embedding_engine)
    report = await evaluate_cases(
        bucket_mgr,
        cases,
        top_k=args.top_k,
        vector_scores_by_query=vector_scores_by_query,
    )
    report["mode"] = "hybrid" if args.with_embedding else "keyword_only"
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging("WARNING")  # 日志走 stderr，保持 stdout 只有 JSON
    report = asyncio.run(_run(args))

    text = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)

    if args.min_hit_rate is not None and report.get("hit_rate", 0.0) < args.min_hit_rate:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
