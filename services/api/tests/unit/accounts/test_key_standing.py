"""E27-T04 W3 (#837): the key standing the order-entry gate's account check reads. A key is active
only while its last recorded pass is inside the self-check's window, by `selfcheck.is_fresh` at
read time (SR-E27-18); a failed key, an account not armed, a read past its age bound and a rejected
credential (24-internal-schemas.md §8.6) refuse at once, and only a later recorded pass clears a
rejection. Fake clock and a fake self-check job: no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.health import AccountHealthMonitor
from candleviewer.accounts.key_standing import REACTIONS, KeyStandings
from candleviewer.accounts.order_gate import AccountHealthCheck, DisabledReason, KeyStanding
from candleviewer.accounts.selfcheck import FRESHNESS_GRACE, KeyCheck, Outcome
from candleviewer.accounts.verification import Refusal, Rule
from candleviewer.storage.repositories.accounts import SelfCheckTargetRow
from tests.unit.accounts._fakes import ACC, ACC_B, DAY, T0, Dms, FakeClock, Sizing, key_of, key_row

HOUR = 3600.0
#: The age bound on the last good read (the wiring passes `TRACKING_FAULT_AFTER_S`).
STALE_S = 60.0
KEY = key_of(ACC)
NEW_KEY = UUID(int=7)
ACTIVE = KeyStanding(True)
NO_KEY = KeyStanding(False)
DISARMED = KeyStanding(False, DisabledReason.ACCOUNT_DISABLED)
SWITCHED_OFF = KeyStanding(True, DisabledReason.ACCOUNT_DISABLED)
IP_REFUSED = KeyStanding(True, DisabledReason.KEY_IP_WHITELIST_MISMATCH)
US = timedelta(microseconds=1)
POLICY_CODES = {reason.value for reason in DisabledReason}


@dataclass
class _Job:
    """The stored-key self-check as the standing reads it: each key's standing result."""

    results: dict[UUID, KeyCheck] = field(default_factory=dict)


def _check(
    outcome: Outcome,
    *,
    key: UUID = KEY,
    last_pass: datetime = T0,
    code: str | None = None,
    checked_at: datetime | None = None,
) -> KeyCheck:
    return KeyCheck(key, ACC, checked_at or last_pass, outcome, code, None, last_pass, None)


def _world(
    *rows: SelfCheckTargetRow, interval_s: float = HOUR
) -> tuple[KeyStandings, _Job, FakeClock]:
    clock, job = FakeClock(), _Job()
    standings = KeyStandings(job, interval_s=interval_s, stale_after_s=STALE_S, clock=clock)
    standings.observe(rows or (key_row(ACC),))
    return standings, job, clock


def _reason(standings: KeyStandings, account: UUID = ACC) -> str | None:
    """The account check's refusal reason over `standings`, for an account with healthy evidence."""
    monitor = AccountHealthMonitor(FakeClock(), Dms())
    monitor.track(account)
    monitor.ws_heartbeat(account)
    refusal = AccountHealthCheck(monitor, standings, Sizing()).refusal(account)
    return None if refusal is None else refusal.reason


def test_an_account_the_last_read_did_not_list_has_no_standing_and_is_refused() -> None:
    standings, _, _ = _world()
    assert standings.standing(ACC_B) is None and _reason(standings, ACC_B) == "no_active_key"


def test_no_account_has_a_standing_once_the_last_good_read_is_older_than_its_bound() -> None:
    """C-2.21: reads that keep failing never leave a frozen list admitting an account switched
    off, deleted or stripped of its keys since. The age is monotonic, and the next read restores."""
    standings, _, clock = _world()
    clock.mono += STALE_S
    assert standings.standing(ACC) == ACTIVE
    clock.mono += 0.001
    assert standings.standing(ACC) is None and _reason(standings) == "no_active_key"
    standings.observe([key_row(ACC)])
    assert standings.standing(ACC) == ACTIVE


@pytest.mark.parametrize("interval_s", [60.0, HOUR])
@pytest.mark.parametrize("source", ["passed", "inconclusive", "stored"])
def test_a_key_is_active_until_exactly_one_interval_plus_the_grace_after_its_last_pass(
    source: Outcome | str, interval_s: float
) -> None:
    """SR-E27-18 at admission, on the job's result (an inconclusive check never moves the last
    pass) or, for a key it holds none for, the stored pass."""
    stored = T0 if source == "stored" else T0 - DAY  # the job's result wins when it holds one
    standings, job, clock = _world(key_row(ACC, verified_at=stored), interval_s=interval_s)
    if source == "passed":
        job.results[KEY] = _check("passed")
    elif source == "inconclusive":
        job.results[KEY] = _check("inconclusive", code="timeout", checked_at=T0 + DAY)
    clock.wall += timedelta(seconds=interval_s) + FRESHNESS_GRACE
    assert standings.standing(ACC) == ACTIVE
    clock.wall += US
    assert standings.standing(ACC) == NO_KEY


