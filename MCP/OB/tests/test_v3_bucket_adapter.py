from pathlib import Path

from ombrebrain.adapters.bucket_adapter import bucket_markdown_to_event
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


def test_bucket_markdown_to_event_maps_type_and_content(tmp_path):
    bucket = tmp_path / "memory.md"
    bucket.write_text(
        """---
id: abc123
name: Test Memory
type: permanent
importance: 9
tags:
- ob
---

OB should keep old bucket data readable.
""",
        encoding="utf-8",
    )

    event = bucket_markdown_to_event(Path(bucket))

    assert event.memory_type == MemoryType.PERMANENT
    assert event.content == "OB should keep old bucket data readable."
    assert event.importance == 9
    assert event.metadata["legacy_bucket_id"] == "abc123"
    assert event.metadata["legacy_name"] == "Test Memory"
    assert event.to_dict()["metadata"]["legacy_bucket_id"] == "abc123"
    assert MemoryEvent.from_dict(event.to_dict()).metadata["legacy_bucket_id"] == "abc123"


def test_bucket_markdown_to_event_uses_migration_defaults(tmp_path):
    bucket = tmp_path / "untagged.md"
    bucket.write_text(
        """---
id: dyn1
name: Untagged
type: unknown
---

legacy body
""",
        encoding="utf-8",
    )

    event = bucket_markdown_to_event(bucket)

    assert event.actor is ActorKind.SYSTEM
    assert event.actor_name == "v2.3.22-migration"
    assert event.memory_type is MemoryType.DYNAMIC
    assert event.visibility is Visibility.PRIVATE
    assert event.importance == 5
    assert event.source_chain == ("legacy_bucket",)
    assert event.metadata["legacy_tags"] == []
    assert event.metadata["legacy_path"] == str(bucket)


def test_bucket_markdown_to_event_maps_foundation_bucket_types(tmp_path):
    for type_name, expected in {
        "letter": MemoryType.LETTER,
        "plan": MemoryType.PLAN,
        "feel": MemoryType.FEEL,
    }.items():
        bucket = tmp_path / f"{type_name}.md"
        bucket.write_text(
            f"""---
type: {type_name}
tags:
- one
---

{type_name} body
""",
            encoding="utf-8",
        )

        event = bucket_markdown_to_event(bucket)

        assert event.memory_type is expected
        assert event.metadata["legacy_tags"] == ["one"]


def test_bucket_markdown_to_event_preserves_full_legacy_metadata(tmp_path):
    bucket = tmp_path / "custom.md"
    bucket.write_text(
        """---
id: custom1
name: Custom Memory
custom: value
nested:
  x: 1
tags:
- one
---

custom body
""",
        encoding="utf-8",
    )

    event = bucket_markdown_to_event(bucket)

    assert event.metadata["legacy_bucket_id"] == "custom1"
    assert event.metadata["legacy_name"] == "Custom Memory"
    assert event.metadata["legacy_tags"] == ["one"]
    assert event.metadata["legacy_metadata"]["custom"] == "value"
    assert event.metadata["legacy_metadata"]["nested"] == {"x": 1}
