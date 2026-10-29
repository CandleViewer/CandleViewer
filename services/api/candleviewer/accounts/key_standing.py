"""Key standing for the order-entry gate (E27-T04 W3, #837; SR-E27-18; 24-internal-schemas §8.4.1).

`KeyStandings` is the `order_gate.KeyStandingPort` that the account check of the composed gate
reads, and the `wallet.CredentialRejections` a signed call reports a rejected credential to. It
answers from memory only, synchronously and with no I/O (C-2.21):

- Accounts and their usable keys come from the account-health tracking read (`observe`, every
  `TRACKING_REFRESH_S`). An account that read did not list has no standing (`None`, refused); one
  switched off or not armed for trading (`trading_enabled` false) is disabled by policy. No account
  has a standing once the last good read is older than `stale_after_s` on the monotonic clock (the
  wiring's `TRACKING_FAULT_AFTER_S`), so reads that keep failing never leave a frozen list
  admitting an account switched off, deleted or stripped of its keys since.
- A key is active only while its last recorded pass is inside the self-check's window, by the
  check's own rule `selfcheck.is_fresh` at read time (the admission-time half of SR-E27-18), so a
  stalled or dead job cannot keep it green. The job's result (`KeySelfCheck.results`, read at each
  call) decides; for a key it holds none for, the stored pass and error code do, as the job judges
  them (decision 3 on #836). A failed key is never active, and it disables the account at once, as
  the job disarms it on every failure: by its rule's own reason when that is a key-policy one,
  otherwise as switched off.
- A rejected credential (`credential_rejected`, 24 §8.6, Option A on #837) takes effect at once,
  held before it is logged: `unknown_key` (10003) and `key_expired` leave no active key;
  `permission_denied` (10005) and `ip_not_allowed` (10010) disable the account by policy. Only a
  later recorded pass of one of the account's keys, not failed since, clears it: one whose check
  began after the rejection and that was not known when it arrived, so a pass the standing already
  knew never clears it. Passes are dated on the wall clock: a check already in flight when the
  rejection arrives, dated after it by a wall-clock step back, can clear it once, until the next
  signed call meets the refusal again (the residual accepted under Option A). Health evidence
  never reaches it, nor is a rejection health evidence (KV-T12). A standing read answers a
  rejection a later pass has cleared as cleared, and keeps it: the next tracking read drops it, so
  should the pass leave the evidence first, the rejection is in force again (it refuses longer,
  never less). One fact per listed account, so what is held is bounded by the read (C-2.18); one
  for an unlisted account is logged and dropped (it is refused).
- A route that disables, deletes or revokes (E27-S04, #898; 24 §8.4.1) holds the standing
  synchronously, once its change is stored and before it returns. The lifecycle hold
  (`hold`, `account_disabled` or `account_deleted`) disables the account by policy and only the
  re-enable's `release` lifts it, and only an `account_disabled` one: no tracking read releases
  it, whenever that read began. A revoke's hold (`revoke`) leaves the revoked key out of the
  account's keys, so its passes neither make the account active nor clear a rejection; it ends
  only with a read that began after it (`read_begins`, given back to `observe`) and no longer
  lists the key, since a read begun before may list it as it was. One hold per account, and its
  revoked keys end with the reads (C-2.18); `credential_rejected` is unchanged for the other
  keys' passes.

Codes only, never exchange text, a key id or a permission list. The durable section 8.6 reaction
(the key marked `invalid`, the account disarmed) is the submit pipeline's (#913); a restart forgets
the fact, and the boot self-check judges the key afresh. A call reads the account's own keys only.

Read from the order lane; written on the serving loop (#913 slice 3 L4, 20-architecture.md 6.2).
`observe`, `credential_rejected`, `hold`, `release` and `revoke` run on the serving loop only (the
tracking loop, the reconciler, the lane's notices, the account routes), and each publishes anew the
one snapshot a read answers from (`_State`: the accounts the last good read listed, their
rejections, the holds and that read's age), by a single assignment, never changing one in place.
`standing()` writes nothing and takes that reference once, by one attribute read, which runs no
Python code another thread could interleave: a read on another thread meets a write whole or not at
all, and every read that begins after a write returns sees it. It reads the self-check's results
once a call too, a key at a time with one `get` each, never iterating them: the job replaces the
mapping at each pass's key-list read and stores each key's result in it, on the serving loop, never
clearing or popping it. A UUID key's hash and comparison are Python code, so a store can land inside
a `get`, but CPython restarts a lookup whose mapping changed under it: each `get` answers from the
mapping before the store or after it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.health import Clock
from candleviewer.accounts.order_gate import DisabledReason, KeyStanding
from candleviewer.accounts.selfcheck import STANDING_FAILURE_CODES, KeyCheck, is_fresh
from candleviewer.accounts.verification import Refusal
from candleviewer.storage.repositories.accounts import SelfCheckTargetRow

#: 24-internal-schemas.md section 8.6, what a rejected credential does to the account's standing
#: until a later pass: `None` leaves it with no active key (AUTH_ERROR marks the key `invalid`, and
#: an expired key is no better); a `DisabledReason` disables it by policy (PERMISSION_DENIED
#: disables trading on the account, IP_NOT_ALLOWED the account). A refusal missing here leaves no
#: active key: fail closed.
REACTIONS: Final[Mapping[Refusal, DisabledReason | None]] = {
    Refusal.UNKNOWN_KEY: None,
    Refusal.KEY_EXPIRED: None,
    Refusal.PERMISSION_DENIED: DisabledReason.ACCOUNT_DISABLED,
    Refusal.IP_NOT_ALLOWED: DisabledReason.KEY_IP_WHITELIST_MISMATCH,
}
_POLICY: Final[Mapping[str | None, DisabledReason]] = {r.value: r for r in DisabledReason}
#: What the lifecycle hold names (24 §8.4.1): only the re-enable's `release` lifts the first.
type HoldReason = Literal["account_disabled", "account_deleted"]


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class SelfCheckResults(Protocol):
    """What the standing reads of the stored-key self-check (`selfcheck.KeySelfCheck`): each key's
    standing result, by key id. Read once a call, a key at a time and never iterated: the job
    replaces the mapping at each pass and stores each key's result in it, never clearing or popping
    it (module docstring)."""

    @property
    def results(self) -> Mapping[UUID, KeyCheck]: ...


@dataclass(frozen=True, slots=True)
class _Key:
    """One usable key as the read listed it: its stored last pass and last error code."""

    key_id: UUID
    verified_at: datetime
    error_code: str | None


@dataclass(frozen=True, slots=True)
class _Account:
    armed: bool  # enabled, with trading armed
    keys: tuple[_Key, ...]
    enabled: bool = True  # `is_enabled` as the read listed it, until a re-enable's `release`


@dataclass(frozen=True, slots=True)
class _Judged:
    """One key as the self-check judges it now: whether it failed, the code, and its last pass."""

    key_id: UUID
    failed: bool
    code: str | None
    last_pass_at: datetime


@dataclass(frozen=True, slots=True)
class _Rejection:
    no_key: bool
    disabled: DisabledReason | None
    at: datetime
    #: Each key's last pass when the rejection arrived: none of these clears it.
    seen: frozenset[tuple[UUID, datetime]]


@dataclass(frozen=True, slots=True)
class _Hold:
    """What the routes held of one account: the lifecycle hold's reason, if any, and each revoked
    key with the generation of its telling (`KeyStandings.read_begins`)."""

    reason: HoldReason | None
    revoked: Mapping[UUID, int]


_NO_HOLD: Final = _Hold(None, {})


@dataclass(frozen=True, slots=True)
class _State:
    """What a read answers from, published anew by each write and never changed in place (module
    docstring): each account the last good read listed, the rejections held for them (one a later
    pass has cleared until the next read drops it), and when that read was taken on the monotonic
    clock."""

    accounts: Mapping[UUID, _Account]
    rejections: Mapping[UUID, _Rejection]
    read_at: float
    holds: Mapping[UUID, _Hold]


class KeyStandings:
    """Over the self-check `selfcheck` (`None` on the fake backend: stored passes only), its window
    `interval_s`, the age bound `stale_after_s` of the last good read, and `clock`: the wall time
    the self-check dates passes on, and the monotonic time that ages the read (module docstring)."""

    def __init__(
        self,
        selfcheck: SelfCheckResults | None,
        *,
        interval_s: float,
        stale_after_s: float,
        clock: Clock,
    ) -> None:
        self._selfcheck, self._interval_s, self._clock = selfcheck, interval_s, clock
        self._stale_after_s = stale_after_s
        #: Published anew by every write, never changed in place.
        self._state = _State({}, {}, float("-inf"), {})
        self._told = 0  # the holds' generation: one per `revoke`

    def observe(self, rows: Iterable[SelfCheckTargetRow], *, began: int | None = None) -> None:
        """Take one usable-key read of the environment whole, reduced at once to each account's
        keys (id, stored pass, error code) and armed flag, keeping no row, and publish it with the
        rejections still in force: an account it does not list has no standing and loses its
        rejection, and a rejection a later pass has cleared, as this read and the self-check's
        result judge it, is dropped here, never by a read. A failed read never gets here. A
        revoked key told before the read began (`began`, from `read_begins`) and not listed by it
        leaves its hold; a read that does not say when it began ends none, and no read ends a
        lifecycle hold."""
        keys: dict[UUID, list[_Key]] = {}
        armed: dict[UUID, bool] = {}
        enabled: dict[UUID, bool] = {}
        for row in rows:
            account = row.account
            stored = _Key(row.key_id, row.verified_at, row.last_error_code)
            keys.setdefault(account.id, []).append(stored)
            armed[account.id] = account.is_enabled and account.trading_enabled
            enabled[account.id] = account.is_enabled
        accounts = {a: _Account(armed[a], tuple(ks), enabled[a]) for a, ks in keys.items()}
        state, results = self._state, self._results()
        holds = state.holds if began is None else _ended(state.holds, accounts, began)
        rejections = {
            a: r
            for a, r in state.rejections.items()
            if a in accounts
            and _held(r, _judge(accounts[a], results, holds.get(a, _NO_HOLD))) is not None
        }
        self._state = _State(accounts, rejections, self._clock.monotonic(), holds)

    @property
    def read_once(self) -> bool:
        """Whether a good tracking read has been taken: the OMS startup waits for the first (#913,
        20-architecture.md 6.2 step 1), so a create a restart resumes is not refused for want of
        it."""
        return self._state.read_at != float("-inf")

    def standing(self, account_id: UUID) -> KeyStanding | None:
        """The account's standing now; `None` if the last good read did not list it or is older
        than `stale_after_s`. It writes nothing: a rejection a later pass has cleared is answered
        cleared and kept for the next tracking read to drop (module docstring)."""
        state = self._state
        account = state.accounts.get(account_id)
        if account is None or self._clock.monotonic() - state.read_at > self._stale_after_s:
            return None
        hold = state.holds.get(account_id, _NO_HOLD)
        keys = _judge(account, self._results(), hold)
        rejection = _held(state.rejections.get(account_id), keys)
        now, interval_s = self._clock.now(), self._interval_s
        active = any(
            not key.failed and is_fresh(key.last_pass_at, now=now, interval_s=interval_s)
            for key in keys
        )
        # every failed key disables, as the job disarms on every failure (module docstring)
        failed = (_POLICY.get(k.code, DisabledReason.ACCOUNT_DISABLED) for k in keys if k.failed)
        disabled = next(failed, None)
        if rejection is not None:
            active = active and not rejection.no_key
            disabled = disabled or rejection.disabled
        if disabled is None and (hold.reason is not None or not account.armed):
            disabled = DisabledReason.ACCOUNT_DISABLED
        return KeyStanding(active, disabled)

    def closed(self, account_id: UUID) -> bool:
        """23 §9.5 (F-01, #898 B3b2): whether a new WS `sub` naming the account is refused for it,
        synchronously and from memory: under a lifecycle hold, when the last good read listed it
        disabled (so the refusal outlives a restart: the read lists `is_enabled=false` again), or
        when every key that read listed is revoked here. An account no read listed is not closed
        by this: one that never had a key, or before the first read. So after a restart a
        disabled account with no key row is subscribable until a read lists it; it has no signable
        key, so no private stream feeds it, and the order gate's `standing()` is `None` for it
        (fail-closed)."""
        state = self._state
        hold = state.holds.get(account_id, _NO_HOLD)
        if hold.reason is not None:
            return True
        account = state.accounts.get(account_id)
        if account is None:
            return False
        return not account.enabled or all(key.key_id in hold.revoked for key in account.keys)

    def read_begins(self) -> int:
        """Called as a tracking read begins, before its await: its generation, which `observe`
        takes back as `began`, so a read in flight when a key is revoked never ends that hold."""
        return self._told

    def hold(self, account_id: UUID, reason: HoldReason) -> None:
        """The account's disable or delete is stored: from now on it is disabled by policy, held
        before it is logged, until the re-enable's `release` (an `account_disabled` hold only; a
        delete's is never released). No tracking read ends it, whenever that read began. A delete
        held over a disable stays a delete."""
        state = self._state
        prior = state.holds.get(account_id, _NO_HOLD)
        kept: HoldReason = "account_deleted" if prior.reason == "account_deleted" else reason
        self._publish(state, account_id, _Hold(kept, prior.revoked))
        logger().warning("account.standing_held", account_id=str(account_id), reason=kept)

    def release(self, account_id: UUID) -> bool:
        """The account's re-enable is stored: its `account_disabled` hold ends (`True`), the
        listed account counts as enabled for `closed`, and the tracking read's rows decide again.
        A delete's hold, or none, is left as it is (`False`); a revoked key stays out until a read
        lets it go."""
        state = self._state
        listed = state.accounts.get(account_id)
        if listed is not None and not listed.enabled:  # stored enabled: no read waited for
            accounts = {**state.accounts, account_id: replace(listed, enabled=True)}
            self._state = state = _State(accounts, state.rejections, state.read_at, state.holds)
        prior = state.holds.get(account_id, _NO_HOLD)
        if prior.reason != "account_disabled":
            return False
        self._publish(state, account_id, _Hold(None, prior.revoked))
        logger().info("account.standing_released", account_id=str(account_id))
        return True

    def revoke(self, account_id: UUID, key_id: UUID) -> None:
        """The revoke of `key_id` is stored: from now on it is no key of the account here, so its
        passes make nothing active and clear no rejection, held before it is logged, until a
        read begun after this call no longer lists it (module docstring)."""
        self._told += 1
        state = self._state
        prior = state.holds.get(account_id, _NO_HOLD)
        revoked = {**prior.revoked, key_id: self._told}
        self._publish(state, account_id, _Hold(prior.reason, revoked))
        logger().warning("account.standing_key_revoked", account_id=str(account_id))

    def _publish(self, state: _State, account_id: UUID, hold: _Hold) -> None:
        holds = {**state.holds, account_id: hold}
        if hold == _NO_HOLD:
            del holds[account_id]
        self._state = _State(state.accounts, state.rejections, state.read_at, holds)

    def credential_rejected(self, account_id: UUID, refusal: Refusal) -> None:
        """Hold the section 8.6 reaction to `refusal` for the account, at once and before it is
        logged, so a logging fault never withholds it (C-2.21). A second rejection adds its
        reaction to a first still in force, and the fact then needs a pass after both. A first
        that a later pass has cleared adds nothing once the next tracking read has dropped it, or
        while that pass is still in evidence (the job's result, or the stored pass of the last
        read). If the pass leaves the evidence before the next tracking read, the first is in force
        again and merges: the 403 reason can differ, and both refuse."""
        state = self._state
        account = state.accounts.get(account_id)
        if account is not None:
            keys = _judge(account, self._results(), state.holds.get(account_id, _NO_HOLD))
            prior = _held(state.rejections.get(account_id), keys)
            disabled = REACTIONS.get(refusal)
            rejection = _Rejection(
                no_key=disabled is None or (prior is not None and prior.no_key),
                disabled=disabled or (None if prior is None else prior.disabled),
                at=self._clock.now(),
                seen=frozenset((key.key_id, key.last_pass_at) for key in keys),
            )
            rejections = {**state.rejections, account_id: rejection}
            self._state = _State(state.accounts, rejections, state.read_at, state.holds)
        logger().error(
            "account.credential_rejected",
            account_id=str(account_id),
            reason=str(refusal),
            listed=account is not None,
        )

    def _results(self) -> Mapping[UUID, KeyCheck]:
        """The self-check's results, taken once a call; none without a job (the fake backend)."""
        return {} if self._selfcheck is None else self._selfcheck.results


def _ended(
    holds: Mapping[UUID, _Hold], accounts: Mapping[UUID, _Account], began: int
) -> dict[UUID, _Hold]:
    """`holds` after a read that began at generation `began` and listed `accounts`: a revoked key
    told before it began and not listed by it leaves; the lifecycle reason always stays."""
    kept: dict[UUID, _Hold] = {}
    for account_id, hold in holds.items():
        account = accounts.get(account_id)
        listed = set() if account is None else {key.key_id for key in account.keys}
        revoked = {k: told for k, told in hold.revoked.items() if told > began or k in listed}
        if hold.reason is not None or revoked:
            kept[account_id] = _Hold(hold.reason, revoked)
    return kept


def _judge(account: _Account, results: Mapping[UUID, KeyCheck], hold: _Hold) -> list[_Judged]:
    """Each of the account's keys but the revoked ones the hold names, as the self-check judges it:
    its result in `results` when the job holds one, otherwise the stored pass and error code
    (decision 3 on #836). One `dict.get` a key: the mapping is never iterated."""
    judged = []
    for key in account.keys:
        if key.key_id in hold.revoked:
            continue
        check = results.get(key.key_id)
        if check is None:
            failed = key.error_code in STANDING_FAILURE_CODES
            judged.append(_Judged(key.key_id, failed, key.error_code, key.verified_at))
        else:
            failed = check.outcome == "failed"
            judged.append(_Judged(key.key_id, failed, check.code, check.last_pass_at))
    return judged


def _held(rejection: _Rejection | None, keys: Iterable[_Judged]) -> _Rejection | None:
    """The rejection while it is in force: `None` once a later pass in `keys` clears it, never
    dropped here (`observe` drops it). `keys` is the evidence now: a pass no longer in it clears
    nothing."""
    if rejection is not None and _passed_since(rejection, keys):
        return None
    return rejection


def _passed_since(rejection: _Rejection, keys: Iterable[_Judged]) -> bool:
    """A later recorded pass: of a key not failed since, newer than the rejection, and not
    already known when it arrived."""
    return any(
        not key.failed
        and key.last_pass_at > rejection.at
        and (key.key_id, key.last_pass_at) not in rejection.seen
        for key in keys
    )
