"""Human-input command arguments."""

import argparse
from pathlib import Path
from typing import Any

from .common_arguments import add_common_arguments, add_config_arguments


def add_domain_subparser(subparsers: Any) -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "domain", help="Read or write human domain input"
    )
    parser.add_argument("path", nargs="?", type=Path, default=Path("."))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--write", metavar="FILE|-", help="Read a JSON write request")
    modes.add_argument("--list-input", action="store_true")
    modes.add_argument("--schema", action="store_true")
    modes.add_argument("--extract-structure", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without writing (requires --write)",
    )
    add_common_arguments(parser)
    add_config_arguments(parser, ["database"])
    return parser
