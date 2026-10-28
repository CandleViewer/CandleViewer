"""Contract, provider side (E27-S04 B3b2, #898): `updateExchangeAccount` as the app serves it.

The world is the RBAC pack's real `create_app()` (no network, C-13.5) over one fake M13 store scoped
as Postgres scopes it (its write a compare-and-set on the tag and the enabled flag, its write-ahead
hook awaited before the write lands), the real consequence read over fake ports, and the real
`AccountLifecycle` over the app's own key standing and WS events, with recording stand-ins for the
rule disarm and the private-stream close. Every answer is checked against the response 22 declares
for its status (2020-12, format checker), and each `ETag` against `AccountETag`.

Covered: RBAC and IDOR (only the Owner, never a challenge for anyone else, one byte-equal `404`),
the `422`s and the `412` before the gate spending no code, the `accounts` challenge and its text,
a `keys` grant refused, the label-only patch without a gate, the disable's write-ahead record and
its effects in the ruled order, C-2.6's `leave_positions` refusal, the exposure answers (each `409`
recorded denied, the grant spent), the repeat and the concurrent disable writing no second record,
the overrun's `503` and its retry, the crash between the commit and the effects, the re-enable,
F-01's WS refusal end to end, the idempotent replays, and no key material in any answer or record;
then hpe-worker-2's notes: the grant binds the query and the body, an unwritable refusal record is
`503`, the `exposure_unknown` `409` is replayed, and an empty label is the declared `422`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

import candleviewer.app as appmod
from candleviewer.accounts.consequences import ConsequenceRead
from candleviewer.accounts.errors import AccountNotFoundError
from candleviewer.accounts.exposure import ExposureRead, KeyExposure, KeyReadFailed
from candleviewer.accounts.lifecycle import AccountLifecycle
from candleviewer.accounts.models import ApiKeyMetadata, ExchangeAccount
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.step_up_challenge import request_fingerprint
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.errors import AuditError
from candleviewer.auth.errors import StepUpMismatch
from candleviewer.exchange.base.errors import PrivateStreamCloseOverran
from candleviewer.storage.repositories.accounts import (
    AccountsPage,
    AccountsStoreScopeDeniedError,
    AccountsStoreStaleError,
    AccountsStoreUnchangedError,
    AccountWriteAhead,
    ApiKeyRow,
    ExchangeAccountPatch,
    ExchangeAccountRow,
    OwnerScope,
)
from tests.contract._admin_support import SPEC, validate_example
from tests.contract.rbac.rbac_harness import (
    ABSENT,
    FOREIGN,
    GRANTED,
    WS_ORIGIN,
    World,
    bearer,
    build_world,
    user_id_of,
)
from tests.contract.rbac.test_scope_and_ws import _auth, _sub
from tests.unit.accounts.test_exposure_decision import _position
from tests.unit.accounts.test_exposure_read import key
from tests.unit.accounts.test_key_import import key_row

PATH = "/exchange-accounts/{accountId}"
OTHER_ENV = uuid.UUID("00000000-0000-4000-8000-0000000000e1")  # a live account on a demo server
KEY = uuid.UUID("00000000-0000-4000-8000-0000000000f1")
#: A whole second: its six fractional digits are all zeros, which only `%f` prints (B4c).
STAMP = datetime(2026, 10, 26, 7, 35, 12, tzinfo=UTC)
PROTECTED = _position(stop_loss=Decimal("58000"))
BARE = _position(symbol="ETHUSDT", side="short")  # no native stop-loss (C-2.6)
DISABLE = {"enabled": False}
EFFECTS = ["hold", "ws", "disarm", "close"]


class Store:
    """The M13 store as Postgres scopes it. Its update is the compare-and-set (`if_match`, then
    `expect_enabled`), running the write-ahead hook before the row changes; `before_write` runs
    just ahead of the compare, as a change committed concurrently would land."""

    def __init__(self) -> None:
        base = ExchangeAccountRow(
            GRANTED, "bybit", "demo", "main", "1000001", None, "Granted", "accent.neutral", True,
            True, "one_way", "cross", "UNIFIED", "USDT", None, None, 5, None, STAMP, STAMP, None,
        )  # fmt: skip
        self.rows = {
            GRANTED: base,
            FOREIGN: dataclasses.replace(base, id=FOREIGN, label="Other", exchange_uid="1000002"),
            OTHER_ENV: dataclasses.replace(base, id=OTHER_ENV, env="live", exchange_uid="1000003"),
        }
        self.reset()

    def reset(self) -> None:
        self.calls, self.writes = 0, 0
        self.before_write: Any = None
        self.lock = asyncio.Lock()

    def _owner(self, scope: Any) -> None:
        self.calls += 1
        if not isinstance(scope, OwnerScope) or scope.user_id != user_id_of("owner"):
            raise AccountsStoreScopeDeniedError

    async def get_account(self, scope: Any, account_id: uuid.UUID) -> ExchangeAccountRow | None:
        self._owner(scope)
        return self.rows.get(account_id)

    async def list_accounts(
        self, scope: Any, *, env: str | None, **_kw: Any
    ) -> AccountsPage[ExchangeAccountRow]:
        self._owner(scope)
        return AccountsPage(tuple(r for r in self.rows.values() if env in (None, r.env)), None)

    async def list_keys(self, scope: OwnerScope, account_id: uuid.UUID) -> tuple[ApiKeyRow, ...]:
        self._owner(scope)
        return (key_row(KEY, "active"),)

    async def update_account(
        self, scope: OwnerScope, account_id: uuid.UUID, patch: ExchangeAccountPatch, *,
        if_match: datetime | None, expect_enabled: bool | None = None,
        write_ahead: AccountWriteAhead | None = None,
    ) -> ExchangeAccountRow | None:  # fmt: skip
        self._owner(scope)
        if self.before_write is not None:
            await self.before_write()
        async with self.lock:  # the row lock: one write at a time
            row = self.rows.get(account_id)
            if row is None:
                return None
            if if_match is not None and row.updated_at != if_match:
                raise AccountsStoreStaleError
            if expect_enabled is not None and row.is_enabled != expect_enabled:
                raise AccountsStoreUnchangedError
            changed = {"label": patch.label} if patch.label is not None else {}
            if patch.is_enabled is not None:
                changed["is_enabled"] = patch.is_enabled
            new = dataclasses.replace(row, updated_at=row.updated_at + timedelta(seconds=1),
                                      **changed)  # fmt: skip
            if write_ahead is not None:
                await write_ahead(new)
            self.rows[account_id] = new
            self.writes += 1
            return new


class Ports:
    """The consequence read's ports over the store's rows; `answer` is the key's exposure read."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.reset()

    def reset(self) -> None:
        self.answer: KeyExposure | KeyReadFailed = KeyExposure((), 0)
        self.reads = 0

    async def get_account(self, scope: Any, account_id: uuid.UUID) -> ExchangeAccount:
        if (row := self.store.rows.get(account_id)) is None:
            raise AccountNotFoundError("account")
        return ExchangeAccount.model_validate(row, from_attributes=True)

    async def list_keys(self, scope: Any, account_id: uuid.UUID) -> tuple[ApiKeyMetadata, ...]:
        return (key(KEY, account=account_id),)

    async def list_grantees(self, scope: Any, account_id: uuid.UUID) -> tuple[Any, ...]:
        return ()

    async def covering(self, account_id: uuid.UUID, *, limit: int) -> tuple[Any, ...]:
        return ()

    async def running(self, account_id: uuid.UUID) -> int:
        return 0

    async def read(self, account: ExchangeAccount, key_id: uuid.UUID) -> KeyExposure:
        self.reads += 1
        if isinstance(self.answer, KeyReadFailed):
            raise self.answer
        return self.answer


