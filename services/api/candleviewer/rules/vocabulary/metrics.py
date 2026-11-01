"""Default metric descriptors (24-internal-schemas.md 7.2) and picker docs.

`DEFAULT_DOCS` carries what the registry descriptor does not: the description
and valid range shown in the picker. A registry metric with no entry fails the
completeness test (and logs a startup warning) so the two lists cannot drift.
The metrics an M9 server kernel computes (`_KERNEL_BOUND`, E13-T02) take their
unit, params, warmup, inputs and `nullable_when` from the indicator catalogue.
"""

# ruff: noqa: E501 - dense data table, one metric per line

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from candleviewer.orderflow.indicators.catalogue import SERVER_DEFINITIONS, JsonValue
from candleviewer.rules.vocabulary.registry import MetricDescriptor, MetricRegistry

# name, title, unit ("enum:a|b" for enums), input, params, warmup, confidence, scope, description, range
_Row = tuple[str, str, str, str, str, int, str, str, str, str]
_E, _S = "exact", "estimated"
_T, _B, _R = "trades", "book", "bars"
_FLOW: tuple[_Row, ...] = (
    ("cvd_slope", "CVD slope", "ratio", _T, "n=10", 10, _E, "symbol", "Least-squares slope of CVD over n bars", ""),
    ("cvd_bar_change", "CVD bar change", "qty", _T, "", 0, _E, "symbol", "CVD change over the last closed bar", ""),
    ("min_delta", "Min delta", "qty", _T, "", 0, _E, "symbol", "Intrabar delta minimum", ""),
    ("max_delta", "Max delta", "qty", _T, "", 0, _E, "symbol", "Intrabar delta maximum", ""),
    ("delta_divergence", "Delta divergence", "bool", _T, "n=10;pivot_lookback=3", 10, _S, "symbol", "Price makes a new n-bar extreme, CVD does not", ""),
    ("cvd_divergence", "CVD divergence", "bool", _T, "n=10", 10, _S, "symbol", "Pivot-based swing comparison of price vs CVD", ""),
    ("buy_sell_ratio", "Buy/sell ratio", "ratio", _T, "", 0, _E, "symbol", "buy_volume / max(sell_volume, qty_step)", ">=0"),
    ("stacked_imbalance_zone", "Stacked imbalance zone", "bool", _T, "n=20", 20, _E, "symbol", "Price is inside a stacked-imbalance run from the last n bars", ""),
    ("unfinished_auction_above", "Unfinished auction above", "count", _T, "n=50", 50, _E, "symbol", "Ticks to the nearest unfinished high within n bars", ""),
    ("unfinished_auction_below", "Unfinished auction below", "count", _T, "n=50", 50, _E, "symbol", "Ticks to the nearest unfinished low within n bars", ""),
    ("absorption", "Absorption", "bool", _T, "min_volume_z=2.0;k=2", 0, _S, "symbol", "Large volume at a level with price failing to move k ticks", ""),
    ("exhaustion", "Exhaustion", "bool", _T, "pct=0.25", 0, _S, "symbol", "One-sided extreme cell with volume below pct of the bar max cell", ""),
    ("big_trade_notional", "Big trade notional", "notional", _T, "window_ms=1000", 0, _E, "symbol", "Largest print notional in the window", ">=0"),
    ("big_trade_zscore", "Big trade z-score", "zscore", _T, "window=500;z_threshold=3.0", 0, _E, "symbol", "Z-score of print size vs rolling mean", ""),
    ("tape_speed", "Tape speed", "count", _T, "window_ms=1000", 0, _E, "symbol", "Trades per second", ">=0"),
    ("tape_speed_zscore", "Tape speed z-score", "zscore", _T, "fast_ms=1000;base_ms=300000", 0, _E, "symbol", "Fast-window tape speed vs baseline", ""),
    ("trade_cluster", "Trade cluster", "count", _T, "window_ms=50", 0, _S, "symbol", "Prints within window at same price/side treated as one aggressor", ">=0"),
    ("iceberg_present_at_level", "Iceberg present", "bool", _B, "min_reload_count=3", 0, _S, "symbol", "Repeated resting-size refills at a level", ""),
    ("iceberg_executed_volume", "Iceberg executed volume", "qty", _B, "min_reload_count=3", 0, _S, "symbol", "Volume traded through a detected iceberg level", ">=0"),
    ("stop_run_detected", "Stop-run detected", "bool", _T, "cluster_min_z=2.0", 0, _S, "symbol", "Aggressive sweep of a liquidity cluster, then reversal", ""),
    ("in_stop_hunt_zone", "In stop-hunt zone", "bool", _T, "k=5", 0, _S, "symbol", "Price within k ticks of a detected stop cluster", ""),
    ("imbalance_zone_count", "Imbalance zone count", "count", _T, "", 0, _E, "symbol", "Open imbalance zones", ">=0"),
    ("nearest_imbalance_zone_distance", "Nearest imbalance zone distance", "count", _T, "", 0, _E, "symbol", "Ticks to the nearest imbalance zone", ">=0"),
    ("imbalance_zone_side", "Imbalance zone side", "enum:buy|sell|none", _T, "", 0, _E, "symbol", "Side of the nearest imbalance zone", ""),
    ("imbalance_zone_strength", "Imbalance zone strength", "ratio", _T, "", 0, _E, "symbol", "Strength of the nearest imbalance zone", ""),
    ("imbalance_zone_mitigated", "Imbalance zone mitigated", "bool", _T, "", 0, _E, "symbol", "Nearest zone has been mitigated", ""),
    ("imbalance_zone_retest_count", "Imbalance zone retests", "count", _T, "", 0, _E, "symbol", "Retests of the nearest zone", ">=0"),
    ("imbalance_hold_rate", "Imbalance hold rate", "pct", _T, "", 0, _E, "symbol", "Share of zones that held on retest", "0..100"),
    ("diagonal_imbalance_at_price", "Diagonal imbalance at price", "bool", _T, "", 0, _E, "symbol", "Diagonal imbalance at the current price", ""),
)  # fmt: skip
_MARKET: tuple[_Row, ...] = (
    ("distance_to_liquidity_cluster", "Distance to liquidity cluster", "count", _B, "z=2.0", 0, _E, "symbol", "Ticks to the nearest heatmap cluster at or above z", ">=0"),
    ("spread_ticks", "Spread (ticks)", "count", _B, "", 0, _E, "symbol", "ask1 - bid1 in ticks", ">=0"),
    ("spread_bps", "Spread (bps)", "bps", _B, "", 0, _E, "symbol", "Spread in basis points of mid", ">=0"),
    ("mid", "Mid price", "price", _B, "", 0, _E, "symbol", "(bid1 + ask1) / 2", ""),
    ("microprice", "Microprice", "price", _B, "", 0, _E, "symbol", "Size-weighted top-of-book price", ""),
    ("dom_imbalance_ratio", "DOM imbalance ratio", "ratio", _B, "n=10", 0, _E, "symbol", "Sum bid qty / sum ask qty over top n levels", ">=0"),
    ("book_pressure", "Book pressure", "ratio", _B, "n=20", 0, _E, "symbol", "(bids - asks) / (bids + asks) over top n levels", "-1..1"),
    ("book_speed", "Book speed", "count", _B, "window_ms=1000", 0, _E, "symbol", "Book updates per second", ">=0"),
    ("queue_position_estimate", "Queue position (estimate)", "qty", _B, "", 0, _S, "position", "Same-side resting size ahead of our order", ">=0"),
    ("slippage_estimate", "Slippage estimate", "bps", _B, "qty", 0, _E, "symbol", "Cost of walking the book for a given qty", ">=0"),
    ("book_staleness_ms", "Book staleness", "ms", _B, "", 0, _E, "symbol", "Age of the last applied book update", ">=0"),
    ("heatmap_cluster_z", "Heatmap cluster z", "zscore", _B, "", 0, _E, "symbol", "Z-score of a heatmap cell's resting size", ""),
    ("liquidity_cluster_notional", "Liquidity cluster notional", "notional", _B, "", 0, _E, "symbol", "Notional resting in the nearest cluster", ">=0"),
    ("liquidity_cluster_persistence_ms", "Liquidity cluster persistence", "ms", _B, "", 0, _E, "symbol", "How long the nearest cluster has persisted", ">=0"),
    ("liquidity_pulled", "Liquidity pulled", "bool", _B, "", 0, _E, "symbol", "A cluster was pulled without trading", ""),
    ("liquidation_cluster_distance", "Liquidation cluster distance", "count", "liquidations", "", 0, _E, "symbol", "Ticks to the nearest liquidation cluster", ">=0"),
    ("liquidation_notional", "Liquidation notional", "notional", "liquidations", "side=both", 0, _E, "symbol", "Per-bar liquidated notional, by liquidated side (long, short or both)", ">=0"),
    ("price", "Price", "price", _R, "source=last", 0, _E, "symbol", "Last / mark / index price", ">0"),
    ("realized_vol", "Realised volatility", "pct", _R, "n=20", 20, _E, "symbol", "Close-close log-return stdev, annualised", ">=0"),
    ("parkinson_vol", "Parkinson volatility", "pct", _R, "n=20", 20, _E, "symbol", "High-low range volatility estimator", ">=0"),
    ("garman_klass_vol", "Garman-Klass volatility", "pct", _R, "n=20", 20, _E, "symbol", "OHLC volatility estimator", ">=0"),
    ("hurst", "Hurst exponent", "ratio", _R, "window=512", 512, _S, "symbol", "R/S analysis slope", "0..1"),
    ("market_regime", "Market regime", "enum:trending|ranging|volatile|mixed", _R, "", 512, _S, "symbol", "Regime from ADX, Hurst and ATR%", ""),
    ("open_interest", "Open interest", "qty", "oi", "", 0, _E, "symbol", "Open interest in contracts", ">=0"),
    ("open_interest_value", "Open interest value", "notional", "oi", "", 0, _E, "symbol", "Open interest notional", ">=0"),
    ("open_interest_delta", "OI change", "qty", "oi", "", 0, _E, "symbol", "OI(close) - OI(open) per bar, in contracts", ""),
    ("oi_price_quadrant", "OI/price quadrant", "enum:long_buildup|short_covering|short_buildup|long_unwind", "oi", "", 0, _E, "symbol", "Quadrant of OI change vs price change", ""),
    ("funding_rate", "Funding rate", "pct", "funding", "", 0, _E, "symbol", "Current funding rate", ""),
    ("funding_annualized", "Funding (annualised)", "pct", "funding", "", 0, _E, "symbol", "Funding rate annualised", ""),
    ("time_to_funding_ms", "Time to funding", "ms", "funding", "", 0, _E, "symbol", "Milliseconds until the next funding", ">=0"),
    ("basis", "Basis", "price", "funding", "source=last", 0, _E, "symbol", "Last (or mark, source=mark) minus index price", ""),
    ("premium_pct", "Premium", "pct", "funding", "source=last", 0, _E, "symbol", "Basis as a percent of the index price", ""),
    ("profile_poc", "Profile POC", "price", _T, "", 0, _E, "symbol", "Point of control", ">0"),
    ("profile_vah", "Profile VAH", "price", _T, "", 0, _E, "symbol", "Value area high", ">0"),
    ("profile_val", "Profile VAL", "price", _T, "", 0, _E, "symbol", "Value area low", ">0"),
    ("profile_in_value_area", "In value area", "bool", _T, "", 0, _E, "symbol", "Price is inside the value area", ""),
    ("profile_hvn_distance", "HVN distance", "count", _T, "", 0, _E, "symbol", "Ticks to the nearest high-volume node", ">=0"),
    ("profile_lvn_distance", "LVN distance", "count", _T, "", 0, _E, "symbol", "Ticks to the nearest low-volume node", ">=0"),
    ("profile_single_print_present", "Single print present", "bool", _T, "", 0, _E, "symbol", "A single-print region exists", ""),
    ("naked_poc_distance", "Naked POC distance", "count", _T, "", 0, _E, "symbol", "Ticks to the nearest untested POC", ">=0"),
    ("developing_va_width", "Developing VA width", "count", _T, "", 0, _E, "symbol", "Width of the developing value area in ticks", ">=0"),
)  # fmt: skip
_ACCOUNT: tuple[_Row, ...] = (
    ("position_open", "Position open", "bool", "positions", "", 0, _E, "position", "A position exists on the symbol", ""),
    ("position_side", "Position side", "enum:long|short|flat", "positions", "", 0, _E, "position", "Side of the position", ""),
    ("position_qty", "Position size", "qty", "positions", "", 0, _E, "position", "Position quantity", ">=0"),
    ("position_notional", "Position notional", "notional", "positions", "", 0, _E, "position", "Position notional", ">=0"),
    ("avg_entry_price", "Average entry", "price", "positions", "", 0, _E, "position", "Average entry price", ">0"),
    ("liq_price", "Liquidation price", "price", "positions", "", 0, _E, "position", "Exchange liquidation price", ">0"),
    ("unrealised_pnl", "Unrealised PnL", "notional", "positions", "", 0, _E, "position", "Unrealised profit and loss", ""),
    ("unrealised_pnl_pct", "Unrealised PnL %", "pct", "positions", "", 0, _E, "position", "Unrealised PnL percent of margin", ""),
    ("unrealised_r_multiple", "Unrealised R", "ratio", "positions", "", 0, _E, "position", "Unrealised PnL in multiples of initial risk", ""),
    ("realised_pnl_today", "Realised PnL today", "notional", "positions", "", 0, _E, "account", "Realised PnL since UTC midnight", ""),
    ("time_in_trade_ms", "Position age", "ms", "positions", "", 0, _E, "position", "Time since the position opened", ">=0"),
    ("open_positions_count", "Open positions", "count", "positions", "", 0, _E, "account", "Number of open positions", ">=0"),
    ("open_orders_count", "Open orders", "count", "orders", "", 0, _E, "account", "Number of open orders", ">=0"),
    ("account_equity", "Account equity", "notional", "wallet", "", 0, _E, "account", "Account equity", ">=0"),
    ("available_margin", "Available margin", "notional", "wallet", "", 0, _E, "account", "Free margin", ">=0"),
    ("margin_ratio", "Margin ratio", "pct", "wallet", "", 0, _E, "account", "Maintenance margin / equity", ">=0"),
    ("leverage", "Leverage", "ratio", "positions", "", 0, _E, "position", "Effective leverage", ">=0"),
    ("daily_loss_pct", "Daily loss", "pct", "wallet", "", 0, _E, "account", "Loss today as percent of start-of-day equity", ">=0"),
    ("drawdown_pct", "Drawdown", "pct", "wallet", "", 0, _E, "account", "Equity drawdown from the high-water mark", ">=0"),
    ("adl_risk_proxy", "ADL risk (proxy)", "ratio", "positions", "", 0, _S, "position", "Proxy for auto-deleverage risk", "0..1"),
    ("replay_position_ms", "Replay position", "ms", "trades", "", 0, _E, "global", "Replay cursor position", ">=0"),
    ("replay_speed", "Replay speed", "ratio", "trades", "", 0, _E, "global", "Replay speed multiplier", ">0"),
    ("replay_integrity_ok", "Replay integrity OK", "bool", "trades", "", 0, _E, "global", "Replay data is gap-free", ""),
)  # fmt: skip
_ROWS: tuple[_Row, ...] = _FLOW + _MARKET + _ACCOUNT
_NULLABLE: Final = "before warmup completes or when an input is unavailable"
_NO_OI: Final = "no OI sample in the bar, or the bar-open OI is past the staleness bound"
#: The per-bar derivatives rows (24 §7.2): bar-scoped, so `on_bar_close`, with the exact None
#: case the `DerivativesEngine` (E24-T04) yields; never defaulted to zero or to a quadrant.
_BAR_SCOPED: Final[Mapping[str, str]] = MappingProxyType(
    {
        "open_interest_delta": _NO_OI,
        "oi_price_quadrant": _NO_OI + ", or a flat price or OI change",
        "liquidation_notional": "never: a bar with no prints is 0",
    }
)

