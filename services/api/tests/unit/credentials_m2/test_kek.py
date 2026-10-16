"""KEK loader: handle reads, permissions, live regular-file refusal, ack, KCV, hardening."""

from __future__ import annotations

import os
import pickle
import shutil
import tempfile
from functools import partial
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cryptography.exceptions import InvalidTag
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from candleviewer.secrets import _envelope as env
from candleviewer.secrets import _kek
from candleviewer.secrets.errors import KekLoadError
from tests.unit.credentials_m2._vectors import KEK_V1, kek


def _write(p: Path, data: bytes, mode: int = 0o400) -> Path:
    p.write_bytes(data)
    p.chmod(mode)
    return p


def _handoff(d: Path, nonce: str = "nonce-1234abcd", mode: int = 0o400) -> None:
    _write(d / "handoff", nonce.encode(), mode)


#: A source binds the process environment into each KEK it loads (#2338); live adds custody.
_demo_src = partial(_kek.PathKekSource, env_name="demo")
_live_src = partial(_kek.PathKekSource, env_name="live", live=True)


def test_none_source_always_fails() -> None:
    with pytest.raises(KekLoadError):
        _kek.NoKekSource().load()


def test_file_source_loads_exact_32(tmp_path: Path) -> None:
    k = _demo_src(_write(tmp_path / "k", KEK_V1), 1, allow_fifo=False).load()
    assert (k.version, k.env_name) == (1, "demo") and k.kcv() == kek().kcv()


@pytest.mark.parametrize("data", [b"", KEK_V1[:31], KEK_V1 + b"x"])
def test_file_source_wrong_length_unavailable(tmp_path: Path, data: bytes) -> None:
    with pytest.raises(KekLoadError) as ei:
        _demo_src(_write(tmp_path / "k", data), 1, allow_fifo=False).load()
    assert ei.value.reason == "kek_unavailable"


def test_missing_handle_unavailable(tmp_path: Path) -> None:
    with pytest.raises(KekLoadError):
        _demo_src(tmp_path / "nope", 1, allow_fifo=True).load()


@pytest.mark.parametrize("mode", [0o600, 0o440, 0o644])
def test_file_bad_mode_refused(tmp_path: Path, mode: int) -> None:
    with pytest.raises(KekLoadError) as ei:
        _demo_src(_write(tmp_path / "k", KEK_V1, mode), 1, allow_fifo=False).load()
    assert ei.value.reason == "kek_handle_permissions"


def test_symlink_refused(tmp_path: Path) -> None:
    real = _write(tmp_path / "k", KEK_V1)
    (tmp_path / "l").symlink_to(real)
    with pytest.raises(KekLoadError):
        _demo_src(tmp_path / "l", 1, allow_fifo=False).load()


def test_live_handle_regular_file_on_disk_refused() -> None:
    """A 0400 service-owned regular file on a *disk* filesystem is refused in live even under
    the systemd credential prefix check (fstatfs on the opened fd, not the path)."""
    home = Path.home()
    d = Path(tempfile.mkdtemp(dir=home))
    try:
        p = _write(d / "k", KEK_V1)
        fd = os.open(p, os.O_RDONLY)
        try:
            if _kek.fs_type(fd) in {0x01021994, 0x858458F6}:
                pytest.fail("test needs a disk-backed $HOME")
        finally:
            os.close(fd)
        with pytest.raises(KekLoadError) as ei:
            _live_src(p, 1, allow_fifo=True).load()
        assert ei.value.reason == "kek_handle_permissions"
    finally:
        shutil.rmtree(d)


def test_live_handle_tmpfs_outside_credentials_dir_refused(tmp_path: Path) -> None:
    p = _write(tmp_path / "k", KEK_V1)  # /tmp is tmpfs here, but not /run/credentials/
    with pytest.raises(KekLoadError):
        _live_src(p, 1, allow_fifo=True).load()


def test_live_handle_tmpfs_credentials_dir_accepted(monkeypatch: pytest.MonkeyPatch,
                                                    tmp_path: Path) -> None:  # fmt: skip
    p = _write(tmp_path / "k", KEK_V1)
    monkeypatch.setattr(_kek, "LIVE_FILE_PREFIX", str(tmp_path) + "/")
    monkeypatch.setattr(_kek, "fs_type", lambda fd: 0x01021994)
    k = _live_src(p, 1, allow_fifo=True).load()
    assert not k.is_fifo and k.env_name == "live" and k.kcv() == kek().kcv()


