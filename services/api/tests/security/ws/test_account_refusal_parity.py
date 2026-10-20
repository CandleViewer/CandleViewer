"""E17-X02 AC-05, its existence leg (#415, threat model `E17-ws-gateway.md` §7, WS-I03): a manager
cannot tell an account that exists outside her scope from an id no user holds. On every
account-scoped family a `sub` naming either leaves one observation, compared whole: every frame the
socket receives up to the `pong` of a later `ping` (the reply among them: code, message, no
`field`), one `ws.subscribe.denied` row, the change in each counter, gauge and histogram (one
`cv_ws_subscribe_total` series), the log events and records, what was printed, and the lookups
made. So does each other form of an out-of-scope request. Neither `sub` reads the principal
loader, the account store or the snapshot source: the principal is read once per socket, at
`auth`, by production's `StorePrincipalLoader` over an account store read by owner, and both
requests are checked against it alike. The timing leg is opt-in, as E09-X02's AC-ENUM-03 is, and
uses its method and threshold through the gateway in process. Both subprotocols; a fake clock
wherever time is not the measurement.
"""

from __future__ import annotations

import gc
import json
import math
import os
import random
import signal
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from functools import partial
from pathlib import Path
from typing import Any, NoReturn

import msgpack
import pytest
from prometheus_client import REGISTRY

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, DenyReason, PrincipalSnapshot, decide
from candleviewer.ws import permissions
from candleviewer.ws.limits import DENIAL_AUDIT_WINDOW_S
from candleviewer.ws.topics import FAMILIES
from candleviewer.ws_wiring import StorePrincipalLoader
from tests.contract.ws._support import Clock
from tests.security.auth.test_credential_abuse import (
    RATIO_TOL,
    SAMPLES,
    WARMUP,
    Z_CRIT,
    mann_whitney_z,
)
from tests.security.ws._raw import Login, RawClient, RawWorld, authenticated, raw_connect
from tests.unit.ws._seq_support import ACC_A

#: The account-scoped families (§6.2), read from the registry, so a new one joins these tests.
SCOPED = sorted(name for name, fam in FAMILIES.items() if fam.account_scoped)
_DRAWN = random.Random(415)  # noqa: S311 - seeded, non-cryptographic test data
#: Ids no user holds, shaped as a guess is (version 4): `UNKNOWN`, then 23 more for a full list.
UNKNOWN, *OTHERS = [uuid.UUID(int=_DRAWN.getrandbits(128), version=4) for _ in range(24)]
#: Ids that exist, of the same form (seeded, version 4), so an id differs from an unknown one in
#: existence only: the account bob holds, and one alice is linked to by a grant row without view
#: (it exists and is outside her scope).
BOB, UNVIEWED = (uuid.UUID(int=_DRAWN.getrandbits(128), version=4) for _ in range(2))
#: The timing leg takes seconds. Its whole timed loop has this long: a reply that never comes ends
#: it in a failure, not a hang.
WATCHDOG_S = 60
#: The §10.2 refusal, with no `field` (§6.2: an absent list is refused the same way).
DENIED = {
    "code": "account_scope_denied",
    "message": "None of the requested accounts are in scope.",
    "retryable": False,
}
NOT_GRANTED = DenyReason.ACCOUNT_NOT_GRANTED
Check = tuple[uuid.UUID | None, DenyReason | None]  # a `decide` call's account and refusal reason
Key = tuple[str, tuple[tuple[str, str], ...]]  # a sample's name and its labels, sorted
Series = dict[Key, float]


@dataclass
class Spies:
    """What requests read: principal loads (by user), account-store reads (by owner), snapshot
    source calls (by method) and, with `checked`, each scope check (`decide`) that
    `ws.permissions` makes."""

    loads: list[uuid.UUID] = field(default_factory=list)
    reads: list[uuid.UUID] = field(default_factory=list)
    snaps: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)


class _Identity:
    """The SQL identity read path as the loader reads it: an active manager with the rig's
    permissions (`world.perms`, read at each load)."""

    def __init__(self, world: RawWorld) -> None:
        self.world = world

    async def user(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "roles": ["manager"], "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": [p.value for p in self.world.perms]}


