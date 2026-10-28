"""E17-T06 (#571), test plan "Integration": after the scripted WS session (`_ws_metrics_session`)
no unexpected label value appeared on any WS series.

Every closed set below is built from the production definition of it (a reason enum, a `Literal`,
a registry of kinds or families), never from a copy of its values, so a reason added in production
is accepted and one removed fails here. The five open-valued labels (`result`, `cause`, `kind` of
`cv_ws_rebuild_refused_total`, `event`, `symbol`) take values from sets the owning module keeps out
of reach; they are bounded by a shape (lower-case words, no digit, so no id) and by the series'
`max_series`.

Assumption: the WS collectors are process-global, and the audit reads every series the scrape
returns, so another test in the same process that observes a test-only label value (an ad-hoc
`reason`, say) would fail it. Today no test does. The scrape cannot be limited to this session's
own samples: the exporters re-export the global collectors, and no per-session registry holds them.
The audit is scoped to the series the scrape returns, as that is all anyone can scrape.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final, get_args

import pytest

from candleviewer.observability.metrics_catalogue import CATALOGUE, MetricSpec
from candleviewer.ws._generated.cvwb_layout import KINDS
from candleviewer.ws._generated.error_codes import WS_ERROR_CODES
from candleviewer.ws.coalescing import MERGED_FAMILIES, Refusal
from candleviewer.ws.lifecycle import CLOSE_REASONS, OTHER_CLOSE_REASON
from candleviewer.ws.metrics import (
    AUDIT_FAILURE_REASONS,
    AUTH_FAILURE_REASONS,
    CV_WS_NAMES,
    EXPORTED_NAMES,
    FRAME_KINDS,
    PRINCIPAL_LOAD_FAILURE_REASONS,
    WITHHELD_REASONS,
)
from candleviewer.ws.outbound import LadderEvent
from candleviewer.ws.pacing import ConnectionClass
from candleviewer.ws.pipeline import CLOSE_FLUSH_DEADLINE
from candleviewer.ws.revocation import RevokedReason
from candleviewer.ws.sequencing import COUNTED_SNAP_REASONS, PUBLISH_DENIED_FAMILIES
from candleviewer.ws.topics import FAMILIES, MACHINE_KINDS
from tests.unit.ws._seq_support import ACC_A, USER
from tests.unit.ws._ws_metrics_session import Run, Scrape, run_session_once
from tests.unit.ws.test_lifecycle_socket import SESSION


@pytest.fixture(scope="module")
def run() -> Run:
    """The scripted session, once for the module (the audits only read the final scrape)."""
    return run_session_once()


#: Closed label sets, series name -> label -> allowed values, from the constants that define them
#: (never from the session). A labelled WS series missing here fails `..._is_audited`.
_TOPIC_FAMILIES: Final = frozenset(FAMILIES) | {"unknown"}
#: `cv_ws_overflow_total{reason}`: the ladder's own events (`LadderEvent.reason` builds the label
#: from action and trigger: drop, drop_share, resnapshot, close_budget, close_redrop), the close
#: whose flush deadline expired (`CLOSE_FLUSH_DEADLINE`), the coalescer's refusal that is not a
#: slow consumer's drop (`unmergeable`, a member of `Refusal`), and `withdrawn`, which the gateway
#: counts as a bare literal (gateway.py has no constant for it).
_UNMERGEABLE: Final = "unmergeable"
assert _UNMERGEABLE in get_args(Refusal)
_OVERFLOW: Final = frozenset(
    {
        LadderEvent("drop", ()).reason,
        LadderEvent("drop", (), "share").reason,
        LadderEvent("resnapshot", ()).reason,
        LadderEvent("close", (), "budget").reason,
        LadderEvent("close", (), "redrop").reason,
        CLOSE_FLUSH_DEADLINE,
        _UNMERGEABLE,
        "withdrawn",
    }
)
_CVWB_KINDS: Final = frozenset(k.name for k in KINDS.values())
_CLOSED: Final[dict[str, dict[str, frozenset[str]]]] = {
    "cvwb_frames_encoded_total": {"kind": _CVWB_KINDS},
    "cvwb_bytes_encoded_total": {"kind": _CVWB_KINDS},
    "cv_ws_auth_failures_total": {"reason": frozenset(AUTH_FAILURE_REASONS)},
    "cv_ws_closes_total": {"reason": frozenset({*CLOSE_REASONS, OTHER_CLOSE_REASON})},
    "cv_ws_system_frames_withheld_total": {"reason": frozenset(WITHHELD_REASONS)},
    "cv_ws_audit_failures_total": {"reason": frozenset(AUDIT_FAILURE_REASONS)},
    "cv_ws_principal_load_failures_total": {"reason": frozenset(PRINCIPAL_LOAD_FAILURE_REASONS)},
    "cv_ws_publish_denied_total": {"topic": frozenset(PUBLISH_DENIED_FAMILIES)},
    "cv_ws_revoked_total": {"reason": frozenset(get_args(RevokedReason))},
    "cv_ws_resync_total": {"reason": frozenset(COUNTED_SNAP_REASONS)},
    "cv_ws_overflow_total": {"reason": _OVERFLOW},
    "cv_ws_conflated_total": {"topic": frozenset(MERGED_FAMILIES)},
    "cv_ws_connection_class": {"state": frozenset(c.value for c in ConnectionClass)},
    "cv_ws_frame_encode_seconds": {"kind": frozenset(FRAME_KINDS)},
    "cv_ws_frame_bytes": {"kind": frozenset(FRAME_KINDS)},
    "cv_ws_snapshot_bytes": {"topic": _TOPIC_FAMILIES},
    "cv_ws_snapshot_build_seconds": {"topic": _TOPIC_FAMILIES},
    "cv_ws_malformed_updates_total": {"topic": _TOPIC_FAMILIES},
    "cv_ws_subscribe_total": {"topic": _TOPIC_FAMILIES},
    "cv_ws_snapshot_overdue_total": {"topic": _TOPIC_FAMILIES},
    "cv_ws_upstream_consumers_in_use": {"topic": _TOPIC_FAMILIES},
    "cv_machine_ws_publish_total": {"entity_kind": frozenset(MACHINE_KINDS)},
    "cv_machine_ws_scope_missing_total": {"entity_kind": frozenset(MACHINE_KINDS)},
    "cv_machine_ws_registry_full_total": {"entity_kind": frozenset(MACHINE_KINDS)},
}

_SYMBOL: Final = re.compile(r"[A-Z0-9]{2,20}USDT")
#: Open-valued labels: lower-case words joined by underscores, no digit, so an id (`u123`, `42`)
#: never passes. `symbol` is a Symbol or `other`; `result` is also checked against the error codes.
_WORDS: Final = re.compile(r"[a-z]+(?:_[a-z]+)*")
_OPEN: Final[dict[tuple[str, str], re.Pattern[str]]] = {
    ("cv_ws_permission_snapshots_refused_total", "event"): _WORDS,
    ("cv_ws_rebuild_refused_total", "kind"): _WORDS,
    ("cv_ws_rebuild_refused_total", "cause"): _WORDS,
    ("cv_ws_subscribe_total", "result"): _WORDS,
    ("cv_ws_upstream_consumers_in_use", "symbol"): re.compile(rf"other|{_SYMBOL.pattern}"),
}
_SUFFIXES: Final = ("_bucket", "_count", "_sum", "_total", "_created")
_UUID: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_CONNECTION_ID: Final = re.compile(r"ws_[0-9a-f]{12}")
#: A token-shaped value: 16+ characters of hex or base64url, never a word of a closed set.
_TOKEN: Final = re.compile(r"[A-Za-z0-9_\-+/=]{16,}")


def _series_name(sample: str, names: Iterable[str]) -> str:
    """The series a sample belongs to (`..._bucket`, `..._count`, ... stripped)."""
    known = set(names)
    for candidate in (sample, *(sample.removesuffix(s) for s in _SUFFIXES)):
        if candidate in known:
            return candidate
        if f"{candidate}_total" in known:
            return f"{candidate}_total"
    return sample


def _ws_specs() -> dict[str, MetricSpec]:
    served = CV_WS_NAMES | EXPORTED_NAMES
    return {s.name: s for s in CATALOGUE if s.name in served and s.exported}


def _labelled(after: Scrape) -> list[tuple[str, dict[str, str]]]:
    """Every (series, labels) of the scrape, `le` dropped, one entry per distinct label set."""
    specs = _ws_specs()
    seen: dict[tuple[str, frozenset[tuple[str, str]]], None] = {}
    for sample, labels in after:
        name = _series_name(sample, specs)
        if name in specs:
            seen[(name, frozenset((k, v) for k, v in labels if k != "le"))] = None
    return [(name, dict(labels)) for name, labels in seen]


def _check_value(name: str, label: str, value: str) -> str | None:
    """Why `value` is not allowed for `name{label}`, or None. An unaudited label is a reason, not
    a `KeyError`."""
    if (name, label) in _OPEN:
        if _OPEN[name, label].fullmatch(value):
            return None
        return f"{name}{{{label}}}={value!r} does not match {_OPEN[name, label].pattern!r}"
    closed = _CLOSED.get(name)
    if closed is None or label not in closed:
        return f"{name}{{{label}}} has no closed set or open pattern here: audit it"
    if value not in closed[label]:
        return f"{name}{{{label}}}={value!r} is outside its closed set {sorted(closed[label])}"
    return None


def test_label_names_are_the_catalogued_ones(run: Run) -> None:
    """Every WS series of the scrape carries exactly the label names the catalogue declares."""
    specs = _ws_specs()
    seen = _labelled(run.after)
    for name, labels in seen:
        assert set(labels) == set(specs[name].labels), name
    # Not vacuous: the series the session moved are among the ones checked.
    moved = {
        "cv_ws_overflow_total",
        "cv_ws_closes_total",
        "cv_ws_resync_total",
        "cv_ws_frame_bytes",
    }
    assert moved <= {name for name, _ in seen}


def test_label_values_belong_to_their_closed_sets_or_open_patterns(run: Run) -> None:
    """Every label value on every labelled series is in the series' closed set (the reason enums,
    the kinds, the topic families, the classes) or matches its open pattern, whatever the session
    did or other tests left; a label nothing audits fails by name."""
    problems = [
        why
        for name, labels in _labelled(run.after)
        for label, value in labels.items()
        if (why := _check_value(name, label, value))
    ]
    assert problems == []


def test_an_unknown_label_name_fails_by_series_and_label() -> None:
    """The audit's failure is readable: it names the series and the label, not a `KeyError`."""
    why = _check_value("cv_ws_closes_total", "bogus", "x")
    assert why is not None and "cv_ws_closes_total{bogus}" in why
    why = _check_value("cv_ws_not_a_series", "reason", "x")
    assert why is not None and "cv_ws_not_a_series{reason}" in why