class Effects:
    """The lifecycle's effect ports: the app's own key standing and WS events behind a log, and
    recording stand-ins for the disarm and the stream close (`overrun` closes that overrun)."""

    def __init__(self) -> None:
        self.standings: Any = None
        self.ws: Any = None
        self.reset()

    def reset(self) -> None:
        self.log: list[str] = []
        self.overrun, self.counted = 0, list[str]()
        self.disarmed: list[dict[str, Any]] = []

    def hold(self, account_id: uuid.UUID, reason: Any) -> None:
        self.log.append("hold")
        self.standings.hold(account_id, reason)

    def release(self, account_id: uuid.UUID) -> bool:
        self.log.append("release")
        return bool(self.standings.release(account_id))

    async def account_revoked(self, account_id: uuid.UUID, reason: Any) -> int:
        self.log.append("ws")
        return int(await self.ws.account_revoked(account_id, reason))

    async def disarm(self, account_id: uuid.UUID, **kw: Any) -> None:
        self.log.append("disarm")
        self.disarmed.append(kw)

    async def close_private_streams(self, key_ref: str, *, reason: Any) -> tuple[uuid.UUID, ...]:
        self.log.append("close")
        if self.overrun:
            self.overrun -= 1
            raise PrivateStreamCloseOverran((GRANTED,))
        return (GRANTED,)

    def reopen_private_streams(self, key_ref: str, *, reason: Any) -> bool:
        self.log.append("lift")
        return True


