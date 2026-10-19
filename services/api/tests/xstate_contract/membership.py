"""Membership rule for the blocking gate (29 §1.7): pure, unit-testable."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

_CHART = re.compile(r"^B(\d{2})\.([a-z0-9_]+)\.machine\.json$")


def missing_contract_modules(machines_dir: Path, suite_dir: Path) -> list[str]:
    """Chart files (`BNN.<id>.machine.json`) with no `test_bNN_<id>*.py`."""
    have = {p.name for p in suite_dir.glob("test_b*.py")}
    missing: list[str] = []
    for chart in sorted(machines_dir.glob("*.machine.json")):
        m = _CHART.match(chart.name)
        if m is None:
            missing.append(f"{chart.name} (name is not BNN.<id>.machine.json)")
            continue
        prefix = f"test_b{m.group(1)}_{m.group(2)}"
        short = f"test_b{m.group(1)}"
        if not any(
            n in (f"{prefix}.py", f"{short}.py") or n.startswith(f"{prefix}_") for n in have
        ):
            missing.append(chart.name)
    return missing


_INV = re.compile(r"^\|\s*\*\*(INV-B(\d+)-[a-z0-9]+)\*\*")


def catalogue_invariants(catalogue: Path, number: int) -> list[str]:
    """`INV-B<number>-*` ids declared in the catalogue's invariant tables
    (28-statechart-catalogue.md; the section number varies per machine, so
    match the id itself), in document order."""
    out: list[str] = []
    for line in catalogue.read_text(encoding="utf-8").splitlines():
        m = _INV.match(line)
        if m and int(m.group(2)) == number and m.group(1) not in out:
            out.append(m.group(1))
    return out


_CATALOGUE = Path(__file__).resolve().parents[4] / "docs" / "plan" / "28-statechart-catalogue.md"
_DEFERRED = re.compile(r"^deferred:E\d{2}$")


def check_ledger(
    number: int, ledger: Mapping[str, str | tuple[str, ...]], scope: dict[str, object]
) -> None:
    """Every catalogue `INV-B<number>-*` is mapped, and only those.

    A value is either the name of a test in the same module (the invariant
    is proven on the library here), `test_file.py::test_name` in this suite,
    or `deferred:E<nn>` — the owning epic
    whose binding bodies the invariant depends on (stubs today) — or a tuple
    of tests when several prove it, each of which must exist. A new catalogue
    invariant therefore fails this gate until it is mapped.
    """
    expected = catalogue_invariants(_CATALOGUE, number)
    assert expected, f"no INV-B{number}-* rows found in the catalogue"
    assert sorted(ledger) == sorted(expected), (
        f"B{number} invariant ledger drifted from the catalogue: "
        f"missing {sorted(set(expected) - set(ledger))}, "
        f"unknown {sorted(set(ledger) - set(expected))}"
    )
    for inv, entry in ledger.items():
        for where in (entry,) if isinstance(entry, str) else entry:
            _check_entry(inv, where, scope)


def _check_entry(inv: str, where: str, scope: dict[str, object]) -> None:
    if _DEFERRED.match(where):
        return
    if "::" in where:  # an existing suite module: `test_x.py::test_name`
        fname, test = where.split("::", 1)
        src = (Path(__file__).resolve().parent / fname).read_text(encoding="utf-8")
        assert re.search(rf"^(async )?def {re.escape(test)}\(", src, re.M), f"{inv}: {where}"
        return
    assert where.startswith("test_") and callable(scope.get(where)), f"{inv}: {where}"
