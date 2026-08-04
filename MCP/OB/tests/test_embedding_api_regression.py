import os


GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_gemini_openai_compat_uses_bare_model_name():
    from embedding_engine import APIEmbeddingEngine

    engine = APIEmbeddingEngine(
        api_key="test-key",
        base_url=GEMINI_OPENAI_BASE_URL,
        model="gemini-embedding-001",
    )

    assert engine.model_name() == "gemini-embedding-001"


def test_gemini_openai_compat_strips_native_models_prefix():
    from embedding_engine import APIEmbeddingEngine

    engine = APIEmbeddingEngine(
        api_key="test-key",
        base_url=GEMINI_OPENAI_BASE_URL,
        model="models/gemini-embedding-001",
    )

    assert engine.model_name() == "gemini-embedding-001"


def test_gemini_openai_compat_default_dim_matches_gemini_embedding_001(tmp_path):
    from embedding_engine import EmbeddingEngine

    buckets_dir = tmp_path / "buckets"
    os.makedirs(buckets_dir, exist_ok=True)
    engine = EmbeddingEngine(
        {
            "buckets_dir": str(buckets_dir),
            "embedding": {
                "enabled": True,
                "api_key": "test-key",
                "api_format": "openai_compat",
                "base_url": GEMINI_OPENAI_BASE_URL,
                "model": "gemini-embedding-001",
            },
        }
    )

    assert engine.status()["vector_dim"] == 3072