# metric, indicator, output, title, tape, description, range
_Bound = tuple[str, str, str, str, bool, str, str]
_TAPE, _NO_TAPE = True, False
#: Rule metrics an M9 server kernel computes (E13-T02): one output of a `SERVER_DEFINITIONS`
#: entry. Their unit (the output's), params (with `params_schema`), warmup, inputs, cadence,
#: `nullable_when` and confidence come from the indicator catalogue, never from here, so this
#: list and `GET /indicators` cannot drift. `tape` adds the `trades` input, as the order-flow
#: rows above have it: these values come from the aggressor split and the traded volume of bars
#: built from a symbol's recorded trades, so `requires_recording` stays true and a symbol off the
#: recorded-symbol list gets them unavailable, with the recorder action (24 §7.2). Binding a
#: `client_worker` indicator here would make it `server` (ADR-0034 rule 2): that needs its
#: kernel first.
_KERNEL_BOUND: tuple[_Bound, ...] = (
    ("delta", "delta", "delta", "Delta", _TAPE, "Bar buy_volume - sell_volume", ""),
    ("cvd", "cvd", "cvd", "CVD", _TAPE, "Running sum of signed volume from the anchor", ""),
    ("bar_volume", "volume", "volume", "Bar volume", _TAPE, "Volume of the last closed bar", ">=0"),
    ("atr", "atr", "atr", "ATR", _NO_TAPE, "Wilder average true range", ">=0"),
    ("ema", "ema", "ema", "EMA", _NO_TAPE, "Exponential moving average", ">0"),
    ("sma", "sma", "sma", "SMA", _NO_TAPE, "Simple moving average", ">0"),
    ("rsi", "rsi", "rsi", "RSI", _NO_TAPE, "Relative strength index", "0..100"),
    ("swing_high", "zigzag", "swing_high", "Swing high", _NO_TAPE, "Most recent confirmed pivot high", ">0"),
    ("swing_low", "zigzag", "swing_low", "Swing low", _NO_TAPE, "Most recent confirmed pivot low", ">0"),
    ("adx", "adx", "adx", "ADX", _NO_TAPE, "Wilder average directional index", "0..100"),
    ("vwap", "vwap", "vwap", "VWAP", _TAPE, "Volume-weighted average price", ">0"),
    ("vwap_band_sigma", "vwap", "band_sigma", "VWAP band sigma", _TAPE, "Distance from VWAP in standard deviations", ""),
)  # fmt: skip