def test_the_jobs_current_result_is_read_at_each_call_and_wins_over_the_stored_columns() -> None:
    standings, job, _ = _world(key_row(ACC, error="key_ip_whitelist_mismatch"))
    assert standings.standing(ACC) == KeyStanding(False, DisabledReason.KEY_IP_WHITELIST_MISMATCH)
    job.results = {KEY: _check("passed")}  # the job replaces its mapping on every pass
    assert standings.standing(ACC) == ACTIVE


def test_with_no_self_check_job_the_stored_columns_decide() -> None:
    """The fake backend has no job: the standing reads the stored pass and error code alone."""
    standings = KeyStandings(None, interval_s=HOUR, stale_after_s=STALE_S, clock=FakeClock())
    standings.observe([key_row(ACC, error="key_withdraw_permission")])
    assert standings.standing(ACC) == KeyStanding(False, DisabledReason.KEY_WITHDRAW_PERMISSION)


@pytest.mark.parametrize("rule", list(Rule))
def test_a_failed_key_is_never_active_and_disables_the_account_by_its_rule_or_as_switched_off(
    rule: Rule,
) -> None:
    """As the job disarms the account on every failure (`selfcheck._failed`)."""
    standings, job, _ = _world()
    job.results[KEY] = _check("failed", code=rule.value)
    policy = rule.value in POLICY_CODES
    disabled = DisabledReason(rule.value) if policy else DisabledReason.ACCOUNT_DISABLED
    assert standings.standing(ACC) == KeyStanding(False, disabled)


def test_a_failed_key_disables_the_account_at_once_beside_a_fresh_one() -> None:
    """A rotation: the other key's pass does not keep the account admitted until the next read."""
    standings, job, _ = _world(key_row(ACC), key_row(ACC, key=NEW_KEY))
    job.results[NEW_KEY] = _check("failed", key=NEW_KEY, code="key_uid_mismatch")
    assert standings.standing(ACC) == SWITCHED_OFF


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("key_withdraw_permission", KeyStanding(False, DisabledReason.KEY_WITHDRAW_PERMISSION)),
        ("key_expired", DISARMED),
        ("timeout", ACTIVE),  # an inconclusive code is no verdict
        (None, ACTIVE),
    ],
)
def test_with_no_result_a_stored_rule_code_is_a_standing_failure(
    code: str | None, expected: KeyStanding
) -> None:
    """Decision 3 on #836, as the job judges a key it holds no result for."""
    standings, _, _ = _world(key_row(ACC, error=code))
    assert standings.standing(ACC) == expected


@pytest.mark.parametrize(("armed", "enabled"), [(False, True), (True, False), (False, False)])
def test_an_account_switched_off_or_not_armed_for_trading_is_disabled_by_policy(
    armed: bool, enabled: bool
) -> None:
    standings, _, _ = _world(key_row(ACC, armed=armed, enabled=enabled))
    assert standings.standing(ACC) == SWITCHED_OFF


def test_one_key_inside_its_window_keeps_the_account_active_beside_one_past_it() -> None:
    rotating = key_row(ACC, verified_at=T0 - DAY, key=NEW_KEY)
    standings, _, _ = _world(rotating, key_row(ACC))
    assert standings.standing(ACC) == ACTIVE


@pytest.mark.parametrize(
    ("refusal", "expected", "reason"),
    [
        (Refusal.UNKNOWN_KEY, NO_KEY, "no_active_key"),
        (Refusal.KEY_EXPIRED, NO_KEY, "no_active_key"),
        (Refusal.PERMISSION_DENIED, SWITCHED_OFF, "account_disabled_by_policy"),
        (Refusal.IP_NOT_ALLOWED, IP_REFUSED, "account_disabled_by_policy"),
    ],
)
def test_a_rejected_credential_refuses_the_next_order_at_once(
    refusal: Refusal, expected: KeyStanding, reason: str
) -> None:
    """24 §8.6, Option A on #837: no re-verification has to run first."""
    standings, _, _ = _world()
    assert _reason(standings) is None
    standings.credential_rejected(ACC, refusal)
    assert standings.standing(ACC) == expected and _reason(standings) == reason


def test_every_refusal_has_a_reaction_and_one_with_none_listed_leaves_no_active_key() -> None:
    assert set(REACTIONS) == set(Refusal)
    standings, _, _ = _world()
    standings.credential_rejected(ACC, cast(Refusal, "a_code_added_later"))
    assert standings.standing(ACC) == NO_KEY