class _Store:
    """The account store as the loader reads it (`SqlAlchemyScopeSource.load_grants`): the
    `user_account_access` rows `RawWorld.login` granted, by owner. Each read is kept."""

    def __init__(self, world: RawWorld, reads: list[uuid.UUID]) -> None:
        self.world, self.reads = world, reads

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        self.reads.append(owner)
        grants = self.world.user_grants.get(owner, ())
        return [(g.exchange_account_id, g.can_view, g.frozen) for g in grants]


def _kept(calls: list[str], name: str, call: Callable[..., Any], *args: Any) -> Any:
    calls.append(name)
    return call(*args)


@pytest.fixture
def spies(world: RawWorld, monkeypatch: pytest.MonkeyPatch) -> Spies:
    """`world` as `create_app` wires the gateway where the rig keeps its own: one audit sink for
    the gateway and its subscriptions, principals from `StorePrincipalLoader` (#2505) over the
    account store, and a fake clock for the denial records' budget. The loader's calls, the
    store's reads and the snapshot source's calls (`SnapshotSource`, the rig's `Source`) are
    kept."""
    seen = Spies()
    world.registry.services.audit = world.audit
    world.registry.services.clock = Clock()
    loader = StorePrincipalLoader(_Identity(world), _Store(world, seen.reads))

    async def load(user: uuid.UUID) -> PrincipalSnapshot:
        seen.loads.append(user)
        return await loader(user)

    monkeypatch.setattr(world.registry, "_resolve", load)
    for name in ("build", "generation", "continuity"):
        port = partial(_kept, seen.snaps, name, getattr(world.source, name))
        monkeypatch.setattr(world.source, name, port)
    return seen


@pytest.fixture
def checked(spies: Spies, monkeypatch: pytest.MonkeyPatch) -> Spies:
    """`spies`, keeping each scope check too (E09's `decide`, as `ws.permissions` calls it): its
    account and its refusal reason (`None`: allowed). The timing leg does without it, so it times
    the scope check unwrapped."""

    def spy(*args: Any, **kwargs: Any) -> Any:
        decision = decide(*args, **kwargs)
        spies.checks.append((kwargs.get("exchange_account_id"), getattr(decision, "reason", None)))
        return decision

    monkeypatch.setattr(permissions, "decide", spy)
    return spies


def _series() -> Series:
    """Every sample of every counter, gauge and histogram in process, where E09-X02 reads them
    too, less the `_created` stamp of a new series and what differs by nature: the interpreter's
    and the process's own collectors (`python_`, `process_`), the sum of a duration
    (`*_seconds_sum`) and a gauge that reads a clock (`*_age_seconds`, bound by `set_function`)."""
    return {
        (s.name, tuple(sorted(s.labels.items()))): s.value
        for metric in REGISTRY.collect()
        if metric.type in {"counter", "gauge", "histogram"}
        and not metric.name.startswith(("python_", "process_"))
        for s in metric.samples
        if not s.name.endswith(("_created", "_seconds_sum", "_age_seconds"))
    }


def _moved(before: Series, after: Series) -> dict[Key, float | str]:
    """The samples that changed from `before` to `after`, each by how much. A gauge can be NaN
    (`cv_audit_chain_verified_state` until its first run) and `nan != nan`: a sample that is NaN in
    both is unchanged, and a change to or from NaN reads `"NaN"`, so equal runs compare equal."""
    moved: dict[Key, float | str] = {}
    for key, now in after.items():
        was = before.get(key, 0.0)
        if now == was or (math.isnan(now) and math.isnan(was)):
            continue
        step = now - was
        moved[key] = "NaN" if math.isnan(step) else step
    return moved


def _sub(ch: str, ids: list[uuid.UUID] | None) -> dict[str, Any]:
    opts = {} if ids is None else {"exchange_account_ids": [str(a) for a in ids]}
    return {"t": "sub", "id": "s", "p": {"topics": [{"ch": ch, "opts": opts}]}}


