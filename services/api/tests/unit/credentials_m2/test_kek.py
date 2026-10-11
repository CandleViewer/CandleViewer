"""KEK loader: source selection, live refusal, handle reads, permissions, ack, KCV."""

from __future__ import annotations

import os
import pickle
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from candleviewer.secrets import _kek
from candleviewer.secrets.errors import KekLoadError, KekSourceNotPermitted
from candleviewer.settings import Environment, Settings
from tests.unit.credentials_m2.conftest import KEK_V1, kek


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]  # pydantic-settings kwarg


def _write(p: Path, data: bytes, mode: int = 0o400) -> Path:
    p.write_bytes(data)
    p.chmod(mode)
    return p


def test_file_source_refused_in_live() -> None:
    with pytest.raises(KekSourceNotPermitted) as ei:
        _kek.source_from_settings(_settings(environment=Environment.LIVE, kek_source="file"))
    assert ei.value.code == "kek_source_not_permitted"


@pytest.mark.parametrize("src", ["handle", "host-keychain"])
def test_handle_source_allows_fifo(src: str) -> None:
    s = _kek.source_from_settings(_settings(kek_source=src, kek_handle="/x"))
    assert isinstance(s, _kek.PathKekSource) and s.allow_fifo


def test_none_source_always_fails() -> None:
    s = _kek.source_from_settings(_settings(kek_source="none"))
    with pytest.raises(KekLoadError):
        s.load()


def test_previous_source_uses_prev_handle_and_version() -> None:
    s = _kek.source_from_settings(
        _settings(kek_source="file", kek_prev_handle="/p", kek_version=2), previous=True
    )
    assert isinstance(s, _kek.PathKekSource) and s.version == 1 and s.path == Path("/p")


def test_file_source_loads_exact_32(tmp_path: Path) -> None:
    p = _write(tmp_path / "k", KEK_V1)
    k = _kek.PathKekSource(p, 1, allow_fifo=False).load()
    assert k.version == 1 and k.kcv() == kek().kcv()


@pytest.mark.parametrize("data", [b"", KEK_V1[:31], KEK_V1 + b"x"])
def test_file_source_wrong_length_unavailable(tmp_path: Path, data: bytes) -> None:
    p = _write(tmp_path / "k", data)
    with pytest.raises(KekLoadError) as ei:
        _kek.PathKekSource(p, 1, allow_fifo=False).load()
    assert ei.value.reason == "kek_unavailable"


def test_missing_handle_unavailable(tmp_path: Path) -> None:
    with pytest.raises(KekLoadError):
        _kek.PathKekSource(tmp_path / "nope", 1, allow_fifo=True).load()


@pytest.mark.parametrize("mode", [0o600, 0o440, 0o644])
def test_file_bad_mode_refused(tmp_path: Path, mode: int) -> None:
    p = _write(tmp_path / "k", KEK_V1, mode)
    with pytest.raises(KekLoadError) as ei:
        _kek.PathKekSource(p, 1, allow_fifo=False).load()
    assert ei.value.reason == "kek_handle_permissions"


def test_symlink_refused(tmp_path: Path) -> None:
    real = _write(tmp_path / "k", KEK_V1)
    link = tmp_path / "l"
    link.symlink_to(real)
    with pytest.raises(KekLoadError):
        _kek.PathKekSource(link, 1, allow_fifo=False).load()


def test_fifo_read_once_and_ack(tmp_path: Path) -> None:
    d = tmp_path / "h"
    d.mkdir()
    fifo = d / "cv_kek"
    os.mkfifo(fifo, 0o600)
    (d / "handoff").write_text("nonce-1234abcd\n")
    ack = tmp_path / "ack"
    wfd = os.open(fifo, os.O_RDWR)  # keep a writer end open (non-blocking open for reader)
    os.write(wfd, KEK_V1)
    clock = iter([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 99.0, 99.0, 99.0])
    src = _kek.PathKekSource(fifo, 1, allow_fifo=True, timeout_s=1.0, ack_path=ack,
                             clock=lambda: next(clock))  # fmt: skip
    k = src.load()
    os.close(wfd)
    assert k.kcv() == kek().kcv()
    assert ack.read_text() == "nonce-1234abcd\n"
    assert (ack.stat().st_mode & 0o777) == 0o600


