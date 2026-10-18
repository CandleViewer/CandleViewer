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
  never reaches it, nor is a rejection health evidence (KV-T12). One fact per listed account, so
  what is held is bounded by the read (C-2.18); one for an unlisted account is logged and dropped
  (it is refused).

Codes only, never exchange text, a key id or a permission list. The durable section 8.6 reaction
(the key marked `invalid`, the account disarmed) is the submit pipeline's (#913); a restart forgets
the fact, and the boot self-check judges the key afresh. A call reads the account's own keys only.
Meant for one event loop.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.health import Clock
from candleviewer.accounts.order_gate import DisabledReason, KeyStanding
from candleviewer.accounts.selfcheck import KeyCheck, is_fresh
from candleviewer.accounts.verification import Refusal, Rule
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
_RULES: Final = frozenset(rule.value for rule in Rule)
_POLICY: Final[Mapping[str | None, DisabledReason]] = {r.value: r for r in DisabledReason}


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class SelfCheckResults(Protocol):
    """What the standing reads of the stored-key self-check (`selfcheck.KeySelfCheck`): each key's
    standing result, by key id. Read at each call: the job replaces the mapping on every pass."""

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
        self._stale_after_s, self._read_at = stale_after_s, float("-inf")
        self._accounts: dict[UUID, _Account] = {}
        self._rejections: dict[UUID, _Rejection] = {}

    def observe(self, rows: Iterable[SelfCheckTargetRow]) -> None:
        """Take one usable-key read of the environment whole, reduced at once to each account's
        keys (id, stored pass, error code) and armed flag, keeping no row. An account it does not
        list has no standing and loses its rejection; a failed read never gets here."""
        keys: dict[UUID, list[_Key]] = {}
        armed: dict[UUID, bool] = {}
        for row in rows:
            account = row.account
            stored = _Key(row.key_id, row.verified_at, row.last_error_code)
            keys.setdefault(account.id, []).append(stored)
            armed[account.id] = account.is_enabled and account.trading_enabled
        self._accounts = {a: _Account(armed[a], tuple(listed)) for a, listed in keys.items()}
        self._rejections = {a: r for a, r in self._rejections.items() if a in self._accounts}
        self._read_at = self._clock.monotonic()

    def standing(self, account_id: UUID) -> KeyStanding | None:
        """The account's standing now; `None` if the last good read did not list it or is older
        than `stale_after_s`. A rejection that a later pass has cleared is dropped here."""
        account = self._accounts.get(account_id)
        if account is None or self._clock.monotonic() - self._read_at > self._stale_after_s:
            return None
        keys = self._judge(account)
        rejection = self._rejections.get(account_id)
        if rejection is not None and _passed_since(rejection, keys):
            del self._rejections[account_id]
            rejection = None
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
        if disabled is None and not account.armed:
            disabled = DisabledReason.ACCOUNT_DISABLED
        return KeyStanding(active, disabled)

    def credential_rejected(self, account_id: UUID, refusal: Refusal) -> None:
        """Hold the section 8.6 reaction to `refusal` for the account, at once and before it is
        logged, so a logging fault never withholds it (C-2.21); a second rejection adds its
        reaction to the first, and the fact then needs a pass after both."""
        account = self._accounts.get(account_id)
        if account is not None:
            prior = self._rejections.get(account_id)
            disabled = REACTIONS.get(refusal)
            self._rejections[account_id] = _Rejection(
                no_key=disabled is None or (prior is not None and prior.no_key),
                disabled=disabled or (None if prior is None else prior.disabled),
                at=self._clock.now(),
                seen=frozenset((key.key_id, key.last_pass_at) for key in self._judge(account)),
            )
        logger().error(
            "account.credential_rejected",
            account_id=str(account_id),
            reason=str(refusal),
            listed=account is not None,
        )

    def _judge(self, account: _Account) -> list[_Judged]:
        """Each of the account's keys as the self-check judges it: its result when the job holds
        one, otherwise the stored pass and error code (decision 3 on #836)."""
        results: Mapping[UUID, KeyCheck] = {}
        if self._selfcheck is not None:
            results = self._selfcheck.results
        judged = []
        for key in account.keys:
            check = results.get(key.key_id)
            if check is None:
                failed = key.error_code in _RULES
                judged.append(_Judged(key.key_id, failed, key.error_code, key.verified_at))
            else:
                failed = check.outcome == "failed"
                judged.append(_Judged(key.key_id, failed, check.code, check.last_pass_at))
        return judged


def _passed_since(rejection: _Rejection, keys: Iterable[_Judged]) -> bool:
    """A later recorded pass: of a key not failed since, newer than the rejection, and not
    already known when it arrived."""
    return any(
        not key.failed
        and key.last_pass_at > rejection.at
        and (key.key_id, key.last_pass_at) not in rejection.seen
        for key in keys
    )
