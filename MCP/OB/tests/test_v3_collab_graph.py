import pytest

from ombrebrain.collab.graph import CollaborationGraph
from ombrebrain.collab.merge_policy import MergeDecision, MergePolicy
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


def _event(
    content: str,
    *,
    actor_name: str = "codex",
    parents: tuple[str, ...] = (),
    source_chain: tuple[str, ...] = (),
) -> MemoryEvent:
    return MemoryEvent.new(
        actor=ActorKind.CODEX,
        actor_name=actor_name,
        memory_type=MemoryType.DYNAMIC,
        content=content,
        visibility=Visibility.PRIVATE,
        parent_event_ids=parents,
        source_chain=source_chain,
    )


def test_collaboration_graph_indexes_parent_child_relationships() -> None:
    root = _event("root")
    child = _event("child", parents=(root.id,))
    sibling = _event("sibling", parents=(root.id,))

    graph = CollaborationGraph([root, child, sibling])

    assert graph.get(root.id) == root
    assert graph.parents(child.id) == (root,)
    assert graph.children(root.id) == (child, sibling)


def test_collaboration_graph_filters_events_for_actor() -> None:
    codex_event = _event("codex event", actor_name="codex")
    claude_event = _event("claude event", actor_name="claude")
    graph = CollaborationGraph([codex_event, claude_event])

    assert graph.events_for_actor("claude") == (claude_event,)


def test_collaboration_graph_expands_source_chain_with_parent_provenance() -> None:
    root = _event("root", source_chain=("legacy_bucket",))
    child = _event("child", parents=(root.id,), source_chain=("mcp.aggregate",))
    grandchild = _event("grandchild", parents=(child.id,), source_chain=("tool.search", "codex"))

    graph = CollaborationGraph([root, child, grandchild])

    assert graph.source_chain(grandchild.id) == (
        "legacy_bucket",
        "mcp.aggregate",
        "tool.search",
        "codex",
    )


def test_collaboration_graph_rejects_duplicate_event_ids() -> None:
    event = _event("same")

    with pytest.raises(ValueError, match="Duplicate memory event"):
        CollaborationGraph([event, event])


def test_merge_policy_marks_same_scope_different_content_as_conflict() -> None:
    existing = _event("old value", source_chain=("bucket:a",))
    incoming = _event("new value", source_chain=("bucket:a",))

    decision = MergePolicy().decide(existing, incoming)

    assert decision == MergeDecision.MARK_CONFLICT


def test_merge_policy_prefers_newer_cluster_position_and_keeps_independent_events() -> None:
    policy = MergePolicy()
    old = _event("old").with_cluster_position(term=1, index=2)
    new = _event("new").with_cluster_position(term=1, index=3)
    independent = _event("unrelated", source_chain=("other",))

    assert policy.decide(old, new) == MergeDecision.PREFER_NEW
    assert policy.decide(old, old) == MergeDecision.PREFER_EXISTING
    assert policy.decide(old, independent) == MergeDecision.KEEP_BOTH
