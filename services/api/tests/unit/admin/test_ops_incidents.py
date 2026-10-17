"""Unit (E42-T05): `AdminIncidentsService`, the read model behind `GET /admin/incidents`. Time is
injected and nothing sleeps: a hung store is cut by a 10 ms budget that only a hang can reach."""

from __future__ import annotations

import base64
import json
import threading
from datetime import timedelta
from typing import Any

import pytest
from structlog.testing import capture_logs

import candleviewer.admin.ops.incidents as incidents_mod
from candleviewer.admin.errors import InvalidCursor, OpsNotWired, OpsUnavailable
from candleviewer.admin.ops.incidents import (
    CURSOR_TTL_S,
    DETAIL_MAX,
    OFFLOAD_ROWS,
    TITLE_MAX,
    AdminIncidentsService,
    decode_cursor,
)
from candleviewer.storage.errors import StorageTierUnavailable
from tests.unit.admin._ops_fakes import NOW, Store, row

#: Built by concatenation (as tests/security does) so no scanner sees a credential literal.
_KEY = "Zq9" + "x" * 20 + "AbCd"
#: 22 letters: the shape `redact_text` masks as a key, with nothing key-like in it.
_PLACEHOLDER = "PLACEHOLDER" * 2


def _service(store: Store | None, **kw: Any) -> AdminIncidentsService:
    return AdminIncidentsService(store, now=lambda: NOW, **kw)


async def test_cursors_visit_every_incident_once_newest_first_with_ties_broken_by_id() -> None:
    tied = row(2).last_seen_at
    store = Store([row(1), row(2), row(3, last_seen_at=tied), row(4), row(5, last_seen_at=tied)])
    seen: list[int] = []
    cursor: str | None = None
    while True:
        page = await _service(store).page(status=None, cursor=cursor, limit=2)
        seen += [r.id.int for r in page.items]
        if (cursor := page.next_cursor) is None:
            break
    assert seen == [1, 5, 3, 2, 4]  # 5, 3 and 2 share a time: the larger id first
    assert [call[2] for call in store.calls] == [3, 3, 3]  # one extra row says "more"


async def test_the_status_filter_reaches_the_store_and_an_empty_store_is_an_empty_page() -> None:
    store = Store([row(1), row(2, status="resolved", resolved_at=NOW)])
    page = await _service(store).page(status="resolved", cursor=None, limit=10)
    assert [r.id.int for r in page.items] == [2] and store.calls[0][0] == "resolved"
    empty = await _service(Store()).page(status=None, cursor=None, limit=10)
    assert (empty.items, empty.next_cursor) == ((), None)


async def test_a_cursor_is_bound_to_the_filter_it_was_issued_for() -> None:
    service = _service(Store([row(n) for n in range(1, 4)]))
    cursor = (await service.page(status="open", cursor=None, limit=1)).next_cursor
    assert cursor is not None
    for status in (None, "resolved"):  # never another listing's position
        with pytest.raises(InvalidCursor):
            await service.page(status=status, cursor=cursor, limit=1)
    assert (await service.page(status="open", cursor=cursor, limit=1)).items[0].id.int == 2


async def test_a_cursor_lives_for_an_hour_on_the_services_clock() -> None:
    clock = [NOW]
    service = AdminIncidentsService(Store([row(1), row(2)]), now=lambda: clock[0])
    cursor = (await service.page(status=None, cursor=None, limit=1)).next_cursor
    clock[0] = NOW + timedelta(seconds=CURSOR_TTL_S)
    await service.page(status=None, cursor=cursor, limit=1)  # exactly an hour: still good
    clock[0] += timedelta(seconds=1)
    with pytest.raises(InvalidCursor):
        await service.page(status=None, cursor=cursor, limit=1)


_GOOD: dict[str, Any] = {
    "v": 1,
    "s": "open",
    "t": NOW.isoformat(),
    "i": str(row(1).id),
    "iat": int(NOW.timestamp()),
}


def _encode(raw: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(raw).encode()).decode().rstrip("=")


def _forged(**over: Any) -> str:
    return _encode(_GOOD | over)


