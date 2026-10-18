#!/usr/bin/env python3
"""Generates the cross-language equivalence corpus consumed by
`packages/protocol/scripts/generate-policy-rules.mjs` (ticket `E08-S02`,
"Client and server never disagree" scenario).

Deliberately **stdlib-only** (no `candleviewer` import): the generated-code
freshness gate (the `gen` step of `.github/workflows/pr.yml` / `tools/ci/
check_gen_freshness.py`) runs `pnpm generate` on a bare Python 3.13
venv with no project dependencies installed, so this
script cannot depend on `pydantic` or any other backend dependency.

Faithfulness to the real `InstrumentPolicy`
(`services/api/candleviewer/exchange/policy.py`) — the single source of
truth for the algorithm — is proven by
`services/api/tests/unit/exchange/test_policy_corpus_equivalence.py`,
which runs *inside* the backend's own test job (full `candleviewer` env
available there) and asserts this module's pure functions produce output
identical to `InstrumentPolicy` for the same generated corpus. That test
is what keeps this file from silently drifting into "a second
implementation" (the exact class of bug `US-MKT-004` exists to prevent).

Usage: `python tools/gen/export_instrument_policy_corpus.py [--check]`
`--check` prints the would-be file content to stdout instead of writing it
(used by the freshness check's git-diff comparison, same convention as
`extract-ws-schema.mjs --check`).
"""

from __future__ import annotations

import json
import random
import sys
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = REPO_ROOT / "packages" / "fixtures" / "golden" / "policy" / "corpus.json"

#: Fixed seed: the corpus must be byte-identical across runs (CI-GEN-003 —
#: the freshness gate runs `pnpm generate` twice and diffs the output).
_SEED = 0xE08_5202
_CASE_COUNT = 200

#: Mirrors `FilterViolationCode` in `services/api/candleviewer/exchange/
#: policy.py` verbatim (ticket "Scope / Deliverables"). Keep this order in
#: sync with the Python `StrEnum` member order — a diff there is a signal
#: this list needs updating too.
VIOLATION_CODES: tuple[str, ...] = (
    "PRICE_NOT_TICK_MULTIPLE",
    "QTY_NOT_LOT_MULTIPLE",
    "QTY_BELOW_MIN",
    "QTY_ABOVE_MAX",
    "NOTIONAL_BELOW_MIN",
    "SYMBOL_NOT_TRADING",
)

#: A handful of representative instrument filter configurations, chosen to
#: exercise every violation code and the tick/lot boundary cases named in
#: the ticket's Gherkin scenarios (not exhaustive — the per-language
#: hypothesis/fast-check property tests cover the continuous space; this
#: corpus is the fixed, cross-language equality fixture).
_INSTRUMENTS: tuple[dict[str, str], ...] = (
    {
        "symbol": "BTCUSDT",
        "status": "trading",
        "tick_size": "0.1",
        "qty_step": "0.001",
        "min_order_qty": "0.001",
        "max_order_qty": "100",
        "min_notional": "5",
    },
    {
        "symbol": "ETHUSDT",
        "status": "trading",
        "tick_size": "0.01",
        "qty_step": "0.01",
        "min_order_qty": "0.01",
        "max_order_qty": "1000",
        "min_notional": "5",
    },
    {
        # min_order_qty is deliberately *not* a qty_step multiple: ticket
        # "Rounding never crosses a limit" scenario.
        "symbol": "AWKWARDUSDT",
        "status": "trading",
        "tick_size": "0.5",
        "qty_step": "0.003",
        "min_order_qty": "0.001",
        "max_order_qty": "10",
        "min_notional": "1",
    },
    {
        "symbol": "DELISTEDUSDT",
        "status": "closed",
        "tick_size": "0.1",
        "qty_step": "0.001",
        "min_order_qty": "0.001",
        "max_order_qty": "100",
        "min_notional": "5",
    },
)


