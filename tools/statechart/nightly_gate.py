"""Nightly xstate gate verdict (E50-T04; 29-statechart-adoption-plan.md §1.7).

Consumes the ``--json`` output of ``docs/research/xstate/gate/run_gate.py`` and
(optionally) the JSON of ``docs/research/xstate/bench/bench_c_timers_v2.py``
(BENCH-6), writes the nightly report and decides the exit code.

* ``--mode pinned``   gates. ``run_gate.py`` itself exits 1 on the *known*
  0.9.1 baseline failures (triaged in ADR-0016), so the verdict here is a
  regression diff: a blocking check (any non-``repro`` FAIL, or any ERROR)
  that is not already failing in the committed baseline result. A BENCH-6
  p99 above the threshold at 500 busy machines (or none at all) also fails,
  and so does lost coverage: a check that PASSED in the baseline but is
  ``SKIP-ENV`` now, because the nightly can no longer see what it gates.
* ``--mode upstream`` never gates: same report, always exit 0, every delta is
  an informational note that feeds the upstream-liaison chore.

Two refinements apply in ``--mode pinned`` only (#579 triage,
``docs/research/xstate/81-nightly-gate-triage.md``):

* ``KNOWN_DELTAS`` excuses a row whose nightly status differs from the
  committed baseline for a reason the research docs already record. Each entry
  names the one status it excuses and carries its justification line, like
  ``run_gate.py``'s ``*_BASELINE_FAILURES`` lists. An entry may also set a
  ``floor``: the row is excused only while the leading number of its detail
  (the measured value) parses and is at or above it, so a collapse still gates.
  Any other status of that row (an ERROR, a different FAIL/PASS) is judged by
  the ordinary rules, and a row that no longer shows its documented status is
  reported as drift.
* When ``--bench`` is supplied, BENCH-6 is judged once, from that measurement.
  ``run_gate.py``'s own ``bench:BENCH-6`` row runs the same script, so it is
  reported but not counted a second time.

Offline and deterministic: it only reads files. Exit 0 = green (or
informational), 1 = pinned regression / BENCH-6 breach / lost coverage, 2 = unreadable input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NamedTuple

BENCH6_THRESHOLD_MS = 100.0
BENCH6_LEVEL = "500"
SKIP_ENV = "SKIP-ENV"
# Above this share of SKIP-ENV checks the report warns that the run says little (#1928).
SKIP_WARN_RATIO = 0.25
# run_gate.py's own BENCH-6 row; superseded by ``--bench`` when that is supplied (#579).
BENCH6_ROW = "bench:BENCH-6"


class KnownDelta(NamedTuple):
    """A documented, justified difference from the committed baseline."""

    status: str  # the single status this entry excuses
    why: str  # one justification line, citing the doc that records it
    floor: float | None = None  # lowest measured value still excused; None = any value


# #579 (81-nightly-gate-triage.md). result-v0.9.1.json was recorded once, on
# Windows / Python 3.13.7 and without benchmarks; the nightly runs on Linux with
# them. Only rows whose difference is already documented are listed. BENCH-1 is
# deliberately absent: a shared-runner BENCH-1 is inconclusive, and how to gate it
# is an open owner decision (item M on #1778).
# Open follow-ups: rewrite criterion [2] of the two 174 scripts, which retires their
# entries (#ISSUE-CRITERION2); bench_c_timers_v2.py reports the second-largest of 5 runs
# as "p99", which bench6() judges (#ISSUE-P99); the upstream job has no upstream checkout,
# so most env rows skip there (#ISSUE-UPSTREAM).
KNOWN_DELTAS: dict[str, KnownDelta] = {
    "bench:BENCH-2": KnownDelta(
        "FAIL",
        "(c) architectural and permanent: per-tick rule evaluation stays plain code "
        "(owner decision 2026-09-24 in 29-statechart-adoption-plan.md; "
        "79-r14-final-readiness-verdict.md s.0 and s.9: 380.9 vs 2,000 ev/s, row 8). "
        "Excused only at or above 380.9 ev/s, the study figure that decision rests on (the "
        "nightly reads 569-1,195); a lower or unreadable value is a regression. "
        "The baseline ran without benches; BENCH-7 remains the hot-path regression guard.",
        floor=380.9,
    ),
    "verifyM4:174": KnownDelta(
        "FAIL",
        "(d) stale criterion [2]: it asserts busy-loop `after` lateness > 15 ms, which only "
        "the Windows ~15.6 ms timer tick produced (20-adoption-gate.md s.3, BENCH-5). "
        "Upstream re-measured #174's busy loop at 0-1 ms (CHANGELOG 0.9.0); Linux reads ~1 ms. "
        "Criteria [1] docs and [3] plain-def service blocks ~500 ms still hold. "
        "Rewrite of [2] tracked in #ISSUE-CRITERION2.",
    ),
    "verifyM5:174": KnownDelta(
        "FAIL",
        "(d) stale criterion [2], as verifyM4:174 (Windows timer tick, not the library). "
        "Criteria [1] docs, [3] plain-def service blocks ~500 ms and [4] async def remedy "
        "fires on time still hold (44-r7 and 49-r8 verdicts: #174 DOCUMENTED-ONLY). "
        "Rewrite of [2] tracked in #ISSUE-CRITERION2.",
    ),
}


def _key(check: dict[str, Any]) -> str:
    return f"{check.get('kind')}:{check.get('id')}"


def _blocking_failures(result: dict[str, Any]) -> dict[str, str]:
    """``kind:id -> status`` for every blocking non-green check."""
    out: dict[str, str] = {}
    for c in result.get("checks", []):
        status = c.get("status")
        if status == "ERROR" or (status == "FAIL" and c.get("kind") != "repro"):
            out[_key(c)] = str(status)
    return out


def regressions(
    result: dict[str, Any], baseline: dict[str, Any], excused: frozenset[str] = frozenset()
) -> list[str]:
    """Blocking failures present in ``result`` but not in ``baseline`` nor ``excused``."""
    known = _blocking_failures(baseline)
    return sorted(k for k in _blocking_failures(result) if k not in known and k not in excused)


def _statuses(result: dict[str, Any]) -> dict[str, str]:
    return {_key(c): str(c.get("status")) for c in result.get("checks", [])}


# run_gate.py words a bench row's detail as "569.00 ev/s (need >= 2,000.00; ...)".
_LEADING_NUMBER = re.compile(r"\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)")


def measured(detail: object) -> float | None:
    """The leading number of a bench row's ``detail`` (thousands separators allowed), or None."""
    m = _LEADING_NUMBER.match(detail) if isinstance(detail, str) else None
    return float(m.group(1).replace(",", "")) if m else None