@dataclasses.dataclass
class Served:
    world: World
    store: Store
    ports: Ports
    fx: Effects
    spends: list[str]


@pytest.fixture(scope="module")
def _served() -> Iterator[Served]:
    store, mp, fx = Store(), pytest.MonkeyPatch(), Effects()
    ports = Ports(store)

    def consequences(*_args: Any, env: str) -> ConsequenceRead:
        return ConsequenceRead(ports, ExposureRead(ports, env=env), ports, ports, env=env)

    def lifecycle(accounts: Any, _rules: Any, *, standings: Any, subscriptions: Any,
                  **_kw: Any) -> AccountLifecycle:  # fmt: skip
        fx.standings, fx.ws = standings, subscriptions
        return AccountLifecycle(accounts, fx, fx, fx, fx, count=lambda r: fx.counted.append(r))

    try:
        mp.setattr(appmod, "_build_accounts_counts", lambda _settings: store)
        mp.setattr(appmod, "wire_consequence_read", consequences)
        mp.setattr(appmod, "wire_account_lifecycle", lifecycle)
        world = build_world(mp)
        spends: list[str] = []
        consume = world.step_up.consume_single_use

        async def spending(session_id: str, action_class: str, *, fingerprint: str) -> Any:
            spent = await consume(session_id, action_class, fingerprint=fingerprint)
            spends.append(action_class)  # reached only when the grant was spent
            return spent

        mp.setattr(world.step_up, "consume_single_use", spending)
        yield Served(world, store, ports, fx, spends)
    finally:
        mp.undo()


@pytest.fixture
def served(_served: Served) -> Iterator[Served]:
    kept = dict(_served.store.rows)
    _served.world.audit.records.clear()
    _served.world.step_up.elevated, _served.world.step_up.classes = True, None
    for part in (_served.store, _served.ports, _served.fx):
        part.reset()
    _served.spends.clear()
    _served.fx.standings.release(GRANTED)
    yield _served
    _served.store.rows.clear()
    _served.store.rows.update(kept)
    _served.fx.standings.release(GRANTED)


def patch(
    s: Served, body: Any, *, actor: str = "owner", account: uuid.UUID = GRANTED,
    choice: str | None = None, if_match: str | None = None, key: str | None = None,
) -> httpx.Response:  # fmt: skip
    headers = bearer(actor) | ({} if if_match is None else {"If-Match": if_match})
    headers |= {} if key is None else {"Idempotency-Key": key}
    params = {} if choice is None else {"open_exposure": choice}
    url = PATH.format(accountId=account)
    resp: httpx.Response = s.world.client.patch(url, json=body, params=params, headers=headers)
    return resp


def answer(resp: httpx.Response) -> Any:
    """The body, once it validates against what the operation declares for its status."""
    status = resp.status_code
    declared = SPEC["paths"][PATH]["patch"]["responses"][str(status)]
    own = "#/paths/" + PATH.replace("/", "~1") + f"/patch/responses/{status}"
    pointer = declared.get("$ref", own)
    media = "application~1json" if status < 400 else "application~1problem+json"
    validate_example(f"{pointer.removeprefix('#')}/content/{media}/schema", resp.json())
    if status == 200:
        validate_example("/components/headers/AccountETag/schema", resp.headers["etag"])
        assert resp.headers["etag"] == f'W/"{resp.json()["updated_at"]}"'
    return resp.json()


def records(s: Served, action: str) -> list[dict[str, Any]]:
    return [r for r in s.world.audit.records if r["action"] == action]


def tag(s: Served, account: uuid.UUID = GRANTED) -> str:
    stamp = s.store.rows[account].updated_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return f'W/"{stamp}"'


def test_the_operation_is_served_and_its_records_registered(served: Served) -> None:
    assert ("PATCH", PATH) in served_operations(served.world.app)
    assert {"account.disabled", "account.updated"} <= AUDIT_ACTIONS


def test_the_owner_disables_a_flat_account_recorded_ahead_then_every_effect_in_order(
    served: Served,
) -> None:
    resp = patch(served, DISABLE)
    body = answer(resp)
    assert (resp.status_code, body["enabled"]) == (200, False)
    assert body["updated_at"] == "2026-10-26T07:35:13.000000Z"  # six digits on a whole second
    (record,) = records(served, "account.disabled")
    assert (record["outcome"], record["object_id"]) == ("success", str(GRANTED))
    assert record["after_state"]["enabled"] is False and record["after_state"]["challenge_id"]
    assert record["before_state"] == {"label": "Granted", "enabled": True}
    assert served.fx.log == EFFECTS and served.spends == ["accounts"]
    assert served.fx.disarmed[0]["lifecycle"] == "account_disabled"
    assert served.fx.counted == ["flat"] and served.ports.reads == 1


