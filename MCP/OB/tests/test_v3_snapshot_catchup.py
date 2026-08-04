import json

import pytest

from ombrebrain.cluster.raft.log import RaftLogEntry
from ombrebrain.cluster.replication.catchup import catch_up_follower
from ombrebrain.cluster.safety.integrity import verify_snapshot
from ombrebrain.fabric.log.snapshot import MemorySnapshot
from ombrebrain.fabric.storage.engine import MemoryFabric
from ombrebrain.kernel.errors import LogIntegrityError, SnapshotRestoreError
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


def _event(content: str, *, index: int, term: int = 1) -> MemoryEvent:
    event = MemoryEvent.new(
        actor=ActorKind.SYSTEM,
        actor_name="snapshot-test",
        memory_type=MemoryType.TRACE,
        content=content,
        visibility=Visibility.INTERNAL,
    )
    return event.with_cluster_position(term=term, index=index)


def test_snapshot_save_load_roundtrip_and_integrity(tmp_path) -> None:
    snapshot = MemorySnapshot.from_events([_event("one", index=1), _event("two", index=2)])
    path = tmp_path / "snapshot.json"

    snapshot.save(path)
    loaded = MemorySnapshot.load(path)

    assert loaded.last_index == 2
    assert loaded.last_term == 1
    assert [event.content for event in loaded.events] == ["one", "two"]
    assert verify_snapshot(loaded)


def test_snapshot_rejects_checksum_tampering(tmp_path) -> None:
    snapshot = MemorySnapshot.from_events([_event("one", index=1)])
    path = tmp_path / "snapshot.json"
    snapshot.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["events"][0]["content"] = "tampered"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(LogIntegrityError):
        MemorySnapshot.load(path)


def test_snapshot_integrity_rejects_sparse_duplicate_and_non_positive_indexes() -> None:
    sparse = MemorySnapshot.from_events([_event("two", index=2)])
    duplicate = MemorySnapshot.from_events([_event("one-a", index=1), _event("one-b", index=1)])
    non_positive = MemorySnapshot.from_events([_event("zero", index=0)])

    with pytest.raises(LogIntegrityError, match="contiguous"):
        verify_snapshot(sparse)
    with pytest.raises(LogIntegrityError, match="contiguous"):
        verify_snapshot(duplicate)
    with pytest.raises(LogIntegrityError, match="contiguous"):
        verify_snapshot(non_positive)


def test_snapshot_integrity_rejects_last_term_mismatch() -> None:
    event = _event("one", index=1, term=2)
    snapshot = MemorySnapshot(
        last_index=1,
        last_term=1,
        events=(event,),
        checksum=MemorySnapshot.from_events([event]).checksum,
    )

    with pytest.raises(LogIntegrityError, match="last_term"):
        verify_snapshot(snapshot)


def test_catchup_appends_missing_log_entries(tmp_path) -> None:
    fabric = MemoryFabric.open(tmp_path / "follower")
    entries = [
        RaftLogEntry.new(term=1, index=1, event=_event("one", index=1)),
        RaftLogEntry.new(term=1, index=2, event=_event("two", index=2)),
    ]

    result = catch_up_follower(fabric, current_index=0, entries=entries)

    assert result.installed_snapshot is False
    assert result.appended_entries == 2
    assert [event.content for event in fabric.replay_events()] == ["one", "two"]


def test_catchup_installs_snapshot_when_follower_is_behind_boundary(tmp_path) -> None:
    fabric = MemoryFabric.open(tmp_path / "follower")
    snapshot = MemorySnapshot.from_events([_event("one", index=1), _event("two", index=2)])
    entries = [RaftLogEntry.new(term=1, index=3, event=_event("three", index=3))]

    result = catch_up_follower(fabric, current_index=0, entries=entries, snapshot=snapshot)

    assert result.installed_snapshot is True
    assert result.appended_entries == 3
    assert [event.content for event in fabric.replay_events()] == ["one", "two", "three"]


def test_catchup_rejects_missing_snapshot_for_log_gap(tmp_path) -> None:
    fabric = MemoryFabric.open(tmp_path / "follower")
    entries = [RaftLogEntry.new(term=1, index=3, event=_event("three", index=3))]

    with pytest.raises(SnapshotRestoreError):
        catch_up_follower(fabric, current_index=0, entries=entries)
