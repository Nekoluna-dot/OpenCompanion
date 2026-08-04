import pytest

from ombrebrain.domain.commands import CommandKind, MemoryCommand, MemoryCommandRouter
from ombrebrain.domain.commands import ProjectionKind
from ombrebrain.projection.observation import ObservationStatus, ProjectionObservation, ProjectionObservationSet
from ombrebrain.projection.observers import ProjectionObserverRegistry
from ombrebrain.projection.runtime import ProjectionRuntime


def test_projection_observation_is_json_safe_and_keyed() -> None:
    obs = ProjectionObservation(
        projection_kind=ProjectionKind.BUCKET_MARKDOWN,
        surface="buckets",
        action="patch",
        status=ObservationStatus.OBSERVED,
        subject="bucket-1",
        metadata={"exists": True},
    )

    assert obs.key == ("bucket_markdown", "buckets", "patch")
    assert obs.to_dict()["status"] == "observed"
    assert obs.to_dict()["metadata"] == {"exists": True}


def test_projection_observation_set_serializes_entries() -> None:
    obs = ProjectionObservation(
        projection_kind=ProjectionKind.DASHBOARD_STATE,
        surface="dashboard",
        action="refresh",
        status=ObservationStatus.UNKNOWN,
    )
    obs_set = ProjectionObservationSet(command_id="cmd_1", observations=(obs,))

    assert obs_set.to_dict()["command_id"] == "cmd_1"
    assert obs_set.to_dict()["observations"][0]["projection_kind"] == "dashboard_state"


def test_projection_package_exports_observer_runtime_symbols() -> None:
    from ombrebrain.projection import ProjectionAuditRuntime, ProjectionObservation, ProjectionObserverRegistry

    assert ProjectionObservation is not None
    assert ProjectionObserverRegistry is not None
    assert ProjectionAuditRuntime is not None


class FakeBucketManager:
    def __init__(self, bucket):
        self.bucket = bucket
        self.calls = []

    async def get(self, bucket_id):
        self.calls.append(("get", bucket_id))
        return self.bucket

    async def update(self, *_args, **_kwargs):  # pragma: no cover - must not be called
        raise AssertionError("observer must not write buckets")


class FakeEmbeddingEngine:
    enabled = True

    def __init__(self, embedding=None, ids=()):
        self.embedding = embedding
        self.ids = tuple(ids)
        self.calls = []

    async def get_embedding(self, bucket_id):
        self.calls.append(("get_embedding", bucket_id))
        return self.embedding

    def list_all_ids(self):
        self.calls.append(("list_all_ids",))
        return set(self.ids)

    async def generate_and_store(self, *_args, **_kwargs):  # pragma: no cover - must not be called
        raise AssertionError("observer must not generate embeddings")


def _trace_plan_and_journal(payload=None):
    command = MemoryCommand.new(kind=CommandKind.TRACE, payload=payload or {"bucket_id": "bucket-1"})
    plan = MemoryCommandRouter.default().plan(command)
    return plan, ProjectionRuntime.default().project(plan, metadata={"payload": payload or {"bucket_id": "bucket-1"}})


@pytest.mark.asyncio
async def test_observer_registry_reads_bucket_without_writing() -> None:
    plan, journal = _trace_plan_and_journal()
    bucket_mgr = FakeBucketManager({"id": "bucket-1", "metadata": {"type": "dynamic"}})

    obs_set = await ProjectionObserverRegistry.default(bucket_manager=bucket_mgr).observe(plan, journal)

    bucket_observations = [obs for obs in obs_set.observations if obs.projection_kind == ProjectionKind.BUCKET_MARKDOWN]
    assert bucket_observations[0].status == ObservationStatus.OBSERVED
    assert bucket_observations[0].subject == "bucket-1"
    assert bucket_mgr.calls == [("get", "bucket-1")]


@pytest.mark.asyncio
async def test_observer_registry_reports_missing_bucket() -> None:
    plan, journal = _trace_plan_and_journal()
    bucket_mgr = FakeBucketManager(None)

    obs_set = await ProjectionObserverRegistry.default(bucket_manager=bucket_mgr).observe(plan, journal)

    bucket_observations = [obs for obs in obs_set.observations if obs.projection_kind == ProjectionKind.BUCKET_MARKDOWN]
    assert bucket_observations[0].status == ObservationStatus.MISSING


@pytest.mark.asyncio
async def test_observer_registry_reads_vector_without_writing() -> None:
    plan, journal = _trace_plan_and_journal()
    embedding_engine = FakeEmbeddingEngine(embedding=[0.1, 0.2])

    obs_set = await ProjectionObserverRegistry.default(embedding_engine=embedding_engine).observe(plan, journal)

    vector_observations = [obs for obs in obs_set.observations if obs.projection_kind == ProjectionKind.VECTOR_INDEX]
    assert vector_observations[0].status == ObservationStatus.OBSERVED
    assert embedding_engine.calls == [("get_embedding", "bucket-1")]


@pytest.mark.asyncio
async def test_observer_registry_observes_dashboard_from_config_snapshot() -> None:
    command = MemoryCommand.new(kind=CommandKind.BREATH, payload={"query": "x"})
    plan = MemoryCommandRouter.default().plan(command)
    journal = ProjectionRuntime.default().project(plan)

    obs_set = await ProjectionObserverRegistry.default(config_snapshot={"buckets_dir": "buckets"}).observe(plan, journal)

    dashboard_observations = [obs for obs in obs_set.observations if obs.projection_kind == ProjectionKind.DASHBOARD_STATE]
    assert dashboard_observations[0].status == ObservationStatus.OBSERVED


@pytest.mark.asyncio
async def test_observer_registry_returns_unknown_without_subject() -> None:
    plan, journal = _trace_plan_and_journal(payload={})

    obs_set = await ProjectionObserverRegistry.default().observe(plan, journal)

    assert all(obs.status == ObservationStatus.UNKNOWN for obs in obs_set.observations)
