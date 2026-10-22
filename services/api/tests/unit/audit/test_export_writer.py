"""The audit export writer (#889 S8, `24-internal-schemas.md` §15.7): the lines pinned byte for byte
(the header, entries with NULLs, non-ASCII text and control characters, one outside the window, an
empty span, and §15.7's worked example), the deterministic gzip, the digest, the file's modes and
links, the caps, the cleanup and the off-loop file steps. An in-memory read port and `tmp_path`:
no database, no network, no sleeps."""

from __future__ import annotations

import asyncio
import errno
import gzip
import hashlib
import json
import os
import stat
import struct
import threading
import uuid
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from audit_fakes import FakeAuditRepository

from candleviewer.audit import export
from candleviewer.audit.export import (
    EXPORT_DIR,
    ExportFile,
    ExportFileFailed,
    ExportPlan,
    ExportSpanChanged,
    ExportTooLarge,
    write_export,
)
from candleviewer.audit.query import _canonical_hash
from candleviewer.observability.context import thread_future
from candleviewer.settings import Environment

_FROM, _TO = datetime(2026, 10, 21, 12, tzinfo=UTC), datetime(2026, 10, 21, 13, tzinfo=UTC)
_PUBLIC = "A" * 43 + "="  # base64 of 32 zero bytes: a test key, never a real one
_KEY_ID = "cv-audit-export-v1:66687aadf862bd77"  # the first 16 hex of its SHA-256
_JOB = uuid.UUID(int=1)
_REASON = 'q" s\\ \b\f\n\r\t\x1b \x7f\u2028\u2029 /'
_GZIP_HEADER = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"  # FLG 0, MTIME 0, XFL 2, OS 255
_DOC = Path(__file__).resolve().parents[5] / "docs/plan/24-internal-schemas.md"
#: The worked example's entry as `audit_field()` frames it: `prev_hash`, then the hashed columns.
_FRAMED = (
    "64:" + "0" * 64 + "36:00000000-0000-4000-8000-0000000000a13:Zo\u00eb--10:auth.login--7:success"
    '4:info--13:{"mfa": true}--29:2026-10-21T12:00:00.000000+00'
)


def _record(n: int, ts: str, **fields: Any) -> dict[str, Any]:
    base = {"actor_label": "system", "outcome": "success", "severity": "info", "event_ts": ts}
    return {**base, "record_id": f"00000000-0000-4000-8000-{n:012d}", **fields}


