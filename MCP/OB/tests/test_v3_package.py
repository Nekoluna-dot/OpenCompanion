from pathlib import Path


def test_ombrebrain_package_exports_version():
    import ombrebrain

    assert isinstance(ombrebrain.__version__, str)
    assert ombrebrain.__version__


def test_version_reader_uses_root_version_file():
    from ombrebrain.version import read_version

    root_version = Path(__file__).resolve().parent.parent / "VERSION"
    assert read_version() == root_version.read_text(encoding="utf-8").strip()