@pytest.mark.parametrize("value", ["u123", "42", "Abc", "a-b", "x" + "_1", ""])
def test_an_id_shaped_open_value_fails_its_pattern(value: str) -> None:
    for name, label in (
        ("cv_ws_subscribe_total", "result"),
        ("cv_ws_rebuild_refused_total", "cause"),
        ("cv_ws_rebuild_refused_total", "kind"),
        ("cv_ws_permission_snapshots_refused_total", "event"),
    ):
        assert _check_value(name, label, value) is not None


def test_a_symbol_label_is_a_symbol_or_other() -> None:
    series = "cv_ws_upstream_consumers_in_use"
    assert _check_value(series, "symbol", "BTCUSDT") is None
    assert _check_value(series, "symbol", "other") is None
    assert _check_value(series, "symbol", "u123") is not None
    assert _check_value(series, "symbol", "42") is not None


def test_the_closed_overflow_set_holds_the_production_reasons() -> None:
    """The ladder's own spellings, as `LadderEvent` builds them (not typed here a second time)."""
    assert {"drop", "drop_share", "resnapshot", "close_budget", "close_redrop"} <= _OVERFLOW
    assert len(_OVERFLOW) == 8


def test_subscribe_result_is_ok_or_a_catalogued_error_code(run: Run) -> None:
    """`cv_ws_subscribe_total{result}` is `ok` or one of the closed 23 section 10.2 codes."""
    results = {
        labels["result"] for name, labels in _labelled(run.after) if name == "cv_ws_subscribe_total"
    }
    assert "ok" in results and results <= {"ok", *WS_ERROR_CODES}


