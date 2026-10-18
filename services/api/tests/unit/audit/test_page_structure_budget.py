"""The Owner page's structure budget (security re-review of #2448). A state costs the `{`, `[`
and `,` of its rendering. States are served in page order while the page's budget lasts; from
the first one that does not fit, every remaining state of the page is withheld: `null` and
listed in `detail.elided`, like a state over the size caps (contract #2446). The accounting
runs with the parse, on the hasher thread. So does a size cap per number literal, whatever
the budget."""

from __future__ import annotations

import gc
import json
import threading
import time
import warnings
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from fastapi.responses import JSONResponse
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.api.audit import _jsonable
from candleviewer.audit import query as query_mod
from candleviewer.audit.models import AuditPage
from candleviewer.audit.query import (
    DEFAULT_PAGE_STRUCTURE_BUDGET,
    NUMBER_MAX_CHARS,
    AuditQueryService,
)
from candleviewer.settings import Settings
from candleviewer.storage.repositories.audit_sqlalchemy import (
    CHAIN_FIELD_MAX_CHARS,
    CHAIN_PAGE_MAX_CHARS,
)


def _rendering(state: dict[str, Any] | None) -> str | None:
    """A state as the fake, like a jsonb column, renders it; `None` is SQL NULL."""
    return None if state is None else json.dumps(state, sort_keys=True)


def _cost(state: dict[str, Any]) -> int:
    text = json.dumps(state, sort_keys=True)
    return text.count("{") + text.count("[") + text.count(",")


def _lists(n: int) -> dict[str, Any]:
    """A container-heavy state: `n` empty lists."""
    return {"a": [[] for _ in range(n)]}


def _record(n: int, clock: FakeClock, before: Any, after: Any) -> dict[str, Any]:
    return {
        "record_id": f"00000000-0000-4000-8000-{n:012d}",
        "action": "orders.submit",
        "actor_label": "alice",
        "outcome": "success",
        "severity": "info",
        "before_state": before,
        "after_state": after,
        "event_ts": clock().isoformat(),
    }


async def _owner_page(
    repo: FakeAuditRepository, clock: FakeClock, rows: list[tuple[Any, Any]], **kw: Any
) -> AuditPage:
    """The Owner's page over `rows`, given newest first as the page lists them."""
    for n, (before, after) in enumerate(reversed(rows)):
        await repo.insert(_record(n, clock, before, after))
    svc = AuditQueryService(repo, **kw)
    try:
        return await svc.query(restrict_to_actor=None, raw=True, limit=len(rows))
    finally:
        svc.close()


async def _details(
    repo: FakeAuditRepository, clock: FakeClock, rows: list[tuple[Any, Any]], **kw: Any
) -> list[dict[str, Any]]:
    return [item.detail for item in (await _owner_page(repo, clock, rows, **kw)).items]


