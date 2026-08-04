from ombrebrain.fabric.storage.engine import MemoryFabric
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


def make_event(memory_type: MemoryType, content: str) -> MemoryEvent:
    return MemoryEvent.new(
        actor=ActorKind.CODEX,
        actor_name="Codex",
        memory_type=memory_type,
        content=content,
        visibility=Visibility.INTERNAL,
    )


def test_memory_fabric_persists_and_replays_events(tmp_path):
    fabric = MemoryFabric.open(tmp_path)
    fabric.append_event(make_event(MemoryType.DYNAMIC, "short thought"))
    fabric.append_event(make_event(MemoryType.PERMANENT, "durable thought"))

    reopened = MemoryFabric.open(tmp_path)
    events = reopened.replay_events()

    assert [event.content for event in events] == ["short thought", "durable thought"]


def test_memory_fabric_queries_by_type(tmp_path):
    fabric = MemoryFabric.open(tmp_path)
    fabric.append_event(make_event(MemoryType.DYNAMIC, "dynamic"))
    fabric.append_event(make_event(MemoryType.PERMANENT, "permanent"))

    permanent = fabric.events_by_type(MemoryType.PERMANENT)

    assert len(permanent) == 1
    assert permanent[0].content == "permanent"
