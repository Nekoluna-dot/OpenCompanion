from dataclasses import replace

from ombrebrain.domain.commands import CommandKind, MemoryCommand, MemoryCommandRouter, ProjectionKind
from ombrebrain.projection.auditor import ConsistencyAuditor
from ombrebrain.projection.journal import ProjectionJournal, ProjectionJournalEntry, ProjectionStatus
from ombrebrain.projection.observation import ObservationStatus, ProjectionObservation, ProjectionObservationSet
from ombrebrain.projection.runtime import ProjectionRuntime


def _trace_plan():
    command = MemoryCommand.new(kind=CommandKind.TRACE, payload={"bucket_id": "b1", "delete": True})
    return MemoryCommandRouter.default().plan(command)


def test_consistency_auditor_accepts_matching_journal() -> None:
    plan = _trace_plan()
    journal = ProjectionRuntime.default().project(plan)

    report = ConsistencyAuditor.default().audit(plan, journal)

    assert report.ok is True
    assert report.expected_count == len(plan.projections)
    assert report.observed_count == len(journal.entries)
    assert report.issues == ()
    assert report.to_dict()["ok"] is True


def test_consistency_auditor_reports_missing_projection() -> None:
    plan = _trace_plan()
    journal = ProjectionRuntime.default().project(plan)
    journal = ProjectionJournal(command_id=journal.command_id, entries=journal.entries[:-1], created_at=journal.created_at)

    report = ConsistencyAuditor.default().audit(plan, journal)

    assert report.ok is False
    assert any(issue.code == "missing_projection" for issue in report.issues)


def test_consistency_auditor_reports_duplicate_projection() -> None:
    plan = _trace_plan()
    journal = ProjectionRuntime.default().project(plan)
    duplicate = journal.entries[0]
    journal = ProjectionJournal(command_id=journal.command_id, entries=journal.entries + (duplicate,), created_at=journal.created_at)

    report = ConsistencyAuditor.default().audit(plan, journal)

    assert report.ok is False
    assert any(issue.code == "duplicate_projection" for issue in report.issues)


def test_consistency_auditor_reports_unexpected_projection() -> None:
    plan = _trace_plan()
    journal = ProjectionRuntime.default().project(plan)
    unexpected = ProjectionJournalEntry(
        command_id=journal.command_id,
        command_kind=CommandKind.TRACE,
        projection_kind=ProjectionKind.EXTERNAL_NETWORK,
        surface="github",
        action="push",
    )
    journal = ProjectionJournal(command_id=journal.command_id, entries=journal.entries + (unexpected,), created_at=journal.created_at)

    report = ConsistencyAuditor.default().audit(plan, journal)

    assert report.ok is False
    assert any(issue.code == "unexpected_projection" for issue in report.issues)


def test_consistency_auditor_reports_command_id_mismatch() -> None:
    plan = _trace_plan()
    journal = ProjectionRuntime.default().project(plan)
    journal = ProjectionJournal(command_id="cmd_other", entries=journal.entries, created_at=journal.created_at)

    report = ConsistencyAuditor.default().audit(plan, journal)

    assert report.ok is False
    assert any(issue.code == "command_id_mismatch" for issue in report.issues)


def test_consistency_auditor_reports_failed_or_skipped_entries() -> None:
    plan = _trace_plan()
    journal = ProjectionRuntime.default().project(plan)
    failed = replace(journal.entries[0], status=ProjectionStatus.FAILED, checksum="")
    journal = ProjectionJournal(command_id=journal.command_id, entries=(failed,) + journal.entries[1:], created_at=journal.created_at)

    report = ConsistencyAuditor.default().audit(plan, journal)

    assert report.ok is False
    assert any(issue.code == "projection_not_planned" for issue in report.issues)


def _observations_for_journal(journal, status=ObservationStatus.OBSERVED):
    return ProjectionObservationSet(
        command_id=journal.command_id,
        observations=tuple(
            ProjectionObservation(
                projection_kind=entry.projection_kind,
                surface=entry.surface,
                action=entry.action,
                status=status,
            )
            for entry in journal.entries
        ),
    )


def test_consistency_auditor_accepts_matching_observations() -> None:
    plan = _trace_plan()
    journal = ProjectionRuntime.default().project(plan)
    observations = _observations_for_journal(journal)

    report = ConsistencyAuditor.default().audit_with_observations(plan, journal, observations)

    assert report.ok is True
    assert report.metadata["observation_count"] == len(journal.entries)


def test_consistency_auditor_reports_missing_observation() -> None:
    plan = _trace_plan()
    journal = ProjectionRuntime.default().project(plan)
    observations = ProjectionObservationSet(command_id=plan.command_id, observations=())

    report = ConsistencyAuditor.default().audit_with_observations(plan, journal, observations)

    assert report.ok is False
    assert any(issue.code == "missing_observation" for issue in report.issues)


def test_consistency_auditor_reports_observer_missing_or_failed() -> None:
    plan = _trace_plan()
    journal = ProjectionRuntime.default().project(plan)
    observations = _observations_for_journal(journal, status=ObservationStatus.MISSING)

    report = ConsistencyAuditor.default().audit_with_observations(plan, journal, observations)

    assert report.ok is False
    assert any(issue.code == "observer_missing_projection" for issue in report.issues)


def test_consistency_auditor_treats_unknown_observations_as_non_blocking() -> None:
    plan = _trace_plan()
    journal = ProjectionRuntime.default().project(plan)
    observations = _observations_for_journal(journal, status=ObservationStatus.UNKNOWN)

    report = ConsistencyAuditor.default().audit_with_observations(plan, journal, observations)

    assert report.ok is True
    assert report.metadata["unknown_observations"] == len(journal.entries)
