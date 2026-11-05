# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The three readings, pinned (#856 "failure taxonomy"; the scout's §3; BQ-7): every row of the
adapter's map against `24` §8.6, the corpus's error fixtures, the create-only variants and the
transport line."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from candleviewer.exchange.bybit import mapping
from spike.oms_demo_path.offline import Corpus, default_corpus
from spike.sl_attach import taxonomy

#: Where the adapter as built is coarser than §8.6 (a finding, not a fix).
DIVERGENT = {
    10005: ("AUTH_ERROR", "PERMISSION_DENIED"),
    10010: ("AUTH_ERROR", "IP_NOT_ALLOWED"),
    110003: ("INSTRUMENT_FILTER", "PRICE_OUT_OF_BOUNDS"),
    110017: ("INSTRUMENT_FILTER", "REDUCE_ONLY_VIOLATION"),
    110020: ("INSTRUMENT_FILTER", "ORDER_CAP_EXCEEDED"),
    **dict.fromkeys(
        (110013, 110016, 110031, 110047, 110048, 110086, 110089, 3400139),
        ("INSTRUMENT_FILTER", "RISK_LIMIT_EXCEEDED"),
    ),
    **dict.fromkeys((110024, 110025, 110028), ("INSTRUMENT_FILTER", "POSITION_MODE_MISMATCH")),
    **dict.fromkeys((110036, 110038, 110043), ("INSTRUMENT_FILTER", "LEVERAGE_ERROR")),
}


@pytest.mark.parametrize("code", sorted(mapping._RET_CODE_MAP))
def test_every_mapped_row_against_s86(code: int) -> None:
    reading = taxonomy.read_answer(code, "text", None, create=False)
    adapter, _ = taxonomy.adapter_code(code, "text", create=False)
    assert reading.adapter_error_code == adapter
    assert reading.s86_code == taxonomy.S86[code]
    if code in DIVERGENT:
        assert (adapter, reading.s86_code) == DIVERGENT[code] and reading.divergent
    else:
        assert adapter == reading.s86_code and not reading.divergent


_DOC = Path(__file__).resolve().parents[5] / "docs" / "plan" / "24-internal-schemas.md"
#: Rows §8.6 keeps out of the general table: `0` (success) and the create-only duplicates,
#: unmapped on any other call.
_NOT_GENERAL = {0, 20006, 110072}


def _s86_rows() -> dict[int, tuple[str, bool]]:
    """`24` §8.6's table as written: retCode -> (its internal code, "Retryable: yes")."""
    text = _DOC.read_text(encoding="utf-8").split("### 8.6 ", 1)[1].split("\n### ", 1)[0]
    rows: dict[int, tuple[str, bool]] = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 6 or not cells[1].startswith("`"):
            continue
        internal = re.findall(r"`([A-Z_]+)`", cells[3])
        for code in map(int, re.findall(r"`(\d+)`", cells[1])):
            if code not in _NOT_GENERAL and internal:
                rows[code] = (internal[0], cells[4].startswith("yes"))
    return rows


def test_the_table_is_s86_as_written() -> None:
    rows = _s86_rows()
    assert len(rows) == 41
    assert taxonomy.S86 == {code: internal for code, (internal, _) in rows.items()}
    assert {code for code, (_, yes) in rows.items() if yes} == taxonomy.S86_RETRYABLE


def test_the_corpus_error_fixtures() -> None:
    corpus = Corpus(default_corpus())
    expected = {
        "error_10002": ("CLOCK_DRIFT", "CLOCK_DRIFT", False),
        "error_10018": ("RATE_LIMITED", "RATE_LIMITED", True),
        "trading-error-110001": ("ORDER_NOT_FOUND", "ORDER_NOT_FOUND", False),
        "trading-error-110072": ("DUPLICATE_CLIENT_ID", "DUPLICATE_CLIENT_ID", False),
    }
    for name, (adapter, internal, retryable) in expected.items():
        body = corpus.rest(name)
        create = name.endswith("110072")
        reading = taxonomy.read_answer(body["retCode"], body["retMsg"], None, create=create)
        assert (reading.adapter_error_code, reading.s86_code) == (adapter, internal), name
        assert reading.retryable is retryable and not reading.divergent


