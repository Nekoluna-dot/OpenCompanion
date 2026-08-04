from pathlib import Path

from ombrebrain.app.legacy_wiring import build_v3_runtime


def test_build_v3_runtime_attaches_to_bucket_manager(tmp_path) -> None:
    class BucketManager:
        def __init__(self) -> None:
            self.attached = None

        def attach_v3_runtime(self, runtime) -> None:
            self.attached = runtime

    manager = BucketManager()
    runtime = build_v3_runtime({"buckets_dir": str(tmp_path / "buckets")}, bucket_mgr=manager)

    assert manager.attached is runtime
    assert runtime.root == Path(tmp_path / "buckets" / ".ombrebrain-v3")
    assert "hot_update.apply" in runtime.capability_names()


def test_build_v3_runtime_tolerates_bucket_manager_without_attach(tmp_path) -> None:
    runtime = build_v3_runtime({"buckets_dir": str(tmp_path / "buckets")}, bucket_mgr=object())

    assert runtime.fabric.next_index() == 1
