"""Command-line entry point."""

from .orders import place_order


def main() -> None:
    place_order("example", 25)