def test_an_unmapped_code_reads_unknown_state_and_exchange_unknown() -> None:
    reading = taxonomy.read_answer(34040, "not modified", None, create=False)
    assert (reading.adapter_error_code, reading.s86_code) == ("UNKNOWN_STATE", "EXCHANGE_UNKNOWN")
    assert reading.divergent and reading.ret_msg_class == "not_modified"


def test_a_duplicate_is_one_on_a_create_only() -> None:
    on_create = taxonomy.read_answer(10001, "Duplicate clientOrderId", None, create=True)
    assert on_create.s86_code == on_create.adapter_error_code == "DUPLICATE_CLIENT_ID"
    elsewhere = taxonomy.read_answer(10001, "Duplicate clientOrderId", None, create=False)
    assert elsewhere.s86_code == elsewhere.adapter_error_code == "INSTRUMENT_FILTER"
    unmapped = taxonomy.read_answer(110072, "OrderLinkedID is duplicate", None, create=False)
    assert (unmapped.adapter_error_code, unmapped.s86_code) == ("UNKNOWN_STATE", "EXCHANGE_UNKNOWN")


def test_10016_is_open_on_a_create_and_retryable_on_a_stop_write() -> None:
    create = taxonomy.read_answer(10016, "Internal server error", None, create=True)
    assert (create.adapter_error_code, create.s86_code, create.retryable) == (
        "TRANSPORT_ERROR",
        "TRANSPORT_ERROR",
        False,
    )
    stop = taxonomy.read_answer(10016, "Internal server error", None, create=False)
    assert (stop.adapter_error_code, stop.s86_code, stop.retryable) == (
        "SERVICE_UNAVAILABLE",
        "SERVICE_UNAVAILABLE",
        True,
    )
    assert taxonomy.adapter_code(110079, "x", create=True) == ("UNKNOWN_STATE", False)
    assert taxonomy.read_answer(110079, "x", None, create=True).retryable is False


@pytest.mark.parametrize("code", [10006, 10018, 10403, 10429])
def test_a_create_rate_limit_stays_retryable(code: int) -> None:
    reading = taxonomy.read_answer(code, "Too many visits!", None, create=True)
    assert (reading.s86_code, reading.retryable, reading.divergent) == ("RATE_LIMITED", True, False)
    assert taxonomy.adapter_code(code, "Too many visits!", create=True) == ("RATE_LIMITED", True)


def test_the_observed_adapter_code_wins_over_the_table() -> None:
    reading = taxonomy.read_answer(10006, "Too many visits!", "RATE_BUDGET_EXCEEDED", create=False)
    assert reading.adapter_error_code == "RATE_BUDGET_EXCEEDED" and reading.divergent
    assert reading.ret_msg_class == "too_many_visits"


@pytest.mark.parametrize(
    ("status", "internal"),
    [
        (403, "IP_NOT_ALLOWED"),
        (429, "RATE_LIMITED"),
        (503, "SERVICE_UNAVAILABLE"),
        (None, "TRANSPORT_ERROR"),
    ],
)
def test_the_transport_line(status: int | None, internal: str) -> None:
    reading = taxonomy.read_transport("TRANSPORT_ERROR", status, create=False)
    assert reading.ret_code is None and reading.s86_code == internal
    assert reading.divergent is (internal != "TRANSPORT_ERROR")
    budget = taxonomy.read_transport("RATE_BUDGET_EXCEEDED", None, create=False)
    assert budget.s86_code == "RATE_BUDGET_EXCEEDED" and not budget.divergent


@pytest.mark.parametrize("status", [500, 503, 599])
def test_a_create_5xx_is_an_open_outcome_as_the_adapter_reports(status: int) -> None:
    reading = taxonomy.read_transport("TRANSPORT_ERROR", status, create=True)
    assert reading.s86_code == "TRANSPORT_ERROR" and not reading.divergent
