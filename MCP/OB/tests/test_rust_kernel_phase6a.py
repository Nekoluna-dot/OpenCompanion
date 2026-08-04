import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "kernel" / "rust" / "ombre-kernel"


def test_rust_kernel_scaffold_exports_replay_contract_types():
    manifest = CRATE / "Cargo.toml"
    lib_rs = CRATE / "src" / "lib.rs"

    assert manifest.exists()
    assert lib_rs.exists()

    manifest_text = manifest.read_text(encoding="utf-8")
    lib_text = lib_rs.read_text(encoding="utf-8")

    assert 'name = "ombre-kernel"' in manifest_text
    assert "[dependencies]" in manifest_text
    assert "serde" not in manifest_text
    assert "pub struct LedgerEvent" in lib_text
    assert "pub struct ReplayReport" in lib_text
    assert "pub enum ViolationCode" in lib_text
    assert "pub struct ReplayKernel" in lib_text
    assert "pub fn validate" in lib_text


def test_rust_kernel_cargo_tests_when_toolchain_is_available():
    cargo = shutil.which("cargo")
    assert (CRATE / "Cargo.toml").exists()
    if cargo is None:
        return

    result = subprocess.run(
        [cargo, "test", "--manifest-path", str(CRATE / "Cargo.toml")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
