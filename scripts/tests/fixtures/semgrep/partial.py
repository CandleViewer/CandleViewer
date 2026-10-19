"""Fixture for #3549: Semgrep 1.99.0 skips one line of this module."""

type Pair = tuple[int, int]


def swap(pair: Pair) -> Pair:
    return pair[1], pair[0]


print(swap((1, 2)))
