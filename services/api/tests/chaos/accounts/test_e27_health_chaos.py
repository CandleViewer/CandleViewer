"""E27-Q03 (#892) chaos on the account health monitor and the stored-key self-check.

BQ-nn markers here: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).

Runs against the account fixture stack (`CV_E27_STACK=1`, the compose override
`infra/compose/docker-compose.account-fixture.yml` of #2893). Marked `chaos` and `harness`: the
default addopts and the PR lanes deselect `harness`, and
the integration lane's `chaos and integration` selection does not match it, so only a run that
names the marker (qa/plans/e27/chaos.md, "How to run") collects it to execute. Without the stack the
`api` fixture fails loudly: a stack-less run is an error, never a silent pass. Loopback only,
recorded fixtures only (the pack's scenarios), no exchange host (C-13.5, BQ-11). Each case runs
twice (the ticket: deterministic, not lucky) and puts the key back on `compliant` afterwards.

Faults are the pack's scenarios plus the switch CLI, never `tc netem` or a proxy (BQ-06): netem
needs `NET_ADMIN` and a new compose service, and `infra/` is a security-review path. Every case is
asserted on what is observable today: the public routes of 22 and `/metrics`. Where a pass
criterion of the ticket has no observable yet it is listed in qa/plans/e27/chaos.md, "Not
asserted", not faked.

C-13.6 numbers (cited by number only, BQ-05): 2 private WS drop; 4 REST 5xx (read path here,
not order submit); 5 rate-limit 10018 (the reserve half needs E34-T02: not asserted); 6 clock drift.
The KEK-loss case (E27-C5) is outside C-13.6. The control CLI has no KEK command, so both its
start-time and running-time halves run in process (`test_e27_kek_and_memory.py`); what the code
does not do as ruled is a finding row in qa/plans/e27/chaos.md section 7, never a skipped test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

from candleviewer.settings import (
    ACCOUNT_DOWN_MAX_S,
    ACCOUNT_HEARTBEAT_MAX_S,
)  # the settings' caps, 10 s / 30 s (US-ACCT-010)
from tests.chaos.accounts._e27_stack import (
    Api,
    health_count,
    metric,
    request_log,
    switch,
    wait_until,
)

pytestmark = [pytest.mark.chaos, pytest.mark.harness]

KEY_ID = os.environ.get("CV_E27_KEY_ID", "fixture-compliant-0001")  # the stack's stored pack key
HOLD_WS_S = float(
    os.environ.get("CV_E27_WS_HOLD_S", 300)
)  # the ticket's 5 minutes; a dry run shortens it
HOLD_5XX_S = float(os.environ.get("CV_E27_5XX_HOLD_S", 120))  # the ticket's 2 minutes
# Not ruled (no BQ-07 stamp): the health tick period is UNVERIFIED and the ticket names no recovery
# time; both are the run's, written into the results.
TICK_TOL_S = float(os.environ.get("CV_E27_TICK_TOL_S", 5))
RECOVER_S = float(os.environ.get("CV_E27_RECOVER_S", 120))
TEST_THROTTLE_S = 65.0  # 22 testApiKey: one test per key per minute
RUNS = [1, 2]  # the ticket: each chaos scenario at least twice


@pytest.fixture(scope="module")
def api() -> Api:
    if os.environ.get("CV_E27_STACK") != "1":
        raise RuntimeError("these cases need the account fixture stack: set CV_E27_STACK=1")
    return Api()


@pytest.fixture
def key(api: Api) -> Iterator[tuple[str, dict[str, Any]]]:
    """(account id, key row) of the stored key the cases switch, `KEY_ID`. 22 ApiKey shows only
    `key_id_masked` (`...` and the last 4); the pack's key ids end in a unique 4-digit serial, so
    exactly one signable key must carry `KEY_ID`'s, or the cases would switch one key and probe
    another."""
    pairs = api.accounts_and_keys()
    assert pairs, "no signable stored key on the stack: seed it first"
    mine = [p for p in pairs if p[1]["key_id_masked"] == "..." + KEY_ID[-4:]]
    assert len(mine) == 1, f"{len(mine)} signable keys carry the masked id of CV_E27_KEY_ID"
    yield mine[0]
    switch(KEY_ID, "compliant")  # always leave the stack as it was found
    assert wait_until(lambda: health_count("healthy") >= 1, RECOVER_S)


def _verdicts() -> dict[str, float]:
    return {
        r: metric("cv_key_verification_total", result=r)
        for r in ("passed", "failed", "inconclusive")
    }


def _test_once(api: Api, account: str, key_row: dict[str, Any]) -> dict[str, Any]:
    """One /test; waits out the per-key throttle (a 429 carries nothing probed)."""
    end_ok = {200}
    for _ in range(3):
        status, body = api.test_key(account, key_row["id"])
        if status in end_ok:
            return dict(body)
        assert status == 429, f"testApiKey answered {status}"
        wait_until(lambda: False, TEST_THROTTLE_S, TEST_THROTTLE_S)
    raise AssertionError("testApiKey stayed throttled")


def _fails_closed(body: dict[str, Any], expected_error: str) -> None:
    """22 KeyTestResult: an exchange failure is a 200 with `rest.error`, no `verification`."""
    assert body["passed"] is False
    assert body["rest"]["ok"] is False
    assert body["rest"]["error"] == expected_error
    assert "verification" not in body, "an outage or refusal must never read as a verdict"


# -- C-13.6 #2: private WS dropped and refused, REST failing --------------------------------------
@pytest.mark.parametrize("run", RUNS)
def test_private_ws_drop_goes_degraded_then_down_then_recovers(
    api: Api, key: tuple[str, dict[str, Any]], run: int
) -> None:
    # BQ-05/BQ-06: `ws_drop_rest_fail`: the WS drops at 5 s and refuses reconnects; REST is 503.
    down_before = metric("cv_account_health_transitions_total", state="down")
    # counts before the switch: a state that stood already must not satisfy the waits below
    amber_before = health_count("degraded") + health_count("down")
    red_before = health_count("down")
    switch(KEY_ID, "ws_drop_rest_fail")
    # amber inside the heartbeat cap (+ the drop at 5 s and a tick), red inside the down cap
    amber_s = 5 + ACCOUNT_HEARTBEAT_MAX_S + TICK_TOL_S
    assert wait_until(
        lambda: health_count("degraded") + health_count("down") > amber_before, amber_s
    ), "no amber inside the heartbeat cap"
    assert wait_until(
        lambda: health_count("down") > red_before, 5 + ACCOUNT_DOWN_MAX_S + TICK_TOL_S
    ), "no red inside the down cap"
    assert metric("cv_account_health_transitions_total", state="down") > down_before, (
        "transition metric did not move"
    )
    # held for the whole window: never back to healthy while the fault stands
    assert not wait_until(lambda: health_count("healthy") >= 1, HOLD_WS_S, 5.0), (
        "went healthy under a standing fault"
    )
    # recovery without a restart: the key answers as compliant again, the WS reconnects
    switch(KEY_ID, "compliant")
    assert wait_until(lambda: health_count("healthy") >= 1 and health_count("down") == 0, RECOVER_S)


# -- C-13.6 #4 (read path): Bybit 5xx during a self-check ------------------------------------------
@pytest.mark.parametrize("run", RUNS)
def test_rest_5xx_during_self_check_fails_closed_and_keeps_prior_verdict(
    api: Api, key: tuple[str, dict[str, Any]], run: int
) -> None:
    account, key_row = key
    prior = _test_once(api, account, key_row)  # the prior verdict, under `compliant`
    assert prior["passed"] is True
    verified_at = next(k for a, k in api.accounts_and_keys() if k["id"] == key_row["id"])[
        "last_verified_at"
    ]
    before = _verdicts()
    switch(KEY_ID, "bybit_5xx")
    first = _test_once(api, account, key_row)
    _fails_closed(first, "service_unavailable")  # KeyProbeError: HTTP 5xx
    # the window of the ticket: the check keeps failing closed through HOLD_5XX_S, never a pass
    wait_until(lambda: False, max(0.0, HOLD_5XX_S - TEST_THROTTLE_S), 5.0)
    _fails_closed(_test_once(api, account, key_row), "service_unavailable")
    after = _verdicts()
    assert after["passed"] == before["passed"], "a failed check was counted as a pass"
    assert after["inconclusive"] > before["inconclusive"], "the failed check left no metric"
    now_row = next(k for a, k in api.accounts_and_keys() if k["id"] == key_row["id"])
    assert now_row["last_verified_at"] == verified_at, (
        "the prior verdict was replaced by a failed check"
    )
    # BQ-14(ii): the "critical alert" is validated by the metric above, not by a page.


# -- C-13.6 #5: rate limit 10018 on the self-check path -------------------------------------------
@pytest.mark.parametrize("run", RUNS)
def test_rate_limit_10018_on_self_check_is_inconclusive_and_does_not_loop(
    api: Api, key: tuple[str, dict[str, Any]], run: int
) -> None:
    account, key_row = key
    before, logged = _verdicts(), len(request_log())
    switch(KEY_ID, "rate_limited_10018")
    _fails_closed(_test_once(api, account, key_row), "rate_limited")
    first_pass = len(request_log()) - logged  # calls one check makes (one pass, no retry)
    # no retry loop (TC-123): nothing more is sent to the stub for a quiet 30 s
    wait_until(lambda: False, 30.0, 30.0)
    assert len(request_log()) - logged == first_pass, (
        "the rate-limited check kept calling the exchange"
    )
    assert _verdicts()["passed"] == before["passed"]
    # Not asserted: "the order path is unaffected" and "a metric records the throttle". The reserve
    # behind the order path is E34-T02's (exchange/bybit/rate_limit.py header) and no
    # cv_exchange_rate_limit_remaining series exists in the catalogue (qa/plans/e27/chaos.md
    # section 5).


# -- C-13.6 #6: clock beyond recv_window ----------------------------------------------------------
@pytest.mark.parametrize("run", RUNS)
def test_clock_drift_beyond_recv_window_reports_the_clock_reason(
    api: Api, key: tuple[str, dict[str, Any]], run: int
) -> None:
    account, key_row = key
    before = _verdicts()
    switch(KEY_ID, "clock_skew")  # the stub clock runs 6 s ahead; the signed probe answers 10002
    _fails_closed(_test_once(api, account, key_row), "clock_drift")  # KeyProbeError: 10002
    assert _verdicts()["passed"] == before["passed"]
    # BQ-05: 22 says a no-verdict probe is a 200 with `rest.error`. The pack's manifest and plan
    # TC-109 still word the outcome as a 502 exchange_error (plan DC-31, a contract question);
    # this asserts
    # the contract (22), and qa/plans/e27/chaos.md section 6 item 8 lists the disagreement.
