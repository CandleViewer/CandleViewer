"""#3319 B1b: the backup sidecar's tests share a short socket path under pytest's temporary
directory (an AF_UNIX path holds at most 107 bytes; a long test's `tmp_path` may not fit)."""

from __future__ import annotations

import pytest


@pytest.fixture
def sock(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("s") / "c.sock"
    assert len(str(path)) < 100, "the pytest base temporary directory is too long for a socket"
    return str(path)
