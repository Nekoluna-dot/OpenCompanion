import os
from pathlib import Path


def test_load_config_applies_api_timeout_env_overrides(monkeypatch, tmp_path):
    from utils import load_config

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
buckets_dir: buckets
dehydration:
  timeout_seconds: 75
embedding:
  timeout_seconds: 45
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("OMBRE_COMPRESS_TIMEOUT_SECONDS", "180")
    monkeypatch.setenv("OMBRE_EMBED_TIMEOUT_SECONDS", "150")

    config = load_config(str(cfg_path))

    assert config["dehydration"]["timeout_seconds"] == 180
    assert config["embedding"]["timeout_seconds"] == 150


def test_dehydrator_uses_configured_timeout(tmp_path):
    from dehydrator import Dehydrator

    buckets_dir = tmp_path / "buckets"
    os.makedirs(buckets_dir, exist_ok=True)

    dehy = Dehydrator(
        {
            "buckets_dir": str(buckets_dir),
            "dehydration": {
                "api_key": "test-key",
                "api_format": "openai_compat",
                "base_url": "https://example.com/v1",
                "model": "test-model",
                "timeout_seconds": 180,
            },
        }
    )

    assert dehy.timeout_seconds == 180.0


def test_embedding_engine_uses_configured_timeout(tmp_path):
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
                "base_url": "https://example.com/v1",
                "model": "test-embedding",
                "timeout_seconds": 150,
            },
        }
    )

    assert engine._backend.timeout_seconds == 150.0


def test_dashboard_env_config_exposes_api_timeout_fields():
    root = Path(__file__).resolve().parents[1]
    for rel_path in ("frontend/dashboard.html",):
        html = (root / rel_path).read_text(encoding="utf-8")

        assert 'id="env-compress-timeout"' in html
        assert 'id="env-embed-timeout"' in html
        assert "OMBRE_COMPRESS_TIMEOUT_SECONDS" in html
        assert "OMBRE_EMBED_TIMEOUT_SECONDS" in html