def test_fs_type_unknown_fd_is_none() -> None:
    assert _kek.fs_type(-1) is None


def _fifo(d: Path) -> tuple[Path, int]:
    fifo = d / "cv_kek"
    os.mkfifo(fifo, 0o600)
    return fifo, os.open(fifo, os.O_RDWR)  # keep a writer end so the reader never sees EOF


def test_live_fifo_read_once_then_ack(tmp_path: Path) -> None:
    d = tmp_path / "h"
    d.mkdir()
    fifo, wfd = _fifo(d)
    _handoff(d)
    os.write(wfd, KEK_V1)
    k = _live_src(fifo, 1, allow_fifo=True, timeout_s=1.0).load()
    os.close(wfd)
    assert k.is_fifo and k.kcv() == kek().kcv()
    ack = tmp_path / "ack"
    _kek.write_ack(_kek.read_handoff(d), ack)
    assert ack.read_text() == "nonce-1234abcd\n" and (ack.stat().st_mode & 0o777) == 0o600


def test_abandoned_load_zeroes_and_refuses(tmp_path: Path) -> None:
    src = _demo_src(_write(tmp_path / "k", KEK_V1), 1, allow_fifo=False)
    src.abandoned.set()
    with pytest.raises(KekLoadError):
        src.load()


def test_fifo_timeout_unavailable(tmp_path: Path) -> None:
    fifo, wfd = _fifo(tmp_path)
    ticks = iter([0.0, 0.0, 0.5, 2.0])
    src = _demo_src(fifo, 1, allow_fifo=True, timeout_s=1.0, clock=lambda: next(ticks))
    with pytest.raises(KekLoadError):
        src.load()
    os.close(wfd)


def test_fifo_not_allowed_for_file_source(tmp_path: Path) -> None:
    fifo, wfd = _fifo(tmp_path)
    with pytest.raises(KekLoadError) as ei:
        _demo_src(fifo, 1, allow_fifo=False).load()
    os.close(wfd)
    assert ei.value.reason == "kek_handle_permissions"


@pytest.mark.parametrize(
    ("nonce", "mode"), [(None, 0o400), ("bad nonce!", 0o400), ("x" * 300, 0o400),
                        ("nonce-1234abcd", 0o644)],
)  # fmt: skip
def test_ack_failures_fail_closed(tmp_path: Path, nonce: str | None, mode: int) -> None:
    if nonce is not None:
        _handoff(tmp_path, nonce, mode)
    with pytest.raises(KekLoadError):
        _kek.read_handoff(tmp_path)


def test_ack_handoff_symlink_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    _write(real, b"nonce-1234abcd")
    (tmp_path / "handoff").symlink_to(real)
    with pytest.raises(KekLoadError):
        _kek.read_handoff(tmp_path)


def test_duplicate_ack_is_refused(tmp_path: Path) -> None:
    (tmp_path / "ack").write_text("x")
    with pytest.raises(KekLoadError):
        _kek.write_ack("nonce-1234abcd", tmp_path / "ack")


def test_write_ack_refuses_invalid_nonce(tmp_path: Path) -> None:
    with pytest.raises(KekLoadError):
        _kek.write_ack("bad nonce!", tmp_path / "ack")
    assert not (tmp_path / "ack").exists()


_EXT4, _TMPFS, _RAMFS = 0xEF53, 0x01021994, 0x858458F6


@pytest.mark.parametrize(
    ("fs", "under_prefix", "accepted"),
    [
        (_TMPFS, True, True),
        (_RAMFS, True, True),
        (_TMPFS, False, False),
        (_EXT4, True, False),
        (_EXT4, False, False),
    ],
)
def test_live_regular_file_rule_is_ram_and_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fs: int, under_prefix: bool, accepted: bool
) -> None:
    """Both halves pinned independently of the host's /tmp: fs_type and the prefix are faked."""
    p = _write(tmp_path / "k", KEK_V1)
    monkeypatch.setattr(_kek, "fs_type", lambda fd: fs)
    prefix = str(tmp_path) + "/" if under_prefix else "/run/credentials/"
    monkeypatch.setattr(_kek, "LIVE_FILE_PREFIX", prefix)
    src = _live_src(p, 1, allow_fifo=True)
    if accepted:
        assert src.load().kcv() == kek().kcv()
    else:
        with pytest.raises(KekLoadError) as ei:
            src.load()
        assert ei.value.reason == "kek_handle_permissions"


