from ledger_property import LedgerReplayPropertyRunner


def test_property_runner_generates_deterministic_strictly_ordered_event_streams():
    runner = LedgerReplayPropertyRunner.default()

    first = runner.generate_case(seed=42, max_events=50)
    second = runner.generate_case(seed=42, max_events=50)

    assert first == second
    assert len(first) == 50
    assert [event["seq"] for event in first] == list(range(1, 51))
    assert all(str(event["trace_id"]).strip() for event in first)
    assert all(str(event["body_hash"]).startswith("sha256:") for event in first)


def test_property_runner_validates_many_randomized_replay_cases():
    report = LedgerReplayPropertyRunner.default().run(seed=20260702, cases=25, max_events=80)

    assert report["ok"] is True
    assert report["seed"] == 20260702
    assert report["cases"] == 25
    assert report["max_events"] == 80
    assert report["checked_events"] == 25 * 80
    assert report["failures"] == []
