"""Fixture for #3549: Semgrep 1.99.0 parses no code line of this module."""

from collections.abc import Callable

print("loaded")


def first[T](items: list[T], keep: Callable[[T], bool]) -> T | None:
    for item in items:
        if keep(item):
            return item
    return None
