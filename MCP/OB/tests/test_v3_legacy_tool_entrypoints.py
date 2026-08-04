import pytest

from tools import _runtime as rt
import tools.breath as breath_mod
import tools.hold as hold_mod
import tools.trace.core as trace_mod


class _Decay:
    async def ensure_started(self):
        return None


@pytest.mark.asyncio
async def test_breath_dispatch_records_v3_tool_event(monkeypatch) -> None:
    calls = []

    async def fake_surface_default(**_kwargs):
        return "breath result"

    rt.init(config={"surfacing": {}}, decay_engine=_Decay(), mark_op=None)
    monkeypatch.setattr(rt, "record_v3_tool_event", lambda name, payload: calls.append((name, payload)))
    monkeypatch.setattr(breath_mod, "surface_default", fake_surface_default)

    result = await breath_mod.dispatch(query="", max_results=2)

    assert result == "breath result"
    assert calls[0][0] == "breath"
    assert calls[0][1]["query"] == ""
    assert calls[0][1]["max_results"] == 2


@pytest.mark.asyncio
async def test_hold_dispatch_records_v3_tool_event_without_content_body(monkeypatch) -> None:
    calls = []

    async def fake_store_core(**_kwargs):
        return "hold result"

    async def fake_importance_quota(importance):
        return importance

    rt.init(config={}, decay_engine=_Decay(), mark_op=None)
    monkeypatch.setattr(rt, "record_v3_tool_event", lambda name, payload: calls.append((name, payload)))
    monkeypatch.setattr(hold_mod, "check_content_size", lambda _content: None)
    monkeypatch.setattr(hold_mod, "enforce_high_importance_quota", fake_importance_quota)
    monkeypatch.setattr(hold_mod, "store_core", fake_store_core)

    result = await hold_mod.dispatch(content="private memory body", tags="x,y", importance=7)

    assert result == "hold result"
    assert calls[0][0] == "hold"
    assert calls[0][1]["content_length"] == len("private memory body")
    assert "content" not in calls[0][1]


@pytest.mark.asyncio
async def test_trace_core_records_v3_tool_event_without_content_body(monkeypatch) -> None:
    calls = []

    rt.init(config={}, mark_op=None)
    monkeypatch.setattr(rt, "record_v3_tool_event", lambda name, payload: calls.append((name, payload)))

    result = await trace_mod.trace_core(bucket_id="", content="private replacement", delete=True)

    assert "bucket_id" in result
    assert calls[0][0] == "trace"
    assert calls[0][1]["delete"] is True
    assert calls[0][1]["content_length"] == len("private replacement")
    assert "content" not in calls[0][1]