#: At `from` (in the window), at `to` (out of it), between them (in).
_ROWS = [
    _record(1, "2026-10-21T12:00:00+00:00", actor_label="Zoë", action="auth.login",
            actor_user_id="00000000-0000-4000-8000-0000000000a1", after_state={"mfa": True}),
    _record(2, "2026-10-21T13:00:00+00:00", action="orders.submit", outcome="denied",
            severity="warning", object_kind="order", object_id="o-1", object_label="BTC 注文",
            reason=_REASON, env="demo"),
    _record(3, "2026-10-21T12:30:00.000001+00:00", actor_ip="203.0.113.7/32", action="auth.logout"),
]  # fmt: skip
_HEAD_SOLO = (
    '{"anchor_hash":"0000000000000000000000000000000000000000000000000000000000000000","environ'
    'ment":"demo","first_id":1,"format":"cv.audit.export.v1","from":"2026-10-21T12:00:00.000000'
    'Z","head_hash":"7258e4839c214d468e05682582186d1a02cd65c513e992f6a8080e7b79461ab2","head_id'
    '":1,"key_id":"cv-audit-export-v1:66687aadf862bd77","last_id":1,"public_key":"AAAAAAAAAAAAA'
    'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=","row_count":1,"to":"2026-10-21T13:00:00.000000Z"}\n'
)
_HEAD_ALL = (
    '{"anchor_hash":"0000000000000000000000000000000000000000000000000000000000000000","environ'
    'ment":"demo","first_id":1,"format":"cv.audit.export.v1","from":"2026-10-21T12:00:00.000000'
    'Z","head_hash":"b465fe51fa73a634d4b38fb26180e41b309e3fe2ecec85b6be4b3017fda6970b","head_id'
    '":3,"key_id":"cv-audit-export-v1:66687aadf862bd77","last_id":3,"public_key":"AAAAAAAAAAAAA'
    'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=","row_count":3,"to":"2026-10-21T13:00:00.000000Z"}\n'
)
_HEAD_EMPTY = (
    '{"anchor_hash":null,"environment":"demo","first_id":null,"format":"cv.audit.export.v1","fr'
    'om":"2026-10-21T12:00:00.000000Z","head_hash":"b465fe51fa73a634d4b38fb26180e41b309e3fe2ece'
    'c85b6be4b3017fda6970b","head_id":3,"key_id":"cv-audit-export-v1:66687aadf862bd77","last_id'
    '":null,"public_key":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=","row_count":0,"to":"202'
    '6-10-21T13:00:00.000000Z"}\n'
)
_E1 = (
    '{"action":"auth.login","actor_ip":null,"actor_label":"Zoë","actor_user_id":"00000000-0000-'
    '4000-8000-0000000000a1","after_state":"{\\"mfa\\": true}","before_state":null,"entry_hash"'
    ':"7258e4839c214d468e05682582186d1a02cd65c513e992f6a8080e7b79461ab2","env":null,"event_ts":'
    '"2026-10-21T12:00:00.000000+00","id":1,"in_window":true,"object_id":null,"object_kind":nul'
    'l,"object_label":null,"outcome":"success","prev_hash":"00000000000000000000000000000000000'
    '00000000000000000000000000000","reason":null,"record_id":"00000000-0000-4000-8000-00000000'
    '0001","request_id":null,"session_id":null,"severity":"info"}\n'
)
_E2 = (
    '{"action":"orders.submit","actor_ip":null,"actor_label":"system","actor_user_id":null,"aft'
    'er_state":null,"before_state":null,"entry_hash":"213eee6c78f2846cbb3bc09f9ae5d74bc95feaa40'
    '532f3f8d0634f65becf02f1","env":"demo","event_ts":"2026-10-21T13:00:00.000000+00","id":2,"i'
    'n_window":false,"object_id":"o-1","object_kind":"order","object_label":"BTC 注文","outcome":'
    '"denied","prev_hash":"7258e4839c214d468e05682582186d1a02cd65c513e992f6a8080e7b79461ab2","r'
    'eason":"q\\" s\\\\ \\b\\f\\n\\r\\t\\u001b \x7f\u2028\u2029 /","record_id":"00000000-0000-4'
    '000-8000-000000000002","request_id":null,"session_id":null,"severity":"warning"}\n'
)
_E3 = (
    '{"action":"auth.logout","actor_ip":"203.0.113.7/32","actor_label":"system","actor_user_id"'
    ':null,"after_state":null,"before_state":null,"entry_hash":"b465fe51fa73a634d4b38fb26180e41'
    'b309e3fe2ecec85b6be4b3017fda6970b","env":null,"event_ts":"2026-10-21T12:30:00.000001+00","'
    'id":3,"in_window":true,"object_id":null,"object_kind":null,"object_label":null,"outcome":"'
    'success","prev_hash":"213eee6c78f2846cbb3bc09f9ae5d74bc95feaa40532f3f8d0634f65becf02f1","r'
    'eason":null,"record_id":"00000000-0000-4000-8000-000000000003","request_id":null,"session_'
    'id":null,"severity":"info"}\n'
)
_ALL = (_HEAD_ALL + _E1 + _E2 + _E3).encode()
#: On ids 1, 3 and 5, a first id of 2 with id 3's anchor: the first entry read differs by its id.
_ID_ALONE = {"first_id": 2, "anchor_hash": json.loads(_E1)["entry_hash"]}


