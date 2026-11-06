"""E29-X02 (#982): the suite checks itself, so a new route, a new topic or a lost guard fails it.

(a) Coverage (BQ-8 as amended: generated from `matrix.yaml`, and every in-scope route listed):

- every operation 22 declares on an E29 path carries `x-rbac` and is a `matrix.yaml` row, both
  ways; every executed row has its cells for every actor and every situation its route class
  pins here (never read back from the generator), and those rows are exactly the E29 operations
  the app serves: a route on an E29 path with no cell fails here, naming it (shown with a probe
  mounted in memory);
- the row `not_mounted` today, `PUT /positions/{positionId}/tpsl`, is not served and owes its
  cells the day its owning epic mounts it (E32, the position SL/TP editor);
- every mounted write has a forbidden-role cell and a cross-account (IDOR) cell, and every list
  and every write naming many accounts refuses a granted account beside a foreign one;
- every private topic of 23 Sec.6.2 is a family `test_ws_scope.py` runs, or is named with the
  suite that owns it; B1's `machines.order` (Sec.6.4) runs too.

(b) The seven reviewed `nosemgrep: cv-oms-` markers under `services/api/candleviewer` are exactly
the rows of the reviewed-exceptions table of `docs/plan/security/ci-gates-e29.md` (rule, file,
enclosing definition, `reason=`), as `tools/ci/check_drawings_exception_sites.py` holds the
drawings rules' sites: a marker moved, added or dropped fails here (S1's n-6).

(c) Scan coverage (BQ-9 as amended). Covered: gitleaks runs its whole default pack (no rule of it
disabled) and the Bybit rules over the whole tree, the recorded fixtures included, and no allowlist
path covers a fixture of
`packages/fixtures` (its scanner's own tests excepted, which plant fake keys on purpose) or this
suite, nor is there another allowlist for one to sit in (an `[[allowlists]]` table or a rule's
own); the suite writes nothing outside pytest's temporary directory (no module of it opens or
makes a file, and its world keeps the bars builders' state there). Manual, on the E29-X03
checklist (#1152): the ticket's "test artefacts" read as anything CI uploads beyond the lanes'
coverage data, and a capture that has not been recorded yet (O-1, E29-K01 #843).

(d) The PR-path budget (the ticket's performance note, BQ-9's "Add (missed)"): the suite's own
items stay within five minutes, held by `conftest.py` in CPU seconds; it waits on no real clock
(no `time.sleep`, no `asyncio.sleep` but a bare yield), every property run is bounded, and each
`TokenBucketGovernor` it builds runs on an injected clock and sleep, the reserve's compressed
bucket included.

And the live guard is E28-X03's, a fixture of every test of this suite.
"""

from __future__ import annotations

import ast
import os
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from fastapi import APIRouter

from candleviewer.api.deny_by_default import served_operations
from tests.contract.rbac.rbac_harness import ACTORS, HTTP
from tests.security.e28.conftest import live_target_refusal
from tests.security.oms import _cells as cells
from tests.security.oms._world import OmsWorld
from tests.security.oms.conftest import BUDGET_S

_HERE: Final = Path(__file__).parent
_ROOT: Final = Path(__file__).resolve().parents[5]
_UNMOUNTED: Final = {"PUT /positions/{positionId}/tpsl": "E32, the position SL/TP editor"}
_PROBE: Final = "GET /positions/{positionId}/probe"
#: Each route class's situations, pinned by hand: a list, and a write whose body names many
#: accounts, also run `mixed` (a granted account beside a foreign one in one request), and a list
#: runs with no filter too.
_SITUATIONS: Final = {
    "list": {"-", "granted", "foreign", "absent", "mixed"},
    "many": {"granted", "foreign", "absent", "mixed"},
    "one": {"granted", "foreign", "absent"},
}
_MANY: Final = {"POST /orders/cancel-all", "POST /positions/close-all"}
#: 23 Sec.6.2's private topics this suite does not run, each with what owns its scope.
_ELSEWHERE: Final = {
    "trade_groups": "E28-X03 (#976): tests/security/e28/test_ws_scope.py",
    "rules": "the rule engine's (rules:read): the matrix pack's topic cells",
    "alerts": "the caller's own alerts, never an account's",
    "recorder": "no account scope (recording:read)",
    "system": "implicit; its account notices: E29-X01's tests/security/ws/test_account_notices.py",
}
_MARKER: Final = re.compile(r"#\s*nosemgrep:\s*(cv-oms-[\w-]+)\s+reason=([\w-]+)")