def test_live_prefix_is_checked_on_the_resolved_fd_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`/run/credentials/../../elsewhere` must not pass the prefix half by string match."""
    inside = tmp_path / "creds"
    inside.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    _write(outside / "k", KEK_V1)
    monkeypatch.setattr(_kek, "fs_type", lambda fd: _TMPFS)
    monkeypatch.setattr(_kek, "LIVE_FILE_PREFIX", str(inside) + "/")
    sneaky = inside / ".." / "elsewhere" / "k"
    with pytest.raises(KekLoadError):
        _live_src(sneaky, 1, allow_fifo=True).load()


def test_loaded_kek_never_renders_or_pickles() -> None:
    k = kek()
    assert repr(k) == "***" and str(k) == "***" and KEK_V1.hex() not in repr(k)
    with pytest.raises(TypeError):
        pickle.dumps(k)


def test_loaded_kek_wrong_length_rejected() -> None:
    with pytest.raises(KekLoadError):
        _kek.LoadedKek(bytearray(16), 1, env_name="demo")


def test_loaded_kek_close_zeroes() -> None:
    buf = bytearray(KEK_V1)
    _kek.LoadedKek(buf, 1, env_name="demo").close()
    assert buf == bytearray(32)


def test_loaded_kek_unknown_environment_refused_and_zeroed() -> None:
    buf = bytearray(KEK_V1)
    with pytest.raises(KekLoadError):
        _kek.LoadedKek(buf, 1, env_name="prod")
    assert buf == bytearray(32)


def test_wrap_is_v2_and_round_trips_in_its_environment() -> None:
    cid, dek = uuid4(), env.new_dek()
    ref = kek(env="live").wrap_dek(dek, credential_id=cid)
    assert ref.startswith("v2:") and kek(env="live").unwrap_dek(ref, credential_id=cid) == dek


def test_legacy_v1_dek_ref_refused() -> None:
    cid = uuid4()
    body = kek().wrap_dek(env.new_dek(), credential_id=cid).partition(":")[2]
    with pytest.raises(ValueError, match="unsupported dek_ref"):
        kek().unwrap_dek("v1:" + body, credential_id=cid)


@settings(max_examples=60, deadline=None)
@given(raw=st.binary(min_size=32, max_size=32), other=st.binary(min_size=32, max_size=32),
       envs=st.permutations(sorted(env.ENVIRONMENTS)), case=st.sampled_from(["env", "kek", "both"]),
       version=st.integers(min_value=1, max_value=10_000), cid=st.uuids())  # fmt: skip
def test_wrap_never_opens_under_another_environment_or_kek(
    raw: bytes, other: bytes, envs: list[str], case: str, version: int, cid: UUID
) -> None:
    assume(raw != other)
    wrapper = _kek.LoadedKek(bytearray(raw), version, env_name=envs[0])
    ref = wrapper.wrap_dek(env.new_dek(), credential_id=cid)
    opener = _kek.LoadedKek(
        bytearray(raw if case == "env" else other),
        version,
        env_name=envs[0] if case == "kek" else envs[1],
    )
    with pytest.raises(InvalidTag):
        opener.unwrap_dek(ref, credential_id=cid)


def test_kcv_constant_time_compare() -> None:
    k = kek()
    assert _kek.kcv_matches(k, k.kcv()) and not _kek.kcv_matches(k, bytes(8))


def test_unwrap_bound_to_credential_id_and_version() -> None:
    cid = uuid4()
    ref = kek().wrap_dek(env.new_dek(), credential_id=cid)
    with pytest.raises(InvalidTag):
        kek().unwrap_dek(ref, credential_id=uuid4())
    with pytest.raises(InvalidTag):
        kek(KEK_V1, 2).unwrap_dek(ref, credential_id=cid)


def test_live_regular_file_real_fstatfs_on_dev_shm(monkeypatch: pytest.MonkeyPatch) -> None:
    """One real measurement (no faked fs_type): /dev/shm is tmpfs on Linux CI runners."""
    shm = Path("/dev") / "shm"  # tmpfs mount, not a temp-file location (mkdtemp below)
    if not shm.is_dir():
        pytest.fail("no shm mount: the live RAM-backed rule cannot be measured here")
    d = Path(tempfile.mkdtemp(dir=shm))
    try:
        p = _write(d / "k", KEK_V1)
        monkeypatch.setattr(_kek, "LIVE_FILE_PREFIX", str(d) + "/")
        assert _live_src(p, 1, allow_fifo=True).load().kcv() == kek().kcv()
    finally:
        shutil.rmtree(d)