def test_fifo_timeout_unavailable(tmp_path: Path) -> None:
    fifo = tmp_path / "cv_kek"
    os.mkfifo(fifo, 0o600)
    wfd = os.open(fifo, os.O_RDWR)
    ticks = iter([0.0, 0.0, 0.5, 2.0])
    src = _kek.PathKekSource(fifo, 1, allow_fifo=True, timeout_s=1.0, clock=lambda: next(ticks))
    with pytest.raises(KekLoadError):
        src.load()
    os.close(wfd)


def test_fifo_not_allowed_for_file_source(tmp_path: Path) -> None:
    fifo = tmp_path / "f"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(KekLoadError) as ei:
        _kek.PathKekSource(fifo, 1, allow_fifo=False).load()
    assert ei.value.reason == "kek_handle_permissions"


@pytest.mark.parametrize("nonce", [None, "bad nonce!"])
def test_ack_failures_fail_closed(tmp_path: Path, nonce: str | None) -> None:
    p = _write(tmp_path / "k", KEK_V1)
    if nonce is not None:
        (tmp_path / "handoff").write_text(nonce)
    with pytest.raises(KekLoadError):
        _kek.PathKekSource(p, 1, allow_fifo=False, ack_path=tmp_path / "ack").load()


def test_duplicate_ack_is_refused(tmp_path: Path) -> None:
    p = _write(tmp_path / "k", KEK_V1)
    (tmp_path / "handoff").write_text("nonce-1234abcd")
    (tmp_path / "ack").write_text("x")
    with pytest.raises(KekLoadError):
        _kek.PathKekSource(p, 1, allow_fifo=False, ack_path=tmp_path / "ack").load()


def test_loaded_kek_never_renders_or_pickles() -> None:
    k = kek()
    assert repr(k) == "***" and str(k) == "***" and KEK_V1.hex() not in repr(k)
    with pytest.raises(TypeError):
        pickle.dumps(k)


def test_loaded_kek_wrong_length_rejected() -> None:
    with pytest.raises(KekLoadError):
        _kek.LoadedKek(bytearray(16), 1)


def test_loaded_kek_close_zeroes() -> None:
    buf = bytearray(KEK_V1)
    _kek.LoadedKek(buf, 1).close()
    assert buf == bytearray(32)


def test_kcv_constant_time_compare() -> None:
    k = kek()
    assert _kek.kcv_matches(k, k.kcv())
    assert not _kek.kcv_matches(k, bytes(8))


def test_unwrap_bound_to_credential_id() -> None:
    k = kek()
    from candleviewer.secrets import _envelope as env

    cid = uuid4()
    ref = k.wrap_dek(env.new_dek(), credential_id=cid)
    from cryptography.exceptions import InvalidTag

    with pytest.raises(InvalidTag):
        k.unwrap_dek(ref, credential_id=uuid4())


def test_harden_process_disables_core_dumps_and_dumpable() -> None:
    # Subprocess: PR_SET_DUMPABLE=0 must not leak into the pytest process.
    code = (
        "import resource;from candleviewer.secrets import _kek;_kek.harden_process();"
        "print(resource.getrlimit(resource.RLIMIT_CORE));"
        "print([l for l in open('/proc/self/status') if l.startswith('Uid')] and "
        "__import__('ctypes').CDLL(None).prctl(3,0,0,0,0))"  # PR_GET_DUMPABLE = 3
    )
    out = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, "-I", "-c", code],
        capture_output=True, text=True, timeout=30, check=True,
        cwd=Path(__file__).resolve().parents[3],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[3])},
    )  # fmt: skip
    assert out.stdout.split() == ["(0,", "0)", "0"]
