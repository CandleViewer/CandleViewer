#!/usr/bin/env python3
"""E49-Q01 (#1335, BQ-4, BQ-5): the GA regression pack's nightly health check.

Reads files that e2e-nightly's read-only `ga-pack-health` job fetched (no network here): the
run's jobs from the Actions API, this run's shard JSON reports (which `_job-e2e.yml` reduces to
titles, statuses and durations before it uploads them for 14 days) and the last ten scheduled
nights' reports. It writes one Markdown section to the job summary:

- CI-E2E-006: the pack's wall-clock, from the first shard job's `started_at` to the last one's
  `completed_at`, over 2,700 s (the 45-minute budget; never a job timeout).
- CI-E2E-007: a quarantined Playwright test (the `@flaky` title tag, read by
  tools/ci/flaky_quarantine_report.py) with no ticket, owner or start date, or past C-9.3's ten
  working days.
- The flake report per test: the `flaky` status (passed on its retry) and the failed attempts of
  the `--retries=1` runs, across every report read.
- On Mondays only, the web shard map recomputed by a greedy longest-first packer over per-spec
  durations, with the predicted longest shard. It is never committed.

Exit codes: 0 both checks pass, 1 CI-E2E-006 or CI-E2E-007, 2 unreadable jobs input. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from tools.ci.flaky_quarantine_report import build_report, playwright_problems

BUDGET_SECONDS = 2700
WEB_SHARDS = 4
#: The lane's shard jobs, e.g. `e2e-nightly / e2e-web (3)` and `e2e-nightly / e2e-electron`.
SHARD_JOB_RE = re.compile(r"\be2e-(?:web|electron)\b")
FAILED = frozenset({"failed", "timedOut", "interrupted"})


@dataclass(frozen=True)
class SpecRun:
    test_id: str
    file: str
    status: str
    failed_attempts: int
    duration_ms: int


#: A reduced shard report is a few hundred KB; anything far larger is skipped, not parsed.
MAX_REPORT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class Report:
    night: str
    lane: str
    tests: tuple[SpecRun, ...]


def _results(test: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [r for r in test.get("results") or [] if isinstance(r, Mapping)]


def _walk(suite: Mapping[str, Any], titles: tuple[str, ...]) -> Iterator[SpecRun]:
    for spec in suite.get("specs") or []:
        file = str(spec.get("file") or suite.get("file") or "")
        path = " › ".join((*titles, str(spec.get("title", ""))))
        for test in spec.get("tests") or []:
            project = str(test.get("projectName") or "")
            results = _results(test)
            yield SpecRun(
                test_id=f"{path} [{project}]" if project else path,
                file=file,
                status=str(test.get("status", "")),
                failed_attempts=sum(1 for r in results if r.get("status") in FAILED),
                duration_ms=sum(int(r.get("duration") or 0) for r in results),
            )
    for child in suite.get("suites") or []:
        yield from _walk(child, (*titles, str(child.get("title", ""))))


def parse_report(data: Mapping[str, Any], night: str, lane: str) -> Report:
    """One Playwright JSON report (raw or reduced): a top-level suite per spec file."""
    tests = [t for s in data.get("suites") or [] for t in _walk(s, (str(s.get("title", "")),))]
    return Report(night=night, lane=lane, tests=tuple(tests))


def load_reports(root: Path, night: str | None) -> tuple[list[Report], list[str]]:
    """Every `results.json` under root: the artifact folder names the lane; with no fixed night,
    the first folder under root names it (the run id). Unreadable files become notes."""
    reports, notes = [], []
    for path in sorted(root.rglob("results.json")) if root.is_dir() else []:
        rel = path.relative_to(root).parts
        try:
            if path.stat().st_size > MAX_REPORT_BYTES:
                notes.append(f"oversized report skipped: {'/'.join(rel)}")
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, Mapping):
                reports.append(parse_report(data, night or rel[0], path.parent.name))
        except (OSError, ValueError, AttributeError, TypeError, RecursionError):
            # A report that parses but has the wrong shape is a note, never a failed check.
            notes.append(f"unreadable report skipped: {'/'.join(rel)}")
    return reports, notes


def load_jobs(text: str) -> list[Mapping[str, Any]]:
    """The run's jobs: an API page (`{"jobs": [...]}`), a list, or JSON lines (`--jq '.jobs[]'`)."""
    try:
        doc: Any = json.loads(text)
    except ValueError:
        doc = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(doc, Mapping):
        doc = doc.get("jobs") or []
    if not isinstance(doc, list):
        raise TypeError("jobs input is not a list")
    return [j for j in doc if isinstance(j, Mapping)]


def _ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def wall_clock(jobs: Iterable[Mapping[str, Any]]) -> tuple[float | None, int]:
    """Seconds from the first shard job's start to the last one's completion, and the job count."""
    shards = [j for j in jobs if SHARD_JOB_RE.search(str(j.get("name", "")))]
    starts = [s for s in (_ts(j.get("started_at")) for j in shards) if s]
    ends = [e for e in (_ts(j.get("completed_at")) for j in shards) if e]
    if not starts or not ends:
        return None, len(shards)
    return (max(ends) - min(starts)).total_seconds(), len(shards)


@dataclass(frozen=True)
class FlakeRow:
    test_id: str
    runs: int
    flaky: int
    failed: int
    failed_attempts: int

    @property
    def rate(self) -> float:
        return self.flaky / self.runs if self.runs else 0.0


