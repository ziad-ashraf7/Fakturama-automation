"""Command-line entry point for the image-to-cash workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from fakturama_automation.config import Settings
from fakturama_automation.domain.outcomes import OutcomeStatus
from fakturama_automation.workflow import run_order_to_cash


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fakturama-automation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="extract one order image and automate Fakturama")
    run.add_argument("image", type=Path)
    args = parser.parse_args(argv)
    if not args.image.is_file():
        parser.error(f"input image does not exist: {args.image}")
    outcome = run_order_to_cash(args.image, Settings())
    print(f"{outcome.status}: {outcome.message}")
    if outcome.status is OutcomeStatus.SUCCESS:
        return 0
    if outcome.status is OutcomeStatus.MANUAL_REVIEW:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
