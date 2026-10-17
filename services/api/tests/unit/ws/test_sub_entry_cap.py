"""SR-192 (#2292): the work, the reply and the audit writes of one `sub` frame are bounded by the
entry cap, never by how long the frame is (E17 threat model WS-D15, AC-29; `23-ws-protocol.md`
§5.2).

- `topics` longer than `MAX_TOPICS_PER_SUB` (§13.5 `maxItems`, `welcome`'s
  `max_topics_per_request`) is refused whole before any entry is read: one `err too_many_topics`
  (`field: topics`), no result per entry, nothing subscribed and no audit record.
- Within the cap, the refusals `ws.subscribe.denied` records (every `forbidden` or
  `account_scope_denied`, and any refusal of a private-family topic) are ONE record for the frame,
  never one per entry. Its columns are the first refusal's, so a lone refusal writes the row it
  writes alone, and a `machines` refusal keeps its full `ch` and internal reason (§6.4, #3057).

Fake collaborators only; the audit sink counts appends. No timing, no sleeps, no network.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, NoReturn

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws.limits import MAX_DENIALS_LISTED, MAX_INBOUND_FRAME_BYTES, MAX_TOPICS_PER_SUB
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices, handle_sub
from candleviewer.ws.topics import FAMILIES, EntityScope

A = uuid.UUID(int=0xA)
B = uuid.UUID(int=0xB)
VIEWER = uuid.UUID(int=0x300)
MANAGER = uuid.UUID(int=0x100)
_CAP = MAX_TOPICS_PER_SUB
_PROTOCOL = Path(__file__).resolve().parents[5] / "docs" / "plan" / "23-ws-protocol.md"
#: Private families a market-data-only principal is refused (`forbidden`) by their bare name.
PRIVATE = ["orders", "positions", "executions", "wallet", "trade_groups", "rules", "alerts"]
#: §6.4 entities: an order on account B (foreign to `_manager()`), one with no entry, and a kind
#: that does not exist. Each is a `machines` refusal, and the first two carry an internal reason.
FOREIGN = "machines.order:0a000000-0000-4000-8000-000000000001.state"
UNKNOWN = "machines.order:0a000000-0000-4000-8000-000000000002.state"
BOGUS = "machines.bogus.state"
_WHY: dict[str, str | None] = {FOREIGN: "foreign", UNKNOWN: "unknown", BOGUS: None}


class _Audit:
    """The audit sink: each `emit` is one append (an fsync'd WAL write in production)."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.records.append({"action": action, **kw})


def _viewer() -> PrincipalSnapshot:
    """The threat model's V here: market data only, so every private family is `forbidden`."""
    perms = frozenset({Permission.MARKETDATA_READ})
    return PrincipalSnapshot(VIEWER, frozenset({"viewer"}), perms)


def _manager() -> PrincipalSnapshot:
    """Market data, orders and positions, on account A only."""
    perms = frozenset(
        {Permission.MARKETDATA_READ, Permission.ORDERS_READ, Permission.POSITIONS_READ}
    )
    grants = (AccountGrant(A, True, False, False),)
    return PrincipalSnapshot(MANAGER, frozenset({"manager"}), perms, grants)


class _Entries:
    """The §6.4 registry as `sub` reads it: one entry, `FOREIGN`'s."""

    def scope(self, ch: str) -> EntityScope | None:
        return EntityScope(accounts=frozenset({B})) if ch == FOREIGN else None


def _conn(principal: PrincipalSnapshot, audit: _Audit) -> ConnectionAuthz:
    services = SubscriptionServices(audit=audit, clock=lambda: 0.0, machines=_Entries())
    return ConnectionAuthz(principal, services)


def _handle(conn: ConnectionAuthz, frame: dict[str, Any]) -> dict[str, Any]:
    """Run `handle_sub` on one frame; it sends exactly one reply."""
    sent: list[dict[str, Any]] = []

    async def send(reply: dict[str, Any]) -> None:
        sent.append(reply)

    asyncio.run(handle_sub(conn, frame, send, now_ms=1))
    (reply,) = sent
    return reply


def _reply(conn: ConnectionAuthz, p: Any) -> dict[str, Any]:
    return _handle(conn, {"t": "sub", "id": "s-1", "p": p})


def _refusal(reply: dict[str, Any]) -> tuple[Any, ...]:
    return (reply["t"], reply["id"], reply["p"]["code"], reply["p"]["field"])


def _footprints(n: int) -> list[str]:
    """`n` distinct public topics on ONE symbol, all of which a market-data principal may hold
    (the 40-symbol cap is another limit, and `bars.*` has its own cap of 16, §6.1)."""
    return [f"footprint.BTCUSDT.tick.{i}" for i in range(1, n + 1)]


# -- the entry cap -------------------------------------------------------------------------------


def test_sub_of_exactly_the_cap_is_answered_entry_by_entry() -> None:
    """§13.5 allows 50 entries, so a frame of exactly 50 is processed: one result per entry, in
    request order, all of them subscribed."""
    conn = _conn(_viewer(), _Audit())
    names = _footprints(_CAP)
    reply = _reply(conn, {"topics": names})
    assert reply["t"] == "sub_ok"
    assert [(r["ch"], r["ok"]) for r in reply["p"]["results"]] == [(n, True) for n in names]
    assert conn.topics == set(names)


@pytest.mark.parametrize("n", [_CAP + 1, 1_000])
def test_sub_over_the_cap_is_refused_whole_with_too_many_topics(n: int) -> None:
    """One `err too_many_topics` (`field: topics`; retryable once the request is split) instead
    of a `sub_ok`: no result per entry, nothing subscribed, nothing echoed. Every entry but the
    first is a refusal the audit would keep (a private family V may not read), yet the frame
    writes no record, because no entry is read."""
    audit = _Audit()
    conn = _conn(_viewer(), audit)
    topics = [*_footprints(1), *(PRIVATE * n)[: n - 1]]
    reply = _reply(conn, {"topics": topics})
    assert _refusal(reply) == ("err", "s-1", "too_many_topics", "topics")
    assert (reply["p"]["retryable"], reply["p"]["close"]) == (True, False)
    assert "ch" not in reply and len(json.dumps(reply)) < 400
    assert conn.by_id == {} and audit.records == []


@pytest.mark.parametrize(
    ("p", "code", "field"),
    [
        # the payload's keys come first: an unknown one names `p`, as the first way in §5.2's list
        pytest.param({"topics": PRIVATE * 8, "bogus": 1}, "invalid_options", "p", id="unknown-key"),
        # the length comes before any entry, so entries that are not topics are never reached
        pytest.param({"topics": [7] * (_CAP + 1)}, "too_many_topics", "topics", id="int-entries"),
        pytest.param(
            {"topics": [{"opts": {}}] * (_CAP + 1)}, "too_many_topics", "topics", id="no-ch"
        ),
        # and neither is a per-topic violation (a `snapshot` that is not a boolean)
        pytest.param(
            {"topics": _footprints(_CAP + 1), "snapshot": "yes"},
            "too_many_topics",
            "topics",
            id="bad-snapshot",
        ),
    ],
)
def test_sub_over_the_cap_is_named_by_the_first_way_that_applies(
    p: Any, code: str, field: str
) -> None:
    audit = _Audit()
    conn = _conn(_viewer(), audit)
    assert _refusal(_reply(conn, p)) == ("err", "s-1", code, field)
    assert conn.by_id == {} and audit.records == []


class _NoEntryRead(list[str]):
    """A `topics` array that fails the test as soon as one of its entries is read, however it
    is read: iterated or reversed, indexed or sliced, searched (`in`, `index`) or counted. Its
    length, which the cap check needs, stays readable (the `unsub` tripwire of #2875)."""

    def _read(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        raise AssertionError("an entry was read")

    __iter__ = __reversed__ = __getitem__ = __contains__ = index = count = _read


def test_sub_over_the_cap_is_refused_before_any_entry_is_read() -> None:
    """The length is checked first, so the handler's cost does not depend on how long the array
    is: 65 536 entries, and any read of one fails the test. No timing."""
    audit = _Audit()
    conn = _conn(_viewer(), audit)
    reply = _reply(conn, {"topics": _NoEntryRead(["orders"] * 65_536)})
    assert _refusal(reply) == ("err", "s-1", "too_many_topics", "topics")
    assert audit.records == []


def _maximal_sub() -> tuple[str, int]:
    """The issue's repro: one `sub` text that fills the 256 KiB inbound cap with bare names, the
    private families V is refused plus one public name, in turn. Returns the text and how many
    entries it holds."""
    head, tail = '{"t":"sub","id":"s-1","p":{"topics":[', "]}}"
    names = [json.dumps(n) for n in (*PRIVATE, "book.BTCUSDT.50")]
    parts: list[str] = []
    size = len(head) + len(tail) - 1  # the first name has no comma before it
    while size + len(names[len(parts) % len(names)]) + 1 <= MAX_INBOUND_FRAME_BYTES:
        name = names[len(parts) % len(names)]
        parts.append(name)
        size += len(name) + 1
    return head + ",".join(parts) + tail, len(parts)


def test_the_largest_sub_the_frame_cap_allows_gets_one_small_err_and_no_audit_append() -> None:
    """WS-D15, AC-29: a frame at the 256 KiB cap holds more than 20 000 bare names. Each used to
    get a result (a reply about 9 times the request) and each private-family one an audit append
    of its own; now the frame gets one `err` of a few hundred bytes and no append."""
    text, entries = _maximal_sub()
    # within one name (at most 18 bytes with its comma) of the cap, and under it
    assert MAX_INBOUND_FRAME_BYTES - 18 < len(text.encode()) <= MAX_INBOUND_FRAME_BYTES
    assert entries > 20_000
    audit = _Audit()
    conn = _conn(_viewer(), audit)
    reply = _handle(conn, json.loads(text))
    assert _refusal(reply) == ("err", "s-1", "too_many_topics", "topics")
    assert len(json.dumps(reply)) < 400
    assert audit.records == [] and conn.by_id == {}


# -- one denial record per frame -----------------------------------------------------------------


def _record(audit: _Audit) -> dict[str, Any]:
    (record,) = audit.records
    return record


#: What every `ws.subscribe.denied` record holds, whatever it records.
_ROW = {
    "action": "ws.subscribe.denied",
    "actor_label": "ws",
    "object_kind": "ws_topic",
    "outcome": AuditOutcome.DENIED,
    "severity": Severity.WARNING,
}


def test_a_frame_of_50_audited_refusals_is_one_record_that_counts_them() -> None:
    """V's 50-entry `sub` of private families is 50 refusals the audit keeps, and one append:
    `count` holds them all, `codes` each code once, and `refusals` the family and code of the
    first `MAX_DENIALS_LISTED` of them, in request order."""
    assert MAX_DENIALS_LISTED < _CAP  # so the list is shorter than the count below
    audit = _Audit()
    conn = _conn(_viewer(), audit)
    topics = (PRIVATE * _CAP)[:_CAP]
    reply = _reply(conn, {"topics": topics})
    assert [r["error"]["code"] for r in reply["p"]["results"]] == ["forbidden"] * _CAP
    assert _record(audit) == {
        **_ROW,
        "actor_user_id": VIEWER,
        "object_id": "orders",
        "reason": "forbidden",
        "after_state": {
            "count": _CAP,
            "codes": ["forbidden"],
            "refusals": [[f, "forbidden"] for f in topics[:MAX_DENIALS_LISTED]],
        },
    }


def test_the_record_holds_only_the_refusals_the_audit_keeps_first_one_first() -> None:
    """A Manager scoped to account A. Kept: an authorisation denial, and any refusal of a
    private-family topic, whatever its code. Not kept: a public topic refused for another reason.
    `object_id` and `reason` are the first kept refusal's family and code, and a family is
    recorded, never the name the client sent (`orders.admin` is `orders`). `codes` is sorted."""
    audit = _Audit()
    conn = _conn(_manager(), audit)
    topics: list[Any] = [
        "ticker.BTCUSDT",
        "orders.admin",
        "nope.BTCUSDT",
        {"ch": "positions", "opts": {"exchange_account_ids": [str(B)]}},
        "book.ETHUSD.50",
        {"ch": "orders", "opts": 1},
        "ticker.BTCUSDT",
        "wallet",
    ]
    reply = _reply(conn, {"topics": topics})
    assert [r["error"]["code"] if not r["ok"] else "ok" for r in reply["p"]["results"]] == [
        "ok",
        "invalid_topic_format",  # private: kept
        "unknown_topic",  # public: not kept
        "account_scope_denied",  # kept
        "unsupported_symbol",  # public: not kept
        "invalid_options",  # private: kept
        "duplicate_subscription",  # public: not kept
        "forbidden",  # no `accounts:read`: kept
    ]
    record = _record(audit)
    assert (record["object_id"], record["reason"]) == ("orders", "invalid_topic_format")
    assert record["after_state"] == {
        "count": 4,
        "codes": ["account_scope_denied", "forbidden", "invalid_options", "invalid_topic_format"],
        "refusals": [
            ["orders", "invalid_topic_format"],
            ["positions", "account_scope_denied"],
            ["orders", "invalid_options"],
            ["wallet", "forbidden"],
        ],
    }


def test_the_contract_states_how_many_refusals_the_record_lists() -> None:
    """§5.2 gives the bound in prose, so a change to the constant has to change the contract."""
    text = _PROTOCOL.read_text(encoding="utf-8")
    assert f"pairs of the first {MAX_DENIALS_LISTED} in request order" in text


def test_a_frame_with_one_kept_refusal_writes_its_row_without_after_state() -> None:
    """No `after_state`: the row a lone refusal wrote before #2292. Here the `forbidden` of a
    public topic (kept whatever the family) for a principal without `marketdata:read`; the unknown
    name beside it is refused before any permission is read, and is not kept. `test_machines.py`
    pins the same row for a lone `machines` refusal (#3057)."""
    audit = _Audit()
    who = uuid.UUID(int=0x400)
    principal = PrincipalSnapshot(who, frozenset({"viewer"}), frozenset({Permission.ORDERS_READ}))
    _reply(_conn(principal, audit), {"topics": ["nope.BTCUSDT", "book.BTCUSDT.50"]})
    assert _record(audit) == {
        **_ROW,
        "actor_user_id": who,
        "object_id": "book",
        "reason": "forbidden",
    }


def test_the_record_keeps_the_full_ch_and_internal_reason_of_each_machines_refusal() -> None:
    """§6.4 (#3057) inside the frame's record: a listed `machines` refusal keeps its full `ch`
    and, when its entity was refused, its internal reason (`foreign`, `unknown`); one whose topic
    is not an entity keeps its code. The refusals around them keep their family and code, so no
    internal reason reaches another row."""
    audit = _Audit()
    positions_b = {"ch": "positions", "opts": {"exchange_account_ids": [str(B)]}}
    topics = ["wallet", FOREIGN, UNKNOWN, BOGUS, positions_b]
    reply = _reply(_conn(_manager(), audit), {"topics": topics})
    assert [r["ok"] for r in reply["p"]["results"]] == [False] * 5
    assert _record(audit) == {
        **_ROW,
        "actor_user_id": MANAGER,
        "object_id": "wallet",
        "reason": "forbidden",
        "after_state": {
            "count": 5,
            "codes": ["account_scope_denied", "forbidden", "invalid_topic_format"],
            "refusals": [
                ["wallet", "forbidden"],
                [FOREIGN, "foreign"],
                [UNKNOWN, "unknown"],
                [BOGUS, "invalid_topic_format"],
                ["positions", "account_scope_denied"],
            ],
        },
    }


def test_a_first_machines_refusal_fills_the_columns_as_its_own_row_does() -> None:
    """The record's `object_id` and `reason` are the first refusal's: for a refused `machines`
    entity its full `ch` and internal reason, as #3057 writes it alone. The private-family refusal
    after it keeps its family and code."""
    audit = _Audit()
    _reply(_conn(_manager(), audit), {"topics": [FOREIGN, "orders.admin"]})
    assert _record(audit) == {
        **_ROW,
        "actor_user_id": MANAGER,
        "object_id": FOREIGN,
        "reason": "foreign",
        "after_state": {
            "count": 2,
            "codes": ["account_scope_denied", "invalid_topic_format"],
            "refusals": [[FOREIGN, "foreign"], ["orders", "invalid_topic_format"]],
        },
    }


def test_a_frame_without_a_kept_refusal_writes_no_record() -> None:
    audit = _Audit()
    conn = _conn(_viewer(), audit)
    topics = ["ticker.BTCUSDT", "nope.BTCUSDT", "book.ETHUSD.50", "ticker.BTCUSDT"]
    reply = _reply(conn, {"topics": topics})
    assert [r["ok"] for r in reply["p"]["results"]] == [True, False, False, False]
    assert audit.records == []


def test_the_record_is_written_before_the_reply_is_sent() -> None:
    """As before #2292, a denial is on record by the time the client reads its result."""
    audit = _Audit()
    conn = _conn(_viewer(), audit)
    seen: list[int] = []

    async def send(_reply: dict[str, Any]) -> None:
        seen.append(len(audit.records))

    frame = {"t": "sub", "id": "s-1", "p": {"topics": ["orders", "wallet"]}}
    asyncio.run(handle_sub(conn, frame, send, now_ms=1))
    assert seen == [1]


class _YieldingAudit(_Audit):
    async def emit(self, action: str, **kw: Any) -> None:
        await asyncio.sleep(0)  # suspends once before it lands, as a real WAL append does
        await super().emit(action, **kw)


@pytest.mark.parametrize("fault", [RuntimeError, asyncio.CancelledError])
def test_a_frame_faulting_mid_loop_still_writes_its_one_record(
    fault: type[BaseException], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.9, WS-R01: two refusals the audit keeps, then a public topic whose upstream await
    raises (the connection then closes 1011) or is cancelled. The fault reaches the caller and
    nothing is sent, but the one record of both refusals is written on the way out, its append
    completing after a delivered cancellation."""
    audit, entered = _YieldingAudit(), asyncio.Event()
    replies: asyncio.Queue[dict[str, Any]] = asyncio.Queue(1)
    conn = _conn(_viewer(), audit)

    async def upstream(_sub: Any) -> None:
        entered.set()
        if fault is RuntimeError:
            raise RuntimeError("upstream down")
        await asyncio.get_running_loop().create_future()  # never resolved: cancelled here

    async def run() -> None:
        frame = {"t": "sub", "p": {"topics": ["wallet", "orders", "ticker.BTCUSDT"]}}
        task = asyncio.create_task(handle_sub(conn, frame, replies.put))
        await entered.wait()
        if fault is asyncio.CancelledError:
            task.cancel()
        await task

    monkeypatch.setattr(conn, "subscribe_upstream", upstream)
    with pytest.raises(fault):
        asyncio.run(run())
    pairs = [["wallet", "forbidden"], ["orders", "forbidden"]]
    after = {"count": 2, "codes": ["forbidden"], "refusals": pairs}
    assert replies.empty() and _record(audit)["after_state"] == after


#: Entries of every kind for `_manager()`: kept refusals, other refusals and successes.
_POOL: list[Any] = [
    *PRIVATE,
    "orders.admin",
    {"ch": "orders", "opts": 1},
    {"ch": "positions", "opts": {"exchange_account_ids": [str(A)]}},
    {"ch": "positions", "opts": {"exchange_account_ids": [str(B)]}},
    "ticker.BTCUSDT",
    "book.BTCUSDT.50",
    "nope.BTCUSDT",
    "book.ETHUSD.50",
    "book.BTCUSDT.7",
    *_WHY,
]


def _kept(result: dict[str, Any]) -> bool:
    """The contract's rule, restated: an authorisation denial, or a private family's refusal."""
    if result["ok"]:
        return False
    family = FAMILIES.get(result["ch"].split(".", 1)[0])
    code = result["error"]["code"]
    return code in {"forbidden", "account_scope_denied"} or (family is not None and family.private)


def _pair(result: dict[str, Any]) -> list[str]:
    """The contract's `[object_id, reason]` of one kept refusal (§5.2, §6.4), restated."""
    ch, code = result["ch"], result["error"]["code"]
    if ch.startswith("machines."):
        return [ch, _WHY[ch] or code]
    return [ch.split(".", 1)[0], code]


@given(st.lists(st.sampled_from(range(len(_POOL))), min_size=1, max_size=_CAP + 10))
def test_one_frame_writes_at_most_one_denial_record_and_it_agrees_with_the_results(
    picks: list[int],
) -> None:
    """SR-192's invariant: one denial record per frame (`ws.subscribe.denied`; a record of any
    other action is not counted). Within the cap the record has the first kept refusal's
    `object_id` and `reason`; with more than one, it counts exactly the kept refusals among the
    results, lists the `[object_id, reason]` of the first `MAX_DENIALS_LISTED` in order (a
    `machines` one by its full `ch` and internal reason) and their codes sorted. Past the cap
    there is no result and no denial record."""
    audit = _Audit()
    reply = _reply(_conn(_manager(), audit), {"topics": [_POOL[i] for i in picks]})
    denied = [r for r in audit.records if r["action"] == "ws.subscribe.denied"]
    if len(picks) > _CAP:
        assert (reply["t"], reply["p"]["code"], denied) == ("err", "too_many_topics", [])
        return
    kept = [r for r in reply["p"]["results"] if _kept(r)]
    assert len(denied) == (1 if kept else 0)
    if kept:
        (record,) = denied
        pairs = [_pair(r) for r in kept]
        assert [record["object_id"], record["reason"]] == pairs[0]
        assert record.get("after_state") == (
            None
            if len(kept) == 1
            else {
                "count": len(kept),
                "codes": sorted({r["error"]["code"] for r in kept}),
                "refusals": pairs[:MAX_DENIALS_LISTED],
            }
        )
