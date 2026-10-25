"""E27-T04 W3 (#837): the key standing the order-entry gate's account check reads. A key is active
only while its last recorded pass is inside the self-check's window, by `selfcheck.is_fresh` at
read time (SR-E27-18); a failed key, an account not armed, a read past its age bound and a rejected
credential (24-internal-schemas.md §8.6) refuse at once, and only a later recorded pass clears a
rejection. The order lane reads it while the serving loop writes it (#913 slice 3 L4), so a read
writes nothing and a write never changes what a read holds. Fake clock and a fake self-check job:
no I/O."""

from __future__ import annotations

import ast
import copy
import inspect
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts import selfcheck
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


def test_the_standing_is_read_once_its_first_good_tracking_read_has_landed() -> None:
    """#913 slice 3E: the OMS startup waits on it, and a failed read never gets here."""
    clock = FakeClock()
    standings = KeyStandings(_Job(), interval_s=HOUR, stale_after_s=STALE_S, clock=clock)
    assert standings.read_once is False
    standings.observe([])
    clock.mono += STALE_S + 1
    assert standings.read_once is True  # however old it is now


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
@pytest.mark.parametrize(
    ("stored", "results"),
    [
        pytest.param(T0 - DAY, {KEY: _check("passed")}, id="passed"),
        pytest.param(
            T0 - DAY,
            {KEY: _check("inconclusive", code="timeout", checked_at=T0 + DAY)},
            id="inconclusive",
        ),
        pytest.param(T0, {}, id="stored"),
    ],
)
def test_a_key_is_active_until_exactly_one_interval_plus_the_grace_after_its_last_pass(
    stored: datetime, results: dict[UUID, KeyCheck], interval_s: float
) -> None:
    """SR-E27-18 at admission, on the job's result (an inconclusive check never moves the last
    pass) or, for a key it holds none for, the stored pass. Where the job holds a result, the
    stored pass is a day older, so only the result can keep the key active."""
    standings, job, clock = _world(key_row(ACC, verified_at=stored), interval_s=interval_s)
    job.results.update(results)
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


#: Each rule a failed key carries and the reason it disables the account by: its own when it is a
#: key-policy one, otherwise `account_disabled`.
FAILED_RULES = [
    (Rule.WITHDRAW_PERMISSION, DisabledReason.KEY_WITHDRAW_PERMISSION),
    (Rule.PERMISSION_NOT_ALLOWED, DisabledReason.KEY_PERMISSION_NOT_ALLOWED),
    (Rule.NOT_READ_ONLY, DisabledReason.KEY_NOT_READ_ONLY),
    (Rule.IP_WHITELIST_MISSING, DisabledReason.KEY_IP_WHITELIST_MISSING),
    (Rule.IP_WHITELIST_MISMATCH, DisabledReason.KEY_IP_WHITELIST_MISMATCH),
    (Rule.MISSING_SCOPES, DisabledReason.ACCOUNT_DISABLED),
    (Rule.UID_MISMATCH, DisabledReason.ACCOUNT_DISABLED),
    (Rule.NOT_UNIFIED, DisabledReason.ACCOUNT_DISABLED),
    (Rule.WRONG_ENVIRONMENT, DisabledReason.ACCOUNT_DISABLED),
    (Rule.KEY_EXPIRED, DisabledReason.ACCOUNT_DISABLED),
    (Rule.PROBE_FAILED, DisabledReason.ACCOUNT_DISABLED),
]


def test_the_failed_rule_table_lists_every_rule_once() -> None:
    assert sorted(rule for rule, _ in FAILED_RULES) == sorted(Rule)


@pytest.mark.parametrize(("rule", "disabled"), FAILED_RULES)
def test_a_failed_key_is_never_active_and_disables_the_account_by_its_rule_or_as_switched_off(
    rule: Rule, disabled: DisabledReason
) -> None:
    """As the job disarms the account on every failure (`selfcheck._failed`)."""
    standings, job, _ = _world()
    job.results[KEY] = _check("failed", code=rule.value)
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


def test_every_refusal_has_a_reaction() -> None:
    assert set(REACTIONS) == set(Refusal)


def test_a_refusal_with_no_reaction_listed_leaves_no_active_key() -> None:
    """Fail closed: a refusal code added before its reaction is."""
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


def test_a_rejection_a_later_pass_cleared_never_merges_into_the_next() -> None:
    """No read runs between the pass and the next rejection, and the pass is still in evidence
    (the job's result): the cleared refusal's disable does not merge into the next."""
    standings, job, clock = _world()
    standings.credential_rejected(ACC, Refusal.IP_NOT_ALLOWED)
    clock.advance(1)
    job.results[KEY] = _check("passed", last_pass=clock.now())
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    assert standings.standing(ACC) == NO_KEY  # without the cleared refusal's disable


def _ports_aside(standings: KeyStandings) -> dict[str, object]:
    """Each object the standing holds, its ports (the job and the clock) aside."""
    return {k: v for k, v in vars(standings).items() if k not in ("_selfcheck", "_clock")}