@pytest.mark.parametrize("actor", ["manager_with_grant", "manager_without_grant", "viewer"])
@pytest.mark.parametrize("account", [GRANTED, FOREIGN, ABSENT])
def test_no_role_but_the_owner_disables_403_audited_never_challenged(
    served: Served, actor: str, account: uuid.UUID
) -> None:
    served.world.step_up.elevated = False  # unelevated: still never a challenge
    resp = patch(served, DISABLE, actor=actor, account=account)
    assert (resp.status_code, answer(resp)["code"]) == (403, "forbidden")
    (record,) = served.world.audit.records
    assert (record["action"], record["object_id"]) == ("rbac.denied", str(account))
    assert (served.store.calls, served.ports.reads, served.spends) == (0, 0, [])
    assert served.fx.log == []


def test_a_managers_foreign_and_absent_answers_are_byte_equal(served: Served) -> None:
    foreign = patch(served, DISABLE, actor="manager_with_grant", account=FOREIGN)
    assert (
        foreign.content
        == patch(served, DISABLE, actor="manager_with_grant", account=ABSENT).content
    )


def test_absent_and_other_environment_accounts_are_one_404_before_the_gate(served: Served) -> None:
    served.world.step_up.elevated = False
    absent, other = (
        patch(served, DISABLE, account=ABSENT),
        patch(served, DISABLE, account=OTHER_ENV),
    )
    assert (absent.status_code, answer(absent)["code"]) == (404, "not_found")
    assert absent.content == other.content and served.spends == []


@pytest.mark.parametrize(
    ("body", "rule"),
    [({}, "empty_patch"), ({"active_profile_id": str(KEY)}, "empty_patch"),
     ({"enabled": False, "margin_mode": "isolated"}, "mode_change_unavailable"),
     ({"position_mode": "hedge"}, "mode_change_unavailable")],
)  # fmt: skip
def test_a_422_is_decided_before_the_gate_and_spends_no_code(
    served: Served, body: dict[str, Any], rule: str
) -> None:
    served.world.step_up.elevated = False
    resp = patch(served, body)
    got = answer(resp)
    assert (resp.status_code, got["errors"][0]["rule"]) == (422, rule)
    assert (served.spends, served.store.writes, served.ports.reads) == ([], 0, 0)


def test_an_open_exposure_outside_its_enum_is_422_before_the_gate(served: Served) -> None:
    served.world.step_up.elevated = False
    resp = patch(served, DISABLE, choice="close_all")
    assert resp.status_code == 422 and served.spends == [] and served.ports.reads == 0


def test_a_stale_if_match_is_412_before_the_gate_spending_nothing_reading_nothing(
    served: Served,
) -> None:
    served.world.step_up.elevated = False
    resp = patch(served, DISABLE, if_match='W/"2026-10-26T07:35:11.000000Z"')
    assert (resp.status_code, answer(resp)["code"]) == (412, "version_conflict")
    assert (served.spends, served.ports.reads, served.store.writes) == ([], 0, 0)
    assert served.world.audit.records == []


def test_an_unelevated_disable_is_challenged_restating_it_with_the_typed_label(
    served: Served,
) -> None:
    served.world.step_up.elevated = False
    got = answer(patch(served, DISABLE, choice="leave_positions"))
    assert (got["code"], got["action_class"]) == ("step_up_required", "accounts")
    summary = "Disable account 'Granted' (demo, UID 1000001), open_exposure=leave_positions"
    assert (got["action_summary"], got["target"]) == (summary, "Granted")
    assert served.ports.reads == 0 and served.store.writes == 0
    twin = dataclasses.replace(served.store.rows[FOREIGN], label="GRANTED")  # not unique
    served.store.rows[FOREIGN] = twin
    assert answer(patch(served, DISABLE))["target"] == str(GRANTED)


def test_an_unelevated_re_enable_is_challenged_with_no_target(served: Served) -> None:
    served.store.rows[GRANTED] = dataclasses.replace(served.store.rows[GRANTED], is_enabled=False)
    served.world.step_up.elevated = False
    got = answer(patch(served, {"enabled": True}, choice="leave_positions"))  # the choice ignored
    assert got["action_summary"] == "Re-enable account 'Granted' (demo, UID 1000001)"
    assert got.get("target") is None