def _contract_e29() -> dict[str, dict[str, object]]:
    return {
        f"{m.upper()} {p}": item[m]
        for p, item in cells.contract()["paths"].items()
        for m in HTTP
        if isinstance(item.get(m), dict) and cells.E29_PATHS.match(p)
    }


def _served(world: OmsWorld) -> set[str]:
    return {f"{m} {p}" for m, p in served_operations(world.app)}


def _class(key: str) -> str:
    """A route's class by its own shape: a read that names no id is a list."""
    if key.startswith("GET ") and "{" not in key:
        return "list"
    return "many" if key in _MANY else "one"


def _uncovered(world: OmsWorld) -> list[str]:
    covered = {cell.key for cell in cells.cells()}
    e29 = {k for k in _served(world) if cells.E29_PATHS.match(k.split(" ", 1)[1])}
    return sorted(e29 - covered)


def test_every_e29_operation_of_22_carries_x_rbac_and_is_a_row_of_the_matrix() -> None:
    declared = _contract_e29()
    assert len(declared) == 16, sorted(declared)  # the ticket's routes: a new one is listed here
    assert all("x-rbac" in op for op in declared.values()), "an E29 route with no x-rbac"
    assert set(declared) == set(cells.rows()), sorted(set(declared) ^ set(cells.rows()))


def test_the_cells_are_generated_and_cover_every_actor_and_situation() -> None:
    made = cells.cells()
    assert len(made) > 200 and len({c.id for c in made}) == len(made)
    for key in cells.rows("executed"):
        got = {(c.actor, c.at) for c in made if c.key == key}
        assert got == {(a, s) for a in ACTORS for s in _SITUATIONS[_class(key)]}, key
    classes = {c.expect for c in made}
    assert classes == {"allow", *cells.ANSWER}, classes  # every refusal class is exercised


def test_every_list_and_every_write_naming_many_accounts_refuses_a_mixed_request() -> None:
    """The smuggling case of C-12.4's IDOR rule: a granted account beside a foreign one, in a
    filter or a body, is refused whole (`scope`), never served in part."""
    made = {c.id: c.expect for c in cells.cells()}
    many = sorted(k for k in cells.rows("executed") if _class(k) != "one")
    assert len(many) == 6 and _MANY <= set(many), many
    mixed = {k: made.get(f"{k}|manager_with_grant|mixed") for k in many}
    assert mixed == dict.fromkeys(many, "scope"), mixed


def test_every_served_e29_route_has_cells_and_no_cell_is_for_a_route_not_served(
    world: OmsWorld,
) -> None:
    assert not _uncovered(world), f"E29 routes served with no cell: {_uncovered(world)}"
    stale = {c.key for c in cells.cells()} - _served(world)
    assert not stale, f"cells for routes not served: {sorted(stale)}"


def test_the_unmounted_row_is_not_served_and_owes_its_cells(world: OmsWorld) -> None:
    assert set(cells.rows("not_mounted")) == set(_UNMOUNTED)
    mounted = sorted(set(_UNMOUNTED) & _served(world))
    assert not mounted, f"now served: give these cells and an executed row: {mounted}"


def test_every_mounted_write_has_its_forbidden_role_and_cross_account_cells() -> None:
    made = cells.cells()
    for key in [k for k in cells.rows("executed") if not k.startswith("GET ")]:
        mine = [c for c in made if c.key == key]
        assert any(c.actor == "viewer" and c.expect == "role" for c in mine), key
        idor = [c for c in mine if c.actor == "manager_with_grant" and c.at in ("foreign", "mixed")]
        assert idor and all(c.denied for c in idor), key