def test_a_standing_read_writes_nothing_not_even_a_rejection_a_later_pass_cleared() -> None:
    """#913 slice 3 L4: the order lane reads the standing while the serving loop writes it, so a
    read never writes, not even what it found (CR-S3L4-06: a write back of an equal snapshot would
    undo one the serving loop published meanwhile). It answers a rejection a later pass has cleared
    as cleared, and keeps it."""
    standings, job, clock = _world()
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    clock.advance(1)
    job.results[KEY] = _check("passed", last_pass=clock.now())
    held = _ports_aside(standings)
    copied = copy.deepcopy(held)
    assert (standings.standing(ACC), standings.standing(ACC_B)) == (ACTIVE, None)
    after = _ports_aside(standings)
    assert [name for name in after if after[name] is not held.get(name)] == []  # none rebound
    assert held == copied  # nor changed in place


def test_each_write_publishes_anew_never_changing_what_a_read_in_flight_holds() -> None:
    """#913 slice 3 L4: a read on the order lane takes what the standing holds by reference, and
    each write on the serving loop publishes anew rather than change it in place, so the read meets
    the write whole or not at all."""
    standings, _, clock = _world(key_row(ACC), key_row(ACC_B))
    writes: tuple[Callable[[], None], ...] = (
        lambda: standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY),
        lambda: standings.observe([key_row(ACC)]),
    )
    for write in writes:
        held = _ports_aside(standings)  # each reference a read in flight holds
        copied = copy.deepcopy(held)
        clock.advance(1)
        write()
        assert held == copied  # each object held before the write is as it was


class _Hooked(FakeClock):
    """A clock that runs one hook inside its next `monotonic()`: a write that lands while a read
    is under way, after the read has taken the standing's snapshot."""

    def __init__(self) -> None:
        super().__init__()
        self.hook: Callable[[], None] | None = None

    def monotonic(self) -> float:
        hook, self.hook = self.hook, None
        if hook is not None:
            hook()
        return super().monotonic()


def test_a_read_answers_from_the_one_snapshot_it_took_though_a_write_lands_inside_it() -> None:
    """#913 slice 3 L4 (CR-S3L4-01): a read takes the standing's snapshot once, so a tracking read
    that lands while it reads, fresh and listing no account, never lends its age to the stale
    snapshot's accounts: no torn pair admits an account the new read dropped."""
    clock = _Hooked()
    standings = KeyStandings(_Job(), interval_s=HOUR, stale_after_s=STALE_S, clock=clock)
    standings.observe([key_row(ACC)])
    clock.mono += STALE_S + 1  # the snapshot the read takes is stale
    clock.hook = lambda: standings.observe([])  # it lands inside the read: fresh, listing none
    assert standings.standing(ACC) is None
    assert clock.hook is None  # it did land inside the read


def test_a_rejection_never_refreshes_the_age_of_the_last_good_read() -> None:
    """C-2.21 (CR-S3L4-01): a rejection publishes the standing anew with the last good read's own
    age, so while the tracking reads keep failing the frozen list still ages out."""
    standings, _, clock = _world(key_row(ACC), key_row(ACC_B))
    clock.mono += STALE_S + 1
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    assert standings.standing(ACC_B) is None  # as stale as it was


class _ByKey(Mapping[UUID, KeyCheck]):
    """The job's results as the lane may read them: a key at a time, never iterated or sized."""

    def __init__(self, held: Mapping[UUID, KeyCheck]) -> None:
        self._held = dict(held)

    def __getitem__(self, key: UUID) -> KeyCheck:
        return self._held[key]

    def __iter__(self) -> Iterator[UUID]:
        raise AssertionError("the job's results were iterated")

    def __len__(self) -> int:
        raise AssertionError("the job's results were sized")


@dataclass
class _ByKeyJob:
    results: Mapping[UUID, KeyCheck]


def test_a_read_takes_the_jobs_results_a_key_at_a_time_and_never_iterates_them() -> None:
    """#913 slice 3 L4 (CR-S3L4-01): the job stores a key's result in its mapping on the serving
    loop while the lane reads it, so a standing read takes one `get` a key and never iterates the
    mapping, which a store landing meanwhile would break."""
    clock, job = FakeClock(), _ByKeyJob({})
    standings = KeyStandings(job, interval_s=HOUR, stale_after_s=STALE_S, clock=clock)
    standings.observe([key_row(ACC), key_row(ACC, key=NEW_KEY)])
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    clock.advance(1)
    job.results = _ByKey({NEW_KEY: _check("passed", key=NEW_KEY, last_pass=clock.now())})
    assert standings.standing(ACC) == ACTIVE  # NEW_KEY's pass, found by its key, clears it


#: How `selfcheck` may read its results from the serving loop, never the lane: by key or iterated.
_READS = frozenset({"get", "values", "items", "keys"})


