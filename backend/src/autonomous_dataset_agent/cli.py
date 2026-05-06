from __future__ import annotations

import argparse
import json
import sys

from .config import build_job_config
from .orchestrator import PipelineRunner
from .utils import dataclass_to_dict


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonomous Dataset Agent backend CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the dataset pipeline")
    run_parser.add_argument("--prompt", required=True, help="Target prompt, e.g. 'forklift in a warehouse'")
    run_parser.add_argument(
        "--classes",
        required=True,
        help="Comma-separated class list, e.g. 'forklift,pallet jack'",
    )
    run_parser.add_argument("--output-root", help="Override the artifact output root")
    run_parser.add_argument("--env-file", help="Optional env file path")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        class_list = [item.strip() for item in args.classes.split(",") if item.strip()]
        config = build_job_config(
            prompt=args.prompt,
            classes=class_list,
            output_root=args.output_root,
            env_file=args.env_file,
        )
        summary = PipelineRunner(config).run()
        print(json.dumps(dataclass_to_dict(summary), indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
