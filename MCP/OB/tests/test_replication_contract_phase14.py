def test_replication_topology_accepts_vnext_shape():
    from ombrebrain.cluster.replication import ReplicationContract, ReplicationTopology

    topology = ReplicationTopology(
        canonical_writers=("leader",),
        projection_readers=("reader-a", "reader-b"),
        encrypted_replicas=("reader-b",),
        segment_mode="snapshot_append_only",
    )

    decision = ReplicationContract.default().evaluate_topology(topology)

    assert decision.ok is True
    assert decision.violations == ()
    assert decision.contract_name == "replication"


def test_replication_topology_rejects_multiple_canonical_writers():
    from ombrebrain.cluster.replication import ReplicationContract, ReplicationTopology

    decision = ReplicationContract.default().evaluate_topology(
        ReplicationTopology(
            canonical_writers=("leader-a", "leader-b"),
            projection_readers=("reader",),
        )
    )

    assert decision.ok is False
    assert any(v["code"] == "multiple_canonical_writers" for v in decision.violations)


def test_replication_topology_rejects_unjustified_full_consensus():
    from ombrebrain.cluster.replication import ReplicationContract, ReplicationTopology

    decision = ReplicationContract.default().evaluate_topology(
        ReplicationTopology(
            canonical_writers=("leader",),
            projection_readers=("reader",),
            consensus_mode="full_distributed_consensus",
            necessity_reason="",
        )
    )

    assert decision.ok is False
    assert any(v["code"] == "unnecessary_full_consensus" for v in decision.violations)


def test_replication_segment_accepts_trace_and_tombstone_replication():
    from ombrebrain.cluster.replication import ReplicationContract, ReplicationSegment

    segment = ReplicationSegment(
        replica_id="replica-a",
        events=[
            {"event_type": "TraceCreated", "trace_id": "t1", "trace_kind": "dynamic"},
            {"event_type": "TraceDeletedToArchive", "trace_id": "t1", "payload": {"tombstone": True}},
        ],
    )

    decision = ReplicationContract.default().evaluate_segment(segment)

    assert decision.ok is True


def test_replication_segment_rejects_database_style_user_records():
    from ombrebrain.cluster.replication import ReplicationContract, ReplicationSegment

    segment = ReplicationSegment(
        replica_id="replica-a",
        events=[
            {
                "record_kind": "user_record",
                "user_id": "u1",
                "profile": {"loyalty_score": 0.9},
            }
        ],
    )

    decision = ReplicationContract.default().evaluate_segment(segment)

    assert decision.ok is False
    assert any(v["code"] == "replicates_user_record" for v in decision.violations)


def test_replica_content_removal_must_include_tombstone():
    from ombrebrain.cluster.replication import ReplicationContract, ReplicationSegment

    segment = ReplicationSegment(
        replica_id="replica-a",
        events=[
            {
                "event_type": "TraceContentRemoved",
                "trace_id": "erased-1",
                "payload": {"erased_content_removed": True},
            }
        ],
    )

    decision = ReplicationContract.default().evaluate_segment(segment)

    assert decision.ok is False
    assert any(v["code"] == "content_removal_without_tombstone" for v in decision.violations)


def test_replication_decision_is_json_safe():
    from ombrebrain.cluster.replication import ReplicationContract, ReplicationSegment

    data = ReplicationContract.default().evaluate_segment(
        ReplicationSegment(
            replica_id="replica-a",
            events=[{"event_type": "TraceContentRemoved", "trace_id": "t1"}],
        )
    ).to_dict()

    assert data["ok"] is False
    assert data["contract_name"] == "replication"
    assert data["violations"][0]["code"] == "content_removal_without_tombstone"


def test_replication_package_exports_contract_symbols():
    from ombrebrain.cluster.replication import (
        ReplicationContract,
        ReplicationDecision,
        ReplicationSegment,
        ReplicationTopology,
    )

    assert ReplicationContract.default() is not None
    assert ReplicationTopology(canonical_writers=("leader",)) is not None
    assert ReplicationSegment(replica_id="r1") is not None
    assert ReplicationDecision is not None