def test_a_keys_grant_never_admits_a_disable(served: Served) -> None:
    served.world.step_up.classes = frozenset({"keys"})
    resp = patch(served, DISABLE)
    assert (resp.status_code, answer(resp)["action_class"]) == (403, "accounts")
    assert served.store.writes == 0 and served.fx.log == []


def test_a_label_only_patch_takes_no_step_up_and_is_recorded_ahead(served: Served) -> None:
    served.world.step_up.elevated = False
    resp = patch(served, {"label": "Renamed"}, if_match=tag(served))
    assert (resp.status_code, answer(resp)["label"]) == (200, "Renamed")
    (record,) = records(served, "account.updated")
    assert record["before_state"]["label"] == "Granted"
    assert record["after_state"]["label"] == "Renamed"
    assert served.spends == [] and served.fx.log == []


def test_a_label_patch_racing_a_disable_is_412_and_changes_nothing(served: Served) -> None:
    sent = tag(served)

    async def disabled_meanwhile() -> None:
        row = served.store.rows[GRANTED]
        later = row.updated_at + timedelta(microseconds=1)
        served.store.rows[GRANTED] = dataclasses.replace(row, is_enabled=False, updated_at=later)

    served.store.before_write = disabled_meanwhile
    resp = patch(served, {"label": "Renamed"}, if_match=sent)
    assert (resp.status_code, answer(resp)["code"]) == (412, "version_conflict")
    assert (
        served.store.rows[GRANTED].label == "Granted" and records(served, "account.updated") == []
    )


def test_a_disable_whose_tag_moves_after_the_gate_is_412_recorded_denied_grant_spent(
    served: Served,
) -> None:
    async def relabelled_meanwhile() -> None:
        row = served.store.rows[GRANTED]
        served.store.rows[GRANTED] = dataclasses.replace(
            row, label="Moved", updated_at=row.updated_at + timedelta(microseconds=1)
        )

    served.store.before_write = relabelled_meanwhile
    resp = patch(served, DISABLE, if_match=tag(served))
    assert (resp.status_code, answer(resp)["code"]) == (412, "version_conflict")
    (record,) = records(served, "account.disabled")
    assert (record["outcome"], record["reason"]) == ("denied", "version_conflict")
    assert served.spends == ["accounts"] and served.fx.log == []


def test_leave_positions_with_a_position_lacking_a_native_stop_is_409_c_2_6(
    served: Served,
) -> None:
    served.ports.answer = KeyExposure((PROTECTED, BARE), 0)
    resp = patch(served, DISABLE, choice="leave_positions")
    got = answer(resp)
    assert (resp.status_code, got["code"]) == (409, "open_exposure")
    assert [p["native_stop_present"] for p in got["consequences"]["open_positions"]] == [
        True,
        False,
    ]
    (record,) = records(served, "account.disabled")
    assert (record["outcome"], record["reason"]) == ("denied", "open_exposure")
    assert record["after_state"]["why"] == "native_stop_missing"
    assert served.store.writes == 0 and served.fx.log == [] and served.spends == ["accounts"]


@pytest.mark.parametrize(
    ("choice", "why"), [(None, "no_choice"), ("flatten_first", "still_not_flat")]
)
def test_a_non_flat_account_without_leave_positions_is_409_and_nothing_changes(
    served: Served, choice: str | None, why: str
) -> None:
    served.ports.answer = KeyExposure((PROTECTED,), 2)
    resp = patch(served, DISABLE, choice=choice)
    assert (resp.status_code, answer(resp)["code"]) == (409, "open_exposure")
    assert records(served, "account.disabled")[0]["after_state"]["why"] == why
    assert served.store.writes == 0 and served.fx.log == []


def test_leave_positions_with_every_position_stopped_disables_the_account(served: Served) -> None:
    served.ports.answer = KeyExposure((PROTECTED,), 1)
    resp = patch(served, DISABLE, choice="leave_positions")
    assert (resp.status_code, answer(resp)["enabled"]) == (200, False)
    assert served.fx.counted == ["leave_positions"] and served.fx.log == EFFECTS


def test_a_fixable_refusal_is_409_with_its_remedy_for_every_choice(served: Served) -> None:
    served.ports.answer = KeyReadFailed("ip_not_allowed")
    resp = patch(served, DISABLE, choice="leave_positions")
    got = answer(resp)
    assert (resp.status_code, got["code"], got["remedy"]) == (409, "exposure_unknown", "fix_key")
    assert "consequences" not in got and served.store.writes == 0


