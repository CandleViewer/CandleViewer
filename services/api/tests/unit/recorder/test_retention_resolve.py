from __future__ import annotations

import re
from pathlib import Path

import pytest

from candleviewer.recorder.retention import (
    HARD_DEFAULT_DAYS,
    PolicyRow,
    RetentionStepUpRequired,
    family_policy,
    partition_family,
    resolve_policy,
)
from candleviewer.storage.models import StreamKind

SYM = PolicyRow("BTCUSDT", "trades", 7, 90)
SYM_PIN = PolicyRow("BTCUSDT", "trades", 7, 90, applies_to_pinned=True)
DFLT = PolicyRow(None, "trades", 3, 60)

_REPO = Path(__file__).resolve().parents[5]
#: §7 names the QuestDB tables; two differ from their `StreamKind` value.
_TABLE_STREAM = {"orderbook_deltas": "orderbook_delta", "orderbook_snapshots": "orderbook_snapshot"}
_Row = tuple[int | None, int | None]


def _horizon(cell: str) -> int | None:
    """A §7 cell in days (`∞` = keep forever); like the seed, 12 mo = 365 d."""
    if cell == "∞":
        return None
    n, unit = cell.split()
    if unit == "d":
        return int(n)
    assert unit == "mo" and int(n) % 12 == 0, f"unparsed §7 horizon {cell!r}"
    return int(n) // 12 * 365


def _section7() -> tuple[dict[str, _Row], dict[tuple[str, str], _Row], dict[str, frozenset[str]]]:
    """Parse `21-database-schema.md` §7: per-stream rows (hot, total horizon), single-family
    rows of a split stream, and the families a split stream's shared row covers."""
    text = (_REPO / "docs/plan/21-database-schema.md").read_text("utf-8")
    body = text.split("## 7. Retention policy matrix", 1)[1].split("\n## ", 1)[0]
    streams: dict[str, _Row] = {}
    families: dict[tuple[str, str], _Row] = {}
    covered: dict[str, frozenset[str]] = {}
    known = {k.value for k in StreamKind}
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        name = re.fullmatch(r"`([a-z_/]+)`", cells[0])
        if name is None or len(cells) < 4:
            continue  # header, separator, pinned row, Postgres tables
        table = name.group(1)
        stream = "bars" if table.startswith("bars_") else _TABLE_STREAM.get(table, table)
        if stream not in known:
            continue  # e.g. `engine_metrics` (not recorded data)
        row = (_horizon(cells[1]), _horizon(cells[3]))
        fams = table.removeprefix("bars_").split("/") if table.startswith("bars_") else []
        if len(fams) == 1:
            families[(stream, fams[0])] = row
        else:
            streams[stream] = row
            if fams:
                covered[stream] = frozenset(fams)
    return streams, families, covered


def test_resolve_pinned_without_override_is_infinite() -> None:
    p = resolve_policy(
        "BTCUSDT", "trades", pinned=True, policies={("BTCUSDT", "trades"): SYM}, elevated=False
    )
    assert p.source == "pinned" and p.total_days is None


def test_resolve_symbol_policy_wins_over_default() -> None:
    pol = {("BTCUSDT", "trades"): SYM, (None, "trades"): DFLT}
    p = resolve_policy("BTCUSDT", "trades", pinned=False, policies=pol, elevated=False)
    assert (p.source, p.total_days) == ("symbol", 90)


def test_resolve_default_policy_when_no_symbol_policy() -> None:
    p = resolve_policy(
        "ETHUSDT", "trades", pinned=False, policies={(None, "trades"): DFLT}, elevated=False
    )
    assert (p.source, p.total_days) == ("default", 60)


def test_resolve_no_policy_row_uses_section7_stream_default_not_30d() -> None:
    """Review H1: pinned -> symbol -> default -> §7 per-stream default -> hard default."""
    p = resolve_policy("ETHUSDT", "trades", pinned=False, policies={}, elevated=False)
    assert (p.source, p.hot_days, p.total_days) == ("stream_default", 30, 730)
    assert HARD_DEFAULT_DAYS == 30


@pytest.mark.parametrize(
    ("stream", "hot", "total"),
    [
        ("trades", 30, 730),
        ("orderbook_delta", 7, 730),
        ("orderbook_snapshot", 30, 730),
        ("tickers", 30, 730),
        ("klines", 90, None),
        ("liquidations", 90, None),
        ("open_interest", 90, None),
        ("funding_rates", 365, None),
        ("bars", 90, 730),
        ("footprint_cells", 30, 365),
        ("profiles", 90, 730),
        ("orderflow_metrics", 90, 730),
        ("heatmap_cells", 7, 90),
    ],
)
def test_resolve_every_stream_without_rows_matches_section7(
    stream: str, hot: int, total: int | None
) -> None:
    p = resolve_policy("BTCUSDT", stream, pinned=False, policies={}, elevated=False)
    assert (p.hot_days, p.total_days, p.source) == (hot, total, "stream_default")


def test_resolve_unknown_stream_keeps_forever() -> None:
    p = resolve_policy("BTCUSDT", "engine_metrics_v9", pinned=False, policies={}, elevated=False)
    assert (p.hot_days, p.total_days, p.source) == (None, None, "unknown_stream")


