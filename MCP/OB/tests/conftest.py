# ============================================================
# Shared test fixtures — isolated temp environment for all tests
# 共享测试 fixtures —— 为所有测试提供隔离的临时环境
#
# IMPORTANT: All tests run against a temp directory.
# Your real /data or local buckets are NEVER touched.
# 重要：所有测试在临时目录运行，绝不触碰真实记忆数据。
# ============================================================

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# ------------------------------------------------------------
# iter 1.8: 必须在任何 src/* 导入之前设置 OMBRE_BUCKETS_DIR
# iter 1.9 F: 统一推荐 OMBRE_VAULT_DIR；测试也优先用新名
# Must set OMBRE_VAULT_DIR / OMBRE_BUCKETS_DIR BEFORE any test
# imports src/server.py, because server.py runs load_config() at
# import time which mkdirs /data.
# ------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEST_BUCKETS = _REPO_ROOT / "test_buckets"
_TEST_BUCKETS.mkdir(exist_ok=True)
if not os.environ.get("OMBRE_VAULT_DIR") and not os.environ.get("OMBRE_BUCKETS_DIR"):
    # iter 1.9 F: 设两个变量同步指向同一目录，避免某个测试用 monkeypatch 覆盖单个变量
    # 时被另一个变量「卡住」。两者都指向 test_buckets 时，谁优先都不影响测试结果。
    os.environ["OMBRE_VAULT_DIR"] = str(_TEST_BUCKETS)
    os.environ["OMBRE_BUCKETS_DIR"] = str(_TEST_BUCKETS)

# F-09: embedding.enabled=true 时无 key 会拒绝启动。测试环境注入 dummy key，
# 避免 `import server`（模块级导入）触发 SystemExit。
# 真实 API 调用在测试中均被 mock，dummy key 不会发起网络请求。
if not os.environ.get("OMBRE_EMBED_API_KEY"):
    os.environ["OMBRE_EMBED_API_KEY"] = "__test_dummy__"

# Ensure src/ is importable
sys.path.insert(0, str(_REPO_ROOT / "src"))


@pytest.fixture
def test_config(tmp_path):
    """
    Minimal config pointing to a temp directory.
    Uses spec-correct scoring weights (after B-05, B-06, B-07 fixes).
    """
    buckets_dir = str(tmp_path / "buckets")
    os.makedirs(os.path.join(buckets_dir, "permanent"), exist_ok=True)
    os.makedirs(os.path.join(buckets_dir, "dynamic"), exist_ok=True)
    os.makedirs(os.path.join(buckets_dir, "archive"), exist_ok=True)
    os.makedirs(os.path.join(buckets_dir, "feel"), exist_ok=True)

    return {
        "buckets_dir": buckets_dir,
        "merge_threshold": 75,
        "matching": {"fuzzy_threshold": 50, "max_results": 10},
        "wikilink": {"enabled": False},
        # Spec-correct weights (post B-05/B-06/B-07 fix)
        "scoring_weights": {
            "topic_relevance": 4.0,
            "emotion_resonance": 2.0,
            "time_proximity": 1.5,   # spec: 1.5 (was 2.5 in buggy code)
            "importance": 1.0,
            "content_weight": 1.0,   # spec: 1.0 (was 3.0 in buggy code)
        },
        "decay": {
            "lambda": 0.05,
            "threshold": 0.3,
            "check_interval_hours": 24,
            "emotion_weights": {"base": 1.0, "arousal_boost": 0.8},
        },
        "dehydration": {
            "api_key": os.environ.get("OMBRE_COMPRESS_API_KEY", "test-key"),
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model": "gemini-2.5-flash-lite",
        },
        "embedding": {
            "api_key": os.environ.get("OMBRE_EMBED_API_KEY", ""),
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model": "gemini-embedding-001",
            "enabled": False,
        },
    }


