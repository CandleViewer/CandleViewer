#!/usr/bin/env python3
"""E49-Q01 (#1335): the GA regression pack's own health check.

Fails (exit 1, one ``::error`` line per finding) when:

* **tags** - a pack test (``@ga-regression``) has no, or more than one, ``@ga-area-<area>`` of
  ``specs.AREAS``; names a ``@story-`` id that docs/plan/11-user-stories.md lacks; carries an area
  or story tag without ``@ga-regression``; or is a ``test.only``.
* **quarantine** (C-9.3, 03 §14, BQ-06) - a ``@flaky`` pack test lacks ``@ticket-<N>`` (its P1
  issue, as the toolchain pack's ``@flaky`` requires), ``@owner-<handle>`` or
  ``@until-YYYY-MM-DD``, or its deadline has passed or lies more than ``MAX_QUARANTINE_DAYS``
  ahead (two one-week sprints). The ``ga-regression`` projects drop ``@flaky`` tests, so this is
  what keeps a quarantined spec from living there indefinitely. C-9.3's "within 24 h" is
  procedural: the nightly's AMBER report and tracker issue name the flaky test the same night; a
  person quarantines it.
* **describe tags** - a ``test.describe`` title carries ``@ga-*`` or ``@story-*`` (Playwright
  would select by it; this reader does not read it).
* **egress** (C-13.5, 03 §11.4, BQ-07) - a web pack spec does not take ``test`` from
  ``apps/web/e2e/ga/fixtures.ts`` (the egress-guarded fixture, which also runs the per-scenario
  axe scan), or still takes it from ``@playwright/test``; an Electron pack spec does not launch
  through ``apps/desktop/e2e/support/shell.ts`` (which installs the Electron egress guard) or
  reaches for ``_electron`` directly. The guards are pattern-based (loopback only), so this lint
  names no host. A file whose pack tests are all ``test.fixme`` stubs runs nothing and is exempt.
* **coverage** - coverage_map.py's findings (a Must story neither covered nor a declared gap).
* **budget** - shard_plan.py's planned-budget findings, a stale ``durations.json`` key, and two
  pack paths where one would match the other as a Playwright file filter.

Warnings (printed, not failing): lanes whose budget is still a default-cost estimate, and the
coverage map's gaps still pending the owner's risk acceptance (``--require-accepted`` makes those
findings, for the sprint-end review).

``python3 tools/ga/health.py [--today YYYY-MM-DD]``. Stdlib only.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

if __package__ in (None, ""):  # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ga import coverage_map, shard_plan, specs

MAX_QUARANTINE_DAYS = 14
OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
WEB_FIXTURE = "apps/web/e2e/ga/fixtures"
ELECTRON_SHELL = "apps/desktop/e2e/support/shell"


def tag_findings(tests: Sequence[specs.SpecTest], known_stories: set[str]) -> list[str]:
    out = []
    for t in tests:
        if not t.in_pack:
            if t.areas or t.stories:
                out.append(f"{t.where}: area/story tags without {specs.GA_TAG}")
            continue
        if len(t.areas) != 1 or t.areas[0] not in specs.AREAS:
            out.append(
                f"{t.where}: a pack test needs exactly one @ga-area-<area> of"
                f" {', '.join(specs.AREAS)}; it has {list(t.areas) or 'none'}"
            )
        for s in t.stories:
            if s not in known_stories:
                out.append(f"{t.where}: @story-{s} is not a story in 11-user-stories.md")
        if t.modifier == "only":
            out.append(f"{t.where}: test.only in the pack")
    return out


def quarantine_findings(tests: Sequence[specs.SpecTest], today: date) -> list[str]:
    out = []
    for t in tests:
        if not (t.in_pack and t.flaky):
            continue
        owner = t.tag_value("@owner-")
        ticket = t.tag_value("@ticket-")
        if ticket is None or not ticket.isdigit():
            out.append(f"{t.where}: quarantined (@flaky) without one @ticket-<P1 issue number>")
        if owner is None or not OWNER_RE.match(owner):
            out.append(f"{t.where}: quarantined (@flaky) without one @owner-<handle>")
        until = t.tag_value("@until-")
        try:
            deadline = date.fromisoformat(until) if until else None
        except ValueError:
            deadline = None
        if deadline is None:
            out.append(f"{t.where}: quarantined (@flaky) without one @until-YYYY-MM-DD")
        elif deadline < today:
            out.append(f"{t.where}: quarantine deadline {deadline} has passed: fix or delete it")
        elif deadline > today + timedelta(days=MAX_QUARANTINE_DAYS):
            out.append(
                f"{t.where}: quarantine deadline {deadline} is more than"
                f" {MAX_QUARANTINE_DAYS} days ahead (03 §14: two sprints)"
            )
    return out


def describe_findings(root: Path) -> list[str]:
    out = []
    for lane in specs.APPS:
        for file in specs.spec_files(root, lane):
            rel = file.relative_to(root).as_posix()
            for line, tags in specs.describe_tags(file.read_text(encoding="utf-8")):
                out.append(
                    f"{rel}:{line}: pack tags {' '.join(tags)} on a test.describe title; tag each"
                    " test instead (Playwright greps describe titles, the pack reader does not)"
                )
    return out


def _resolves_to(spec_path: str, specifier: str, target: str) -> bool:
    if not specifier.startswith("."):
        return False
    parts: list[str] = []
    for part in (PurePosixPath(spec_path).parent / specifier).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    resolved = "/".join(parts)
    return resolved.removesuffix(".ts") == target


def _names(clause: str) -> set[str]:
    inner = clause[clause.find("{") + 1 : clause.rfind("}")] if "{" in clause else ""
    names = set()
    for item in inner.split(","):
        words = item.replace("type ", "").split(" as ")
        if words[0].strip():
            names.add(words[-1].strip())
    return names


def egress_findings(tests: Sequence[specs.SpecTest], root: Path) -> list[str]:
    out = []
    runnable = sorted({(t.lane, t.path) for t in tests if t.in_pack and not t.stub})
    for lane, path in runnable:
        source = (root / path).read_text(encoding="utf-8")
        imps = specs.imports(source)
        if lane == "web-chromium":
            guarded = any(
                "test" in _names(c) and _resolves_to(path, s, WEB_FIXTURE) for c, s in imps
            )
            raw = any("test" in _names(c) and s == "@playwright/test" for c, s in imps)
            if not guarded or raw:
                out.append(
                    f"{path}: a web pack spec takes `test` from e2e/ga/fixtures.ts (egress guard"
                    " and per-scenario axe), never from @playwright/test"
                )
        else:
            guarded = any(_resolves_to(path, s, ELECTRON_SHELL) for _, s in imps)
            if not guarded or re.search(r"\b_electron\b", source):
                out.append(
                    f"{path}: an Electron pack spec launches through e2e/support/shell.ts"
                    " (egress guard), never through _electron directly"
                )
    return out


def _pack_files(tests: Sequence[specs.SpecTest]) -> dict[str, list[str]]:
    return {lane: specs.pack_files(list(tests), lane) for lane in specs.APPS}


def run(root: Path, today: date, require_accepted: bool = False) -> list[str]:
    tests = specs.scan(root)
    findings = tag_findings(tests, set(specs.stories(root)))
    findings += quarantine_findings(tests, today)
    findings += describe_findings(root)
    findings += egress_findings(tests, root)
    findings += coverage_map.check(root, tests)
    if require_accepted:
        findings += [f"{g}: gap pending owner acceptance" for g in coverage_map.pending(root)]
    plans, durations = shard_plan.all_plans(root)
    findings += shard_plan.budget_findings(plans, durations)
    files = _pack_files(tests)
    findings += shard_plan.duration_findings(files, durations)
    for lane_files in files.values():
        findings += shard_plan.filter_overlaps(lane_files)
    return findings


def notes(root: Path) -> list[str]:
    """What passes but must not be read as proven: provisional budgets, unaccepted gaps."""
    tests = specs.scan(root)
    _, durations = shard_plan.all_plans(root)
    out = shard_plan.duration_notes(_pack_files(tests), durations)
    pending = coverage_map.pending(root)
    if pending:
        out.append(
            f"coverage: {len(pending)} declared gap(s) pending owner risk acceptance (PROPOSED);"
            " Gherkin 1 is not met until the owner accepts them"
        )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--root", type=Path, default=specs.REPO_ROOT)
    p.add_argument("--today", type=date.fromisoformat, default=None, help="UTC date (tests)")
    p.add_argument(
        "--require-accepted", action="store_true", help="a gap pending acceptance is a finding"
    )
    args = p.parse_args(argv)
    today = args.today or datetime.now(timezone.utc).date()
    findings = run(args.root, today, args.require_accepted)
    for f in findings:
        print(f"::error title=ga-regression health::{f}")
    for n in notes(args.root):
        print(f"::warning title=ga-regression health::{n}")
    tests = specs.scan(args.root)
    pack = [t for t in tests if t.in_pack]
    print(
        f"ga-regression health: {len(pack)} pack tests ({sum(t.stub for t in pack)} fixme stubs,"
        f" {sum(t.flaky for t in pack)} quarantined), {len(findings)} finding(s)"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
