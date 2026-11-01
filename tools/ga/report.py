#!/usr/bin/env python3
"""E49-Q01 (#1335, BQ-08/BQ-09): the GA regression pack's nightly report, metrics and flake rates.

Reads the shards' Playwright JSON reports (``RESULTS/ga-results-<lane>-<shard>/results.json``, as
the nightly downloads them) and earlier nights' ``ga-report.json`` files (``--history``), and
writes to ``--out``:

* ``ga-report.json`` - per lane and per area (``@ga-area-*``) pass/fail/flaky/skipped, each test's
  outcome and duration, the flake table, the 7-night trend, the wall-clock budget verdict, the
  failing areas and the failure-artefact name of each failing shard; a pure function of its inputs;
* ``ga-report.md`` - the same for the job summary and the failure alert;
* ``ga-regression.prom`` - Prometheus text for the E49-T02 dashboard: ``ga_regression_pass_total``,
  ``ga_regression_fail_total`` and ``ga_regression_axe_p2_total`` per area,
  ``ga_regression_duration_seconds`` and ``ga_regression_flake_rate`` per spec, in the exposition
  format tools/ga_defects/metrics.py pushes (pushing it is a carried row: no gateway is wired here);
* ``ga-durations.json`` - this night's per-file seconds, the proposal for the weekly refresh of
  tools/ga/durations.json (shard_plan.py).

Flake rate (Gherkin "A flaky spec cannot hide", BQ-06): over the last ``FLAKE_WINDOW`` runs of a
test (this night and the history), the number of times its outcome flipped between failed and
passed, plus any run it passed only on retry, over the runs in the window. The pack runs with zero
retries (#1335 ruling), so a flake on the night itself is a failure (RED); the retry term counts
only a report from a run given retries by hand. A test with a rate above zero is listed with its
owner: its ``@owner-`` tag, else the CODEOWNERS of its file.

Axe (BQ-14): the pack fixture records each serious/critical violation of a scenario's final
screen as a ``ga-axe-p2`` annotation; they are counted per area at P2 and fail nothing here.

``--fail-on-red`` exits 1 when an area failed or the wall-clock budget was missed (RED);
``--fail-on-amber`` also exits 1 when a test has a flake rate above zero over the window, or
passed only on a retry given by hand (AMBER, the C-9.3 flake gate), so the nightly files it on
the tracker issue instead of reading as green. Skipped tests are split out as ``fixme`` (the
carried stubs). Stdlib only.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ga import shard_plan, specs

FLAKE_WINDOW = 3
TREND_WINDOW = 7
RESULTS_DIR = re.compile(r"^ga-results-(?P<lane>[a-z-]+?)-(?P<shard>\d+)$")
OUTCOME = {"expected": "passed", "unexpected": "failed", "flaky": "flaky", "skipped": "skipped"}
_TAG = re.compile(r"@[A-Za-z][\w.-]*")


@dataclass(frozen=True)
class TestResult:
    id: str
    lane: str
    shard: int
    file: str
    title: str
    area: str
    outcome: str
    seconds: float
    owner: str | None
    axe_p2: int
    fixme: bool = False


def _walk(suite: Mapping[str, Any], file: str) -> Iterator[tuple[str, Mapping[str, Any]]]:
    file = suite.get("file") or file
    for spec in suite.get("specs", []):
        yield file, spec
    for child in suite.get("suites", []):
        yield from _walk(child, file)


def _clean_title(title: str) -> str:
    return " ".join(w for w in title.split() if not _TAG.fullmatch(w))


def parse_playwright(
    report: Mapping[str, Any], lane: str, shard: int, package: str
) -> list[TestResult]:
    out = []
    for top in report.get("suites", []):
        for file, spec in _walk(top, ""):
            tags = set(spec.get("tags", [])) | set(_TAG.findall(spec.get("title", "")))
            tags = {t if t.startswith("@") else f"@{t}" for t in tags}
            if specs.GA_TAG not in tags:
                continue
            areas = sorted(t.removeprefix("@ga-area-") for t in tags if t.startswith("@ga-area-"))
            owners = sorted(t.removeprefix("@owner-") for t in tags if t.startswith("@owner-"))
            path = f"{package}/e2e/{file}" if file and not file.startswith(package) else file
            for test in spec.get("tests", []):
                results = test.get("results", [])
                # Playwright copies a test's annotations onto its results: read them once.
                notes = list(test.get("annotations", [])) or [
                    n for r in results for n in r.get("annotations", [])
                ]
                axe = sum(1 for n in notes if n.get("type") == "ga-axe-p2")
                fixme = any(n.get("type") == "fixme" for n in notes)
                title = _clean_title(spec.get("title", ""))
                out.append(
                    TestResult(
                        id=f"{lane}:{path}::{title}",
                        lane=lane,
                        shard=shard,
                        file=path,
                        title=title,
                        area=areas[0] if len(areas) == 1 else "untagged",
                        outcome=OUTCOME.get(test.get("status", ""), "failed"),
                        seconds=round(sum(r.get("duration", 0) for r in results) / 1000, 3),
                        owner=owners[0] if owners else None,
                        axe_p2=axe,
                        fixme=fixme,
                    )
                )
    return out


def load_results(results_dir: Path) -> list[TestResult]:
    found: list[TestResult] = []
    for d in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        m = RESULTS_DIR.match(d.name)
        if not m or m.group("lane") not in specs.APPS:
            continue
        for f in sorted(d.rglob("*.json")):
            report = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(report, dict) and "suites" in report:
                lane = m.group("lane")
                found += parse_playwright(report, lane, int(m.group("shard")), specs.APPS[lane])
    return sorted(found, key=lambda t: t.id)


def codeowners(root: Path) -> list[tuple[str, list[str]]]:
    path = root / ".github/CODEOWNERS"
    rules = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split("#", 1)[0].split()
            if len(parts) >= 2:
                rules.append((parts[0], parts[1:]))
    return rules


def owner_of(path: str, rules: Sequence[tuple[str, list[str]]]) -> str:
    found = "unowned"
    for pattern, owners in rules:  # the last matching rule wins
        p = pattern.lstrip("/")
        hit = (
            pattern == "*"
            or (p.endswith("/") and path.startswith(p))
            or fnmatch.fnmatch(path, p)
            or fnmatch.fnmatch(path, p.rstrip("/") + "/*")
        )
        if hit:
            found = owners[0]
    return found


def flake_rates(
    current: Sequence[TestResult], history: Sequence[Mapping[str, Any]]
) -> dict[str, float]:
    """Per test id: flake events over the last FLAKE_WINDOW runs (oldest history first)."""
    runs = [{t["id"]: t["outcome"] for t in h.get("tests", [])} for h in history]
    runs.append({t.id: t.outcome for t in current})
    window = runs[-FLAKE_WINDOW:]
    rates = {}
    for t in current:
        seq = [r[t.id] for r in window if t.id in r and r[t.id] != "skipped"]
        if not seq:
            continue
        events = sum(o == "flaky" for o in seq)
        events += sum(
            1 for a, b in zip(seq, seq[1:], strict=False) if {a, b} == {"failed", "passed"}
        )
        rates[t.id] = round(events / len(seq), 3)
    return rates


def _counts(tests: Iterable[TestResult]) -> dict[str, int]:
    """Outcomes, plus `fixme`: the skipped tests that are carried stubs (never read as a pass)."""
    c = {"passed": 0, "failed": 0, "flaky": 0, "skipped": 0, "fixme": 0}
    for t in tests:
        c[t.outcome] += 1
        c["fixme"] += t.outcome == "skipped" and t.fixme
    return c


def build(
    tests: Sequence[TestResult],
    history: Sequence[Mapping[str, Any]],
    run: Mapping[str, Any],
    root: Path = specs.REPO_ROOT,
    started_at: str | None = None,
    finished_at: str | None = None,
    budget: int = shard_plan.BUDGET_SECONDS,
) -> dict[str, Any]:
    rules = codeowners(root)
    history = sorted(history, key=lambda h: int(h.get("run", {}).get("number", 0)))
    areas: dict[str, list[TestResult]] = defaultdict(list)
    for t in tests:
        areas[t.area].append(t)
    rates = flake_rates(tests, history)
    flakes = [
        {
            "id": t.id,
            "rate": rates[t.id],
            "owner": t.owner or owner_of(t.file, rules),
            "owner_source": "tag" if t.owner else "CODEOWNERS",
        }
        for t in tests
        if rates.get(t.id, 0) > 0
    ]
    failing = sorted(a for a, ts in areas.items() if any(t.outcome == "failed" for t in ts))
    failed_shards = sorted(
        {f"ga-failure-{t.lane}-{t.shard}" for t in tests if t.outcome == "failed"}
    )
    wall = None
    if started_at and finished_at:
        wall = round(
            (
                datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
            ).total_seconds()
        )
    summary = _counts(tests)
    report: dict[str, Any] = {
        "schema": 1,
        "run": dict(run),
        "summary": summary,
        "lanes": {lane: _counts(t for t in tests if t.lane == lane) for lane in specs.APPS},
        "areas": {
            a: {**_counts(ts), "axe_p2": sum(t.axe_p2 for t in ts)}
            for a, ts in sorted(areas.items())
        },
        "failing_areas": failing,
        "failure_artifacts": failed_shards,
        "flakes": sorted(flakes, key=lambda f: (-f["rate"], f["id"])),
        "budget": {
            "seconds": budget,
            "wall_clock_seconds": wall,
            "within": None if wall is None else wall <= budget,
        },
        "tests": [asdict(t) for t in tests],
    }
    trend = [
        {"run": h.get("run", {}).get("number"), **h.get("summary", {})}
        for h in history[-(TREND_WINDOW - 1) :]
    ]
    report["trend"] = trend + [{"run": run.get("number"), **summary}]
    return report


def is_red(report: Mapping[str, Any]) -> bool:
    return bool(report["failing_areas"]) or report["budget"]["within"] is False


def is_amber(report: Mapping[str, Any]) -> bool:
    """The C-9.3 flake gate: a test flipped across the window (a flake rate over zero). The pack
    runs with zero retries, so a flake tonight is RED; a pass on a retry given by hand still
    reads AMBER, never green."""
    return bool(report["summary"]["flaky"]) or bool(report["flakes"])


def status(report: Mapping[str, Any]) -> str:
    return "RED" if is_red(report) else "AMBER" if is_amber(report) else "green"


def markdown(report: Mapping[str, Any]) -> str:
    run = report["run"]
    s = report["summary"]
    url = run.get("url", "")
    lines = [
        f"## GA regression pack: {status(report)}",
        "",
        f"{s['passed']} passed, {s['failed']} failed, {s['flaky']} flaky (passed on retry),"
        f" {s['skipped']} skipped ({s.get('fixme', 0)} of them carried `test.fixme` stubs, which"
        f" cover nothing). Commit {run.get('sha', '?')}.",
        "",
    ]
    if is_amber(report) and not is_red(report):
        lines += [
            "AMBER (C-9.3 flake gate): a test flipped between failed and passed across the last"
            f" {FLAKE_WINDOW} nights. Quarantine it within 24 h with a P1 ticket, or fix it.",
            "",
        ]
    b = report["budget"]
    if b["wall_clock_seconds"] is not None:
        lines.append(
            f"Wall-clock {b['wall_clock_seconds']} s of the {b['seconds']} s budget:"
            f" {'within' if b['within'] else 'OVER BUDGET'}."
        )
        lines.append("")
    if report["failing_areas"]:
        lines.append(f"Failing areas: {', '.join(report['failing_areas'])}.")
        arts = ", ".join(f"`{a}`" for a in report["failure_artifacts"])
        where = f"[this run's artefacts]({url}#artifacts)" if url else "this run"
        lines.append(f"Traces (scrubbed): artefacts {arts} of {where}.")
        lines.append("")
    lines += [
        "| area | passed | failed | flaky | skipped | of which fixme | axe P2 |",
        "|---|---|---|---|---|---|---|",
    ]
    for area, c in report["areas"].items():
        lines.append(
            f"| {area} | {c['passed']} | {c['failed']} | {c['flaky']} | {c['skipped']} |"
            f" {c.get('fixme', 0)} | {c['axe_p2']} |"
        )
    failed = [t for t in report["tests"] if t["outcome"] == "failed"]
    if failed:
        lines += ["", "Failed tests:", ""]
        lines += [f"- [{t['area']}] `{t['file']}`: {t['title']}" for t in failed]
    if report["flakes"]:
        lines += ["", "| flaky test | rate | owner |", "|---|---|---|"]
        lines += [
            f"| {f['id']} | {f['rate']} | {f['owner']} ({f['owner_source']}) |"
            for f in report["flakes"]
        ]
    lines += ["", "| run | passed | failed | flaky | skipped |", "|---|---|---|---|---|"]
    for r in report["trend"]:
        lines.append(
            f"| {r.get('run')} | {r.get('passed', 0)} | {r.get('failed', 0)} |"
            f" {r.get('flaky', 0)} | {r.get('skipped', 0)} |"
        )
    return "\n".join(lines) + "\n"


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def metrics(report: Mapping[str, Any]) -> str:
    out = []
    for area, c in report["areas"].items():
        out.append(f'ga_regression_pass_total{{area="{_label(area)}"}} {c["passed"] + c["flaky"]}')
        out.append(f'ga_regression_fail_total{{area="{_label(area)}"}} {c["failed"]}')
        out.append(f'ga_regression_axe_p2_total{{area="{_label(area)}"}} {c["axe_p2"]}')
    rates = {f["id"]: f["rate"] for f in report["flakes"]}
    for t in report["tests"]:
        spec = _label(t["id"])
        out.append(f'ga_regression_duration_seconds{{spec="{spec}"}} {t["seconds"]}')
        out.append(f'ga_regression_flake_rate{{spec="{spec}"}} {rates.get(t["id"], 0)}')
    return "\n".join(out) + "\n"


def durations(report: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {lane: {} for lane in specs.APPS}
    for t in report["tests"]:
        if t.get("fixme"):
            continue  # a carried stub runs nothing; its file is no pack file to plan
        rel = t["file"].removeprefix(specs.APPS[t["lane"]] + "/")
        out[t["lane"]][rel] = round(out[t["lane"]].get(rel, 0) + t["seconds"], 1)
    return {lane: dict(sorted(v.items())) for lane, v in out.items()}


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("results", type=Path, help="directory of ga-results-<lane>-<shard>/ folders")
    p.add_argument("--history", type=Path, help="directory of earlier ga-report.json files")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--run-number", type=int, default=0)
    p.add_argument("--run-url", default="")
    p.add_argument("--sha", default="")
    p.add_argument("--started-at", help="ISO time the workflow run started")
    p.add_argument("--finished-at", help="ISO time the last shard finished")
    p.add_argument("--fail-on-red", action="store_true")
    p.add_argument("--fail-on-amber", action="store_true", help="the C-9.3 flake gate fails too")
    args = p.parse_args(argv)
    history = []
    if args.history and args.history.is_dir():
        history = [
            json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(args.history.rglob("ga-report.json"))
        ]
    run = {"number": args.run_number, "url": args.run_url, "sha": args.sha}
    report = build(
        load_results(args.results),
        history,
        run,
        started_at=args.started_at,
        finished_at=args.finished_at,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "ga-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.out / "ga-report.md").write_text(markdown(report), encoding="utf-8")
    (args.out / "ga-regression.prom").write_text(metrics(report), encoding="utf-8")
    (args.out / "ga-durations.json").write_text(
        json.dumps(durations(report), indent=2) + "\n", encoding="utf-8"
    )
    print(markdown(report))
    if args.fail_on_red and is_red(report):
        return 1
    return 1 if args.fail_on_amber and is_amber(report) else 0


if __name__ == "__main__":
    sys.exit(main())