def _observe(
    world: RawWorld, spies: Spies, c: RawClient, ch: str, ids: list[uuid.UUID] | None
) -> tuple[dict[str, Any], list[Check]]:
    """What one `sub` of `ch` naming `ids` left, read once a later `ping` is answered (the gateway
    handles a socket's frames in turn): its reply, every frame the socket received from the `sub`
    to the `pong` (a `ping` among them), audit rows, change in each series, log events and
    records, what was printed to stdout and stderr, and the lookups it caused (principal loads,
    store reads, snapshot source calls); and, apart, its scope checks."""
    rows, events, stdlib, loads, reads, snaps, checks, frames = (
        len(x)
        for x in (
            world.audit.records,
            world.events,
            world.log.record_tuples,
            spies.loads,
            spies.reads,
            spies.snaps,
            spies.checks,
            c.seen,
        )
    )
    world.std.readouterr()  # what was printed so far is not this window's
    before = _series()
    c.send(_sub(ch, ids))
    reply = c.next_of("sub_ok")
    c.send({"t": "ping", "id": "p"})
    c.next_of("pong")
    after = _series()
    printed = world.std.readouterr()
    seen = {
        "reply": reply,
        "frames": c.seen[frames:],
        "rows": world.audit.records[rows:],
        "series": _moved(before, after),
        "events": world.events[events:],
        "stdlib": world.log.record_tuples[stdlib:],
        "std": (printed.out, printed.err),
        "lookups": spies.loads[loads:] + spies.reads[reads:] + spies.snaps[snaps:],
    }
    return seen, spies.checks[checks:]


def _denied_row(world: RawWorld, login: Login, family: str, reason: str) -> dict[str, Any]:
    """The `ws.subscribe.denied` row of one refusal (23 §5.2): the family and the code, no id; and
    the socket it came from, which the row names (#415, E17-R-16), once that socket has closed."""
    return {
        "action": "ws.subscribe.denied",
        "actor_label": "ws",
        "actor_user_id": login.user_id,
        "object_kind": "ws_topic",
        "object_id": family,
        "outcome": AuditOutcome.DENIED,
        "severity": Severity.WARNING,
        "reason": reason,
        **world.named_by(login),
    }


@pytest.mark.parametrize("family", SCOPED)
def test_x02_ac_05_an_existing_account_and_an_unknown_id_get_one_refusal(
    world: RawWorld, checked: Spies, family: str
) -> None:
    alice = world.login("alice")  # may view ACC_A only
    world.login("bob", BOB)  # BOB exists: bob holds it
    assert all(g.exchange_account_id != UNKNOWN for gs in world.user_grants.values() for g in gs)
    with raw_connect(world) as c:
        authenticated(c, alice)
        assert checked.loads == checked.reads == [alice.user_id]  # once, at `auth`, by owner
        existing, by_existing = _observe(world, checked, c, family, [BOB])
        unknown, by_unknown = _observe(world, checked, c, family, [UNKNOWN])
    assert existing == unknown  # frames, row, series, log events and records, lookups: whole
    assert existing["reply"]["p"]["results"] == [{"ch": family, "ok": False, "error": DENIED}]
    assert existing["rows"] == [_denied_row(world, alice, family, "account_scope_denied")]
    labels = ("cv_ws_subscribe_total", (("result", "account_scope_denied"), ("topic", family)))
    assert {k: v for k, v in existing["series"].items() if k[0] == labels[0]} == {labels: 1.0}
    assert existing["events"] == existing["stdlib"] == existing["lookups"] == []
    assert existing["std"] == ("", "")  # nothing printed
    assert str(BOB) not in repr(existing)  # bob's account is named nowhere
    # One scope check each way: the family's permission, then the id against alice's grants.
    assert by_existing == [(None, None), (BOB, NOT_GRANTED)]
    assert by_unknown == [(None, None), (UNKNOWN, NOT_GRANTED)]