def test_a_dead_account_is_disabled_only_with_leave_positions_its_record_saying_why(
    served: Served,
) -> None:
    served.ports.answer = KeyReadFailed("auth_error")
    refused = patch(served, DISABLE)
    assert answer(refused)["remedy"] == "leave_positions" and served.store.writes == 0
    served.world.audit.records.clear()
    resp = patch(served, DISABLE, choice="leave_positions")
    assert (resp.status_code, answer(resp)["enabled"]) == (200, False)
    (record,) = records(served, "account.disabled")
    after = record["after_state"]
    assert (after["code"], after["lifted"]) == ("exposure_unknown", True)
    assert after["key_errors"] == [{"key_id": str(KEY), "error": "auth_error"}]
    assert served.fx.counted == ["dead"]


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [("timeout", 503, "exchange_unavailable"), ("rate_limited", 502, "exchange_error")],
)
def test_a_failed_read_fails_closed_unrecorded_and_never_kept_for_replay(
    served: Served, failure: str, status: int, code: str
) -> None:
    served.ports.answer = KeyReadFailed(failure, 10006 if status == 502 else None)
    once = str(uuid.uuid4())
    first = patch(served, DISABLE, key=once)
    assert (first.status_code, answer(first)["code"]) == (status, code)
    assert records(served, "account.disabled") == [] and served.store.writes == 0
    served.ports.answer = KeyExposure((), 0)
    again = patch(served, DISABLE, key=once)  # a first submission: read again, then disabled
    assert again.status_code == 200 and "idempotency-replayed" not in again.headers
    assert served.ports.reads == 2


def test_a_repeat_disable_answers_200_unchanged_with_no_record_and_reads_nothing(
    served: Served,
) -> None:
    served.store.rows[GRANTED] = dataclasses.replace(served.store.rows[GRANTED], is_enabled=False)
    resp = patch(served, DISABLE, choice="flatten_first")
    assert (resp.status_code, answer(resp)["updated_at"]) == (200, "2026-10-26T07:35:12.000000Z")
    assert records(served, "account.disabled") == [] and served.ports.reads == 0
    assert served.fx.log == EFFECTS and served.spends == ["accounts"]  # the caller's cost


def test_a_crash_between_the_commit_and_the_effects_is_completed_by_the_repeat(
    served: Served,
) -> None:
    """The row says disabled (the commit landed) and no effect ran: the account is held by its
    stored flag, and the repeat completes the hold, the revoke, the disarm and the close."""
    served.store.rows[GRANTED] = dataclasses.replace(served.store.rows[GRANTED], is_enabled=False)
    assert served.fx.standings.closed(GRANTED) is False  # no tracking read on this world yet
    resp = patch(served, DISABLE)
    assert resp.status_code == 200 and served.fx.log == EFFECTS
    assert served.fx.standings.closed(GRANTED) is True and records(served, "account.disabled") == []


def test_two_concurrent_disables_store_once_and_record_once(served: Served) -> None:
    """Ruling 6: both read the account enabled; the second's compare-and-set finds it disabled and
    is a repeat."""
    arrived = asyncio.Event()
    waiting = 0

    async def together() -> None:
        nonlocal waiting
        waiting += 1
        if waiting == 2:
            arrived.set()
        await arrived.wait()

    served.store.before_write = together

    async def both() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=served.world.app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            sent = [
                c.patch(PATH.format(accountId=GRANTED), json=DISABLE,
                        headers=bearer("owner") | {"origin": WS_ORIGIN})
                for _ in range(2)
            ]  # fmt: skip
            return list(await asyncio.gather(*sent))

    answers = asyncio.run(both())
    assert [r.status_code for r in answers] == [200, 200]
    assert len(records(served, "account.disabled")) == 1 and served.store.writes == 1
    assert served.fx.counted == ["flat"]


