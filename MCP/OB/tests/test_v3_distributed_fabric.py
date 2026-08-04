from __future__ import annotations

import pytest

from ombrebrain.distributed import ClusterMembership, DistributedMemoryFabricCluster
from ombrebrain.kernel.errors import QuorumTimeout
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


def _event(content: str = "hello") -> MemoryEvent:
    return MemoryEvent.new(
        actor=ActorKind.SYSTEM,
        actor_name="distributed-test",
        memory_type=MemoryType.TRACE,
        content=content,
        visibility=Visibility.INTERNAL,
        source_chain=("test",),
    )


def test_cluster_membership_tracks_majority_and_reachable_nodes() -> None:
    membership = ClusterMembership(("n1", "n2", "n3")).with_reachable(("n1", "n3"))

    assert membership.majority == 2
    assert membership.has_majority() is True
    assert membership.reachable == ("n1", "n3")


def test_distributed_fabric_commits_to_quorum_and_allows_follower_reads(tmp_path) -> None:
    cluster = DistributedMemoryFabricCluster(("n1", "n2", "n3"), tmp_path)
    assert cluster.elect_leader("n1") is True

    result = cluster.commit(_event("first"))

    assert result.committed is True
    assert result.index == 1
    assert result.acks == ("n1", "n2", "n3")
    assert cluster.read_events("n2")[0].content == "first"
    assert cluster.leader_lease().leader_id == "n1"
    assert cluster.leader_lease().valid is True


def test_distributed_fabric_rejects_minority_commit(tmp_path) -> None:
    cluster = DistributedMemoryFabricCluster(("n1", "n2", "n3"), tmp_path)
    cluster.transport.set_reachable(("n1",))
    assert cluster.elect_leader("n1") is False

    cluster.transport.set_reachable(("n1", "n2"))
    assert cluster.elect_leader("n1") is True
    cluster.transport.set_reachable(("n1",))

    with pytest.raises(QuorumTimeout):
        cluster.commit(_event("minority"))


def test_distributed_fabric_catches_up_lagging_follower(tmp_path) -> None:
    cluster = DistributedMemoryFabricCluster(("n1", "n2", "n3"), tmp_path)
    assert cluster.elect_leader("n1") is True
    cluster.transport.set_reachable(("n1", "n2"))

    cluster.commit(_event("while-n3-away"))
    assert cluster.read_events("n3") == []

    cluster.transport.set_reachable(("n1", "n2", "n3"))
    result = cluster.catch_up("n3")

    assert result.appended_entries == 1
    assert cluster.read_events("n3")[0].content == "while-n3-away"
