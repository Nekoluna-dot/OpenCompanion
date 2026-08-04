import hashlib

from ombrebrain.protocol.manifests import FileManifest, UpdateManifest
import web
from web import _shared as sh


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_web_shared_accepts_v3_runtime_injection() -> None:
    runtime = object()

    sh.init_runtime(v3_runtime=runtime)

    assert sh.v3_runtime is runtime


def test_web_shared_evaluates_v3_update_policy_when_runtime_is_available() -> None:
    class Runtime:
        def evaluate_update_manifest(self, manifest, content_by_path):
            return {"version": manifest.version, "content_count": len(content_by_path)}

    sh.init_runtime(v3_runtime=Runtime())
    data = b"ok"
    manifest = UpdateManifest(
        version="3.0.0",
        files=(FileManifest(path="src/x.py", sha256=_sha(data), size=len(data)),),
    )

    assert sh.evaluate_v3_update_manifest(manifest, {"src/x.py": data}) == {
        "version": "3.0.0",
        "content_count": 1,
    }


def test_web_shared_evaluates_v3_update_policy_directly_without_runtime() -> None:
    sh.init_runtime(v3_runtime=None)
    data = b"secret"
    manifest = UpdateManifest(
        version="3.0.0",
        files=(FileManifest(path=".env", sha256=_sha(data), size=len(data)),),
    )

    plan = sh.evaluate_v3_update_manifest(manifest, {".env": data})

    assert plan.rejected == {".env": "protected path"}


def test_web_shared_runs_v3_web_operation_with_result_passthrough() -> None:
    calls = []

    class Runtime:
        def run_operation(self, envelope, handler):
            calls.append((envelope.module, envelope.operation, envelope.payload))
            return handler()

    sh.init_runtime(v3_runtime=Runtime())

    result = sh.run_v3_web_operation(
        "save-port",
        {"host_port": 18001},
        lambda: {"ok": True},
        module="web.config_api",
    )

    assert result == {"ok": True}
    assert calls == [("web.config_api", "save-port", {"host_port": 18001})]


def test_web_shared_web_operation_is_noop_without_v3_runtime() -> None:
    sh.init_runtime(v3_runtime=None)

    assert sh.run_v3_web_operation("route", {}, lambda: "legacy", module="web.dashboard") == "legacy"


def test_web_register_all_uses_v3_web_operation(monkeypatch) -> None:
    calls = []
    registered = []

    def fake_run(operation, payload, handler, *, module, **_kwargs):
        calls.append((operation, module, payload))
        return handler()

    def fake_register(mcp):
        registered.append(mcp)

    monkeypatch.setattr(web._shared, "run_v3_web_operation", fake_run)
    monkeypatch.setattr(web, "_WEB_MODULES", (("web.fake", fake_register),))

    web.register_all("mcp")

    assert registered == ["mcp"]
    assert calls == [("register_all", "web.*", {"modules": ["web.fake"]})]
