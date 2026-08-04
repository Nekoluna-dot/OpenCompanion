import pytest


@pytest.mark.parametrize(
    "metric_name",
    [
        "trace_count_by_state",
        "unresolved_trace_count",
        "average_accessibility",
        "decay_distribution",
        "tombstone_count",
        "projection_lag",
        "ledger_replay_time",
        "surfacing_rejection_reasons",
        "archive_growth",
        "compression_lineage_depth",
    ],
)
def test_observability_boundary_allows_memory_health_metrics(metric_name):
    from ombrebrain.observability import ObservabilityMetricBoundary, ObservabilityMetricSpec

    decision = ObservabilityMetricBoundary.default().evaluate_metric(
        ObservabilityMetricSpec(name=metric_name, value=1)
    )

    assert decision.allowed is True
    assert decision.reason == "allowed"
    assert decision.metric_family == "memory_health"


@pytest.mark.parametrize(
    "metric_name",
    [
        "user_loyalty_score",
        "user_emotional_dependency_score",
        "persuasion_score",
        "manipulation_success_score",
        "personality_compliance_score",
    ],
)
def test_observability_boundary_rejects_user_value_metrics(metric_name):
    from ombrebrain.observability import ObservabilityMetricBoundary, ObservabilityMetricSpec

    decision = ObservabilityMetricBoundary.default().evaluate_metric(
        ObservabilityMetricSpec(name=metric_name, value=0.7)
    )

    assert decision.allowed is False
    assert decision.reason == "forbidden user-value metric"
    assert decision.forbidden_metric == metric_name


def test_observability_boundary_rejects_unknown_metric_by_default():
    from ombrebrain.observability import ObservabilityMetricBoundary, ObservabilityMetricSpec

    decision = ObservabilityMetricBoundary.default().evaluate_metric(
        ObservabilityMetricSpec(name="conversation_quality_score", value=0.8)
    )

    assert decision.allowed is False
    assert decision.reason == "unknown metric"


def test_allowed_metric_cannot_carry_forbidden_user_value_labels():
    from ombrebrain.observability import ObservabilityMetricBoundary, ObservabilityMetricSpec

    decision = ObservabilityMetricBoundary.default().evaluate_metric(
        ObservabilityMetricSpec(
            name="trace_count_by_state",
            value=3,
            labels={"user_loyalty_score": "high"},
        )
    )

    assert decision.allowed is False
    assert decision.reason == "forbidden metric label"
    assert decision.forbidden_metric == "user_loyalty_score"


def test_observability_manifest_report_is_json_safe():
    from ombrebrain.observability import ObservabilityMetricBoundary

    report = ObservabilityMetricBoundary.default().evaluate_manifest(
        [
            {"name": "trace count by state", "value": {"active": 2}},
            {"name": "persuasion score", "value": 0.9},
            {"name": "unknown_new_metric", "value": 1},
        ]
    )
    data = report.to_dict()

    assert report.ok is False
    assert data["metric_count"] == 3
    assert data["allowed_count"] == 1
    assert data["rejected_count"] == 2
    assert data["decisions"][0]["metric_name"] == "trace_count_by_state"
    assert data["decisions"][1]["forbidden_metric"] == "persuasion_score"


def test_observability_package_exports_boundary_symbols():
    from ombrebrain.observability import (
        ObservabilityDecision,
        ObservabilityMetricBoundary,
        ObservabilityMetricSpec,
        ObservabilityReport,
    )

    assert ObservabilityMetricBoundary.default() is not None
    assert ObservabilityMetricSpec(name="trace_count_by_state") is not None
    assert ObservabilityDecision is not None
    assert ObservabilityReport is not None