def _results_use(node: ast.Attribute, parent: ast.AST) -> str:
    """How `selfcheck` uses `.results` at `node`: replaced whole, one key stored, read, or else the
    line, for the test to name."""
    if isinstance(parent, ast.Assign) and node in parent.targets:
        return "replaced"
    if isinstance(parent, ast.AnnAssign) and parent.target is node:
        return "replaced"
    if isinstance(parent, ast.Subscript) and parent.value is node:
        if isinstance(parent.ctx, ast.Store | ast.Load):
            return "stored" if isinstance(parent.ctx, ast.Store) else "read"
    if isinstance(parent, ast.Attribute) and parent.attr in _READS:
        return "read"
    return f"line {node.lineno}"


def test_the_job_replaces_its_results_whole_or_stores_one_key_never_clearing_or_popping() -> None:
    """#913 slice 3 L4 (CR-S3L4-02): the lane's read of the job's results is safe only while the
    job, on the serving loop, replaces the mapping whole or stores one key's result in it (module
    docstring): never a clear, pop, delete, update or alias, which could leave a read without a
    failed key's result."""
    tree = ast.parse(inspect.getsource(selfcheck))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    uses = Counter(
        _results_use(node, parents[node])
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "results"
    )
    assert set(uses) <= {"replaced", "stored", "read"}, uses
    assert uses["replaced"] >= 2 and uses["stored"] >= 1  # the init and each pass; each key


def test_a_cleared_rejection_is_in_force_again_if_its_pass_leaves_before_the_next_read() -> None:
    """#913 slice 3 L4's changed rule, failing closed: a read keeps a rejection a later pass has
    cleared, so if the pass leaves the evidence (its key fails) before the next tracking read drops
    it, the rejection is in force again, where a read used to drop it for good: it refuses longer,
    never less."""
    standings, job, clock = _world(key_row(ACC), key_row(ACC, key=NEW_KEY))
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    clock.advance(1)
    job.results[NEW_KEY] = _check("passed", key=NEW_KEY, last_pass=clock.now())
    assert standings.standing(ACC) == ACTIVE  # answered cleared, and kept
    failed = _check("failed", key=NEW_KEY, last_pass=clock.now(), code="key_ip_whitelist_mismatch")
    job.results[NEW_KEY] = failed
    assert standings.standing(ACC) == KeyStanding(False, DisabledReason.KEY_IP_WHITELIST_MISMATCH)


def test_a_rejection_a_tracking_read_found_cleared_stays_dropped_when_that_key_fails() -> None:
    """The tracking read, on the serving loop, drops a rejection a later pass has cleared: once
    dropped, nothing revives it."""
    standings, job, clock = _world(key_row(ACC), key_row(ACC, key=NEW_KEY))
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    clock.advance(1)
    job.results[NEW_KEY] = _check("passed", key=NEW_KEY, last_pass=clock.now())
    standings.observe([key_row(ACC), key_row(ACC, key=NEW_KEY)])  # it finds it cleared
    failed = _check("failed", key=NEW_KEY, last_pass=clock.now(), code="key_ip_whitelist_mismatch")
    job.results[NEW_KEY] = failed
    assert standings.standing(ACC) == IP_REFUSED  # the other key stays active: nothing revives


@pytest.mark.parametrize(
    ("tracked", "expected"),
    [
        (False, KeyStanding(False, DisabledReason.KEY_IP_WHITELIST_MISMATCH)),  # in force: merged
        (True, NO_KEY),  # dropped by the tracking read: it adds nothing
    ],
)
def test_a_cleared_rejection_merges_into_the_next_only_until_the_next_tracking_read(
    tracked: bool, expected: KeyStanding
) -> None:
    """`credential_rejected` since L4: a first rejection that a later pass has cleared adds nothing
    once the next tracking read has dropped it; if the pass leaves the evidence before that read,
    the first is in force again and merges, and both refuse."""
    standings, job, clock = _world()
    standings.credential_rejected(ACC, Refusal.IP_NOT_ALLOWED)
    clock.advance(1)
    job.results[KEY] = _check("passed", last_pass=clock.now())  # it clears the first
    if tracked:
        standings.observe([key_row(ACC)])
    job.results.clear()  # the pass leaves the evidence: the stored pass predates the first
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    assert standings.standing(ACC) == expected


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
    """C-2.18: an account that leaves the read takes its rejection with it and comes back with
    none, while one the read keeps listing keeps its own."""
    standings, _, _ = _world(key_row(ACC), key_row(ACC_B))
    standings.credential_rejected(ACC, Refusal.UNKNOWN_KEY)
    standings.credential_rejected(ACC_B, Refusal.UNKNOWN_KEY)
    standings.observe([key_row(ACC)])  # ACC_B leaves the read
    standings.observe([key_row(ACC), key_row(ACC_B)])  # and comes back
    assert (standings.standing(ACC), standings.standing(ACC_B)) == (NO_KEY, ACTIVE)