def test_a_rejection_is_cleared_only_by_a_recorded_pass_whose_check_began_after_it() -> None:
    standings, job, clock = _world()
    job.results[KEY] = _check("passed")
    clock.advance(20)
    began = clock.now()  # a check in flight when the rejection arrives
    clock.advance(1)
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    at = clock.now()
    clock.advance(20)
    assert standings.standing(ACC) == NO_KEY  # the pass it knew does not clear it
    job.results[KEY] = _check("passed", last_pass=began)  # the check in flight lands
    assert standings.standing(ACC) == NO_KEY
    job.results[KEY] = _check("passed", last_pass=at)  # one begun as it arrived: not after it
    assert standings.standing(ACC) == NO_KEY
    job.results[KEY] = _check("passed", last_pass=T0, checked_at=clock.now())  # record refused
    assert standings.standing(ACC) == NO_KEY
    job.results[KEY] = _check("passed", last_pass=clock.now())
    assert standings.standing(ACC) == ACTIVE


def test_a_wall_clock_step_back_never_lets_the_pass_it_knew_clear_a_rejection() -> None:
    standings, job, clock = _world()
    job.results[KEY] = _check("passed")
    clock.wall -= timedelta(minutes=5)  # an NTP step after the last pass
    standings.credential_rejected(ACC, Refusal.IP_NOT_ALLOWED)
    assert standings.standing(ACC) == IP_REFUSED  # its pass reads later, but it was known


def test_each_rejection_adds_its_reaction_and_only_a_pass_after_the_last_clears_them() -> None:
    standings, job, clock = _world()
    standings.credential_rejected(ACC, Refusal.IP_NOT_ALLOWED)
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    assert standings.standing(ACC) == KeyStanding(False, DisabledReason.KEY_IP_WHITELIST_MISMATCH)
    clock.advance(1)
    between = clock.now()
    clock.advance(1)
    standings.credential_rejected(ACC, Refusal.PERMISSION_DENIED)  # the newer disable reads
    both = KeyStanding(False, DisabledReason.ACCOUNT_DISABLED)
    assert standings.standing(ACC) == both
    job.results[KEY] = _check("passed", last_pass=between)
    assert standings.standing(ACC) == both
    clock.advance(1)
    job.results[KEY] = _check("passed", last_pass=clock.now())
    assert standings.standing(ACC) == ACTIVE


def test_the_later_pass_of_a_key_that_has_failed_since_does_not_clear_a_rejection() -> None:
    standings, job, clock = _world(key_row(ACC), key_row(ACC, key=NEW_KEY))
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    clock.advance(30)
    failed = KeyCheck(NEW_KEY, ACC, clock.now(), "failed", "key_expired", None, clock.now(), None)
    job.results[NEW_KEY] = failed  # it passed after the rejection, then failed
    assert standings.standing(ACC) == DISARMED  # not SWITCHED_OFF: the other key stays held


def test_a_rejection_a_later_pass_cleared_is_dropped_and_never_merges_into_the_next() -> None:
    standings, job, clock = _world()
    standings.credential_rejected(ACC, Refusal.IP_NOT_ALLOWED)
    clock.advance(1)
    job.results[KEY] = _check("passed", last_pass=clock.now())
    assert standings.standing(ACC) == ACTIVE  # cleared, and dropped as it is read
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    assert standings.standing(ACC) == NO_KEY  # without the cleared refusal's disable


def test_a_rejection_is_held_before_it_is_logged_so_a_logging_fault_withholds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.21: blocking takes effect before the line that records it is written."""

    def fault(*_args: object, **_fields: object) -> None:
        raise RuntimeError("a structlog processor fault")

    standings, _, _ = _world()
    target = "candleviewer.accounts.key_standing.logger"
    monkeypatch.setattr(target, lambda: SimpleNamespace(error=fault))
    with pytest.raises(RuntimeError):
        standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    assert standings.standing(ACC) == NO_KEY


def test_a_rejection_of_an_unlisted_account_is_logged_by_its_codes_and_dropped() -> None:
    standings, _, _ = _world()
    with capture_logs() as logs:
        standings.credential_rejected(ACC_B, Refusal.UNKNOWN_KEY)
        standings.credential_rejected(ACC, Refusal.PERMISSION_DENIED)
    standings.observe([key_row(ACC), key_row(ACC_B)])
    assert standings.standing(ACC_B) == ACTIVE
    fields = ("event", "log_level", "account_id", "reason", "listed")
    assert [tuple(e[f] for f in fields) for e in logs] == [
        ("account.credential_rejected", "error", str(ACC_B), "unknown_key", False),
        ("account.credential_rejected", "error", str(ACC), "permission_denied", True),
    ]
    assert {f for e in logs for f in e} == set(fields)  # codes only: no exchange text


def test_the_rejections_held_are_bounded_by_the_accounts_the_last_read_listed() -> None:
    """C-2.18: an account that leaves the read takes its fact with it; it is refused while
    unlisted, and comes back only with a key that passes."""
    standings, _, _ = _world(key_row(ACC), key_row(ACC_B))
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    standings.credential_rejected(ACC_B, Refusal.UNKNOWN_KEY)
    standings.observe([key_row(ACC)])
    assert set(standings._rejections) == {ACC}
    assert standings.standing(ACC_B) is None