async def _filled(n: int = 3, gap: int = 0) -> FakeAuditRepository:
    repo = FakeAuditRepository()
    for row in _ROWS[:n]:
        await repo.insert(row)
        repo.burn_ids(gap)  # `gap=1`: ids 1, 3 and 5, as rolled-back inserts leave them
    return repo


def _plan(repo: FakeAuditRepository, **change: Any) -> ExportPlan:
    head, span = repo.rows[-1], {"first_id": 1, "anchor_hash": "0" * 64, "compressed": False}
    plan: dict[str, Any] = {"from_ts": _FROM, "to_ts": _TO, "environment": Environment.DEMO}
    plan |= {"head_id": head["id"], "head_hash": head["entry_hash"], "last_id": head["id"]}
    return ExportPlan(**plan | span | {"key_id": _KEY_ID, "public_key": _PUBLIC} | change)


async def _write(repo: FakeAuditRepository, root: Path, plan: ExportPlan, **kw: Any) -> bytes:
    done = await write_export(plan, repo, data_dir=root, job_id=_JOB, **kw)
    data = (root / EXPORT_DIR / done.name).read_bytes()
    assert (done.size_bytes, done.sha256) == (len(data), hashlib.sha256(data).hexdigest())
    return data


def _left(root: Path) -> list[str]:
    return sorted(os.listdir(root / EXPORT_DIR))


async def test_the_worked_example_of_15_7_is_pinned_byte_for_byte(tmp_path: Path) -> None:
    repo = await _filled(1)
    done = await write_export(_plan(repo), repo, data_dir=tmp_path, job_id=_JOB)
    path = tmp_path / EXPORT_DIR / f"{_JOB}.ndjson"
    assert path.read_bytes() == (_HEAD_SOLO + _E1).encode()
    digest = "a5c3cb72b08ae1216483a9d68799590a4d49a7f4c0cd0e4106a298b9a9499281"
    assert done == ExportFile(path.name, 1043, digest, 1, 1, 1)
    assert hashlib.sha256(_FRAMED.encode()).hexdigest() == json.loads(_E1)["entry_hash"]
    shown = _DOC.read_text(encoding="utf-8").split("**Worked example (S8).**", 1)[1]
    shown = shown.split("**Signature.**", 1)[0]  # the doc shows these very bytes
    assert all(part in shown for part in (_HEAD_SOLO + _E1, _FRAMED, digest, "1043 bytes"))


@pytest.mark.parametrize("compressed", [False, True])
async def test_the_file_is_0600_in_a_0700_directory(tmp_path: Path, compressed: bool) -> None:
    repo, directory = await _filled(), tmp_path / EXPORT_DIR
    await _write(repo, tmp_path, _plan(repo, compressed=compressed))
    (name,) = _left(tmp_path)
    assert [stat.S_IMODE(p.stat().st_mode) for p in (directory / name, directory)] == [0o600, 0o700]


async def test_a_span_s_lines_are_pinned_and_every_entry_hash_and_link_recomputes(
    tmp_path: Path,
) -> None:
    repo = await _filled()
    data = await _write(repo, tmp_path, _plan(repo), batch_size=1)
    assert data == _ALL and repo.export_calls == [(0, 3, 1), (1, 3, 1), (2, 3, 1)]
    header, *entries = (json.loads(line) for line in data.split(b"\n")[:-1])
    prev = header["anchor_hash"]
    for entry in entries:  # §3.10.1's `audit_field()` framing, then SHA-256
        assert entry["prev_hash"] == prev and _canonical_hash(prev, entry) == entry["entry_hash"]
        prev = entry["entry_hash"]
    assert [e["in_window"] for e in entries] == [True, False, True]


