import pytest

from ombrebrain.cluster.consensus import SingleNodeConsensus
from ombrebrain.cluster.node import NodeIdentity, NodeRole
from ombrebrain.fabric.storage.engine import MemoryFabric
from ombrebrain.kernel.errors import NotLeader
from ombrebrain.protocol.schemas import ActorKind, MemoryEvent, MemoryType, Visibility


def make_event() -> MemoryEvent:
    return MemoryEvent.new(
        actor=ActorKind.SYSTEM,
        actor_name="cluster-test",
        memory_type=MemoryType.TRACE,
        content="single node commit",
        visibility=Visibility.INTERNAL,
    )


def test_single_node_consensus_commits_to_fabric(tmp_path):
    node = NodeIdentity(node_id="n1", address="127.0.0.1:8001", role=NodeRole.LEADER)
    fabric = MemoryFabric.open(tmp_path)
    consensus = SingleNodeConsensus(node=node, fabric=fabric)

    event = make_event()
    result = consensus.commit(event)

    assert result.committed is True
    assert result.index == 1
    assert result.term == 1
    assert result.leader_id == "n1"
    persisted = fabric.replay_events()
    assert len(persisted) == 1
    assert persisted[0].content == event.content
    assert persisted[0].cluster_term == result.term
    assert persisted[0].cluster_index == result.index
    assert persisted[0].id != event.id


def test_single_node_consensus_rejects_non_leader(tmp_path):
    node = NodeIdentity(node_id="n1", address="127.0.0.1:8001", role=NodeRole.FOLLOWER)
    consensus = SingleNodeConsensus(node=node, fabric=MemoryFabric.open(tmp_path))

    with pytest.raises(NotLeader):
        consensus.commit(make_event())
