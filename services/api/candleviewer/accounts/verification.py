"""Mandatory API-key verification pipeline (E27-T03, #836).

The seven checks of `createApiKey` (`docs/plan/22-api-openapi.yaml`) as one judgement over
venue-neutral facts, shared by key import, the `test` route, the boot assertion and the hourly
self-check (C-12.2). The exchange adapter parses the key-info and probe replies and classifies
refusals; this module imports neither M3 nor M4 (C-3.1) and holds no credential material (C-2.7).
It applies the E27 threat model (`docs/security/threat-models/E27-accounts.md` §5, SR-E27-04,
SR-E27-08, SR-E27-18):

- Fund rights (C-2.8, D6): the shared deny-list predicate plus an allow-list. Any other right
  fails `key_withdraw_permission`, and `withdraw_enabled` is true.
- Write access comes from the key's read-only flag, UTA from the venue's unified-trade flag.
- The whitelist is non-empty host addresses, all equal to the configured egress IP. No switch
  turns this off (C-4.14).
- An expiry at or before `now` fails `key_expired` (SR-030a: in the future), as does the venue's
  own expired-key refusal; an expiry inside the warning window only warns.
- Failures and warnings are fixed codes; messages are templates that echo no exchange text.
- A refusal that says nothing about the key (signature, clock, rate limit, outage) raises
  `VerificationInconclusive`: no verdict, so it never refreshes a key. So does an accepted probe
  slower than the receive window: the venue enforces that window itself, so lateness after
  acceptance says nothing about the key.

`verify()` fixes the order: key facts first, the fund-right gate before every other check, and the
signed probe only after every blocking check passed. An over-privileged, foreign or unwhitelisted
key is never used for a second signed call.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from ipaddress import IPv4Address, IPv6Address, ip_network
from typing import Final, Protocol

from candleviewer.accounts._permissions import reject_withdraw
from candleviewer.accounts.errors import AccountsError, WithdrawPermissionError
from candleviewer.accounts.models import ExchangeAccount

#: The only rights a key may hold (SR-E27-04, model §5 item 2, #2270): exact ASCII names, every
#: other group empty. Anything else is refused, fail closed.
ALLOWED_RIGHTS: Final[Mapping[str, frozenset[str]]] = {
    "ContractTrade": frozenset({"Order", "Position"}),
    "Derivatives": frozenset({"DerivativesTrade"}),
}
TRADE_GROUP: Final = "ContractTrade"
TRADE_RIGHTS: Final = ("Order", "Position")
#: A name safe to echo in a message: a short ASCII identifier (SR-E27-08).
_TOKEN: Final = re.compile(r"[A-Za-z][A-Za-z0-9]{0,63}")
_WILDCARD: Final = "*"


class Rule(StrEnum):
    """Failure codes, one per check (`Problem.errors[].rule`)."""

    WITHDRAW_PERMISSION = "key_withdraw_permission"
    MISSING_SCOPES = "key_missing_scopes"
    UID_MISMATCH = "key_uid_mismatch"
    NOT_UNIFIED = "key_not_unified"
    IP_WHITELIST_MISSING = "key_ip_whitelist_missing"
    IP_WHITELIST_MISMATCH = "key_ip_whitelist_mismatch"
    WRONG_ENVIRONMENT = "key_wrong_environment"
    KEY_EXPIRED = "key_expired"
    PROBE_FAILED = "key_probe_failed"


class VerificationWarning(StrEnum):
    """Advisory codes: attached to the result, never a failure."""

    KEY_EXPIRES_SOON = "key_expires_soon"
    CLOCK_OFFSET = "clock_offset_high"


class Refusal(StrEnum):
    """An exchange refusal that is a verdict about the key, as the adapter classifies it."""

    UNKNOWN_KEY = "unknown_key"
    IP_NOT_ALLOWED = "ip_not_allowed"
    PERMISSION_DENIED = "permission_denied"
    KEY_EXPIRED = "key_expired"


class KeyRefused(AccountsError):
    """A source's signed call was refused with a verdict about the key; `code` is the venue's."""

    def __init__(self, reason: Refusal, code: int | None = None) -> None:
        super().__init__(reason.value)
        self.reason, self.code = reason, code


class VerificationInconclusive(AccountsError):
    """No verdict: refused signature, clock drift, rate limit, outage, a slow or unreadable reply.
    Import answers 502 and stores nothing; a self-check keeps no fresh result (SR-E27-18)."""


class KeyFacts(Protocol):
    """What the key-info reply says about the key (adapter-parsed)."""

    @property
    def uid(self) -> str: ...
    @property
    def unified(self) -> bool: ...
    @property
    def read_only(self) -> bool: ...
    @property
    def permissions(self) -> Mapping[str, object]: ...
    @property
    def ip_whitelist(self) -> Sequence[str]: ...
    @property
    def expires_at(self) -> datetime | None: ...


class ProbeFacts(Protocol):
    """A successful signed probe: the exchange's clock and the local send/receive times (ms)."""

    @property
    def server_time_ms(self) -> int: ...
    @property
    def sent_at_ms(self) -> int: ...
    @property
    def received_at_ms(self) -> int: ...