@pytest.mark.parametrize("enabled", [False, True])
def test_a_flip_landing_inside_the_gate_is_decided_on_the_state_after_it(
    served: Served, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    """Round-1 F-1: the account read before the gate says this request is a repeat, and a
    concurrent request flips it while the grant is spent. The route re-reads after the gate, so
    the request is a change: stored with its record, never a repeat's effects on an account the
    row no longer matches."""
    rows, consume = served.store.rows, served.world.step_up.consume_single_use
    rows[GRANTED] = dataclasses.replace(rows[GRANTED], is_enabled=enabled)

    async def flipped(session_id: str, action_class: str, *, fingerprint: str) -> Any:
        rows[GRANTED] = dataclasses.replace(rows[GRANTED], is_enabled=not enabled)
        return await consume(session_id, action_class, fingerprint=fingerprint)

    monkeypatch.setattr(served.world.step_up, "consume_single_use", flipped)
    resp = patch(served, {"enabled": enabled})
    assert (resp.status_code, answer(resp)["enabled"]) == (200, enabled)
    assert rows[GRANTED].is_enabled is enabled and served.store.writes == 1
    action = "account.updated" if enabled else "account.disabled"
    (record,) = records(served, action)
    assert record["before_state"]["enabled"] is not enabled
    assert served.fx.log == (["lift", "release"] if enabled else EFFECTS)
    assert served.fx.standings.closed(GRANTED) is not enabled


def test_an_overrun_close_is_503_with_retry_after_and_the_retry_completes_it(
    served: Served,
) -> None:
    served.fx.overrun = 1
    once = str(uuid.uuid4())
    resp = patch(served, DISABLE, key=once)
    got = answer(resp)
    assert (resp.status_code, got["code"]) == (503, "exchange_unavailable")
    assert resp.headers["retry-after"] and served.store.rows[GRANTED].is_enabled is False
    assert len(records(served, "account.disabled")) == 1  # stored, its record ahead
    served.fx.log.clear()
    again = patch(served, DISABLE, key=once)  # never kept: a first submission, now a repeat
    assert again.status_code == 200 and "idempotency-replayed" not in again.headers
    assert served.fx.log == EFFECTS and len(records(served, "account.disabled")) == 1


def test_a_re_enable_lifts_before_it_stores_and_releases_after_recorded_ahead(
    served: Served,
) -> None:
    assert patch(served, DISABLE).status_code == 200
    served.fx.log.clear()
    resp = patch(served, {"enabled": True, "label": "Back"})
    body = answer(resp)
    assert (resp.status_code, body["enabled"], body["label"]) == (200, True, "Back")
    assert served.fx.log == ["lift", "release"]
    (record,) = records(served, "account.updated")
    assert record["after_state"]["enabled"] is True and record["after_state"]["challenge_id"]
    assert served.fx.standings.closed(GRANTED) is False


def test_a_new_sub_on_a_disabled_account_is_refused_until_its_re_enable(served: Served) -> None:
    """F-01 end to end: the app binds the WS scope to the key standing the disable holds."""
    world = served.world

    def subscribed() -> str:
        with world.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            assert _auth(ws, "owner")["t"] == "auth_ok"
            result = _sub(ws, "orders", GRANTED)
        return "sub_ok" if result["ok"] else str(result["error"]["code"])

    assert subscribed() == "sub_ok"
    assert patch(served, DISABLE).status_code == 200
    assert subscribed() == "account_scope_denied"
    assert patch(served, {"enabled": True}).status_code == 200
    assert subscribed() == "sub_ok"


def test_the_same_key_replays_the_answer_behind_a_fresh_code_and_another_request_is_409(
    served: Served,
) -> None:
    once = str(uuid.uuid4())
    served.ports.answer = KeyExposure((PROTECTED,), 0)
    first = patch(served, DISABLE, key=once)  # 409 open_exposure: kept (22)
    again = patch(served, DISABLE, key=once)
    assert (again.status_code, again.content) == (first.status_code, first.content) == (
        409, first.content,
    )  # fmt: skip
    assert again.headers["idempotency-replayed"] == "true" and served.ports.reads == 1
    reuse = patch(served, DISABLE, key=once, choice="leave_positions")
    assert (reuse.status_code, answer(reuse)["code"]) == (409, "idempotency_key_reuse")
    assert served.spends == ["accounts"] * 3  # each behind its own fresh code
    served.world.step_up.elevated = False
    assert patch(served, DISABLE, key=once).json()["code"] == "step_up_required"


def test_no_answer_and_no_record_carries_key_material_or_exchange_text(served: Served) -> None:
    served.ports.answer = KeyReadFailed("auth_error")
    shown = [patch(served, DISABLE).text, patch(served, DISABLE, choice="leave_positions").text]
    shown.append(json.dumps(served.world.audit.records, default=str))
    for text in shown:
        assert "A1b2" not in text and "AbC1" not in text  # the keys' last four
        assert "ret_msg" not in text and "permission_snapshot" not in text


# -- hpe-worker-2's B3b2 review notes (items 5-7) --------------------------------------------------


@pytest.mark.parametrize(
    ("body", "choice"),
    [(DISABLE, "flatten_first"), (DISABLE, None), ({"enabled": False, "label": "Granted"},
                                                    "leave_positions")],
)  # fmt: skip
def test_a_grant_bound_to_one_disable_admits_no_other_query_or_body(
    served: Served, monkeypatch: pytest.MonkeyPatch, body: dict[str, Any], choice: str | None
) -> None:
    """Item 5: the harness's grant ignores the fingerprint, so this one binds it as the real
    `StepUpService.consume_single_use` does. The grant is for `PATCH` of the raw target with its
    query and the validated body; another `open_exposure` (or none) or another body is a mismatch,
    never admitted, and the bound request itself is."""
    path = PATH.format(accountId=GRANTED).encode()
    bound = request_fingerprint("PATCH", path + b"?open_exposure=leave_positions", DISABLE)
    assert bound != request_fingerprint("PATCH", path, DISABLE)  # the path alone is not enough
    seen: list[str] = []
    pending = served.world.step_up.record_pending

    async def bound_grant(session_id: str, action_class: str, *, fingerprint: str) -> Any:
        seen.append(fingerprint)
        if fingerprint != bound:
            who, challenge = str(user_id_of("owner")), str(uuid.uuid4())
            raise StepUpMismatch(
                action_class, user_id=who, challenge_id=challenge, bound=bound, refused=fingerprint
            )
        return await pending(session_id, action_class, fingerprint=fingerprint)

    monkeypatch.setattr(served.world.step_up, "consume_single_use", bound_grant)
    refused = patch(served, body, choice=choice)
    assert (refused.status_code, answer(refused)["code"]) == (403, "step_up_required")
    assert seen == [refused_fp := seen[0]] and refused_fp != bound
    assert (served.store.writes, served.ports.reads, served.fx.log) == (0, 0, [])
    admitted = patch(served, DISABLE, choice="leave_positions")
    assert admitted.status_code == 200 and seen[-1] == bound


@pytest.mark.parametrize("refusal", ["open_exposure", "version_conflict"])
def test_a_refusal_after_the_gate_whose_record_cannot_be_written_is_503_audit_unavailable(
    served: Served, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    """Item 6: `denied()` writes its record ahead of the answer (R4); a record that cannot be
    written is `503 audit_unavailable`, the grant spent and nothing changed."""
    sink, if_match = served.world.audit, None
    emit = sink.emit

    async def refusing(action: str, **kw: Any) -> None:
        if kw.get("outcome") == "denied" and action == "account.disabled":
            raise AuditError("the audit writer is down")
        await emit(action, **kw)

    monkeypatch.setattr(sink, "emit", refusing)
    if refusal == "open_exposure":
        served.ports.answer = KeyExposure((BARE,), 0)
    else:
        if_match = tag(served)

        async def moved() -> None:
            row = served.store.rows[GRANTED]
            later = row.updated_at + timedelta(microseconds=1)
            served.store.rows[GRANTED] = dataclasses.replace(row, label="Moved", updated_at=later)

        served.store.before_write = moved
    resp = patch(served, DISABLE, choice="leave_positions", if_match=if_match)
    assert (resp.status_code, answer(resp)["code"]) == (503, "audit_unavailable")
    assert records(served, "account.disabled") == [] and served.spends == ["accounts"]
    assert served.store.rows[GRANTED].is_enabled and served.fx.log == []


def test_the_exposure_unknown_409_is_kept_and_replayed_under_its_key(served: Served) -> None:
    """Item 6: like the `open_exposure` `409`, `exposure_unknown` is kept for the key's replay
    (ruling R5): read once, recorded once, the same bytes behind a fresh code."""
    served.ports.answer = KeyReadFailed("ip_not_allowed")
    once = str(uuid.uuid4())
    first = patch(served, DISABLE, key=once)
    assert (first.status_code, answer(first)["code"]) == (409, "exposure_unknown")
    again = patch(served, DISABLE, key=once)
    assert (again.status_code, again.content) == (409, first.content)
    assert again.headers["idempotency-replayed"] == "true" and served.ports.reads == 1
    assert len(records(served, "account.disabled")) == 1 and served.spends == ["accounts"] * 2


def test_an_empty_label_is_422_by_the_declared_min_length_before_anything(served: Served) -> None:
    """Item 7: 22's `UpdateExchangeAccountRequest.label` has `minLength: 1`, as the create's has."""
    label = SPEC["components"]["schemas"]["UpdateExchangeAccountRequest"]["properties"]["label"]
    assert label["minLength"] == 1
    served.world.step_up.elevated = False
    resp = patch(served, {"label": ""})
    got = answer(resp)
    assert (resp.status_code, got["code"]) == (422, "validation_failed")
    (error,) = got["errors"]
    assert (error["field"], error["rule"]) == ("body.label", "string_too_short")
    assert (served.store.writes, served.spends, served.world.audit.records) == (0, [], [])