@pytest.fixture
def probe(world: OmsWorld) -> Iterator[str]:
    """`_PROBE` mounted as a ticket might, with no cell; the routes restored by identity."""
    routes = list(world.app.router.routes)
    router = APIRouter()

    @router.get("/positions/{positionId}/probe")
    async def leaked() -> dict[str, str]:
        return {"state": "leaked"}

    world.app.include_router(router)
    try:
        yield _PROBE
    finally:
        world.app.router.routes[:] = routes
    assert _PROBE not in _served(world)


def test_an_e29_route_mounted_without_cells_fails_the_coverage(world: OmsWorld, probe: str) -> None:
    assert _uncovered(world) == [probe]


def test_every_private_topic_of_23_is_run_here_or_named_with_its_owner() -> None:
    text = (_ROOT / "docs/plan/23-ws-protocol.md").read_text("utf-8")
    table = text[text.index("### 6.2 Private topics") : text.index("**`orders` and `executions`")]
    private = set(re.findall(r"^\| `(\w+)`", table, re.M))
    ours = set(cells.WS_TOPICS) - {"machines.order"}
    assert private == ours | set(_ELSEWHERE), sorted(private ^ (ours | set(_ELSEWHERE)))
    topics = cells.matrix()["topics"]
    assert all(topics[t]["scope"] == "granted_accounts" for t in cells.WS_TOPICS)
    assert all(set(cells.ws_outcomes(t)) == set(ACTORS) for t in cells.WS_TOPICS)


def _markers() -> list[tuple[str, str, str, str]]:
    """Each `nosemgrep: cv-oms-` marker: its rule, file, enclosing definition and reason."""
    base = _ROOT / "services/api/candleviewer"
    found: list[tuple[str, str, str, str]] = []
    for path in sorted(base.rglob("*.py")):
        lines = path.read_text("utf-8").splitlines()
        hits = [(n, m) for n, line in enumerate(lines, 1) if (m := _MARKER.search(line))]
        if not hits:
            continue
        tree = ast.parse("\n".join(lines))
        for line, match in hits:
            name = _enclosing(tree, line + 1)
            found.append((match[1], str(path.relative_to(base)), name, match[2]))
    return sorted(found)


def _enclosing(tree: ast.AST, line: int) -> str:
    """The qualified name of the innermost class or function holding `line`, outermost first."""
    names: list[str] = []
    node: ast.AST = tree
    while True:
        inner = [
            child for child in ast.iter_child_nodes(node)
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and child.lineno <= line <= (child.end_lineno or child.lineno)
        ]  # fmt: skip
        if not inner:
            return ".".join(names)
        node = inner[0]
        names.append(inner[0].name)


def _table() -> list[tuple[str, str, str, str]]:
    """The reviewed-exceptions table of S1's rule doc: rule, file, definition, reason."""
    text = (_ROOT / "docs/plan/security/ci-gates-e29.md").read_text("utf-8")
    section = text[text.index("## Reviewed exceptions") :].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) == 4 and cols[0].startswith("`cv-oms-"):
            site = re.findall(r"`([^`]+)`", cols[1])
            rows.append((cols[0].strip("`"), site[0], site[1], cols[2].strip("`")))
    return sorted(rows)


def test_the_oms_markers_are_exactly_the_reviewed_exceptions_of_the_rule_doc() -> None:
    markers, table = _markers(), _table()
    assert len(table) == 7, table
    assert [(r, f, d.split(".<")[0], why) for r, f, d, why in markers] == table


def test_no_gitleaks_allowlist_path_covers_a_recorded_fixture_or_this_suite() -> None:
    config = tomllib.loads((_ROOT / ".gitleaks.toml").read_text("utf-8"))
    assert config["extend"] == {"useDefault": True}, "the default pack is not whole"
    assert {"bybit-api-key", "bybit-hmac-signature"} <= {r["id"] for r in config["rules"]}
    assert "allowlists" not in config, "an [[allowlists]] table, which this test does not read"
    scoped = [r["id"] for r in config["rules"] if {"allowlist", "allowlists"} & set(r)]
    assert not scoped, f"a rule-level allowlist, which this test does not read: {scoped}"
    allowed = [re.compile(p) for p in config["allowlist"]["paths"]]
    fixtures = _ROOT / "packages/fixtures"
    files = [p for p in fixtures.rglob("*") if p.is_file() and "node_modules" not in p.parts]
    covered = sorted(
        rel for p in [*files, *_HERE.glob("*.py")]
        if any(a.search(rel := str(p.relative_to(_ROOT))) for a in allowed)
    )  # fmt: skip
    assert len(files) > 50 and all(c.startswith("packages/fixtures/test/") for c in covered), (
        covered
    )


