"""#913 (E29-T04), contract first (C-6.1): the order path's span names.

The orchestrator ruled on 2026-10-28 that `oms.submit`, `oms.persist` and `oms.send` enter
`20-architecture.md` Sec.12.3 in a docs PR of their own, ahead of S4-G3, the slice that starts
them. These pins hold 20 Sec.12.3, 24 Sec.8.2's span sentence and ADR-0014's pointer to them;
S4-G3 adds the pin that ties `observability.tracing.ORDER_PATH_SPANS` to the same names.
"""

from __future__ import annotations

import re
from pathlib import Path

from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH

PLAN = OPENAPI_SPEC_PATH.parent


def _words(text: str) -> str:
    """The text with Markdown's line wrapping and repeated spaces folded to single spaces."""
    return re.sub(r"\s+", " ", text)


def _section(path: Path, heading: str) -> str:
    """The body of `heading` up to the next heading of the same or a higher level."""
    text = path.read_text(encoding="utf-8")
    start = text.index(heading)
    level = heading.split(" ", 1)[0]
    rest = text[start + len(heading) :]
    found = re.search(rf"^#{{1,{len(level)}}} ", rest, flags=re.MULTILINE)
    return _words(rest[: found.start()] if found else rest)


def test_20_names_a_single_orders_spans_and_their_parent() -> None:
    tracing = _section(PLAN / "20-architecture.md", "### 12.3 Tracing")
    assert "A single order is one trace: `http.request` (on `placeOrder`) → `oms.submit` →" in (
        tracing
    )
    assert (
        "`oms.submit` has three children: `oms.validate` (24 §8.4 steps 1\u20138), `oms.persist` "
        "(step 9) and `oms.send` (steps 10\u201311)." in tracing
    )
    assert (
        "so `oms.send` hands the venue call a W3C trace context and `exchange.place_order` "
        "starts under it as `oms.send`'s child" in tracing
    )
    assert "a create resumed after a restart has none and starts a trace of its own" in tracing
    assert "A trade group's legs add `oms.fanout` (E34-S01)" in tracing
    assert "a fill is `private_ws.fill`, a trace of its own" in tracing


def test_20_keeps_span_attributes_to_ids_and_codes_and_exceptions_to_their_class() -> None:
    tracing = _section(PLAN / "20-architecture.md", "### 12.3 Tracing")
    assert (
        "`oms.submit` carries `symbol`, `env`, `order_link_id` and its `result` code, and "
        "`http.request` its method, route and status code." in tracing
    )
    assert (
        "A span that ends in an exception records the exception's class, never its message or "
        "traceback (C-12.6)." in tracing
    )
    assert "Market-data hot loops are _not_ traced per event" in tracing


def test_24_says_the_facade_starts_one_span_and_the_pipeline_owns_a_submissions() -> None:
    schemas = _words((PLAN / "24-internal-schemas.md").read_text(encoding="utf-8"))
    assert (
        "The facade's one span is `private_ws.fill`, not one per transition; a submission's "
        "spans are the pipeline's (§8.4; `20-architecture.md` §12.3)" in schemas
    )
    assert "the two ADR-0014 §5 names" not in schemas


def test_adr_0014_points_at_20_for_the_order_paths_names() -> None:
    adr = PLAN / "27-adrs" / "ADR-0014-observability.md"
    addendum = _section(adr, "## Addendum (2026-10-28) — E29-T04 order-path spans")
    assert "§5's order-path span names are maintained in `20-architecture.md` §12.3." in addendum
    assert "No decision is overturned." in addendum
