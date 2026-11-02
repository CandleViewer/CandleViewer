"""E29-S07 (#1028, BQ-9; 24-internal-schemas.md Sec.8.5 "The digest", 22 `ReconciliationDigest`):
the digest of a pass's `oms.reconcile` record and the latest one kept per account. Each record is
the one `reconcile_report.audit_state` writes for a real `ReconcileReport`, so the digest reads
what the record writer writes. Pure: no clock, no I/O."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId, TsUs
from candleviewer.oms.reconcile_digest import (
    DIGEST_LISTS,
    MAX_DIGEST_ACCOUNTS,
    MAX_DIGEST_ITEMS,
    ReconcileDigests,
    digest_of,
)
from candleviewer.oms.reconcile_report import (
    NO_RECORD_IN_FORCE,
    PassError,
    PositionDrift,
    ReconcileReport,
    audit_state,
)

A = AccountId(UUID("0a000000-0000-4000-8000-0000000000a1"))
RUN_ID = "a3000000-0000-4000-8000-000000000001"
FROM_US, TO_US = 1_793_613_480_000_000, 1_793_613_600_123_456  # 2026-11-02 09:58Z, 10:00Z
WINDOW: tuple[TsUs, TsUs] = (FROM_US, TO_US)


def _state(**lists: Any) -> dict[str, object]:
    report = ReconcileReport(A, RUN_ID, "reconnect", WINDOW, duration_ms=840, **lists)
    return audit_state(report)


def _empty() -> dict[str, object]:
    return {name: [] for name in DIGEST_LISTS}


def test_digest_of_an_empty_report_is_clean_with_nothing_listed() -> None:
    digest = digest_of(A, _state())
    assert digest == {
        "exchange_account_id": str(A),
        "pass_id": RUN_ID,
        "trigger": "reconnect",
        "result": "clean",
        "gap_window": {"from": "2026-11-02T09:58:00.000000Z", "to": "2026-11-02T10:00:00.123456Z"},
        "confirmed_at": "2026-11-02T10:00:00.123456Z",
        **_empty(),
        "position_drift": [],
        "unprotected": [],
        "counts": dict.fromkeys((*DIGEST_LISTS, "position_drift", "unprotected"), 0),
    }


@pytest.mark.parametrize("name", DIGEST_LISTS)
def test_digest_of_carries_each_report_list_as_the_record_holds_it(name: str) -> None:
    entry = "BTCUSDT" if name.startswith("sl_") else f"{name}-1"
    digest = digest_of(A, _state(**{name: (entry,)}))
    assert digest[name] == [entry]
    assert {k: v for k, v in digest.items() if k in DIGEST_LISTS and k != name} == {
        k: v for k, v in _empty().items() if k != name
    }
    counts = digest["counts"]
    assert isinstance(counts, dict) and counts[name] == 1


def test_digest_carries_position_drift_with_both_values() -> None:
    drift = PositionDrift("ETHUSDT", 0, "buy", Decimal("1.50"), None, Decimal("0"))
    digest = digest_of(A, _state(position_drift=(drift,)))
    assert digest["position_drift"] == [
        {
            "symbol": "ETHUSDT", "position_idx": 0, "side_before": "buy", "qty_before": "1.5",
            "side_after": None, "qty_after": "0",
        }
    ]  # fmt: skip
    assert digest["result"] == "corrected"


def test_digest_lists_unprotected_positions_from_no_record_in_force_errors_only() -> None:
    """An error's class or a hand-over's id never reaches a client: only the naked positions."""
    errors = (
        PassError("5", NO_RECORD_IN_FORCE, "SOLUSDT"),
        PassError("2", "ExchangeError", "cvl-1"),
        PassError("1", "handover_unreadable", "c0ffee00-0000-4000-8000-000000000001"),
    )
    digest = digest_of(A, _state(errors=errors))
    assert digest["unprotected"] == ["SOLUSDT"] and digest["result"] == "errored"
    text = json.dumps(digest)
    assert "ExchangeError" not in text and "c0ffee00" not in text and "cvl-1" not in text


def test_digest_lists_are_cut_to_their_cap_and_counts_give_full_lengths() -> None:
    many = tuple(f"cvl-{n}" for n in range(MAX_DIGEST_ITEMS + 5))
    digest = digest_of(A, _state(corrected=many))
    assert digest["corrected"] == list(many[:MAX_DIGEST_ITEMS])
    counts = digest["counts"]
    assert isinstance(counts, dict) and counts["corrected"] == MAX_DIGEST_ITEMS + 5
    assert MAX_DIGEST_ITEMS == 256


@pytest.mark.parametrize(
    "change",
    [{"gap_window": [1]}, {"gap_window": ["1", "2"]}, {"corrected": "cvl-1"}],
    ids=["one-bound", "text-bounds", "not-a-list"],
)
def test_digest_of_a_record_audit_state_does_not_write_raises(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        digest_of(A, _state() | change)


def test_digests_keep_the_latest_per_account_and_none_before_a_pass() -> None:
    digests = ReconcileDigests()
    assert digests.latest(A) is None  # nothing reported since the start
    digests.keep(A, _state(corrected=("cvl-1",)))
    digests.keep(A, _state(sl_repaired=("BTCUSDT",)))
    latest = digests.latest(A)
    assert latest is not None
    assert json.loads(latest) == digest_of(A, _state(sl_repaired=("BTCUSDT",)))
    assert digests.latest(AccountId(UUID(int=1))) is None


def test_digests_bounded_drop_the_least_recently_reported() -> None:
    assert MAX_DIGEST_ACCOUNTS == 4096
    digests = ReconcileDigests(max_accounts=3)
    accounts = [AccountId(UUID(int=n)) for n in range(1, 6)]
    with capture_logs() as logs:
        for account in accounts[:3]:
            digests.keep(account, _state())
        digests.keep(accounts[0], _state())  # reported again: the newest
        digests.keep(accounts[3], _state())
        digests.keep(accounts[4], _state())
    assert [digests.latest(a) is not None for a in accounts] == [True, False, False, True, True]
    [full] = [log for log in logs if log["event"] == "reconcile_digests_full"]
    assert (full["log_level"], full["accounts"]) == ("warning", 3)
    assert not any(str(account) in repr(logs) for account in accounts)
