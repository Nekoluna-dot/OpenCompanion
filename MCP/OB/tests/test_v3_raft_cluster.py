import pytest

from ombrebrain.cluster.raft.leader import InMemoryRaftCluster
from ombrebrain.cluster.raft.quorum import Quorum
from ombrebrain.kernel.errors import NotLeader, QuorumTimeout
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


def _event(content: str = "cluster event") -> MemoryEvent:
    return MemoryEvent.new(
        actor=ActorKind.SYSTEM,
        actor_name="cluster-test",
        memory_type=MemoryType.TRACE,
        content=content,
        visibility=Visibility.INTERNAL,
    )


def test_quorum_majority_helper() -> None:
    quorum = Quorum(3)

    assert quorum.majority == 2
    assert quorum.has_majority(2)
    assert not quorum.has_majority(1)


def test_cluster_elects_leader_only_with_majority(tmp_path) -> None:
    cluster = InMemoryRaftCluster(("n1", "n2", "n3"), tmp_path)

    assert cluster.elect_leader("n1", voters={"n1", "n2"})
    assert cluster.leader_id == "n1"

    cluster.set_reachable({"n1"})

    assert not cluster.elect_leader("n1", voters={"n1"})
    assert cluster.leader_id == "n1"


def test_leader_commit_replicates_to_reachable_majority_and_applies_to_leader(tmp_path) -> None:
    cluster = InMemoryRaftCluster(("n1", "n2", "n3"), tmp_path)
    cluster.elect_leader("n1")
    cluster.set_reachable({"n1", "n2"})

    entry = cluster.commit(_event("majority write"))

    assert entry.term == 1
    assert entry.index == 1
    assert [item.event.content for item in cluster.log_for("n1")] == ["majority write"]
    assert [item.event.content for item in cluster.log_for("n2")] == ["majority write"]
    assert cluster.log_for("n3") == ()
    assert [event.content for event in cluster.fabric_for("n1").replay_events()] == ["majority write"]


def test_minority_partition_rejects_commits(tmp_path) -> None:
    cluster = InMemoryRaftCluster(("n1", "n2", "n3"), tmp_path)
    cluster.elect_leader("n1")
    cluster.set_reachable({"n1"})

    with pytest.raises(QuorumTimeout):
        cluster.commit(_event("minority write"))

    assert cluster.log_for("n1") == ()


def test_commit_requires_a_leader(tmp_path) -> None:
    cluster = InMemoryRaftCluster(("n1", "n2", "n3"), tmp_path)

    with pytest.raises(NotLeader):
        cluster.commit(_event())
