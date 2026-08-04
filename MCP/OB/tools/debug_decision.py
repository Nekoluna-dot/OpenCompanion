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


def _runtime(args: argparse.Namespace) -> LegacyRuntime:
    return LegacyRuntime.from_config({"buckets_dir": str(args.buckets_dir)})


def _print_json(value: Any) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    return _print_json(
        _runtime(args).debug_decisions(
            limit=args.limit,
            module=args.module,
            operation=args.operation,
        )
    )


def _cmd_show(args: argparse.Namespace) -> int:
    result = _runtime(args).debug_decision(args.identifier)
    return _print_json(result)


def _cmd_replay(args: argparse.Namespace) -> int:
    result = _runtime(args).replay_decision(args.identifier)
    return _print_json(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only OmbreBrain v2.4.0 decision debug CLI")
    parser.add_argument("--buckets-dir", default="buckets", type=Path, help="Path to the legacy buckets directory")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="List recent decision records")
    list_cmd.add_argument("--limit", default=20, type=int)
    list_cmd.add_argument("--module", default="")
    list_cmd.add_argument("--operation", default="")
    list_cmd.set_defaults(func=_cmd_list)

    show_cmd = sub.add_parser("show", help="Show a decision by decision id or command id")
    show_cmd.add_argument("identifier")
    show_cmd.set_defaults(func=_cmd_show)

    replay_cmd = sub.add_parser("replay", help="Replay-check a decision by decision id or command id")
    replay_cmd.add_argument("identifier")
    replay_cmd.set_defaults(func=_cmd_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