KeyInfoSource = Callable[[], Awaitable[KeyFacts]]
ProbeSource = Callable[[], Awaitable[ProbeFacts]]


@dataclass(frozen=True)
class VerificationPolicy:
    """Deployment inputs (`CV_EGRESS_IP`, `CV_KEY_EXPIRY_WARN_DAYS`, `CV_RECV_WINDOW_MS`)."""

    egress_ip: str | None
    expiry_warn_days: int = 14
    recv_window_ms: int = 5000
    #: 24-internal-schemas §14.2 item 9: warn above 500 ms; blocking stays with the clock guard.
    clock_warn_ms: int = 500


@dataclass(frozen=True)
class VerificationFailure:
    rule: Rule
    message: str


@dataclass(frozen=True)
class VerificationResult:
    """`KeyVerification` plus what persistence needs. No credential field exists (C-2.7).

    `key_info_ret_code` and `probe_ret_code` are the venue codes of the key-info call (check 1)
    and the signed probe (check 7): 0 when accepted, the refusal code when refused, `None` when
    that call was not made. A key-info refusal never shows up as a probe code."""

    passed: bool
    uid: str | None = None
    unified: bool = False
    permissions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    withdraw_enabled: bool = False
    ip_whitelist: tuple[str, ...] = ()
    ip_whitelist_matches_egress: bool = False
    clock_offset_ms: int | None = None
    key_info_ret_code: int | None = None
    probe_ret_code: int | None = None
    warnings: tuple[VerificationWarning, ...] = ()
    failures: tuple[VerificationFailure, ...] = ()
    read_only: bool = False
    can_trade: bool = False
    expires_at: datetime | None = None


def _token(value: object) -> str | None:
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else None


def _grants_nothing(value: object) -> bool:
    return value is None or (isinstance(value, str | list) and not value)


def _outside_allow_list(permissions: Mapping[str, object]) -> list[tuple[str | None, str | None]]:
    """Every (group, right) the allow-list refuses; `None` where a name is not safe to echo."""
    found: list[tuple[str | None, str | None]] = []
    for group, value in permissions.items():
        if _grants_nothing(value):
            continue
        allowed = ALLOWED_RIGHTS.get(group)
        if allowed is None or not isinstance(value, list):
            rights = value if isinstance(value, list) else [None]
            found += [(_token(group), _token(right)) for right in rights]
            continue
        found += [(group, _token(r)) for r in value if not isinstance(r, str) or r not in allowed]
    return found


def _right_message(group: str | None, right: str | None) -> str:
    if group is None:
        return "permissions hold a group outside the allowed set"
    if right is None:
        return f"permissions.{group} holds a right outside the allowed set"
    return f"permissions.{group} contains '{right}'"


