import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("sh") is None,
    reason="entrypoint behavior test requires a POSIX shell",
)


def _prepare_image(root: Path, source: str = "IMAGE = 'one'\n") -> None:
    shutil.copytree(ROOT / "src", root / "src")
    (root / "src" / "server.py").write_text(source, encoding="utf-8")
    (root / "frontend").mkdir(parents=True)
    (root / "frontend" / "dashboard.html").write_text("<h1>image</h1>\n", encoding="utf-8")
    (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    (root / "config.default.yaml").write_text("buckets_dir: ./buckets\n", encoding="utf-8")


def _run(
    image_root: Path,
    code_dir: Path,
    data_dir: Path,
    **extra_env: str,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({
        "OMBRE_IMAGE_ROOT": str(image_root),
        "OMBRE_CODE_DIR": str(code_dir),
        "OMBRE_BUCKETS_DIR": str(data_dir),
        "OMBRE_CONFIG_PATH": str(data_dir / "config.yaml"),
        "OMBRE_BOOTSTRAP_ONLY": "1",
        **extra_env,
    })
    return subprocess.run(
        ["sh", str(ROOT / "entrypoint.sh")],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_same_version_changed_image_reseeds_but_unchanged_image_preserves_hot_update(tmp_path):
    image = tmp_path / "image"
    code = tmp_path / "code" / "_app"
    data = tmp_path / "data"
    _prepare_image(image)

    first = _run(image, code, data)
    assert first.returncode == 0, first.stdout + first.stderr
    assert (code / "src" / "server.py").read_text(encoding="utf-8") == "IMAGE = 'one'\n"
    assert (code / ".seeded_image_fingerprint").is_file()

    # Dashboard hot update: image did not change, so the persisted runtime must win.
    (code / "src" / "server.py").write_text("HOT_UPDATE = True\n", encoding="utf-8")
    unchanged = _run(image, code, data)
    assert unchanged.returncode == 0, unchanged.stdout + unchanged.stderr
    assert (code / "src" / "server.py").read_text(encoding="utf-8") == "HOT_UPDATE = True\n"

    # A locally rebuilt image with the same VERSION must still replace the old baseline.
    (image / "src" / "server.py").write_text("IMAGE = 'two'\n", encoding="utf-8")
    rebuilt = _run(image, code, data)
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    assert (code / "src" / "server.py").read_text(encoding="utf-8") == "IMAGE = 'two'\n"
    assert "代码指纹" in rebuilt.stdout


def test_non_active_legacy_data_app_is_reported_without_deletion(tmp_path):
    image = tmp_path / "image"
    code = tmp_path / "code" / "_app"
    data = tmp_path / "data"
    _prepare_image(image)
    legacy = data / "_app"
    (legacy / "src").mkdir(parents=True)
    (legacy / "src" / "server.py").write_text("LEGACY = True\n", encoding="utf-8")
    (legacy / "VERSION").write_text("2.4.6\n", encoding="utf-8")

    result = _run(image, code, data)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "旧布局代码遗留" in result.stdout
    assert "未被当前进程使用" in result.stdout
    assert (legacy / "src" / "server.py").is_file()


def test_image_seed_failure_keeps_existing_runtime_tree(tmp_path):
    image = tmp_path / "image"
    code = tmp_path / "code" / "_app"
    data = tmp_path / "data"
    _prepare_image(image)
    assert _run(image, code, data).returncode == 0
    before = (code / "src" / "server.py").read_bytes()

    shutil.rmtree(image / "frontend")
    failed = _run(image, code, data, OMBRE_FORCE_CODE_RESEED="1")

    assert "持久卷代码不可用" in failed.stdout
    assert (code / "src" / "server.py").read_bytes() == before


def test_crash_rollback_is_not_immediately_overwritten_by_same_image(tmp_path):
    image = tmp_path / "image"
    code = tmp_path / "code" / "_app"
    data = tmp_path / "data"
    _prepare_image(image, "IMAGE = 'known-good'\n")
    assert _run(image, code, data).returncode == 0

    # Same VERSION, new image content. Seeding keeps the healthy prior runtime in _prev.
    (image / "src" / "server.py").write_text("IMAGE = 'crashing'\n", encoding="utf-8")
    assert _run(image, code, data).returncode == 0
    assert (code / "_prev" / "src" / "server.py").read_text(encoding="utf-8") == (
        "IMAGE = 'known-good'\n"
    )

    # Simulate two failed service starts. The next entrypoint pass must restore _prev
    # and treat it as a persisted override instead of reseeding the same bad image.
    (code / ".boot_fails").write_text("2\n", encoding="utf-8")
    rolled_back = _run(image, code, data)

    assert rolled_back.returncode == 0, rolled_back.stdout + rolled_back.stderr
    assert "回滚到上一版代码" in rolled_back.stdout
    assert "reason=image-fingerprint-changed" not in rolled_back.stdout
    assert (code / "src" / "server.py").read_text(encoding="utf-8") == (
        "IMAGE = 'known-good'\n"
    )