@pytest.mark.parametrize(
    ("max_bytes", "max_entry", "calls"),
    [
        (1, None, [(0, 4, 256), (1, 4, 2), (2, 4, 2), (3, 4, 2)]),  # one row a batch
        (None, 1_000, [(0, 4, 256), (3, 4, 6)]),  # the large entry ends a batch, then alone
    ],
)
async def test_a_short_batch_is_not_the_end_of_the_span(
    tmp_path: Path, max_bytes: int | None, max_entry: int | None, calls: list[tuple[int, int, int]]
) -> None:
    """The read port may stop a batch short, on its byte budget or before an entry over its
    per-entry cap, which then comes alone. The walk goes on to the last id, asking for twice the
    rows the last batch held, and writes the file that uncut batches give."""
    repo = await _filled()
    await repo.insert(
        _record(4, "2026-10-21T12:45:00+00:00", action="auth.login", reason="r" * 5000)
    )
    whole = await _write(repo, tmp_path / "whole", _plan(repo))
    repo.max_bytes, repo.max_entry, repo.export_calls = max_bytes, max_entry, []
    assert await _write(repo, tmp_path / "cut", _plan(repo)) == whole
    assert repo.export_calls == calls
    assert (export.EXPORT_BATCH_SIZE, export.FIRST_BATCH) == (10_000, 256)  # the walk's batches


async def test_a_span_with_id_gaps_is_walked_by_id_and_counted_by_entry(tmp_path: Path) -> None:
    repo = await _filled(gap=1)
    data = await _write(repo, tmp_path, _plan(repo), batch_size=1)  # the span 1 to 5
    header, *entries = (json.loads(line) for line in data.splitlines())
    assert (header["row_count"], [entry["id"] for entry in entries]) == (3, [1, 3, 5])
    assert repo.export_calls == [(0, 5, 1), (1, 5, 1), (3, 5, 1)]


async def test_an_empty_span_is_its_header_alone_and_reads_nothing(tmp_path: Path) -> None:
    repo = await _filled()
    for compressed in (False, True):  # compressed: the gzip of the header alone
        plan = _plan(repo, first_id=None, last_id=None, anchor_hash=None, compressed=compressed)
        data = await _write(repo, tmp_path / str(compressed), plan)
        assert (gzip.decompress(data) if compressed else data) == _HEAD_EMPTY.encode()
    assert repo.export_calls == []


async def test_the_gzip_is_one_deterministic_member_of_the_plain_file(tmp_path: Path) -> None:
    repo = await _filled()
    plan = _plan(repo, compressed=True)
    first = await _write(repo, tmp_path / "a", plan, batch_size=1)
    assert await _write(repo, tmp_path / "b", plan) == first  # other batches, the same bytes
    assert first[:10] == _GZIP_HEADER
    deflate = zlib.compressobj(9, zlib.DEFLATED, -15)
    body = deflate.compress(_ALL) + deflate.flush()  # one stream: no flush between batches
    assert first[10:] == body + struct.pack("<II", zlib.crc32(_ALL), len(_ALL))
    assert gzip.decompress(first) == _ALL


@pytest.mark.parametrize("planted", [f".{_JOB}.ndjson.tmp", f"{_JOB}.ndjson"])
async def test_a_link_planted_at_the_temporary_or_the_file_name_is_refused_and_not_followed(
    tmp_path: Path, planted: str
) -> None:
    repo, target = await _filled(), tmp_path / "target"
    target.write_bytes(b"theirs")
    (tmp_path / EXPORT_DIR).mkdir(mode=0o700)
    (tmp_path / EXPORT_DIR / planted).symlink_to(target)
    with pytest.raises(ExportFileFailed) as refused:
        await _write(repo, tmp_path, _plan(repo))
    failed = refused.value
    assert failed.errno == errno.EEXIST and planted not in f"{failed}{failed.args}"
    assert target.read_bytes() == b"theirs" and _left(tmp_path) == [planted]