def _fund_right_failures(permissions: Mapping[str, object]) -> list[VerificationFailure]:
    """C-2.8 gate: the deny-list shared with M2 and the DB CHECK, then the allow-list."""
    try:
        reject_withdraw(permissions)
        offending = _outside_allow_list(permissions)
    except WithdrawPermissionError:
        offending = _outside_allow_list(permissions) or [(None, None)]
    messages = dict.fromkeys(_right_message(g, r) for g, r in offending)
    return [VerificationFailure(Rule.WITHDRAW_PERMISSION, text) for text in sorted(messages)]


def _rights(permissions: Mapping[str, object], group: str) -> set[str]:
    value = permissions.get(group)
    return {r for r in value if isinstance(r, str)} if isinstance(value, list) else set()


def _scope_failures(facts: KeyFacts, read_only: bool) -> list[VerificationFailure]:
    """Check 3. Write access is the key's read-only flag (model §5 item 3)."""
    if read_only and not facts.read_only:
        return [VerificationFailure(Rule.MISSING_SCOPES, "a read-only key has write access")]
    if read_only:
        return []
    if facts.read_only:
        text = "the key is read-only; a trade key needs write access"
        return [VerificationFailure(Rule.MISSING_SCOPES, text)]
    missing = [r for r in TRADE_RIGHTS if r not in _rights(facts.permissions, TRADE_GROUP)]
    if not missing:
        return []
    names = ", ".join(f"'{r}'" for r in missing)
    return [VerificationFailure(Rule.MISSING_SCOPES, f"permissions.{TRADE_GROUP} lacks {names}")]


def _host(entry: str) -> IPv4Address | IPv6Address | None:
    """A single host address (a bare address or a /32, /128 network), IPv4-mapped unwrapped."""
    try:
        net = ip_network(entry, strict=True)
    except ValueError:
        return None
    if net.prefixlen != net.max_prefixlen:
        return None
    addr = net.network_address
    mapped = addr.ipv4_mapped if isinstance(addr, IPv6Address) else None
    return mapped or addr


def _is_network(entry: str) -> bool:
    try:
        ip_network(entry, strict=False)
    except ValueError:
        return False
    return True


def _whitelist(entries: Sequence[str], egress: str | None) -> VerificationFailure | None:
    """Check 5 (SR-E27-04): non-empty, no wildcard, every entry the egress address."""
    target = _host(egress) if egress else None
    if not entries or _WILDCARD in entries:
        where = f"add {target}" if target else "set the egress IP and add it"
        text = f"the key has no IP whitelist; {where} in the exchange's key settings"
        return VerificationFailure(Rule.IP_WHITELIST_MISSING, text)
    if target is None:
        return VerificationFailure(Rule.IP_WHITELIST_MISMATCH, "the egress IP is not configured")
    if any(_host(entry) != target for entry in entries):
        text = f"the IP whitelist must hold only the egress IP {target}"
        return VerificationFailure(Rule.IP_WHITELIST_MISMATCH, text)
    return None


def _display(permissions: Mapping[str, object]) -> dict[str, tuple[str, ...]]:
    """Groups and rights safe to show: canonical names only (SR-E27-08)."""
    return {
        group: tuple(r for r in value if _token(r) is not None)
        for group, value in permissions.items()
        if _token(group) is not None and isinstance(value, list)
    }


_REFUSAL_RULES: Final = {
    Refusal.UNKNOWN_KEY: (Rule.WRONG_ENVIRONMENT, "key does not belong to this environment"),
    Refusal.IP_NOT_ALLOWED: (Rule.IP_WHITELIST_MISMATCH, "the exchange refused the egress IP"),
    Refusal.PERMISSION_DENIED: (Rule.MISSING_SCOPES, "the key lacks a required permission"),
    Refusal.KEY_EXPIRED: (Rule.KEY_EXPIRED, "the exchange refused the key as expired"),
}


