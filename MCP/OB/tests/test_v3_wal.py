import json

import pytest

from ombrebrain.fabric.log.wal import WalStore
from ombrebrain.kernel.errors import LogIntegrityError
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


def make_event(content: str) -> MemoryEvent:
    return MemoryEvent.new(
        actor=ActorKind.USER,
        actor_name="tester",
        memory_type=MemoryType.DYNAMIC,
        content=content,
        visibility=Visibility.PRIVATE,
    )


def test_wal_appends_and_replays_events(tmp_path):
    wal = WalStore(tmp_path / "memory.wal")
    first = wal.append(make_event("first").to_dict())
    second = wal.append(make_event("second").to_dict())

    replayed = list(wal.replay())

    assert first.index == 1
    assert second.index == 2
    assert [entry.payload["content"] for entry in replayed] == ["first", "second"]


def test_wal_detects_payload_corruption(tmp_path):
    wal_path = tmp_path / "memory.wal"
    wal = WalStore(wal_path)
    wal.append(make_event("clean").to_dict())

    line = wal_path.read_text(encoding="utf-8").splitlines()[0]
    record = json.loads(line)
    record["payload"]["content"] = "tampered"
    wal_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(LogIntegrityError):
        list(WalStore(wal_path).replay())


def test_wal_detects_broken_previous_checksum(tmp_path):
    wal_path = tmp_path / "memory.wal"
    wal = WalStore(wal_path)
    wal.append(make_event("first").to_dict())
    wal.append(make_event("second").to_dict())

    lines = wal_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["previous_checksum"] = "wrong"
    lines[1] = json.dumps(record, ensure_ascii=False)
    wal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LogIntegrityError):
        list(WalStore(wal_path).replay())


def test_wal_detects_unexpected_index(tmp_path):
    wal_path = tmp_path / "memory.wal"
    wal = WalStore(wal_path)
    wal.append(make_event("first").to_dict())

    line = wal_path.read_text(encoding="utf-8").splitlines()[0]
    record = json.loads(line)
    record["index"] = 2
    wal_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(LogIntegrityError):
        list(WalStore(wal_path).replay())


def test_wal_checksum_binds_index_and_previous_checksum(tmp_path):
    wal_path = tmp_path / "memory.wal"
    wal = WalStore(wal_path)
    wal.append(make_event("first").to_dict())
    wal.append(make_event("second").to_dict())

    second_record = json.loads(wal_path.read_text(encoding="utf-8").splitlines()[1])
    second_record["index"] = 1
    second_record["previous_checksum"] = ""
    wal_path.write_text(json.dumps(second_record, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(LogIntegrityError):
        list(WalStore(wal_path).replay())


def test_wal_detects_invalid_json_record(tmp_path):
    wal_path = tmp_path / "memory.wal"
    wal_path.write_text("{invalid json}\n", encoding="utf-8")

    with pytest.raises(LogIntegrityError):
        list(WalStore(wal_path).replay())