@pytest.fixture
def buggy_config(tmp_path):
    """
    Config using the PRE-FIX (buggy) scoring weights.
    Used in regression tests to document the old broken behaviour.
    """
    buckets_dir = str(tmp_path / "buckets")
    for d in ["permanent", "dynamic", "archive", "feel"]:
        os.makedirs(os.path.join(buckets_dir, d), exist_ok=True)

    return {
        "buckets_dir": buckets_dir,
        "merge_threshold": 75,
        "matching": {"fuzzy_threshold": 50, "max_results": 10},
        "wikilink": {"enabled": False},
        # Buggy weights (before B-05/B-06/B-07 fixes)
        "scoring_weights": {
            "topic_relevance": 4.0,
            "emotion_resonance": 2.0,
            "time_proximity": 2.5,   # B-06: was too high
            "importance": 1.0,
            "content_weight": 3.0,   # B-07: was too high
        },
        "decay": {
            "lambda": 0.05,
            "threshold": 0.3,
            "check_interval_hours": 24,
            "emotion_weights": {"base": 1.0, "arousal_boost": 0.8},
        },
        "dehydration": {
            "api_key": "",
            "base_url": "https://example.com",
            "model": "test-model",
        },
        "embedding": {"enabled": False, "api_key": ""},
    }


class FakeEmbeddingEngine:
    """最小化可用的 embedding 引擎替身。

    Markdown 是写入真源，embedding 是可重建的派生索引。大多数测试要验证
    评分/衰减/检索等逻辑，所以默认 bucket_mgr fixture 配一个永远成功的
    fake；离线写入与后台重试契约在 test_embedding_outbox.py 单独覆盖。
    """

    enabled = True

    def __init__(self):
        self._store: dict[str, list[float]] = {}

    async def generate_and_store(self, bucket_id: str, content: str) -> bool:
        self._store[bucket_id] = [0.1, 0.2, 0.3]
        return True

    def delete_embedding(self, bucket_id: str) -> None:
        self._store.pop(bucket_id, None)

    async def get_embedding(self, bucket_id: str) -> list[float] | None:
        return self._store.get(bucket_id)

    async def search_similar(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        return []


@pytest.fixture
def fake_embedding_engine():
    return FakeEmbeddingEngine()


@pytest.fixture
def bucket_mgr(test_config, fake_embedding_engine):
    from bucket_manager import BucketManager
    return BucketManager(test_config, embedding_engine=fake_embedding_engine)


@pytest.fixture
def decay_eng(test_config, bucket_mgr):
    from decay_engine import DecayEngine
    return DecayEngine(test_config, bucket_mgr)


@pytest.fixture
def mock_dehydrator():
    """
    Mock Dehydrator that returns deterministic results without any API calls.
    Suitable for integration tests that do not test LLM behaviour.
    """
    dh = MagicMock()

    async def fake_dehydrate(content, meta=None):
        return f"[摘要] {content[:60]}"

    async def fake_analyze(content):
        return {
            "domain": ["学习"],
            "valence": 0.7,
            "arousal": 0.5,
            "tags": ["测试"],
            "suggested_name": "测试记忆",
        }

    async def fake_merge(old, new):
        return old + "\n---合并---\n" + new

    async def fake_digest(content):
        return [
            {
                "name": "条目一",
                "content": content[:100],
                "domain": ["日常"],
                "valence": 0.6,
                "arousal": 0.4,
                "tags": ["测试"],
                "importance": 5,
            }
        ]

    dh.dehydrate = AsyncMock(side_effect=fake_dehydrate)
    dh.analyze = AsyncMock(side_effect=fake_analyze)
    dh.merge = AsyncMock(side_effect=fake_merge)
    dh.digest = AsyncMock(side_effect=fake_digest)
    dh.api_available = True
    return dh


@pytest.fixture
def mock_embedding_engine():
    """Mock EmbeddingEngine that returns empty results — no network calls."""
    ee = MagicMock()
    ee.enabled = False
    ee.generate_and_store = AsyncMock(return_value=None)
    ee.search_similar = AsyncMock(return_value=[])
    ee.delete_embedding = MagicMock(return_value=True)   # sync function, not async
    ee.get_embedding = AsyncMock(return_value=None)
    return ee


async def _write_bucket_file(bucket_mgr, content, **kwargs):
    """
    Helper: create a bucket and optionally patch its frontmatter fields.
    Accepts extra kwargs like created/last_active/resolved/digested/pinned.
    Returns bucket_id.
    """
    import frontmatter as fm

    direct_fields = {
        k: kwargs.pop(k) for k in list(kwargs.keys())
        if k in ("created", "last_active", "resolved", "digested", "activation_count")
    }

    bid = await bucket_mgr.create(content=content, **kwargs)

    if direct_fields:
        fpath = bucket_mgr._find_bucket_file(bid)
        post = fm.load(fpath)
        for k, v in direct_fields.items():
            post[k] = v
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(fm.dumps(post))

    return bid
