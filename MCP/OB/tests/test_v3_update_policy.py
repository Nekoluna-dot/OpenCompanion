import hashlib

from ombrebrain.policy.update_policy import evaluate_update_manifest
from ombrebrain.protocol.manifests import FileManifest, UpdateManifest


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_update_policy_rejects_protected_runtime_state_paths() -> None:
    content = b"secret"
    manifest = UpdateManifest(
        version="3.0.0",
        files=(
            FileManifest(path=".env", sha256=_sha(content), size=len(content)),
            FileManifest(path="config.yaml", sha256=_sha(content), size=len(content)),
            FileManifest(path="buckets/permanent/a.md", sha256=_sha(content), size=len(content)),
            FileManifest(path="data/vector/chroma.sqlite3", sha256=_sha(content), size=len(content)),
            FileManifest(path="deploy/docker-compose.user.yml", sha256=_sha(content), size=len(content)),
            FileManifest(path="oauth/client_secret.json", sha256=_sha(content), size=len(content)),
        ),
    )

    plan = evaluate_update_manifest(manifest, {item.path: content for item in manifest.files})

    assert plan.accepted == ()
    assert set(plan.rejected) == {item.path for item in manifest.files}


def test_update_policy_rejects_absolute_and_traversal_paths() -> None:
    content = b"bad"
    manifest = UpdateManifest(
        version="3.0.0",
        files=(
            FileManifest(path="../README.md", sha256=_sha(content), size=len(content)),
            FileManifest(path="/tmp/evil.py", sha256=_sha(content), size=len(content)),
            FileManifest(path="C:/Users/Public/evil.py", sha256=_sha(content), size=len(content)),
            FileManifest(path="C:evil.py", sha256=_sha(content), size=len(content)),
            FileManifest(path="src/file.py:ads", sha256=_sha(content), size=len(content)),
        ),
    )

    plan = evaluate_update_manifest(manifest, {item.path: content for item in manifest.files})

    assert plan.accepted == ()
    assert all("unsafe path" in reason for reason in plan.rejected.values())


def test_update_policy_verifies_sha256_and_keeps_allowed_files_separate() -> None:
    good = b"print('ok')\n"
    bad = b"print('no')\n"
    manifest = UpdateManifest(
        version="3.0.0",
        rollout_strategy="rolling-majority",
        files=(
            FileManifest(path="src/ombrebrain/new_module.py", sha256=_sha(good), size=len(good)),
            FileManifest(path="frontend/dashboard.html", sha256=_sha(good), size=len(good)),
            FileManifest(path="src/ombrebrain/bad_hash.py", sha256=_sha(good), size=len(good)),
        ),
    )

    plan = evaluate_update_manifest(
        manifest,
        {
            "src/ombrebrain/new_module.py": good,
            "frontend/dashboard.html": good,
            "src/ombrebrain/bad_hash.py": bad,
        },
    )

    assert tuple(item.path for item in plan.accepted) == (
        "src/ombrebrain/new_module.py",
        "frontend/dashboard.html",
    )
    assert plan.rejected == {"src/ombrebrain/bad_hash.py": "sha256 mismatch"}
    assert plan.rollout_strategy == "rolling-majority"
    assert plan.executed is False