async def test_container_heavy_states_past_the_budget_are_withheld_and_listed(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """The budget fits the first three states exactly. The fourth is withheld, and so is
    every later state, however small; a stored null is never listed."""
    s1, s2, s3, s4 = _lists(30), _lists(20), _lists(10), _lists(40)
    rows = [(s1, s2), (s3, s4), (None, {"qty": "1"})]
    budget = _cost(s1) + _cost(s2) + _cost(s3)
    assert await _details(repo, clock, rows, structure_budget=budget) == [
        {"before": s1, "after": s2},
        {"before": s3, "after": None, "elided": ["after"]},
        {"before": None, "after": None, "elided": ["after"]},
    ]


@pytest.mark.parametrize("budget", ["exact", "default"])
async def test_states_within_the_budget_are_parsed_as_before(
    repo: FakeAuditRepository, clock: FakeClock, budget: str
) -> None:
    s1, s2, s3 = _lists(30), _lists(20), {"qty": "1"}
    exact = _cost(s1) + _cost(s2) + _cost(s3)
    kw = {"structure_budget": exact} if budget == "exact" else {}
    details = await _details(repo, clock, [(s1, s2), (None, s3)], **kw)
    assert details == [{"before": s1, "after": s2}, {"before": None, "after": s3}]


async def test_one_row_at_the_field_cap_fits_the_smallest_budget(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """The setting's floor: two states at the field cap, each as costly as one can be (every
    character but the object's own a token), so the floor leaves budget room for one row's
    states."""
    state = {"s": "," * (CHAIN_FIELD_MAX_CHARS - 9)}
    assert len(json.dumps(state)) == CHAIN_FIELD_MAX_CHARS
    budget = 2 * CHAIN_FIELD_MAX_CHARS
    [detail] = await _details(repo, clock, [(state, state)], structure_budget=budget)
    assert detail == {"before": state, "after": state}


async def test_the_budget_is_spent_with_the_parse_on_the_hasher_thread(
    repo: FakeAuditRepository, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads: list[str] = []
    real = query_mod._StructureBudget.spend

    def spy(self: Any, tokens: int) -> bool:
        threads.append(threading.current_thread().name)
        return real(self, tokens)

    monkeypatch.setattr(query_mod._StructureBudget, "spend", spy)
    await _details(repo, clock, [(_lists(2), _lists(3))])
    assert len(threads) == 2 and all(t.startswith("cv-audit-hash") for t in threads)


_STATES = st.one_of(st.none(), st.integers(1, 30).map(_lists))


@settings(max_examples=200, deadline=None)
@given(rows=st.lists(st.tuples(_STATES, _STATES), max_size=6), budget=st.integers(0, 150))
def test_the_states_served_are_the_longest_run_in_page_order_within_the_budget(
    rows: list[tuple[dict[str, Any] | None, dict[str, Any] | None]], budget: int
) -> None:
    """Every later state is withheld and listed; a stored null is null and never listed."""
    spend = query_mod._StructureBudget(budget)
    served: list[bool] = []
    costs: list[int] = []
    for before, after in rows:
        chain = {"before_state": _rendering(before), "after_state": _rendering(after)}
        detail = query_mod._owner_detail({"chain": chain}, spend)
        for key, state in (("before", before), ("after", after)):
            listed = key in detail.get("elided", [])
            if state is None:
                assert detail[key] is None and not listed
                continue
            assert detail[key] in (None, state) and listed == (detail[key] is None)
            served.append(detail[key] is not None)
            costs.append(_cost(state))
    assert served == [sum(costs[: i + 1]) <= budget for i in range(len(costs))]


def test_the_budget_setting_defaults_to_the_service_default_within_its_bounds() -> None:
    assert Settings().audit_page_structure_budget == DEFAULT_PAGE_STRUCTURE_BUDGET == 50_000
    floor = 2 * CHAIN_FIELD_MAX_CHARS
    for bound in (floor, 65_536):
        assert Settings(audit_page_structure_budget=bound).audit_page_structure_budget == bound
    for out_of_range in (floor - 1, 65_537):
        with pytest.raises(ValidationError):
            Settings(audit_page_structure_budget=out_of_range)


@pytest.mark.parametrize(
    ("literal", "served"),
    [
        ("9" * 64, True),
        ("9" * 65, False),
        ("-" + "9" * 64, False),
        ("0." + "1" * 62, True),
        ("0." + "1" * 63, False),
        ("1." + "2" * 58 + "e+300", False),
        ('"' + "9" * 65 + '"', True),
        ("1e999", False),
        ("-1e999", False),
        ("NaN", False),
    ],
    ids=["int_64", "int_65", "signed_int_65", "float_64", "float_mantissa_65",
         "float_exponent_65", "digits_in_a_string", "float_past_the_range",
         "negative_float_past_the_range", "nan"],
)  # fmt: skip
def test_a_state_holding_a_number_over_64_characters_or_not_finite_is_withheld_and_listed(
    literal: str, served: bool
) -> None:
    """A size cap per number literal (digits, sign, `.`, `e`/`E`), whatever the page's
    structure budget; a run of digits inside a string is no number literal. A number that
    is not finite (`1e999`, `NaN`) is withheld too."""
    assert NUMBER_MAX_CHARS == 64
    state = '{"n": ' + literal + "}"
    chain = {"before_state": state, "after_state": '{"qty": "1"}'}
    budget = query_mod._StructureBudget(DEFAULT_PAGE_STRUCTURE_BUDGET)
    detail = query_mod._owner_detail({"chain": chain}, budget)
    after = {"qty": "1"}
    withheld = {"before": None, "after": after, "elided": ["before"]}
    assert detail == ({"before": json.loads(state), "after": after} if served else withheld)


# ---- The on-loop render of an Owner page at the page cap once the budget applies ---------

#: Shared CI runners get no tight wall-clock assert: a render over C-2.17's 50 ms warns, and
#: only a generous sanity bound fails.
_WARN_S = 0.05
_HARD_S = 0.25
#: 128 rows of two states of about 16 000 characters each, so the page's renderings reach
#: its 4 Mi-character cap.
_ROWS, _STATE_LISTS = 128, 3_998
#: The renderings the repository fetches for a row's chain check, which its caps count.
_HASHED = (
    "actor_user_id", "actor_label", "actor_ip", "session_id", "action", "object_kind",
    "object_id", "outcome", "severity", "reason", "before_state", "after_state",
    "request_id", "env", "event_ts",
)  # fmt: skip


def _page_renderings(shape: str) -> list[str]:
    """Each row's state rendering, newest row first, as Postgres renders jsonb (non-ASCII
    characters raw). `utf8_then_floats` is the costliest page measured once the budget
    applies: strings of 4-byte UTF-8 characters (one token a state, four bytes a character),
    then 17-digit floats until the budget runs out."""
    if shape == "empty_containers":
        return [json.dumps(_lists(_STATE_LISTS))] * _ROWS
    text = '{"s": "' + "\U0001f600" * 15_991 + '"}'
    floats = '{"a": [' + ", ".join(["0.12345678901234568"] * 761) + "]}"
    return [text] * 94 + [floats] * 34


def _render_s(page: AuditPage) -> float:
    """The handler's own render of a served page, timed."""
    gc.collect()
    started = time.perf_counter()
    JSONResponse(status_code=200, content=_jsonable(page))
    return time.perf_counter() - started


@pytest.mark.perf
@pytest.mark.parametrize("shape", ["empty_containers", "utf8_then_floats"])
async def test_an_owner_page_at_the_cap_renders_within_the_sanity_bound(
    repo: FakeAuditRepository, clock: FakeClock, shape: str
) -> None:
    """The structural bound is exact: the states served never cost more than the budget.
    The render time of what is served is a sanity check and a warning."""
    for n in range(_ROWS):
        await repo.insert(_record(n, clock, {"x": 1}, {"x": 1}))
    for row, rendering in zip(reversed(repo.rows), _page_renderings(shape), strict=True):
        row["before_state"] = row["after_state"] = rendering
    sizes = [len(r[c]) for r in repo.rows for c in _HASHED if r[c] is not None]
    assert max(sizes) <= CHAIN_FIELD_MAX_CHARS
    assert 0.95 * CHAIN_PAGE_MAX_CHARS < sum(sizes) <= CHAIN_PAGE_MAX_CHARS
    svc = AuditQueryService(repo)
    try:
        page = await svc.query(restrict_to_actor=None, raw=True, limit=_ROWS)
    finally:
        svc.close()
    served = [i.detail[k] for i in page.items for k in ("before", "after")]
    assert 0 < sum(_cost(s) for s in served if s is not None) <= DEFAULT_PAGE_STRUCTURE_BUDGET
    assert any(s is None for s in served)  # the budget withheld the rest of the page
    best = min(_render_s(page) for _ in range(5))  # best-of-5 damps scheduler noise
    if best >= _WARN_S:
        warnings.warn(
            f"Owner audit page render ({shape}) {best * 1000:.1f} ms is over C-2.17's "
            "50 ms on this runner (sanity bound 250 ms)",
            stacklevel=1,
        )
    assert best < _HARD_S
