import json
from pathlib import Path


def test_bucket_read_normalizes_yaml_datetimes_for_json(test_config, fake_embedding_engine):
    from bucket_manager import BucketManager

    dynamic_dir = Path(test_config["buckets_dir"]) / "dynamic" / "测试"
    dynamic_dir.mkdir(parents=True, exist_ok=True)
    bucket_file = dynamic_dir / "datetime_bucket_dt-bucket.md"
    bucket_file.write_text(
        """---
id: dt-bucket
name: datetime bucket
created: 2026-07-01T12:34:56
last_active: 2026-07-01T13:00:00
type: dynamic
domain:
  - 测试
valence: 0.5
arousal: 0.3
importance: 5
---
content
""",
        encoding="utf-8",
    )

    manager = BucketManager(test_config, embedding_engine=fake_embedding_engine)
    bucket = manager._load_bucket(str(bucket_file))

    assert bucket is not None
    assert bucket["metadata"]["created"] == "2026-07-01T12:34:56"
    assert bucket["metadata"]["last_active"] == "2026-07-01T13:00:00"
    json.dumps(bucket)
