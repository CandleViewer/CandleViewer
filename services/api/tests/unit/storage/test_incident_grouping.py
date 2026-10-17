"""The incident grouping of an `error` or `critical` system event (E42-T05,
`21-database-schema.md` 3.10.2a): the message normaliser strips ids, timestamps, numbers and
symbols, deterministically; the signature is 16 hex of sha256 over the component, the error class
and the normalised message; `title` and `detail` pass through `redact_text` and are cut, and a
`detail` that cannot be redacted is `None`."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.admin.ops import incidents as admin_incidents
from candleviewer.storage.repositories import incident_grouping as grouping
from candleviewer.storage.repositories.incident_grouping import (
    DETAIL_MAX,
    TITLE_MAX,
    IncidentOccurrence,
    incident_occurrence,
    incident_signature,
    normalise_message,
)


@pytest.mark.parametrize(
    ("message", "normalised"),
    [
        # the contract's own example (`listIncidents`, 22-api-openapi.yaml)
        (
            "parquet write failed for BTCUSDT segment 41",
            "parquet write failed for <symbol> segment <n>",
        ),
        (
            "postgres healthy -> down: postgres unreachable",
            "postgres healthy -> down: postgres unreachable",
        ),
        ("disk healthy -> down: used 98%", "disk healthy -> down: used <n>%"),
        ("audit chain break at id 12345", "audit chain break at id <n>"),
        ("lag 1.25 s, 1,000 rows", "lag <n> s, <n> rows"),
        ("user 6f1c2b7a-0d4e-4c55-9a3b-1e2f3a4b5c6d refused", "user <id> refused"),
        ("user DEADBEEF-DEAD-BEEF-DEAD-BEEFDEADBEEF refused", "user <id> refused"),
        ("digest 9f86d081884c7d659a2feaa0c55ad015 mismatch", "digest <id> mismatch"),
        ("order 0x1F3A and ab12cd34ef rejected", "order <id> and <id> rejected"),
        (
            "refused at 2026-10-17T10:00:00+00:00 (accepted: +/-1 step)",
            "refused at <ts> (accepted: +/-<n> step)",
        ),
        ("gap on 1000PEPEUSDT at 2026-10-17 10:00:00.123Z", "gap on <symbol> at <ts>"),
        ("day 2026-10-17 closed", "day <ts> closed"),
        ("topic orderbook.50.ETHUSDT stale", "topic orderbook.<n>.<symbol> stale"),
        ("  spread \n\t over   lines ", "spread over lines"),
        # kept: words that only look like ids or symbols, and text without a variable part
        ("deadbeef facade decade", "deadbeef facade decade"),
        ("USDT balance low", "USDT balance low"),
        ("btcusdt is not a symbol code", "btcusdt is not a symbol code"),
        ("x86_64 build", "x<n>_<n> build"),
        ("", ""),
    ],
)
def test_normalise_message_strips_ids_timestamps_numbers_and_symbols(
    message: str, normalised: str
) -> None:
    assert normalise_message(message) == normalised


_TEXT = st.text(max_size=300)
_SYMBOLS = st.from_regex(r"[A-Z0-9]{1,16}USDT", fullmatch=True)
_TIMES = st.datetimes(
    min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1), timezones=st.just(UTC)
)
# Dates, UUIDs, hex runs, `0x` literals, numbers and USDT symbols glued together with no
# separator, so every boundary rule meets its edge (a date against a UUID, a symbol against a
# number): arbitrary text almost never builds one.
_TOKENS = st.one_of(
    _TIMES.map(lambda t: t.isoformat()),
    st.dates().map(str),
    st.uuids().map(str),
    st.from_regex(r"[a-f]{8}(?:-[a-f]{4}){3}-[a-f]{12}", fullmatch=True),  # a UUID with no digit
    st.from_regex(r"[0-9a-fA-F]{8,32}", fullmatch=True),
    st.from_regex(r"0[xX][0-9a-fA-F]{1,16}", fullmatch=True),
    st.integers(0, 10**15).map(str),
    _SYMBOLS,
    st.sampled_from(["-", ".", ",", ":", " ", "T", "Z", "+", "x", "USDT", "<id>", "<n>"]),
)
_SOUP = st.lists(_TOKENS, max_size=12).map("".join)


@given(_SOUP)
def test_normalising_token_soup_is_deterministic_and_leaves_no_digit(message: str) -> None:
    normalised = normalise_message(message)
    assert normalised == normalise_message(message)
    assert re.search(r"\d", normalised) is None


@given(_TEXT)
def test_no_digit_survives_normalisation(message: str) -> None:
    assert re.search(r"\d", normalise_message(message)) is None


@given(
    st.lists(
        st.tuples(_SYMBOLS, st.integers(0, 10**12), st.uuids(), _TIMES), min_size=2, max_size=5
    )
)
def test_one_fault_never_fragments_by_symbol_number_id_or_time(
    values: list[tuple[str, int, uuid.UUID, datetime]],
) -> None:
    def message(symbol: str, n: int, ident: uuid.UUID, at: datetime) -> str:
        return f"write failed for {symbol} segment {n} run {ident} at {at.isoformat()}"

    titles = {normalise_message(message(*v)) for v in values}
    assert titles == {"write failed for <symbol> segment <n> run <id> at <ts>"}
    signatures = {incident_signature("recorder", "parquet_write", t) for t in titles}
    assert len(signatures) == 1


@given(st.text(max_size=40), st.text(max_size=40), _TEXT)
def test_the_signature_is_sixteen_lowercase_hex_and_deterministic(
    component: str, kind: str, normalised: str
) -> None:
    signature = incident_signature(component, kind, normalised)
    assert re.fullmatch(r"[0-9a-f]{16}", signature)
    assert signature == incident_signature(component, kind, normalised)


def test_the_signature_value_is_pinned() -> None:
    # Changing the encoding re-keys every stored incident (`ux_incidents_group`).
    assert incident_signature("db", "health_degraded", "x") == "4dc4d0364f592295"


def test_the_signature_keeps_the_component_kind_and_message_apart() -> None:
    signatures = {
        incident_signature("db", "health_degraded", "x"),
        incident_signature("api", "health_degraded", "x"),  # another component
        incident_signature("db", "health_recovered", "x"),  # another error class
        incident_signature("db", "health_degraded", "y"),  # another message
        incident_signature("dbhealth", "_degraded", "x"),  # the fields are never concatenated
        incident_signature("db", "health", "_degraded x"),
    }
    assert len(signatures) == 6


def test_an_occurrence_carries_the_redacted_normalised_title_and_the_redacted_message() -> None:
    occ = incident_occurrence(
        component="recorder",
        kind="parquet_write",
        severity="error",
        message="parquet write failed for BTCUSDT segment 41",
    )
    title = "parquet write failed for <symbol> segment <n>"
    assert occ == IncidentOccurrence(
        component="recorder",
        signature=incident_signature("recorder", "parquet_write", title),
        severity="error",
        title=title,
        detail="parquet write failed for BTCUSDT segment 41",
    )


def test_title_and_detail_pass_through_redact_text() -> None:
    occ = incident_occurrence(
        component="api",
        kind="probe",
        severity="critical",
        message="probe key abcdefghijklmnopqrstu code 123456 refused",  # key- and totp-shaped
    )
    assert occ.title == "[redacted:key-shape]"  # the letters-only key survives normalising
    assert occ.detail == "[redacted:key-shape]"  # the raw message: the first match wins


def test_title_and_detail_are_cut_to_the_contract_lengths_after_redaction() -> None:
    occ = incident_occurrence(component="api", kind="k", severity="error", message="ab " * 2000)
    assert (len(occ.title), len(occ.detail or "")) == (TITLE_MAX, DETAIL_MAX)
    assert (TITLE_MAX, DETAIL_MAX) == (admin_incidents.TITLE_MAX, admin_incidents.DETAIL_MAX)


def test_a_secret_across_the_cut_is_redacted_before_it_is_cut() -> None:
    # A key-shaped run that starts before the cut and ends after it: cut first, its 10-character
    # stub is too short for the redactor and would be stored.
    shaped = "abcdefghij" + "klmnopqrst" + "0123456789"
    message = "x " * ((DETAIL_MAX - 10) // 2) + shaped
    occ = incident_occurrence(component="api", kind="k", severity="error", message=message)
    assert occ.detail == "[redacted:key-shape]"


@pytest.mark.parametrize("severity", ["debug", "info", "warning"])
def test_only_errors_and_criticals_are_incidents(severity: str) -> None:
    with pytest.raises(ValueError, match=f"not an incident severity: '{severity}'"):
        incident_occurrence(component="db", kind="k", severity=severity, message="m")


def test_a_text_that_cannot_be_redacted_is_never_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "probe saw " + "hunter2"  # built by concatenation: what an exception could echo

    def broken(text: str) -> str:
        raise RuntimeError(text)

    monkeypatch.setattr(grouping, "redact_text", broken)
    with capture_logs() as logs:
        occ = incident_occurrence(component="db", kind="k", severity="error", message=secret)
    assert (occ.title, occ.detail) == ("", None)  # `title` is NOT NULL
    assert logs == [
        {
            "event": "incident_redaction_failed",
            "field": f,
            "error": "RuntimeError",
            "log_level": "error",
        }
        for f in ("title", "detail")
    ]
    assert "hunter2" not in repr(logs)


def test_timestamps_of_any_offset_and_precision_normalise_alike() -> None:
    at = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
    shifted = at.astimezone(timezone(timedelta(hours=-5, minutes=-30))) + timedelta(microseconds=7)
    assert {normalise_message(f"at {t.isoformat()}") for t in (at, shifted)} == {"at <ts>"}