def _refusal_failure(reason: Refusal, egress: str | None) -> VerificationFailure:
    """A key-info refusal. An IP refusal names the egress IP, for copying into the whitelist."""
    rule, text = _REFUSAL_RULES[reason]
    target = _host(egress) if egress else None
    if reason is Refusal.IP_NOT_ALLOWED and target is not None:
        text = f"{text} {target}; add it to the key's IP whitelist"
    return VerificationFailure(rule, text)


async def verify(
    account: ExchangeAccount,
    *,
    read_only: bool,
    key_info: KeyInfoSource,
    probe: ProbeSource,
    policy: VerificationPolicy,
    now: datetime,
) -> VerificationResult:
    """Run the seven checks against `account` for a key declared `read_only` (or not).

    `key_info` and `probe` make the two signed calls on the account's own environment host. They
    raise `KeyRefused` for a verdict and `VerificationInconclusive` for none; the latter
    propagates. `now` is tz-aware UTC from the injected clock."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    try:
        facts = await key_info()
    except KeyRefused as refused:
        failure = _refusal_failure(refused.reason, policy.egress_ip)
        return VerificationResult(False, key_info_ret_code=refused.code, failures=(failure,))
    shown = tuple(e for e in facts.ip_whitelist if e == _WILDCARD or _is_network(e))
    base = VerificationResult(
        False,
        key_info_ret_code=0,
        uid=facts.uid,
        unified=facts.unified,
        permissions=_display(facts.permissions),
        ip_whitelist=shown,
        read_only=facts.read_only,
        expires_at=facts.expires_at,
    )
    gate = _fund_right_failures(facts.permissions)
    if gate:
        return replace(base, withdraw_enabled=True, failures=tuple(gate))
    failures = _scope_failures(facts, read_only)
    if not facts.unified:
        text = "the account is not a unified trading account"
        failures.append(VerificationFailure(Rule.NOT_UNIFIED, text))
    if facts.uid != account.exchange_uid:
        text = f"the key belongs to another UID, not {account.exchange_uid}"
        failures.append(VerificationFailure(Rule.UID_MISMATCH, text))
    ip_failure = _whitelist(facts.ip_whitelist, policy.egress_ip)
    if ip_failure is not None:
        failures.append(ip_failure)
    expiry = facts.expires_at
    if expiry is not None and expiry <= now:
        failures.append(VerificationFailure(Rule.KEY_EXPIRED, "the key has expired"))
    soon = expiry is not None and now < expiry < now + timedelta(days=policy.expiry_warn_days)
    base = replace(
        base,
        ip_whitelist_matches_egress=ip_failure is None,
        warnings=(VerificationWarning.KEY_EXPIRES_SOON,) if soon else (),
    )
    if failures:
        return replace(base, failures=tuple(failures))
    return await _probe(base, probe, policy, can_trade=not read_only)


async def _probe(
    base: VerificationResult, probe: ProbeSource, policy: VerificationPolicy, *, can_trade: bool
) -> VerificationResult:
    """Check 7: the signed no-op probe is accepted, and answers inside the receive window or the
    run is inconclusive. The clock offset is exchange time minus the midpoint of the local send
    and receive times."""
    try:
        seen = await probe()
    except KeyRefused as refused:
        failure = VerificationFailure(Rule.PROBE_FAILED, "the exchange refused the signed probe")
        return replace(base, probe_ret_code=refused.code, failures=(failure,))
    latency = seen.received_at_ms - seen.sent_at_ms
    if latency < 0:
        raise VerificationInconclusive("probe_clock_step")
    if latency > policy.recv_window_ms:
        raise VerificationInconclusive("probe_slow")
    offset = seen.server_time_ms - (seen.sent_at_ms + seen.received_at_ms) // 2
    warnings = base.warnings
    if abs(offset) > policy.clock_warn_ms:
        warnings += (VerificationWarning.CLOCK_OFFSET,)
    return replace(
        base,
        passed=True,
        can_trade=can_trade,
        clock_offset_ms=offset,
        probe_ret_code=0,
        warnings=warnings,
    )