def _excused(row: Mapping[str, Any] | None, delta: KnownDelta) -> bool:
    """``row`` shows the status ``delta`` excuses and, if it sets a floor, a value at or above it.

    A floor that cannot be checked (no readable value) excuses nothing: fail closed.
    """
    if row is None or row.get("status") != delta.status:
        return False
    if delta.floor is None:
        return True
    value = measured(row.get("detail"))
    return value is not None and value >= delta.floor


def documented_deltas(
    result: dict[str, Any], table: Mapping[str, KnownDelta] = KNOWN_DELTAS
) -> list[str]:
    """Rows their ``KNOWN_DELTAS`` entry excuses: the documented status, at or above any floor."""
    rows = {_key(c): c for c in result.get("checks", [])}
    return sorted(k for k, d in table.items() if _excused(rows.get(k), d))


def below_floor(
    result: dict[str, Any], table: Mapping[str, KnownDelta] = KNOWN_DELTAS
) -> list[str]:
    """Rows at the documented status that the floor does not excuse: they are regressions."""
    rows = {_key(c): c for c in result.get("checks", [])}
    out: list[str] = []
    for k, d in table.items():
        row = rows.get(k)
        if row is not None and row.get("status") == d.status and not _excused(row, d):
            value = measured(row.get("detail"))
            shown = "unreadable" if value is None else f"{value:,.2f}"
            out.append(f"{k} {d.status}: measured {shown}, floor {d.floor}")
    return sorted(out)


def delta_drift(
    result: dict[str, Any], table: Mapping[str, KnownDelta] = KNOWN_DELTAS
) -> list[str]:
    """Entries whose row is missing or shows another status: the entry needs re-triage."""
    now = _statuses(result)
    return sorted(
        f"{k} is {now.get(k, 'missing')}, documented as {d.status}"
        for k, d in table.items()
        if now.get(k) not in (d.status, SKIP_ENV)
    )


def skipped_env(result: dict[str, Any]) -> list[str]:
    """Checks run_gate.py reported as ``SKIP-ENV`` (skipped (environment), #1928)."""
    return sorted(_key(c) for c in result.get("checks", []) if c.get("status") == SKIP_ENV)