def _bound(row: _Bound) -> MetricDescriptor:
    """A kernel-bound metric's descriptor, from its indicator definition."""
    metric, indicator, output, title, tape, _, _ = row
    definition = SERVER_DEFINITIONS[indicator]
    if output not in {o.id for o in definition.outputs}:
        raise ValueError(f"{metric}: {indicator} has no output {output}")
    inputs = (*definition.inputs, _T) if tape else definition.inputs
    return MetricDescriptor.model_validate(
        {
            "name": metric, "title": title, "unit": definition.output_unit(output),
            "value_type": definition.value_type, "scope": definition.scope, "inputs": inputs,
            "params": {k: str(v) for k, v in definition.json_defaults().items()},
            "warmup_bars": definition.warmup_bars(), "cadence": definition.cadence,
            "nullable_when": definition.nullable_when, "deterministic": definition.deterministic,
            "confidence": definition.confidence,
        }
    )  # fmt: skip


def _build() -> tuple[tuple[MetricDescriptor, ...], dict[str, tuple[str, str]]]:
    descs: list[MetricDescriptor] = []
    docs: dict[str, tuple[str, str]] = {}
    for name, title, unit_raw, inp, params, warmup, conf, scope, desc, rng in _ROWS:
        unit, enums = (
            ("enum", tuple(unit_raw[5:].split("|")))
            if unit_raw.startswith("enum:")
            else (unit_raw, ())
        )
        p = {kv.partition("=")[0]: kv.partition("=")[2] for kv in params.split(";") if kv}
        kwargs: dict[str, object] = {
            "name": name, "title": title, "unit": unit, "enum_values": enums, "scope": scope,
            "inputs": (inp,), "params": p, "warmup_bars": warmup, "confidence": conf,
            "value_type": "enum" if unit == "enum" else "bool" if unit == "bool" else "number",
            "cadence": "on_bar_close" if inp == "bars" or name in _BAR_SCOPED else "on_trade",
            "nullable_when": _BAR_SCOPED.get(name, _NULLABLE),
        }  # fmt: skip
        descs.append(MetricDescriptor.model_validate(kwargs))
        docs[name] = (desc, rng)
    for row in _KERNEL_BOUND:
        descs.append(_bound(row))
        docs[row[0]] = (row[5], row[6])
    return tuple(descs), docs


DEFAULT_DESCRIPTORS, DEFAULT_DOCS = _build()
_INDICATOR_OF: Final[Mapping[str, str]] = MappingProxyType({r[0]: r[1] for r in _KERNEL_BOUND})


def kernel_params_schema(metric: str) -> dict[str, JsonValue] | None:
    """The `params_schema` of a kernel-bound metric, its indicator's (a fresh copy); else None."""
    indicator = _INDICATOR_OF.get(metric)
    return None if indicator is None else SERVER_DEFINITIONS[indicator].params_schema()


def default_registry() -> MetricRegistry:
    return MetricRegistry(DEFAULT_DESCRIPTORS)