async def test_a_link_planted_at_the_directory_is_refused_and_not_followed(tmp_path: Path) -> None:
    repo, theirs = await _filled(), tmp_path / "theirs"
    theirs.mkdir()
    theirs.chmod(0o755)  # whatever the umask
    (tmp_path / EXPORT_DIR).symlink_to(theirs)
    with pytest.raises(ExportFileFailed) as refused:  # `O_NOFOLLOW`: never followed
        await write_export(_plan(repo), repo, data_dir=tmp_path, job_id=_JOB)
    failed = refused.value  # raised past the handler: neither cause nor context holds the path
    assert failed.errno in (errno.ELOOP, errno.ENOTDIR) and failed.__context__ is None
    assert failed.code == "internal_error" and EXPORT_DIR not in f"{failed}{failed.args}"
    assert os.listdir(theirs) == [] and stat.S_IMODE(theirs.stat().st_mode) == 0o755


async def test_the_row_cap_fails_before_anything_is_written(tmp_path: Path) -> None:
    repo = await _filled()
    assert await _write(repo, tmp_path / "a", _plan(repo), max_rows=3) == _ALL  # at the cap
    repo.export_calls.clear()
    with pytest.raises(ExportTooLarge) as refused:
        await _write(repo, tmp_path / "b", _plan(repo), max_rows=2)
    assert refused.value.code == "export_too_large"
    assert repo.export_calls == [] and not (tmp_path / "b" / EXPORT_DIR).exists()


async def test_the_byte_cap_stops_at_the_write_that_would_pass_it(tmp_path: Path) -> None:
    repo = await _filled()
    assert await _write(repo, tmp_path / "a", _plan(repo), max_bytes=len(_ALL)) == _ALL
    repo.export_calls.clear()
    cap = len(_HEAD_ALL.encode() + _E1.encode()) + 1  # the header and one entry fit
    with pytest.raises(ExportTooLarge):
        await _write(repo, tmp_path / "b", _plan(repo), max_bytes=cap, batch_size=1)
    assert repo.export_calls == [(0, 3, 1), (1, 3, 1)] and _left(tmp_path / "b") == []
    gz = _plan(repo, compressed=True)
    size = len(await _write(repo, tmp_path / "c", gz))
    repo.export_calls.clear()
    with pytest.raises(ExportTooLarge):  # deflate holds the entries back: `finish` writes them
        await _write(repo, tmp_path / "d", gz, max_bytes=size - 1, batch_size=1)
    assert repo.export_calls == [(0, 3, 1), (1, 3, 1), (2, 3, 1)] and _left(tmp_path / "d") == []


async def test_a_failure_mid_write_leaves_nothing_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = await _filled()
    read = repo.fetch_export_batch

    async def second_fails(**kw: Any) -> list[tuple[Any, ...]]:
        if repo.export_calls:
            raise TimeoutError("audit read exceeded its time budget")
        return await read(**kw)

    monkeypatch.setattr(repo, "fetch_export_batch", second_fails)
    with pytest.raises(TimeoutError):
        await _write(repo, tmp_path, _plan(repo, compressed=True), batch_size=1)
    assert _left(tmp_path) == []


async def test_the_linked_file_is_removed_though_the_temporary_name_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unlink, repo, tmp = os.unlink, await _filled(), f".{_JOB}.ndjson.tmp"

    def denied(name: str, **kw: Any) -> None:
        if name == tmp:
            raise PermissionError(errno.EACCES, "denied")
        unlink(name, **kw)

    monkeypatch.setattr(os, "unlink", denied)
    with pytest.raises(ExportFileFailed) as failed:
        await _write(repo, tmp_path, _plan(repo))
    assert failed.value.errno == errno.EACCES and _left(tmp_path) == [tmp]


