from ombrebrain.domain.commands import CommandKind, MemoryCommand
from ombrebrain.domain.invariants import MemoryInvariantSet


def test_invariants_mark_permanent_memory_as_non_decaying() -> None:
    verdict = MemoryInvariantSet.default().evaluate(
        MemoryCommand.new(kind=CommandKind.DECAY, payload={"memory_type": "permanent"})
    )

    assert "non-decaying-permanent" in verdict.rules
    assert verdict.allowed is True


def test_invariants_mark_feel_memory_as_not_ordinary_breath() -> None:
    verdict = MemoryInvariantSet.default().evaluate(
        MemoryCommand.new(kind=CommandKind.BREATH, payload={"memory_type": "feel", "ordinary": True})
    )

    assert verdict.allowed is False
    assert "feel-excluded-from-ordinary-breath" in verdict.rules


def test_invariants_mark_plan_as_status_lifecycle() -> None:
    verdict = MemoryInvariantSet.default().evaluate(
        MemoryCommand.new(kind=CommandKind.TRACE, payload={"memory_type": "plan", "status": "resolved"})
    )

    assert verdict.allowed is True
    assert "plan-status-lifecycle" in verdict.rules


def test_invariants_mark_letters_as_raw_preserved() -> None:
    verdict = MemoryInvariantSet.default().evaluate(
        MemoryCommand.new(kind=CommandKind.HOLD, payload={"memory_type": "letter"})
    )

    assert verdict.allowed is True
    assert "letter-raw-preserved" in verdict.rules