@pytest.mark.parametrize(
    "cursor",
    [
        base64.urlsafe_b64encode(b"not json").decode(),
        _forged(v=2),
        _forged(t="2026-10-15T09:00:00"),  # no zone
        _forged(i="not-a-uuid"),
        _forged(iat=True),
        _forged(iat=int(NOW.timestamp()) + 1),  # issued in the future: forged
        _forged(pad="x" * 600),  # well-formed, but over the contract's 512 characters
        _encode({}),  # valid JSON that is not a cursor: every key missing
        _encode([]),
        _encode(1),
        _encode({k: v for k, v in _GOOD.items() if k != "iat"}),
        _forged(t="0001-01-01T00:00:00+01:00"),  # an instant before year 1 once in UTC
        _forged(t="9999-12-31T23:59:59-01:00"),  # and one after year 9999
    ],
    ids=(
        "not-json version naive-time bad-uuid bool-iat future long "
        "empty-object empty-list number no-iat before-year-1 after-year-9999"
    ).split(),
)
def test_a_malformed_cursor_is_refused_without_echoing_it(cursor: str) -> None:
    with pytest.raises(InvalidCursor) as refused:
        decode_cursor(cursor, "open", int(NOW.timestamp()))
    assert cursor not in str(refused.value)


async def test_title_and_detail_are_redacted_again_and_cut_to_the_contract_lengths() -> None:
    leaky = row(1, title=f"api_key={_KEY}", detail="d" * 2500)
    long = row(2, title="t" * 300, detail=f"token {_KEY}")
    page = await _service(Store([leaky, long, row(3, detail=None)])).page(
        status=None, cursor=None, limit=10
    )
    first, second, third = page.items
    assert (first.title, len(first.detail or "")) == ("[redacted:key-shape]", 2000)
    assert (len(second.title or ""), second.detail) == (200, "[redacted:key-shape]")
    assert third.detail is None  # a stored NULL stays null: nothing was read, nothing is made up
    assert _KEY not in repr(page)


async def test_a_secret_straddling_the_cut_is_masked_whole_because_redaction_runs_first() -> None:
    # The key starts 10 characters before each cap. Cut first, the 10 left are too short for
    # `redact_text` to match and they would leave as a stub of the secret.
    straddling = row(
        1,
        title="t" * (TITLE_MAX - 11) + " " + _PLACEHOLDER,
        detail="d" * (DETAIL_MAX - 11) + " " + _PLACEHOLDER,
    )
    page = await _service(Store([straddling])).page(status=None, cursor=None, limit=10)
    assert (page.items[0].title, page.items[0].detail) == ("[redacted:key-shape]",) * 2


async def test_a_text_that_cannot_be_redacted_is_left_out_not_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_: str) -> str:
        raise RuntimeError(_KEY)

    monkeypatch.setattr(incidents_mod, "redact_text", broken)
    with capture_logs() as logs:
        page = await _service(Store([row(1)])).page(status=None, cursor=None, limit=10)
    assert (page.items[0].title, page.items[0].detail) == (None, None)
    assert _KEY not in repr(logs) and logs[0]["error"] == "RuntimeError"


@pytest.mark.parametrize(
    ("rows", "off_loop"),
    [(OFFLOAD_ROWS, False), (OFFLOAD_ROWS + 1, True)],
    ids=["fifty", "fifty-one"],
)
async def test_a_page_of_more_than_fifty_rows_is_redacted_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch, rows: int, off_loop: bool
) -> None:
    ran_on: set[int] = set()

    def spy(text: str) -> str:
        ran_on.add(threading.get_ident())
        return text

    monkeypatch.setattr(incidents_mod, "redact_text", spy)
    store = Store([row(n) for n in range(1, rows + 1)])
    page = await _service(store).page(status=None, cursor=None, limit=rows)
    assert len(page.items) == rows and ran_on  # the whole page was redacted, title and detail
    assert (threading.get_ident() in ran_on) is not off_loop


async def test_no_store_is_not_wired() -> None:
    with pytest.raises(OpsNotWired):
        await _service(None).page(status=None, cursor=None, limit=10)


@pytest.mark.parametrize(
    "store",
    [
        Store(error=StorageTierUnavailable(f"password={_KEY}")),
        Store(error=TimeoutError(_KEY)),
        Store(hang=True),
    ],
    ids=["tier-down", "timeout", "hang"],
)
async def test_a_store_that_fails_or_hangs_is_unavailable_never_an_empty_page(
    store: Store,
) -> None:
    with capture_logs() as logs, pytest.raises(OpsUnavailable) as refused:
        await _service(store, budget_s=0.01).page(status=None, cursor=None, limit=10)
    assert str(refused.value) == "incidents: store unavailable"  # a fixed literal
    assert refused.value.__cause__ is None and _KEY not in repr(logs)  # only the class is logged


async def test_a_bug_in_the_store_is_not_mistaken_for_an_outage() -> None:
    with pytest.raises(RuntimeError):
        await _service(Store(error=RuntimeError("bug"))).page(status=None, cursor=None, limit=1)
