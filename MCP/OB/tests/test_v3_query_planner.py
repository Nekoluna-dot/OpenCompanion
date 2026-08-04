from __future__ import annotations

from ombrebrain.app.legacy_runtime import LegacyRuntime
from ombrebrain.retrieval import QueryPlanner, RetrievalEngine


def test_query_planner_builds_multichannel_retrieval_plan() -> None:
    plan = QueryPlanner.default().plan({"query": "weather mood permanent", "max_results": 5}, operation="breath")

    assert plan.intent.query == "weather mood permanent"
    assert plan.intent.operation == "breath"
    assert plan.channels == ("dynamic", "permanent", "feel", "letter")
    assert tuple(stage.name for stage in plan.stages) == (
        "lexical_prefilter",
        "semantic_vector_probe",
        "recency_importance_merge",
        "policy_visibility_filter",
        "explainable_rerank",
    )
    assert plan.limit == 5


def test_query_planner_respects_explicit_memory_type_channel() -> None:
    plan = QueryPlanner.default().plan({"query": "today", "type": "feel"}, operation="breath")

    assert plan.channels == ("feel",)
    assert plan.intent.tags == ("type:feel",)


def test_retrieval_engine_emits_stable_trace_without_mutating_candidates() -> None:
    candidates = ({"id": "b1", "importance": 9}, {"id": "b2", "importance": 3})
    plan = QueryPlanner.default().plan({"query": "memory"}, operation="search")

    trace = RetrievalEngine.default().trace(plan, candidates)

    assert trace["query"] == "memory"
    assert trace["operation"] == "search"
    assert trace["candidate_count"] == 2
    assert trace["stage_count"] == 5
    assert trace["selected_channels"] == ["dynamic", "permanent", "feel", "letter"]
    assert candidates[0]["id"] == "b1"


def test_legacy_runtime_breath_trace_includes_retrieval_metadata(tmp_path) -> None:
    runtime = LegacyRuntime.from_config({"buckets_dir": str(tmp_path / "buckets")})

    runtime.record_tool_event("breath", {"query": "permanent", "max_results": 3})

    metadata = runtime.fabric.replay_events()[0].metadata
    assert metadata["retrieval_plan"]["query"] == "permanent"
    assert metadata["retrieval_plan"]["operation"] == "breath"
    assert metadata["retrieval_plan"]["limit"] == 3
    assert metadata["retrieval_trace"]["stage_count"] == 5