def test_in_package_defaults_and_repo_seed_equal_section7() -> None:
    """Review round 4 (1): §7 is the reference, not the seed. The in-package table, the bar
    family split and the repo seed must all equal the parsed §7 matrix. The seed has one
    stream-wide row per stream (for `bars`: §7's non-`time` families), so it never shortens
    `bars_time` (keep forever), which only the per-family table expresses."""
    from candleviewer.recorder.retention_defaults import (
        FAMILY_DEFAULTS,
        STREAM_DEFAULTS,
        STREAM_ROW_FAMILIES,
    )
    from candleviewer.storage.retention.policy import load_defaults

    streams, families, covered = _section7()
    assert set(streams) == {k.value for k in StreamKind}  # §7 covers every recorder stream
    assert dict(STREAM_DEFAULTS) == streams
    assert dict(FAMILY_DEFAULTS) == families and dict(STREAM_ROW_FAMILIES) == covered
    seed = load_defaults(_REPO / "backend/db/seeds/retention_defaults.yaml")
    assert {r.stream.value: (r.hot_days, r.cold_days) for r in seed} == streams
    assert len(seed) == len(streams)  # one row per stream: no second row can override §7


@pytest.mark.parametrize(
    ("family", "total", "source"),
    [
        ("family=time/", None, "family_default"),  # §7 `bars_time`: keep forever
        ("family=tick/", 730, "stream_default"),  # §7 `bars_tick/...`: 24 mo
        ("family=delta/", 730, "stream_default"),
        ("family=pnf/", None, "family_default"),  # not in §7: fail toward retaining
        ("", None, "family_default"),  # no `family=` segment: fail toward retaining
    ],
)
def test_bars_family_policy_keeps_time_and_unlisted_families_forever(
    family: str, total: int | None, source: str
) -> None:
    eff = resolve_policy("BTCUSDT", "bars", pinned=False, policies={}, elevated=False)
    p = family_policy(eff, f"bars/{family}symbol=BTCUSDT/bar_param=1m/ym=2024-01")
    assert (p.total_days, p.source) == (total, source)


def test_family_policy_never_shortens_and_leaves_unsplit_streams_alone() -> None:
    seed_row = {(None, "bars"): PolicyRow(None, "bars", 90, 730)}  # the seed's stream-wide row
    eff = resolve_policy("BTCUSDT", "bars", pinned=False, policies=seed_row, elevated=False)
    assert eff.source == "default"
    assert family_policy(eff, "bars/family=time/symbol=BTCUSDT/ym=2024-01").total_days is None
    fp = resolve_policy("BTCUSDT", "footprint_cells", pinned=False, policies={}, elevated=False)
    key = "footprint_cells/symbol=BTCUSDT/bar_family=time/bar_param=1m/dt=2024-01-01"
    assert family_policy(fp, key) == fp  # `bar_family=` is not a §7 split
    pinned = resolve_policy("BTCUSDT", "bars", pinned=True, policies={}, elevated=False)
    assert family_policy(pinned, "bars/family=tick/symbol=BTCUSDT/ym=2024-01") == pinned
    assert partition_family("bars/family=renko/symbol=BTCUSDT/ym=2024-01") == "renko"


def test_stream_defaults_load_from_the_package_not_the_repo() -> None:
    """Review H3: importable from the installed package with no repo path or file read."""
    import importlib

    mod = importlib.import_module("candleviewer.recorder.retention_defaults")
    assert mod.STREAM_DEFAULTS["funding_rates"] == (365, None)
    assert mod.canonical_stream("funding") == "funding_rates"
    assert mod.__file__ is not None and "backend" not in mod.__file__


def test_resolve_applies_to_pinned_without_step_up_raises() -> None:
    with pytest.raises(RetentionStepUpRequired):
        resolve_policy(
            "BTCUSDT",
            "trades",
            pinned=True,
            policies={("BTCUSDT", "trades"): SYM_PIN},
            elevated=False,
        )


def test_resolve_applies_to_pinned_with_step_up_uses_policy() -> None:
    p = resolve_policy(
        "BTCUSDT", "trades", pinned=True, policies={("BTCUSDT", "trades"): SYM_PIN}, elevated=True
    )
    assert (p.source, p.total_days) == ("symbol", 90)


def test_validator_rejects_bars_outliving_trades() -> None:
    from candleviewer.recorder.retention import InvalidRetentionPolicy, validate_policies

    ok = {(None, "trades"): PolicyRow(None, "trades", 30, 730), (None, "bars"): DFLT_BARS}
    validate_policies(ok)
    for bad_days in (731, None):
        bad = ok | {("BTCUSDT", "bars"): PolicyRow("BTCUSDT", "bars", 30, bad_days)}
        with pytest.raises(InvalidRetentionPolicy):
            validate_policies(bad)
    validate_policies({(None, "bars"): PolicyRow(None, "bars", 1, 730)})  # == §7 trades
    with pytest.raises(InvalidRetentionPolicy):  # no trades row: §7 trades default applies
        validate_policies({(None, "bars"): PolicyRow(None, "bars", 1, None)})


DFLT_BARS = PolicyRow(None, "bars", 90, 730)
