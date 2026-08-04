# ombre-kernel

`ombre-kernel` is the Phase 6A Rust scaffold for Ombre Brain's replay kernel.

It is intentionally shadow-only:

- It does not replace the Python runtime.
- It has no external Rust dependencies.
- It models the same baseline replay invariants as `src/ledger_replay.py`.
- It is meant to become the future FFI/kernel boundary after the replay contract is stable.

Run when Rust is available:

```bash
cargo test --manifest-path kernel/rust/ombre-kernel/Cargo.toml
```