def flake_rows(reports: Iterable[Report]) -> list[FlakeRow]:
    """Per test across reports: runs (not skipped), passed only on retry, failed after the
    retry, and failed attempts. Only tests with a flaky pass or a failure are listed."""
    acc: dict[str, list[int]] = {}
    for report in reports:
        for t in report.tests:
            if t.status == "skipped":
                continue
            row = acc.setdefault(t.test_id, [0, 0, 0, 0])
            row[0] += 1
            row[1] += t.status == "flaky"
            row[2] += t.status == "unexpected"
            row[3] += t.failed_attempts
    rows = [FlakeRow(k, *v) for k, v in acc.items() if v[1] or v[2]]
    return sorted(rows, key=lambda r: (-r.rate, -r.failed, r.test_id))


def spec_durations(reports: Iterable[Report], lane_prefix: str = "e2e-web") -> dict[str, float]:
    """Seconds per spec file: each night's total for the file, then the median over nights."""
    per_night: dict[tuple[str, str], int] = {}
    for report in reports:
        if not report.lane.startswith(lane_prefix):
            continue
        for t in report.tests:
            key = (report.night, t.file)
            per_night[key] = per_night.get(key, 0) + t.duration_ms
    by_file: dict[str, list[float]] = {}
    for (_, file), ms in per_night.items():
        by_file.setdefault(file, []).append(ms / 1000)
    return {file: float(statistics.median(v)) for file, v in by_file.items()}


def pack_shards(durations: Mapping[str, float], shards: int) -> list[tuple[float, list[str]]]:
    """Greedy longest-first: each spec, longest first, joins the shard with the least total."""
    bins: list[tuple[float, list[str]]] = [(0.0, []) for _ in range(shards)]
    for file, seconds in sorted(durations.items(), key=lambda kv: (-kv[1], kv[0])):
        at = min(range(shards), key=lambda i: (bins[i][0], i))
        total, files = bins[at]
        bins[at] = (total + seconds, [*files, file])
    return bins


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render(
    *,
    seconds: float | None,
    shard_jobs: int,
    budget: int,
    quarantine: Sequence[str],
    rows: Sequence[FlakeRow],
    nights: int,
    shard_map: Sequence[tuple[float, list[str]]] | None,
    notes: Sequence[str],
) -> str:
    out = ["## GA pack health (E49-Q01)", ""]
    if seconds is None:
        out.append(f"- Wall-clock: not measured ({shard_jobs} shard job(s) with no timestamps).")
    else:
        verdict = "CI-E2E-006: over budget" if seconds > budget else "within budget"
        out.append(
            f"- Wall-clock: {seconds:.0f} s over {shard_jobs} shard job(s),"
            f" budget {budget} s: {verdict}."
        )
    if quarantine:
        out.append(f"- CI-E2E-007: {len(quarantine)} quarantined test(s) unowned or overdue:")
        out += [f"  - {_cell(q)}" for q in quarantine]
    else:
        out.append(
            "- Quarantine: every `@flaky` Playwright test is owned and within 10 working days."
        )
    out += ["", f"### Flake report ({nights} report night(s))", ""]
    if rows:
        out += ["| Test | Runs | Passed on retry | Failed | Failed attempts | Flake rate |"]
        out += ["| --- | ---: | ---: | ---: | ---: | ---: |"]
        out += [
            f"| {_cell(r.test_id)} | {r.runs} | {r.flaky} | {r.failed} | {r.failed_attempts}"
            f" | {r.rate:.0%} |"
            for r in rows
        ]
    else:
        out.append("No test passed only on retry or failed.")
    if shard_map is not None:
        longest = max((total for total, _ in shard_map), default=0.0)
        out += [
            "",
            (
                f"### Shard map (Monday recompute; predicted longest shard {longest:.0f} s,"
                " test time only)"
            ),
            "",
        ]
        out += ["| Shard | Predicted s | Spec files |", "| ---: | ---: | --- |"]
        out += [
            f"| {i} | {total:.0f} | {_cell(', '.join(files)) or '-'} |"
            for i, (total, files) in enumerate(shard_map, start=1)
        ]
        out.append("")
        out.append(
            "Not committed: the shards still split by `--shard`; this is the input to a change."
        )
    if notes:
        out += ["", *(f"- Note: {_cell(n)}" for n in notes)]
    return "\n".join(out) + "\n"


def check(args: argparse.Namespace) -> int:
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    try:
        jobs = load_jobs(Path(args.jobs).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        print(f"ga-pack-health: cannot read the jobs input: {exc}", file=sys.stderr)
        return 2
    seconds, shard_jobs = wall_clock(jobs)
    current, notes = load_reports(Path(args.current), "this run")
    history, more = load_reports(Path(args.history), None)
    reports = current + history
    quarantine = playwright_problems(build_report(Path(args.repo_root).resolve()), today)
    shard_map = None
    if today.weekday() == 0:
        shard_map = pack_shards(spec_durations(reports), args.shards)
    text = render(
        seconds=seconds,
        shard_jobs=shard_jobs,
        budget=args.budget,
        quarantine=quarantine,
        rows=flake_rows(reports),
        nights=len({r.night for r in reports}),
        shard_map=shard_map,
        notes=[*notes, *more],
    )
    print(text, end="")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as summary:
            summary.write(text)
    over = seconds is not None and seconds > args.budget
    return 1 if over or quarantine else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", required=True, help="the run's jobs (Actions API JSON)")
    parser.add_argument("--current", required=True, help="this run's shard reports")
    parser.add_argument("--history", required=True, help="past nights' reports, one per run")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--today", help="YYYY-MM-DD (UTC); defaults to the clock")
    parser.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    parser.add_argument("--budget", type=int, default=BUDGET_SECONDS)
    parser.add_argument("--shards", type=int, default=WEB_SHARDS)
    return check(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
