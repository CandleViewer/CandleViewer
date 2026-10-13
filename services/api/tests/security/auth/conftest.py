"""Shared fixtures for the E09-X02 HTTP abuse cases (#2144). Modules that define their own
`stack` (e.g. `test_csrf_double_submit.py`) keep it: a module fixture overrides this one."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from ._stack import Stack, open_stack


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    """`create_app()` over the in-memory auth stack of `_stack.py`."""
    with open_stack(monkeypatch) as s:
        yield s