def test_labelled_series_is_audited(run: Run) -> None:
    """Every label of every labelled WS series the catalogue lists has a closed set or an open
    pattern above, so a new one cannot slip in unchecked; no series is served that the catalogue
    does not list."""
    specs = _ws_specs()
    for name, spec in specs.items():
        audited = set(_CLOSED.get(name, {})) | {lbl for n, lbl in _OPEN if n == name}
        assert set(spec.labels) <= audited, f"{name}: unaudited {set(spec.labels) - audited}"
    served = {_series_name(n, CV_WS_NAMES | EXPORTED_NAMES) for n, _ in run.after}
    assert {n for n in served if n.startswith(("cv_ws_", "cvwb_"))} <= set(specs)


def test_series_counts_stay_within_the_catalogue_caps(run: Run) -> None:
    """No WS series holds more label sets than its `max_series` (the cardinality audit's table)."""
    specs = _ws_specs()
    counts: dict[str, int] = {}
    for name, _ in _labelled(run.after):
        counts[name] = counts.get(name, 0) + 1
    over = {n: (c, specs[n].max_series) for n, c in counts.items() if c > specs[n].max_series}
    assert over == {}


def _closed_values() -> frozenset[str]:
    values = {v for labels in _CLOSED.values() for vs in labels.values() for v in vs}
    return frozenset(values | {"ok", *WS_ERROR_CODES})


