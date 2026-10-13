"""SR-009 process hardening: core dumps off and not dumpable, checked and read back."""

from __future__ import annotations

import ctypes
import os
import resource
import subprocess
import sys
from pathlib import Path

import pytest

from candleviewer.secrets import _kek

_ROOT = Path(__file__).resolve().parents[3]


def _py(code: str) -> list[str]:
    """Hermetic subprocess: no `-I` (it drops the package root from sys.path); the package root
    is passed explicitly via PYTHONPATH and cwd, and stderr is shown on failure."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(_ROOT)
    r = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=30, cwd=_ROOT, env=env,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout.split()


def test_harden_process_takes_effect() -> None:
    # Subprocess: PR_SET_DUMPABLE=0 must not leak into the pytest process.
    out = _py(
        "import resource,ctypes;from candleviewer.secrets import _kek;"
        "print(_kek.harden_process(), resource.getrlimit(resource.RLIMIT_CORE)[0],"
        "ctypes.CDLL(None).prctl(3,0,0,0,0))"
    )
    assert out == ["True", "0", "0"]


def test_harden_process_reports_failure() -> None:
    out = _py(
        "import resource;from candleviewer.secrets import _kek;"
        "resource.setrlimit=lambda *a:(_ for _ in ()).throw(ValueError());"
        "print(_kek.harden_process())"
    )
    assert out == ["False"]


def test_harden_process_reports_missing_prctl() -> None:
    out = _py(
        "import ctypes;from candleviewer.secrets import _kek;"
        "ctypes.CDLL=lambda *a,**k:(_ for _ in ()).throw(OSError());"
        "print(_kek.harden_process())"
    )
    assert out == ["False"]


class _Libc:
    def __init__(self, set_rc: int, get_rc: int) -> None:
        self.rc = {4: set_rc, 3: get_rc}

    def prctl(self, op: int, *a: int) -> int:
        return self.rc[op]


@pytest.mark.parametrize(
    ("core", "set_rc", "get_rc", "expected"),
    [((0, 0), 0, 0, True), ((0, 0), -1, 0, False), ((0, 0), 0, 1, False),
     ((1, 1), 0, 0, False)],
)  # fmt: skip
def test_harden_process_in_process_with_fakes(
    monkeypatch: pytest.MonkeyPatch, core: tuple[int, int], set_rc: int, get_rc: int,
    expected: bool,
) -> None:  # fmt: skip
    monkeypatch.setattr(resource, "setrlimit", lambda *a: None)
    monkeypatch.setattr(resource, "getrlimit", lambda *a: core)
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: _Libc(set_rc, get_rc))
    assert _kek.harden_process() is expected


def test_harden_process_in_process_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise OSError

    monkeypatch.setattr(resource, "setrlimit", boom)
    monkeypatch.setattr(ctypes, "CDLL", boom)
    assert _kek.harden_process() is False
