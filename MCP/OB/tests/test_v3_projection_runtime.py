from ombrebrain.domain.commands import CommandKind, MemoryCommand, MemoryCommandRouter
from ombrebrain.projection.runtime import ProjectionRuntime


def test_projection_runtime_creates_one_journal_entry_per_plan_step() -> None:
    command = MemoryCommand.new(kind=CommandKind.HOLD, payload={"bucket_id": "b1"})
    plan = MemoryCommandRouter.default().plan(command)

    journal = ProjectionRuntime.default().project(plan)

    assert journal.command_id == plan.command_id
    assert len(journal.entries) == len(plan.projections)
    assert journal.entries[0].projection_kind == plan.projections[0].kind
    assert journal.entries[0].status.value == "planned"
    assert journal.to_dict()["entries"][0]["checksum"].startswith("proj_")


def test_projection_runtime_checksums_are_deterministic() -> None:
    command = MemoryCommand.new(kind=CommandKind.TRACE, payload={"bucket_id": "b1", "delete": True})
    plan = MemoryCommandRouter.default().plan(command)

    first = ProjectionRuntime.default().project(plan)
    second = ProjectionRuntime.default().project(plan)

    assert [entry.checksum for entry in first.entries] == [entry.checksum for entry in second.entries]


def test_projection_runtime_does_not_mutate_command_plan() -> None:
    command = MemoryCommand.new(kind=CommandKind.BREATH, payload={"query": "x"})
    plan = MemoryCommandRouter.default().plan(command)
    before = plan.to_dict()

    ProjectionRuntime.default().project(plan)

    assert plan.to_dict() == before


def test_projection_journal_serializes_as_json_safe_dict() -> None:
    command = MemoryCommand.new(kind=CommandKind.SYNC, payload={"remote": "github"})
    plan = MemoryCommandRouter.default().plan(command)

    data = ProjectionRuntime.default().project(plan).to_dict()

    assert data["command_id"] == plan.command_id
    assert isinstance(data["entries"], list)
    assert data["entries"][0]["projection_kind"] == "fabric_event"
    assert data["entries"][0]["metadata"]["policy_tags"] == ["network-side-effect"]