def round_price_nearest(price: Decimal, tick_size: Decimal) -> Decimal:
    """Pure-stdlib mirror of `InstrumentPolicy.round_price` (mode=nearest)."""
    steps = (price / tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    return steps * tick_size


def round_qty_down(qty: Decimal, qty_step: Decimal) -> Decimal:
    """Pure-stdlib mirror of `InstrumentPolicy.round_qty` (mode=down)."""
    steps = (qty / qty_step).to_integral_value(rounding=ROUND_DOWN)
    return steps * qty_step


def validate(price: Decimal, qty: Decimal, *, instrument: dict[str, str]) -> list[str]:
    """Pure-stdlib mirror of `InstrumentPolicy.validate`, returning just the
    violation codes (in the same order) — the corpus does not need the
    `user_message` text, only proof the two implementations agree on which
    filters fired."""
    tick_size = Decimal(instrument["tick_size"])
    qty_step = Decimal(instrument["qty_step"])
    min_order_qty = Decimal(instrument["min_order_qty"])
    max_order_qty = Decimal(instrument["max_order_qty"])
    min_notional = Decimal(instrument["min_notional"])

    codes: list[str] = []

    if instrument["status"] != "trading":
        codes.append("SYMBOL_NOT_TRADING")

    if (price % tick_size) != 0:
        codes.append("PRICE_NOT_TICK_MULTIPLE")

    qty_is_lot_multiple = (qty % qty_step) == 0
    if not qty_is_lot_multiple:
        codes.append("QTY_NOT_LOT_MULTIPLE")

    effective_qty = qty if qty_is_lot_multiple else round_qty_down(qty, qty_step)
    if effective_qty < min_order_qty:
        codes.append("QTY_BELOW_MIN")
    elif qty > max_order_qty:
        codes.append("QTY_ABOVE_MAX")

    if (price * qty) < min_notional:
        codes.append("NOTIONAL_BELOW_MIN")

    return codes


def _random_decimal(rng: random.Random, *, lo: str, hi: str, places: int) -> Decimal:
    lo_d, hi_d = Decimal(lo), Decimal(hi)
    span = hi_d - lo_d
    fraction = Decimal(rng.random()).quantize(Decimal(1).scaleb(-places))
    return (lo_d + span * fraction).quantize(Decimal(1).scaleb(-places))


def build_cases() -> list[dict[str, Any]]:
    rng = random.Random(_SEED)  # noqa: S311 - deterministic test-fixture generation, not crypto
    cases: list[dict[str, Any]] = []

    # Fixed edge cases first (ticket Gherkin scenarios verbatim), so every
    # `VIOLATION_CODES` member and both rounding-boundary scenarios are
    # guaranteed present regardless of what the random draw below happens
    # to produce.
    fixed: tuple[tuple[dict[str, str], str, str], ...] = (
        (_INSTRUMENTS[0], "50000.04", "1.000"),  # "Tick rounding"
        (_INSTRUMENTS[0], "50000.0", "0.0019"),  # "Lot rounding always rounds down"
        (_INSTRUMENTS[0], "50000.0", "150"),  # "Out of range": QTY_ABOVE_MAX
        (_INSTRUMENTS[0], "1.0", "0.001"),  # NOTIONAL_BELOW_MIN
        (_INSTRUMENTS[2], "50000.0", "0.001"),  # "Rounding never crosses a limit"
        (_INSTRUMENTS[3], "50000.0", "1.000"),  # SYMBOL_NOT_TRADING
    )
    for instrument, price_s, qty_s in fixed:
        price, qty = Decimal(price_s), Decimal(qty_s)
        cases.append(_build_case(instrument, price, qty))

    for _ in range(_CASE_COUNT):
        instrument = rng.choice(_INSTRUMENTS)
        price = _random_decimal(rng, lo="0.1", hi="100000", places=4)
        qty = _random_decimal(rng, lo="0.0001", hi="500", places=4)
        cases.append(_build_case(instrument, price, qty))
    return cases


def _build_case(
    instrument: dict[str, str], price: Decimal, qty: Decimal
) -> dict[str, Any]:
    rounded_price = round_price_nearest(price, Decimal(instrument["tick_size"]))
    rounded_qty = round_qty_down(qty, Decimal(instrument["qty_step"]))
    codes = validate(price, qty, instrument=instrument)
    return {
        "instrument": instrument,
        "price": str(price),
        "qty": str(qty),
        "expected_rounded_price": str(rounded_price),
        "expected_rounded_qty": str(rounded_qty),
        "expected_violation_codes": codes,
    }


def build_document() -> dict[str, Any]:
    return {
        "$schema_note": (
            "GENERATED - do not hand-edit. Regenerate with "
            "`python tools/gen/export_instrument_policy_corpus.py` "
            "(also run by `pnpm --filter @candleviewer/protocol generate`). "
            "Source of truth: services/api/candleviewer/exchange/policy.py."
        ),
        "violation_codes": list(VIOLATION_CODES),
        "cases": build_cases(),
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    document = build_document()
    text = json.dumps(document, indent=2, sort_keys=False, ensure_ascii=False) + "\n"

    if "--check" in argv:
        sys.stdout.write(text)
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"[export_instrument_policy_corpus] wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
