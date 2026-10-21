"""E17-T06 (#571) acceptance "Label cardinality stays bounded", over the catalogue's WS series.

The ticket's design notes: `topic` (the family) and `kind` are safe labels; a symbol or a user id
is not, and belongs in logs. Each label below has a closed value set in code, and each labelled
series a `max_series` cap in the catalogue; the per-series tests (`tests/unit/ws/`) pin each set
against its cap. Here: no WS series takes a label outside the reviewed names or an identifier,
each labelled one declares a cap, and the one series with a `symbol` label folds every symbol past
the first `MAX_SYMBOL_LABELS` into `other`.
"""

from __future__ import annotations

from candleviewer.observability.metrics_catalogue import CATALOGUE, MetricSpec
from candleviewer.ws.metrics import CV_WS_NAMES, EXPORTED_NAMES
from candleviewer.ws.upstream import MAX_SYMBOL_LABELS

#: The label names WS series carry, each a closed set in code: a bye/resync/ladder/audit `reason`,
#: a topic family, a sub `result`, a body or codec `kind`, a connection class `state`, a refusing
#: `cause`, a permission-snapshot `event`, and the folded `symbol`.
CLOSED_LABELS = frozenset(
    {"reason", "topic", "result", "kind", "state", "cause", "event", "symbol"}
)
#: Identifiers that must never be a label (one series each): they go in logs and audit rows.
IDENTIFIERS = frozenset(
    {
        "user",
        "user_id",
        "account",
        "account_id",
        "exchange_account_id",
        "connection",
        "connection_id",
        "session",
        "session_id",
        "request_id",
        "ch",
        "channel",
        "sub_id",
        "sp",
        "span_id",
        "source_ip",
    }
)
#: The largest cap a WS series declares: `cv_ws_subscribe_total`, topic family x result.
LARGEST_CAP = 256


def _ws_specs() -> list[MetricSpec]:
    return [s for s in CATALOGUE if s.name.startswith(("cv_ws_", "cvwb_"))]


def test_every_series_the_ws_package_serves_is_catalogued_and_live() -> None:
    """An uncatalogued series would escape the label review below."""
    live = {s.name for s in _ws_specs() if s.status == "live"}
    assert sorted((CV_WS_NAMES | EXPORTED_NAMES) - {s.name for s in CATALOGUE}) == []
    assert {n for n in CV_WS_NAMES | EXPORTED_NAMES if n.startswith(("cv_ws_", "cvwb_"))} <= live


def test_ws_series_carry_only_closed_labels_and_never_an_identifier() -> None:
    for spec in _ws_specs():
        assert set(spec.labels) <= CLOSED_LABELS, f"{spec.name}: {spec.labels}"
        assert not set(spec.labels) & IDENTIFIERS, spec.name


def test_every_labelled_ws_series_declares_its_cap() -> None:
    capped = {s.name: s.max_series for s in _ws_specs() if s.labels}
    assert capped
    assert {n: cap for n, cap in capped.items() if not 1 <= cap <= LARGEST_CAP} == {}


def test_symbol_is_a_label_only_where_symbols_fold_into_other() -> None:
    with_symbol = [s for s in _ws_specs() if "symbol" in s.labels]
    assert [s.name for s in with_symbol] == ["cv_ws_upstream_consumers_in_use"]
    # Per family: the first MAX_SYMBOL_LABELS symbols and `other`, never one series per symbol.
    assert with_symbol[0].max_series % (MAX_SYMBOL_LABELS + 1) == 0
