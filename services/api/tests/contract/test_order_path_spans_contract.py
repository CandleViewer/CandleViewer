"""#913 (E29-T04), contract first (C-6.1): the order path's span names.

The orchestrator ruled on 2026-10-28 that `oms.submit`, `oms.persist` and `oms.send` enter
`20-architecture.md` Sec.12.3 in a docs PR of their own, ahead of S4-G3, the slice that starts
them. These pins hold 20 Sec.12.3, 24 Sec.8.2's span sentence and ADR-0014's pointer to them, and
tie the step ranges 20 cites to `OrderSubmission.submit`'s own list; S4-G3 adds the pin that ties
`observability.tracing.ORDER_PATH_SPANS` to the same names.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH
from candleviewer.observability.tracing import CREDENTIAL_SPANS, ORDER_PATH_SPANS

PLAN = OPENAPI_SPEC_PATH.parent
PACKAGE = Path(__file__).resolve().parents[2] / "candleviewer"
SUBMIT = PACKAGE / "oms" / "submit.py"


def _words(text: str) -> str:
    """The text with Markdown's line wrapping and repeated spaces folded to single spaces."""
    return re.sub(r"\s+", " ", text)


def _section(path: Path, heading: str) -> str:
    """The body of the heading matching `heading` (a regex) up to the next heading of the same
    or a higher level."""
    text = path.read_text(encoding="utf-8")
    found = re.search(heading, text, flags=re.MULTILINE)
    assert found is not None, heading
    level = found.group(0).split(" ", 1)[0]
    rest = text[found.end() :]
    after = re.search(rf"^#{{1,{len(level)}}} ", rest, flags=re.MULTILINE)
    return _words(rest[: after.start()] if after else rest)


def _tracing() -> str:
    return _section(PLAN / "20-architecture.md", r"^### 12\.3 Tracing$")


def test_20_names_a_single_orders_spans_and_their_parent() -> None:
    tracing = _tracing()
    assert (
        "A single order's submission is one trace: `http.request` (on `placeOrder`), then "
        "`oms.submit`, then its children, `oms.validate`, `oms.persist` and `oms.send`, each "
        "started when its first step is reached" in tracing
    )
    assert "with `exchange.place_order` under `oms.send`." in tracing
    assert (
        "`oms.validate` wrapped B1's first persist in E29-T03's facade; from S4-G3 it covers "
        "steps 1\u20138." in tracing
    )
    assert (
        "so `oms.send` hands the venue call a W3C trace context in process (nothing goes to the "
        "exchange), and `exchange.place_order` starts under it as `oms.send`'s child." in tracing
    )
    assert "A create B1 resumes after a restart or a rebuild has none" in tracing
    assert "`secrets.credential_borrow`, `exchange.place_order`'s child" in tracing
    assert "A trade group adds one `oms.fanout` over its legs (E34-S02)" in tracing
    assert "a fill is `private_ws.fill`, a trace of its own" in tracing
    assert "oms.validate → oms.fanout" not in tracing  # the old chain is gone


def test_20s_step_ranges_are_order_submissions_own_steps() -> None:
    """20 cites `OrderSubmission.submit`'s eleven steps, not 24 Sec.8.4's lists: steps 1 to 8 end
    at the `order_link_id`, step 9 is B1's `VALIDATE` persist, and steps 10 and 11 send and
    answer."""
    tracing = _tracing()
    assert (
        "The children follow `OrderSubmission.submit`'s own eleven steps (the list in "
        "`oms/submit.py`'s docstring)" in tracing
    )
    assert "`oms.validate` covers steps 1\u20138, from the clock halt to the `order_link_id`" in (
        tracing
    )
    assert "`oms.persist` covers step 9, B1's `VALIDATE` write-ahead persist" in tracing
    assert "`oms.send` covers steps 10\u201311, B1's `SEND` through the answer" in tracing
    doc = _words(ast.get_docstring(ast.parse(SUBMIT.read_text(encoding="utf-8"))) or "")
    steps = {int(n): text for n, text in re.findall(r"(?:^| )(\d{1,2})\. (\S+ \S+ \S+)", doc)}
    assert set(steps) == set(range(1, 12))
    assert steps[1].startswith("the clock halt")
    assert steps[8].startswith("the `order_link_id`")
    assert steps[9].startswith("the first persist")
    assert steps[10].startswith("`SEND`")
    assert steps[11].startswith("the answer")


def test_20_keeps_span_attributes_to_ids_and_codes_and_exceptions_to_their_class() -> None:
    tracing = _tracing()
    assert (
        "`oms.submit` carries `symbol`, `env`, `order_link_id` and its `result` code; its three "
        "children carry none of their own; and `http.request` carries its method, route and "
        "status code." in tracing
    )
    assert (
        "A span that ends in an exception records the exception's class, never its message or "
        "traceback (C-12.6)." in tracing
    )
    assert "traced per event" in tracing


def test_24_says_the_facade_starts_one_span_and_the_pipeline_owns_a_submissions() -> None:
    schemas = _words((PLAN / "24-internal-schemas.md").read_text(encoding="utf-8"))
    assert (
        "The facade's one span is `private_ws.fill`, not one per transition; a submission's "
        "spans are the pipeline's (`20-architecture.md` §12.3)" in schemas
    )
    assert "the two ADR-0014 §5 names" not in schemas


def test_adr_0014_points_at_20_for_the_order_paths_names() -> None:
    adr = PLAN / "27-adrs" / "ADR-0014-observability.md"
    addendum = _section(adr, r"^## Addendum \([0-9-]+\) — E29-T04 order-path spans$")
    assert "Status: reconciled; no decision overturned." in addendum
    assert "§5's order-path span names are maintained in `20-architecture.md` §12.3." in addendum


def _started(module: Path) -> list[str]:
    """The span names `module` starts: each `span("...")` call's literal name, sorted."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    return sorted(
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "span"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    )


def test_tracing_holds_20s_order_path_names_and_the_code_starts_each_where_20_says() -> None:
    """S4-G3: `ORDER_PATH_SPANS`, with the credential borrow's span, is exactly the span names 20
    Sec.12.3 gives the order path, so a name added in one place only fails here; and each is
    started where 20 and 24 Sec.8.2 put it: the route's `http.request`, the pipeline's
    `oms.submit` family, the command port's `exchange.place_order`, the facade's one span,
    `private_ws.fill`, and the broker's borrow. `oms.fanout` is E34-S02's, started nowhere yet."""
    named = set(re.findall(r"`([a-z_]+\.[a-z_]+)`", _tracing()))
    assert named - {"tracing.py"} == set(ORDER_PATH_SPANS) | set(CREDENTIAL_SPANS)
    path_names = set(ORDER_PATH_SPANS) | set(CREDENTIAL_SPANS)
    started = {
        module.relative_to(PACKAGE).as_posix(): names
        for module in sorted(PACKAGE.rglob("*.py"))
        if "migrations" not in module.parts  # SQL text, never a span
        and (names := [name for name in _started(module) if name in path_names])
    }
    assert started == {
        "api/orders.py": ["http.request"],
        "oms/commands.py": ["exchange.place_order"],
        "oms/order_machine.py": ["private_ws.fill"],
        "oms/submit.py": ["oms.persist", "oms.send", "oms.submit", "oms.validate"],
        "secrets/broker.py": ["secrets.credential_borrow"],
    }