async def test_the_file_is_synced_linked_and_unlinked_then_its_directory_synced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = mock.Mock()
    for name in ("fsync", "link", "unlink"):
        calls.attach_mock(mock.Mock(wraps=getattr(os, name)), name)
        monkeypatch.setattr(os, name, getattr(calls, name))
    repo = await _filled()
    await _write(repo, tmp_path, _plan(repo))
    fsync, link, unlink, synced = calls.mock_calls
    assert [fsync[0], link[0], unlink[0], synced[0]] == ["fsync", "link", "unlink", "fsync"]
    assert link.args[0] == unlink.args[0] == f".{_JOB}.ndjson.tmp"
    assert synced.args == (unlink.kwargs["dir_fd"],) != fsync.args  # the directory, not the file


@pytest.mark.parametrize(
    "change",
    [{"anchor_hash": "f" * 64}, _ID_ALONE, {"last_id": 4}, {"count": 2}, {"count": 4}],
)
async def test_a_read_that_is_not_the_planned_span_fails_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    repo, plan = await _filled(gap=1), {k: v for k, v in change.items() if k != "count"}

    async def counted(**_: Any) -> int:  # the span the count saw is not the one read
        return int(change["count"])

    if "count" in change:
        monkeypatch.setattr(repo, "count_export_span", counted)
    with pytest.raises(ExportSpanChanged) as failed:
        await _write(repo, tmp_path, _plan(repo, **plan))
    assert failed.value.code == "internal_error" and _left(tmp_path) == []


async def test_every_file_step_runs_off_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steps: list[str] = []
    threads: set[int] = set()

    def spy(step: Any, *args: Any) -> asyncio.Future[Any]:
        def traced(*inner: Any) -> Any:
            threads.add(threading.get_ident())
            return step(*inner)

        steps.append(step.__name__)
        return thread_future(traced, *args)

    monkeypatch.setattr(export, "thread_future", spy)
    repo = await _filled()
    assert await _write(repo, tmp_path, _plan(repo), batch_size=2) == _ALL
    assert steps == ["open", "write", "entries", "entries", "finish", "close"]
    assert threads and threading.get_ident() not in threads


async def test_a_cancel_waits_for_the_running_step_then_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop, entered, release = asyncio.get_running_loop(), asyncio.Event(), threading.Event()
    entries, steps = export._Sink.entries, []

    def held(sink: Any, *args: Any) -> None:
        loop.call_soon_threadsafe(entered.set)
        release.wait(10)  # a guard against a hang, never a timing
        entries(sink, *args)

    def recorded(step: Any, *args: Any) -> asyncio.Future[Any]:
        steps.append(step.__name__)
        return thread_future(step, *args)

    monkeypatch.setattr(export._Sink, "entries", held)
    monkeypatch.setattr(export, "thread_future", recorded)
    repo = await _filled()
    task = asyncio.create_task(_write(repo, tmp_path, _plan(repo)))
    await entered.wait()
    for other in asyncio.all_tasks() - {asyncio.current_task()}:  # as `asyncio.run` tears down
        other.cancel()
    try:
        for _ in range(5):  # loop turns, no wall-clock wait: a cleanup would have started by now
            await asyncio.sleep(0)
        assert steps[-1] == "held" and _left(tmp_path) == [f".{_JOB}.ndjson.tmp"]
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert steps[-1] == "close" and _left(tmp_path) == []


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ({"anchor_hash": None}, "or none"),
        ({"from_ts": datetime(2026, 10, 21, 12)}, "timezone-aware"),
        ({"to_ts": datetime(2026, 10, 21, 13)}, "timezone-aware"),
        ({"to_ts": _FROM}, "start before it ends"),  # 22: `from` earlier than `to`
        ({"first_id": 0}, "1 <= first_id <= last_id <= head_id"),  # before id 1
        ({"first_id": 3, "last_id": 2}, "1 <= first_id <= last_id <= head_id"),  # out of order
        ({"last_id": 4}, "1 <= first_id <= last_id <= head_id"),  # past the head
    ],
)
async def test_an_inconsistent_plan_is_refused(change: dict[str, Any], refusal: str) -> None:
    repo = await _filled()
    with pytest.raises(ValueError, match=refusal):
        _plan(repo, **change)