#: Each other form of an out-of-scope request: an account alice holds a row for without view, a
#: foreign and an unknown id together, one id twice, the 25 ids the option allows, and no id.
FORMS: dict[str, list[uuid.UUID] | None] = {
    "row_without_view": [UNVIEWED],
    "foreign_and_unknown": [BOB, UNKNOWN],
    "one_id_twice": [UNKNOWN, UNKNOWN],
    "25_ids": [BOB, UNVIEWED, *OTHERS],
    "no_id": None,
}


@pytest.mark.parametrize("family", SCOPED)
@pytest.mark.parametrize("ids", FORMS.values(), ids=list(FORMS))
def test_x02_ac_05_each_form_of_an_out_of_scope_request_gets_the_unknown_ids_refusal(
    world: RawWorld, checked: Spies, family: str, ids: list[uuid.UUID] | None
) -> None:
    alice = world.login("alice")
    world.login("bob", BOB)
    world.user_grants[alice.user_id] += (AccountGrant(UNVIEWED, False, False, False),)
    with raw_connect(world) as c:
        authenticated(c, alice)
        base, _ = _observe(world, checked, c, family, [UNKNOWN])
        seen, checks = _observe(world, checked, c, family, ids)
    assert seen == base
    named = sorted(set(ids or ()), key=str)  # as `validate_options` orders them
    assert checks == [(None, None), *[(a, NOT_GRANTED) for a in named]]  # each id: her grants alone
    assert checked.loads == checked.reads == [alice.user_id]  # once, at `auth`


@pytest.mark.parametrize("family", SCOPED)
def test_x02_ac_05_without_the_family_permission_both_ids_get_forbidden(
    world: RawWorld, checked: Spies, family: str
) -> None:
    """Decided before any id is checked: one scope check, on the permission."""
    alice = world.login("alice")
    world.login("bob", BOB)
    world.perms = frozenset({Permission.MARKETDATA_READ})  # read by `auth`
    with raw_connect(world) as c:
        authenticated(c, alice)
        foreign, by_foreign = _observe(world, checked, c, family, [BOB])
        unknown, by_unknown = _observe(world, checked, c, family, [UNKNOWN])
    assert foreign == unknown
    assert foreign["rows"] == [_denied_row(world, alice, family, "forbidden")]
    assert by_foreign == by_unknown == [(None, DenyReason.MISSING_PERMISSION)]
    assert checked.loads == checked.reads == [alice.user_id]  # once, at `auth`


def test_x02_ac_05_the_spies_see_a_sub_that_is_served(world: RawWorld, spies: Spies) -> None:
    """The control for the lookups above: a `sub` of an account alice may view builds its
    snapshot, which the snapshot source's spy sees. A public topic is built through the shared
    cache, which asks for the `generation` too; a private family is built without it."""
    alice = world.login("alice")
    with raw_connect(world) as c:
        authenticated(c, alice)
        served, _ = _observe(world, spies, c, "positions", [ACC_A])
        public, _ = _observe(world, spies, c, "ticker.BTCUSDT", None)
    assert served["reply"]["p"]["results"][0]["ok"] is True
    assert "build" in served["lookups"]
    assert {"build", "generation"} <= set(public["lookups"])  # not `continuity`: no-snapshot only


def test_x02_ac_05_every_collaborator_of_the_subscription_services_is_known_to_the_spies() -> None:
    known = {"upstream", "bars", "series", "audit", "clock", "instrument_known", "snapshots"}
    known |= {"snapshot_cache", "sequencing", "bars_off", "machines", "span_ids", "user_rebuilds"}
    known |= {"qty_step"}  # SR-E12-03 (#3885): read only for a `bar_type` topic, to bound a param
    assert {f.name for f in fields(permissions.SubscriptionServices)} == known, (
        "a new collaborator of the subscription services: wire it into `spies` and the arms, so "
        "that a `sub` that reads it is seen, then add it here"
    )