def coverage_lost(result: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Checks that PASSED in the baseline but are SKIP-ENV now (lost coverage, not a regression)."""
    passed = {_key(c) for c in baseline.get("checks", []) if c.get("status") == "PASS"}
    return [k for k in skipped_env(result) if k in passed]


def skip_ratio(result: dict[str, Any]) -> float:
    """Share of all checks that were SKIP-ENV (0.0 when there are no checks)."""
    total = len(result.get("checks", []))
    return len(skipped_env(result)) / total if total else 0.0


def fixed(result: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Baseline blocking failures that no longer fail (improvements).

    A check skipped for environment reasons was not run, so it is not "fixed".
    """
    now = _blocking_failures(result)
    skipped = set(skipped_env(result))
    return sorted(k for k in _blocking_failures(baseline) if k not in now and k not in skipped)


def bench6(bench: dict[str, Any] | None, threshold: float) -> tuple[bool | None, float | None]:
    """Return ``(ok, p99)``.

    ``ok`` is None when no bench was supplied, False when the p99 is missing
    (absence of evidence never passes) or over budget.
    """
    if bench is None:
        return None, None
    level = (bench.get("summary_by_busy_level") or {}).get(BENCH6_LEVEL) or {}
    p99 = level.get("p99")
    if p99 is None:
        return False, None
    return float(p99) <= threshold, float(p99)


def render(
    *,
    mode: str,
    date: str,
    result: dict[str, Any],
    new: list[str],
    gone: list[str],
    bench_ok: bool | None,
    p99: float | None,
    threshold: float,
    skipped: list[str] | None = None,
    lost: list[str] | None = None,
    ratio: float = 0.0,
    documented: list[tuple[str, KnownDelta]] | None = None,
    drift: list[str] | None = None,
    bench6_row: str | None = None,
    unexcused: list[str] | None = None,
) -> str:
    gating = mode == "pinned"
    red = bool(new) or bench_ok is False or (gating and bool(lost))
    verdict = ("RED" if red else "GREEN") if gating else ("NOTE" if red else "CLEAN")
    lines = [
        f"# xstate nightly gate - {date} ({mode})",
        "",
        f"- Verdict: **{verdict}**" + ("" if gating else " (informational, never gates)"),
        f"- Library: {result.get('library_version')} @ {result.get('library_commit')}",
        f"- Build: {result.get('build')}",
        f"- run_gate exit code: {result.get('exit_code')}",
        "",
        "## Regressions vs committed baseline",
    ]
    lines += [f"- {k}" for k in new] or ["- none"]
    lines += ["", "## Baseline failures now passing"]
    lines += [f"- {k}" for k in gone] or ["- none"]
    lines += ["", "## Skipped (environment) - not run on this host, not a regression"]
    lines += [f"- {k}" for k in skipped or []] or ["- none"]
    for k in lost or []:
        gate = " - blocking in pinned mode" if gating else ""
        lines.append(
            f"- COVERAGE LOSS: {k} passed in the baseline but was skipped (environment){gate}"
        )
    if ratio > SKIP_WARN_RATIO:
        lines.append(
            f"- WARNING: {ratio:.0%} of checks skipped (environment), above "
            f"{SKIP_WARN_RATIO:.0%}; this run covers little (non-blocking)"
        )
    if documented is not None:
        lines += ["", "## Documented deltas vs committed baseline - excused, each justified"]
        lines += [f"- {k} {d.status}: {d.why}" for k, d in documented] or ["- none"]
        lines += [f"- NOT EXCUSED (blocking): {u}" for u in unexcused or []]
        lines += [f"- DRIFT (re-triage the entry, non-blocking): {d}" for d in drift or []]
    lines += ["", "## BENCH-6 (timer lateness, 500 busy machines, p99)"]
    if bench_ok is None:
        lines.append("- not run")
    else:
        shown = "missing" if p99 is None else f"{p99:.1f} ms"
        status = "ok" if bench_ok else "BREACH"
        lines.append(f"- p99 {shown} vs budget {threshold:.0f} ms: {status}")
    if bench6_row is not None:
        lines.append(
            f"- run_gate row {BENCH6_ROW} ({bench6_row}) runs the same script: "
            "superseded by this measurement, not counted twice"
        )
    if gating and red:
        lines += ["", "Notify: E50-C17 (upstream liaison) - pinned gate regression."]
    return "\n".join(lines) + "\n"


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path}: expected a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("pinned", "upstream"), required=True)
    ap.add_argument("--result", type=Path, required=True, help="run_gate.py --json output")
    ap.add_argument("--baseline", type=Path, required=True, help="committed baseline result JSON")
    ap.add_argument("--bench", type=Path, help="bench_c_timers_v2.py JSON (BENCH-6)")
    ap.add_argument("--threshold", type=float, default=BENCH6_THRESHOLD_MS)
    ap.add_argument("--date", required=True, help="report date, YYYY-MM-DD")
    ap.add_argument("--out", type=Path, required=True, help="artifacts/xstate-gate/<date>.md")
    args = ap.parse_args(argv)
    try:
        result = _load(args.result)
        baseline = _load(args.baseline)
        bench = _load(args.bench) if args.bench else None
    except (OSError, ValueError, TypeError) as exc:
        print(f"nightly_gate: {exc}", file=sys.stderr)
        return 2
    pinned = args.mode == "pinned"
    deltas = documented_deltas(result) if pinned else []
    excused = set(deltas)
    bench6_row = None
    if pinned and bench is not None:
        excused.add(BENCH6_ROW)
        bench6_row = _statuses(result).get(BENCH6_ROW, "missing")
    new = regressions(result, baseline, frozenset(excused))
    gone = fixed(result, baseline)
    lost = coverage_lost(result, baseline)
    ok, p99 = bench6(bench, args.threshold)
    report = render(
        mode=args.mode,
        date=args.date,
        result=result,
        new=new,
        gone=gone,
        bench_ok=ok,
        p99=p99,
        threshold=args.threshold,
        skipped=skipped_env(result),
        lost=lost,
        ratio=skip_ratio(result),
        documented=[(k, KNOWN_DELTAS[k]) for k in deltas] if pinned else None,
        drift=delta_drift(result) if pinned else None,
        bench6_row=bench6_row,
        unexcused=below_floor(result) if pinned else None,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    if args.mode == "upstream":
        return 0
    return 1 if (new or ok is False or lost) else 0


if __name__ == "__main__":
    sys.exit(main())