_WRITERS: Final = {"write_text", "write_bytes", "mkdir", "mkdtemp", "mkstemp", "touch"}


def _writes(call: ast.Call) -> bool:
    """A call that makes or writes a file: an `open` in a writing mode, or one of `_WRITERS`."""
    name = getattr(call.func, "attr", getattr(call.func, "id", ""))
    modes = [a.value for a in [*call.args, *(k.value for k in call.keywords)]
             if isinstance(a, ast.Constant) and isinstance(a.value, str)]  # fmt: skip
    return name in _WRITERS or (name == "open" and any(set(m) & set("wax+") for m in modes))


def test_the_suite_writes_nothing_outside_the_temporary_directory(
    world: OmsWorld, tmp_path_factory: pytest.TempPathFactory
) -> None:
    for module in _HERE.glob("*.py"):
        tree = ast.parse(module.read_text("utf-8"))
        writes = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and _writes(n)]
        assert not writes, (module.name, writes)
    root = Path(world.app.state.app_context.settings.bars_state_root)
    assert root.is_relative_to(tmp_path_factory.getbasetemp().resolve()), root


def test_the_guard_is_e28s_and_refuses_a_live_target() -> None:
    assert live_target_refusal({"CV_ENVIRONMENT": "live"}) == "CV_ENVIRONMENT targets live"
    assert live_target_refusal({"CV_ENVIRONMENT": "demo"}) is None


def test_every_test_of_the_suite_runs_behind_the_guard(request: pytest.FixtureRequest) -> None:
    here = os.fspath(_HERE)
    mine = [i for i in request.session.items if str(getattr(i, "path", "")).startswith(here)]
    assert mine, "no item of the suite collected"
    unguarded = [i.nodeid for i in mine if "_live_guard" not in getattr(i, "fixturenames", ())]
    assert not unguarded, unguarded


def _named(call: ast.Call) -> str:
    """A call's dotted name as written (`asyncio.sleep`, `settings`), or empty."""
    return ast.unparse(call.func) if isinstance(call.func, ast.Name | ast.Attribute) else ""


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {k.arg: k.value for k in call.keywords if k.arg is not None}


def test_the_suite_keeps_the_pr_path_budget_on_injected_clocks_and_bounded_runs() -> None:
    assert BUDGET_S == 5 * 60  # the ticket's performance note, held by conftest.py
    calls = [
        (module.name, node) for module in sorted(_HERE.glob("*.py"))
        for node in ast.walk(ast.parse(module.read_text("utf-8"))) if isinstance(node, ast.Call)
    ]  # fmt: skip
    waits = [(m, _named(c), ast.unparse(c)) for m, c in calls if _named(c).endswith("sleep")]
    real = [w for w in waits if w[1] != "asyncio.sleep" or w[2] != "asyncio.sleep(0)"]
    assert not real, f"a real wait: {real}"
    runs = [(m, _keywords(c).get("max_examples")) for m, c in calls if _named(c) == "settings"]
    bound = [(m, n.value if isinstance(n, ast.Constant) else None) for m, n in runs]
    unbounded = [m for m, n in bound if not (isinstance(n, int) and n <= 25)]
    assert runs and not unbounded, f"a property run with no bound of 25 examples: {unbounded}"
    built = [(m, _keywords(c)) for m, c in calls if _named(c) == "TokenBucketGovernor"]
    real_clock = [m for m, kw in built if not {"clock", "sleep"} <= set(kw)]
    assert built and not real_clock, f"a governor on the real clock: {real_clock}"
