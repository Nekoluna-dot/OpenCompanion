from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ombrebrain.app.legacy_runtime import LegacyRuntime  # noqa: E402
from ombrebrain.maintenance.report import V3MaintenanceReportBuilder  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a read-only OmbreBrain v2.4.0 health report")
    parser.add_argument("--buckets-dir", default="buckets", type=Path, help="Path to the legacy buckets directory")
    parser.add_argument("--decision-limit", default=20, type=int, help="Number of recent decision records to include")
    parser.add_argument("--output", type=Path, help="Optional JSON output file")
    return parser


def _print_or_write(report: dict[str, Any], output: Path | None) -> int:
    text = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = LegacyRuntime.from_config({"buckets_dir": str(args.buckets_dir)})
    report = V3MaintenanceReportBuilder(runtime).build(decision_limit=args.decision_limit)
    return _print_or_write(report, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
