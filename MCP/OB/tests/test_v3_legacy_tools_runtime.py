from tools import _runtime as rt


def test_tools_runtime_accepts_v3_runtime_injection() -> None:
    class Runtime:
        def capability_names(self):
            return ("tools.search",)

    runtime = Runtime()
    rt.init(v3_runtime=runtime)

    assert rt.v3_runtime is runtime


def test_tools_runtime_dispatches_v3_capability_when_available() -> None:
    calls = []

    class Runtime:
        def dispatch_capability(self, name, payload, *, permissions, actor_name, source):
            calls.append((name, payload, permissions, actor_name, source))
            return {"ok": True, "name": name}

    rt.init(v3_runtime=Runtime())

    result = rt.run_v3_capability(
        "tools.search",
        {"query": "x"},
        permissions=("mcp:read", "mcp:call", "tools:search"),
        actor_name="codex",
        source="breath",
    )

    assert result == {"ok": True, "name": "tools.search"}
    assert calls == [
        (
            "tools.search",
            {"query": "x"},
            ("mcp:read", "mcp:call", "tools:search"),
            "codex",
            "breath",
        )
    ]


def test_tools_runtime_v3_capability_is_best_effort() -> None:
    rt.init(v3_runtime=None)

    assert rt.run_v3_capability(
        "tools.search",
        {},
        permissions=("tools:search",),
        actor_name="codex",
        source="breath",
    ) is None


def test_tools_runtime_records_v3_tool_event_best_effort() -> None:
    calls = []

    class Runtime:
        def record_tool_event(self, tool_name, payload):
            calls.append((tool_name, payload))
            return 3

    rt.init(v3_runtime=Runtime())

    assert rt.record_v3_tool_event("breath", {"query": "x"}) == 3
    assert calls == [("breath", {"query": "x"})]


def test_tools_runtime_enriches_v3_tool_event_with_command_plan() -> None:
    calls = []

    class Plan:
        def to_dict(self):
            return {"command_kind": "breath", "writes_memory": False}

    class Runtime:
        def plan_legacy_command(self, envelope):
            calls.append(("plan", envelope.module, envelope.operation, envelope.payload))
            return Plan()

        def record_tool_event(self, tool_name, payload):
            calls.append(("record", tool_name, payload))
            return 4

    rt.init(v3_runtime=Runtime())

    assert rt.record_v3_tool_event("breath", {"query": "x"}) == 4
    assert calls[0] == ("plan", "tools.breath", "breath", {"query": "x"})
    assert calls[1][0:2] == ("record", "breath")
    assert calls[1][2]["query"] == "x"
    assert calls[1][2]["command_plan"] == {"command_kind": "breath", "writes_memory": False}


def test_tools_runtime_runs_v3_operation_with_result_passthrough() -> None:
    calls = []

    class Runtime:
        def run_operation(self, envelope, handler):
            calls.append((envelope.module, envelope.operation, envelope.payload))
            return handler()

    rt.init(v3_runtime=Runtime())

    result = rt.run_v3_operation(
        "dispatch",
        {"query": "x"},
        lambda: "tool result",
        module="tools.breath",
    )

    assert result == "tool result"
    assert calls == [("tools.breath", "dispatch", {"query": "x"})]


def test_tools_runtime_operation_is_noop_without_v3_runtime() -> None:
    rt.init(v3_runtime=None)

    assert rt.run_v3_operation("dispatch", {}, lambda: "legacy", module="tools.dream") == "legacy"


async def _async_value():
    return "async result"


async def _async_raise():
    raise RuntimeError("boom")


def test_tools_runtime_async_operation_is_available() -> None:
    assert hasattr(rt, "run_v3_async_operation")
