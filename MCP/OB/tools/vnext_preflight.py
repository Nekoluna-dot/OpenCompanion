from __future__ import annotations

# ============================================================
# tools/vnext_preflight.py
# 这是什么：vNext preflight 报告的只读命令行入口。
# 做什么：加载 LegacyRuntime，跑 VNextPreflightReportBuilder，把聚合结果
#         （各 vNext 契约 check 的健康状况）以 JSON 打印或写文件。
# 不做什么：不改任何记忆、不写 ledger、不触发发布门禁；纯只读诊断。
# 对外暴露：build_parser() / main(argv)；命令行用法见下方 build_parser。
# 位置约定：与 tools/v3_health_report.py 并列，沿用同一套 CLI 结构与输出风格。
# 说明：src/web/system.py 的系统诊断 check「preflight_cli_diagnostics」会校验
#       本文件存在且包含 build_parser / --buckets-dir / --output / --coverage-only /
#       LegacyRuntime.from_config / VNextPreflightReportBuilder(runtime).build()。
# ============================================================

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
from ombrebrain.maintenance.report import VNextPreflightReportBuilder  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the read-only OmbreBrain vNext preflight report")
    parser.add_argument("--buckets-dir", default="buckets", type=Path, help="Path to the legacy buckets directory")
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="Only emit the vNext coverage matrix (schema vnext-coverage.v1), not the full preflight report",
    )
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
    report = VNextPreflightReportBuilder(runtime).build()
    if args.coverage_only:
        # coverage-only：只抽出覆盖矩阵子报告（schema=vnext-coverage.v1），
        # 它本身不含 "checks" 键，正是命令行覆盖模式期望的形状。
        report = report["checks"]["vnext_coverage"]
    return _print_or_write(report, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
