"""Fixture for #3549: Semgrep 1.181.0 parses no part of this module."""

import re
from dataclasses import dataclass

LIMIT = 80
NAME_RE = re.compile(rf"[a-z]{{1,{LIMIT}}}")


@dataclass(frozen=True)
class Named[T]:
    name: str
    value: T


print(Named("a", NAME_RE))