def test_no_label_value_is_an_identifier(run: Run) -> None:
    """No label value is a user, account, session, connection or span id, a token, or a symbol:
    the ids and tokens the session used are matched literally, the rest by shape. The one series
    that may name a symbol folds the rest into `other`."""
    forbidden = {str(USER), str(ACC_A), SESSION, "tok", "BTCUSDT", "h", "a", "s"}
    for name, labels in _labelled(run.after):
        for label, value in labels.items():
            if (name, label) == ("cv_ws_upstream_consumers_in_use", "symbol"):
                continue
            assert value not in forbidden, (name, label, value)
            assert not _UUID.fullmatch(value), (name, label, value)
            assert not _CONNECTION_ID.search(value), (name, label, value)
            assert not _SYMBOL.fullmatch(value), (name, label, value)
            assert not (_TOKEN.fullmatch(value) and value not in _closed_values()), (
                name,
                label,
                value,
            )


def test_symbols_appear_only_on_the_upstream_series_and_fold_into_other(run: Run) -> None:
    """`symbol` is a label of `cv_ws_upstream_consumers_in_use` alone, and there at most 20
    distinct symbols and `other` (cap 210 = 21 x 10 public families)."""
    with_symbol = {name for name, labels in _labelled(run.after) if "symbol" in labels}
    assert with_symbol <= {"cv_ws_upstream_consumers_in_use"}
    symbols = {
        labels["symbol"]
        for name, labels in _labelled(run.after)
        if name == "cv_ws_upstream_consumers_in_use"
    }
    assert len(symbols) <= 21 and all(
        _check_value("cv_ws_upstream_consumers_in_use", "symbol", s) is None for s in symbols
    )