def _round_trip(c: RawClient, payload: bytes | str) -> dict[str, Any]:
    """`payload` out and the next frame in, by the socket session itself: the harness's bounded
    receive starts a thread per frame, which would more than double the time measured."""
    if isinstance(payload, bytes):
        c.ws.send_bytes(payload)
        reply: dict[str, Any] = msgpack.unpackb(c.ws.receive_bytes())
    else:
        c.ws.send_text(payload)
        reply = json.loads(c.ws.receive_text())
    return reply


def _no_reply(*_: object) -> NoReturn:
    raise TimeoutError(f"the timed loop did not finish within {WATCHDOG_S} s (a reply never came)")


@pytest.mark.perf
@pytest.mark.skipif(
    os.environ.get("CV_RUN_PERF") != "1",
    reason="wall-clock statistical test: opt in with CV_RUN_PERF=1, as AC-ENUM-03",
)
def test_x02_ac_05_the_two_refusals_take_the_same_time(
    world: RawWorld, spies: Spies, tmp_path: Path
) -> None:
    """AC-ENUM-03's method and threshold through the gateway in process: on one socket, `sub
    positions` naming the foreign account or the unknown id, the two frames of one size and
    encoded once; interleaved, each pair's order alternating; `WARMUP` pairs dropped, then
    `SAMPLES` per arm with gc off; the ratio of medians and Mann-Whitney. Before each frame the
    gateway's clock steps 0.25 s (inside the inbound limits) and the clock of the connection's
    denial-record budget a full window, so every sample writes its row. The whole timed loop has
    `WATCHDOG_S` seconds (an alarm: the session's receive has no bound), so a reply that never
    comes fails the leg instead of hanging it. The raw samples go to `tmp_path` only: #298 classes
    them SECRET."""
    alice = world.login("alice")
    world.login("bob", BOB)
    budget = Clock()
    world.registry.services.clock = budget
    with raw_connect(world) as c:
        authenticated(c, alice)
        frames = {"existing": _sub("positions", [BOB]), "unknown": _sub("positions", [UNKNOWN])}
        payloads = {k: msgpack.packb(f) if c.msgpack else json.dumps(f) for k, f in frames.items()}
        assert len({len(p) for p in payloads.values()}) == 1  # one frame size
        refused = [{"ch": "positions", "ok": False, "error": DENIED}]
        arms: dict[str, list[float]] = {name: [] for name in payloads}
        before = signal.getsignal(signal.SIGALRM)
        gc.collect()
        try:
            signal.signal(signal.SIGALRM, _no_reply)
            signal.alarm(WATCHDOG_S)  # the first statements of the `try`: the loop is on this clock
            gc.disable()
            for i in range(WARMUP + SAMPLES):
                for name in sorted(arms, reverse=i % 2 == 1):
                    world.clock.now += 0.25
                    budget.now += DENIAL_AUDIT_WINDOW_S
                    t0 = time.perf_counter()
                    reply = _round_trip(c, payloads[name])
                    dt = time.perf_counter() - t0
                    assert reply["p"]["results"] == refused
                    if i >= WARMUP:
                        arms[name].append(dt)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, before)
            gc.enable()
    assert len(world.audit.of("ws.subscribe.denied")) == 2 * (WARMUP + SAMPLES)  # none kept back
    assert spies.loads == spies.reads == [alice.user_id]  # none during the run
    assert spies.snaps == []
    a, b = sorted(arms["existing"]), sorted(arms["unknown"])
    ratio = a[len(a) // 2] / b[len(b) // 2]
    z = mann_whitney_z(arms["existing"], arms["unknown"])
    raw = tmp_path / "x02-ac-05-samples.json"
    raw.write_text(json.dumps({"unit": "s", "warmup_dropped": WARMUP, **arms}), encoding="utf-8")
    print(f"X02 AC-05 evidence: n={len(a)}/arm ratio={ratio:.4f} mann_whitney_z={z:.3f} raw={raw}")
    assert len(a) == len(b) == SAMPLES
    assert 1 - RATIO_TOL < ratio < 1 + RATIO_TOL, f"median ratio {ratio:.3f}"
    assert abs(z) < Z_CRIT, f"Mann-Whitney z={z:.2f}"
