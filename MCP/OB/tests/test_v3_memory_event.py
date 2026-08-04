import json

import pytest

from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


def test_actor_kind_matches_v3_foundation_set():
    assert {actor.value for actor in ActorKind} == {
        "user",
        "codex",
        "claude",
        "gpt",
        "gemini",
        "mcp_tool",
        "web_dashboard",
        "system",
    }


def test_memory_type_matches_v3_foundation_set():
    assert {memory_type.value for memory_type in MemoryType} == {
        "dynamic",
        "permanent",
        "trace",
        "letter",
        "plan",
        "feel",
    }


def test_visibility_matches_v3_foundation_set():
    assert {visibility.value for visibility in Visibility} == {
        "private",
        "internal",
        "shared",
    }


def test_memory_event_has_deterministic_id_for_same_payload():
    first = MemoryEvent.new(
        actor=ActorKind.USER,
        actor_name="rin",
        memory_type=MemoryType.PERMANENT,
        content="OB remembers permanent memories.",
        visibility=Visibility.PRIVATE,
        session_id="s1",
        task_id="t1",
    )
    second = MemoryEvent.new(
        actor=ActorKind.USER,
        actor_name="rin",
        memory_type=MemoryType.PERMANENT,
        content="OB remembers permanent memories.",
        visibility=Visibility.PRIVATE,
        session_id="s1",
        task_id="t1",
    )

    assert first.id == second.id
    assert first.vector_state == "pending"


def test_memory_event_serializes_without_enum_objects():
    event = MemoryEvent.new(
        actor=ActorKind.CODEX,
        actor_name="Codex",
        memory_type=MemoryType.TRACE,
        content="Trace source is preserved.",
        visibility=Visibility.INTERNAL,
        source_chain=["mcp", "trace"],
        parent_event_ids=("mem_parent",),
        cluster_term=2,
        cluster_index=7,
        created_at="2026-06-29T00:00:00+00:00",
    )

    payload = event.to_dict()

    assert payload["actor"] == "codex"
    assert payload["memory_type"] == "trace"
    assert payload["visibility"] == "internal"
    assert payload["source_chain"] == ["mcp", "trace"]
    assert payload["parent_event_ids"] == ["mem_parent"]
    assert payload["cluster_term"] == 2
    assert payload["cluster_index"] == 7
    assert payload["created_at"] == "2026-06-29T00:00:00+00:00"


def test_memory_event_round_trips_metadata_and_uses_it_in_id():
    first = MemoryEvent.new(
        actor=ActorKind.SYSTEM,
        actor_name="migration",
        memory_type=MemoryType.PERMANENT,
        content="Legacy bucket content.",
        visibility=Visibility.PRIVATE,
        metadata={"legacy_bucket_id": "abc123", "legacy_name": "Test Memory"},
    )
    second = MemoryEvent.new(
        actor=ActorKind.SYSTEM,
        actor_name="migration",
        memory_type=MemoryType.PERMANENT,
        content="Legacy bucket content.",
        visibility=Visibility.PRIVATE,
        metadata={"legacy_bucket_id": "def456", "legacy_name": "Test Memory"},
    )

    assert first.id != second.id
    assert first.to_dict()["metadata"] == {
        "legacy_bucket_id": "abc123",
        "legacy_name": "Test Memory",
    }
    assert MemoryEvent.from_dict(first.to_dict()).metadata == first.metadata


def test_memory_event_from_dict_restores_event_and_clamps_scores():
    payload = {
        "actor": "user",
        "actor_name": "rin",
        "memory_type": "permanent",
        "content": "Clamp scores for WAL replay.",
        "visibility": "private",
        "confidence": 2.0,
        "importance": 42,
        "source_chain": ("wal", "replay"),
    }

    event = MemoryEvent.from_dict(payload)

    assert event.id.startswith("mem_")
    assert event.actor is ActorKind.USER
    assert event.memory_type is MemoryType.PERMANENT
    assert event.visibility is Visibility.PRIVATE
    assert event.confidence == 1.0
    assert event.importance == 10
    assert event.to_dict()["source_chain"] == ["wal", "replay"]


def test_memory_event_defaults_created_at_for_deterministic_ids():
    event = MemoryEvent.new(
        actor=ActorKind.USER,
        actor_name="rin",
        memory_type=MemoryType.PERMANENT,
        content="Default timestamps stay deterministic.",
        visibility=Visibility.PRIVATE,
    )

    assert event.created_at == "1970-01-01T00:00:00+00:00"
    assert event.to_dict()["created_at"] == "1970-01-01T00:00:00+00:00"


def test_memory_event_id_includes_cluster_and_parent_fields():
    base = MemoryEvent.new(
        actor=ActorKind.USER,
        actor_name="rin",
        memory_type=MemoryType.PERMANENT,
        content="Cluster coordinates affect identity.",
        visibility=Visibility.PRIVATE,
    )
    with_parent = MemoryEvent.new(
        actor=ActorKind.USER,
        actor_name="rin",
        memory_type=MemoryType.PERMANENT,
        content="Cluster coordinates affect identity.",
        visibility=Visibility.PRIVATE,
        parent_event_ids=(base.id,),
    )
    with_position = MemoryEvent.new(
        actor=ActorKind.USER,
        actor_name="rin",
        memory_type=MemoryType.PERMANENT,
        content="Cluster coordinates affect identity.",
        visibility=Visibility.PRIVATE,
        cluster_term=1,
        cluster_index=1,
    )

    assert base.id != with_parent.id
    assert base.id != with_position.id


def test_memory_event_from_dict_rejects_mismatched_id():
    event = MemoryEvent.new(
        actor=ActorKind.USER,
        actor_name="rin",
        memory_type=MemoryType.PERMANENT,
        content="Original content.",
        visibility=Visibility.PRIVATE,
    )
    payload = event.to_dict()
    payload["content"] = "Tampered content."

    with pytest.raises(ValueError):
        MemoryEvent.from_dict(payload)


def test_memory_event_with_cluster_position_rederives_id():
    event = MemoryEvent.new(
        actor=ActorKind.SYSTEM,
        actor_name="cluster",
        memory_type=MemoryType.TRACE,
        content="Commit me.",
        visibility=Visibility.INTERNAL,
    )

    positioned = event.with_cluster_position(term=3, index=4)

    assert positioned.cluster_term == 3
    assert positioned.cluster_index == 4
    assert positioned.id != event.id
    assert positioned.to_dict()["cluster_term"] == 3
    assert MemoryEvent.from_dict(positioned.to_dict()) == positioned


def test_memory_event_rejects_nan_confidence():
    with pytest.raises(ValueError):
        MemoryEvent.new(
            actor=ActorKind.USER,
            actor_name="rin",
            memory_type=MemoryType.PERMANENT,
            content="NaN confidence should not enter WAL.",
            visibility=Visibility.PRIVATE,
            confidence=float("nan"),
        )


def test_memory_event_rejects_infinite_confidence():
    with pytest.raises(ValueError):
        MemoryEvent.new(
            actor=ActorKind.USER,
            actor_name="rin",
            memory_type=MemoryType.PERMANENT,
            content="Infinite confidence should not enter WAL.",
            visibility=Visibility.PRIVATE,
            confidence=float("inf"),
        )


def test_memory_event_rejects_nan_metadata_before_id_derivation():
    with pytest.raises(ValueError):
        MemoryEvent.new(
            actor=ActorKind.USER,
            actor_name="rin",
            memory_type=MemoryType.PERMANENT,
            content="NaN metadata should not enter deterministic IDs.",
            visibility=Visibility.PRIVATE,
            metadata={"score": float("nan")},
        )


def test_memory_event_to_dict_is_strict_json_writable():
    event = MemoryEvent.new(
        actor=ActorKind.CODEX,
        actor_name="Codex",
        memory_type=MemoryType.TRACE,
        content="Strict JSON writes for WAL.",
        visibility=Visibility.INTERNAL,
        confidence=0.5,
    )

    json.dumps(event.to_dict(), allow_nan=False)


def test_memory_event_from_dict_round_trips_payload():
    event = MemoryEvent.new(
        actor=ActorKind.USER,
        actor_name="rin",
        memory_type=MemoryType.PERMANENT,
        content="Round trip payloads for WAL replay.",
        visibility=Visibility.PRIVATE,
        session_id="s1",
        task_id="t1",
        source_chain=["wal", "replay"],
        confidence=0.75,
        importance=8,
    )
    payload = event.to_dict()

    restored = MemoryEvent.from_dict(payload)

    assert restored.to_dict() == payload


def test_memory_event_round_trips_foundation_specialized_types():
    for memory_type in (MemoryType.LETTER, MemoryType.PLAN, MemoryType.FEEL):
        event = MemoryEvent.new(
            actor=ActorKind.CODEX,
            actor_name="Codex",
            memory_type=memory_type,
            content=f"{memory_type.value} memory",
            visibility=Visibility.INTERNAL,
        )

        restored = MemoryEvent.from_dict(event.to_dict())

        assert restored.memory_type is memory_type
        assert restored.to_dict() == event.to_dict()
