#!/usr/bin/env python3
"""GOV-005 support: reconcile the required-check names embedded in
.github/branch-protection.json (`required_status_checks.checks` and
`pending_checks`) against CONSTITUTION.md §9 (the single source of truth
for check names, C-16.5) and the job names declared in .github/workflows/*.yml.

Every name in the desired-state file must exist verbatim in the §9 table, or be
`ci-required` (the ADR-0013 rule 2 aggregate). Every §9 check must be required, or
run by a lane `ci-required` judges (`prove_lanes`), or in `pending_checks` with a
reason — this closes the gap where a check is renamed and its "required" status
silently evaporates.

Exit codes: 0 clean, 1 mismatch found, 2 internal error.
Stdlib only.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from typing import Any

DEFAULT_DESIRED_STATE_PATH = ".github/branch-protection.json"
DEFAULT_CONSTITUTION_PATH = "CONSTITUTION.md"
DEFAULT_WORKFLOWS_GLOB = ".github/workflows/*.yml"

AGGREGATE_CONTEXT = "ci-required"
RESOLVER = "scripts/ci_gate_resolver.mjs"

# §9 names that differ from the lane (`<lane>`) or the job of a lane's reusable workflow
# (`<lane>/<job>`) that runs the check. Reviewed; a target `ci-required` stops judging fails.
LANE_ALIASES: dict[str, tuple[str, ...]] = {
    "unit-backend": ("py/py-tests",),
    "e2e-smoke": ("e2e/e2e-web",),
    "sast": ("security/codeql", "security/semgrep-bandit"),
    "sca": ("security/read-only-scans",),
    "secrets-scan": ("security/gitleaks",),
    "container-scan": ("security/trivy",),
    "license-check": ("security/read-only-scans",),
    "generated-code-check": ("gen",),
}

# Matches a row of the §9 table: "| 1 | `lint` | ... |"
CHECK_ROW_RE = re.compile(r"^\|\s*\d+\s*\|\s*`([a-z0-9-]+)`\s*\|")
JOB_NAME_RE = re.compile(r"^\s{0,2}([a-zA-Z0-9_-]+):\s*$")
# A lane of the resolver table in `ci-required`: name, applicability, the env var with its result.
LANE_RE = re.compile(
    r'"?([a-z0-9-]+)"?:\s*\{\s*applicable:\s*([^{}]*?),\s*'
    r"result:\s*process\.env\.(RESULT_[A-Z0-9_]+)"
)


class ReconciliationError(Exception):
    pass


def load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise ReconciliationError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReconciliationError(f"{path} is not valid JSON: {exc}") from exc


def load_constitution_check_names(path: str) -> list[str]:
    names: list[str] = []
    try:
        with open(path, encoding="utf-8") as fh:
            in_table = False
            for line in fh:
                if line.strip().startswith("| # | Check name"):
                    in_table = True
                    continue
                if in_table:
                    if not line.strip().startswith("|"):
                        break
                    match = CHECK_ROW_RE.match(line.strip())
                    if match:
                        names.append(match.group(1))
    except FileNotFoundError as exc:
        raise ReconciliationError(f"file not found: {path}") from exc
    if not names:
        raise ReconciliationError(
            f"no §9 check rows found in {path} — table heading may have moved"
        )
    return names


def _job_blocks(text: str) -> dict[str, list[str]]:
    """A workflow's top-level jobs: job id -> its lines (stdlib only, no YAML parser)."""
    jobs: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.split("\njobs:\n", 1)[-1].splitlines() if "\njobs:\n" in text else []:
        if line[:1] not in ("", " ", "#"):
            break  # the next top-level key
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$", line)
        if match:
            current = jobs.setdefault(match.group(1), [])
        elif current is not None:
            current.append(line)
    return jobs


def load_workflow_job_names(workflows_glob: str, event: str = "pull_request") -> set[str]:
    """Check-run names reported by the jobs of every workflow that `event` triggers (stdlib only):
    a job's literal `name:`, else its id. Empty when no workflow matches."""
    names: set[str] = set()
    for wf_path in sorted(glob.glob(workflows_glob)):
        with open(wf_path, encoding="utf-8") as fh:
            text = fh.read()
        on = re.search(r"^[\"']?on[\"']?:(.*?)^[^\s#]", text + "\nend", re.M | re.S)
        if not (on and re.search(rf"(?<![\w-]){event}(?![\w-])", re.sub("#.*", "", on.group(1)))):
            continue
        for job_id, lines in _job_blocks(text).items():
            named = [
                m.group(1) for m in map(re.compile(r"^    name:\s*(.+?)\s*$").match, lines) if m
            ]
            name = named[0].split(" #")[0].strip("\"' ") if named else job_id
            if "${{" not in name:
                names.add(name)
    return names


def prove_lanes(workflows_dir: str) -> tuple[set[str], list[str]]:
    """The lanes pr.yml's `ci-required` judges: each lane's name, and `<lane>/<job>` for every job
    of the reusable workflow it calls. A lane counts when the resolver table takes its result from
    a job `ci-required` needs, or from a `gates` output that a step backs, and its applicability is
    not the literal `false`. Returns (lanes, errors)."""
    path = os.path.join(workflows_dir, "pr.yml")
    jobs = _job_blocks(_read(path))
    body = "\n".join(jobs.get(AGGREGATE_CONTEXT, []))
    table = re.search(r"const lanes = \{(.*?)\n\s*\};", body, re.S)
    if (
        not re.search(r"^    if:\s*(\$\{\{\s*)?always\(\)\s*(\}\})?\s*$", body, re.M)
        or RESOLVER not in body
    ):
        return set(), [f"{path}: `{AGGREGATE_CONTEXT}` must run {RESOLVER} with `if: always()`"]
    needs = set(re.findall(r"^      - ([A-Za-z0-9_-]+)\s*$", body.split("\n    steps:")[0], re.M))
    env = dict(re.findall(r"^\s+(RESULT_[A-Z0-9_]+):\s*\$\{\{\s*(\S+)\s*\}\}\s*$", body, re.M))
    gates = "\n".join(jobs.get("gates", []))
    step_ids = set(re.findall(r"^\s+id:\s*([A-Za-z0-9_-]+)\s*$", gates, re.M))
    outputs = re.findall(
        r"^      ([a-z0-9-]+):\s*\$\{\{\s*steps\.([\w-]+)\.outcome\s*\}\}", gates, re.M
    )
    exported = {key for key, step in outputs if step in step_ids}
    lanes: set[str] = set()
    for lane, applicable, var in LANE_RE.findall(table.group(1) if table else ""):
        job = re.fullmatch(r"needs\.([\w-]+)\.result", env.get(var, ""))
        step = re.fullmatch(r"needs\.gates\.outputs\.([\w-]+)", env.get(var, ""))
        if applicable.strip() == "false":
            continue
        if job and job.group(1) in needs and job.group(1) in jobs:
            lanes.add(lane)
            uses = re.search(
                r"^    uses:\s*\./\.github/workflows/(\S+)", "\n".join(jobs[job.group(1)]), re.M
            )
            if uses:
                called = _job_blocks(_read(os.path.join(workflows_dir, uses.group(1))))
                lanes.update(f"{lane}/{called_job}" for called_job in called)
        elif step and "gates" in needs and step.group(1) in exported:
            lanes.add(lane)
    return lanes, [] if lanes else [f"{path}: no lane table in `{AGGREGATE_CONTEXT}`"]


def aggregated_checks(names: list[str], lanes: set[str]) -> tuple[set[str], list[str]]:
    """The §9 checks a judged lane runs: a lane or lane job of that name, else every target of the
    name's LANE_ALIASES entry. Returns (checks, errors for aliases that are stale or unknown)."""
    jobs = {entry.split("/", 1)[1] for entry in lanes if "/" in entry}
    covered = {name for name in names if name in lanes or name in jobs}
    errors = [
        f"LANE_ALIASES['{n}'] is not a §9 check" for n in sorted(set(LANE_ALIASES) - set(names))
    ]
    for name, targets in sorted(LANE_ALIASES.items()):
        missing = [target for target in targets if target not in lanes]
        if name in names and name not in covered and missing:
            errors.append(f"LANE_ALIASES['{name}'] is stale: no judged {', '.join(missing)}")
        elif name in names and name not in covered:
            covered.add(name)
    return covered, errors


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError as exc:
        raise ReconciliationError(f"file not found: {path}") from exc


def required_contexts(desired_state: dict[str, Any]) -> set[str]:
    checks = desired_state.get("required_status_checks", {}).get("checks", [])
    return {
        c["context"] for c in checks if isinstance(c, dict) and isinstance(c.get("context"), str)
    }


def reconcile(
    desired_state: dict[str, Any],
    constitution_names: list[str],
    workflow_job_names: set[str],
    aggregated: frozenset[str] | set[str] = frozenset(),
) -> list[str]:
    errors: list[str] = []
    constitution_set = set(constitution_names)
    contexts = required_contexts(desired_state)
    reasons = desired_state.get("pending_checks", {}).items()
    pending = {name for name, why in reasons if name[:1] != "$" and str(why).strip()}
    enforced = contexts | (set(aggregated) if AGGREGATE_CONTEXT in contexts else set())

    for name in sorted(contexts | pending):
        if name not in constitution_set and name != AGGREGATE_CONTEXT:
            errors.append(
                f"'{name}' in branch-protection.json is not a §9 check name in CONSTITUTION.md"
            )

    for name in sorted(constitution_set):
        if name not in enforced and name not in pending:
            errors.append(
                f"§9 check '{name}' is missing: not required, not run by a lane "
                f"`{AGGREGATE_CONTEXT}` judges, and not in pending_checks with a reason"
            )

    overlap = enforced & pending
    for name in sorted(overlap):
        errors.append(f"'{name}' is enforced and in pending_checks (remove it from there)")

    for name in sorted(contexts):
        if name not in workflow_job_names:
            errors.append(
                f"'{name}' is required on main but no job named '{name}' runs on pull_request "
                "in .github/workflows/*.yml"
            )

    return errors


def reconcile_repo(
    desired_path: str, constitution_path: str, workflows_glob: str
) -> tuple[list[str], list[str]]:
    """Every check above on the repository's files. Returns (errors, pending check names)."""
    desired_state = load_json(desired_path)
    names = load_constitution_check_names(constitution_path)
    errors: list[str] = []
    aggregated: set[str] = set()
    if AGGREGATE_CONTEXT in required_contexts(desired_state):
        lanes, errors = prove_lanes(os.path.dirname(workflows_glob))
        aggregated, alias_errors = aggregated_checks(names, lanes)
        errors += alias_errors
    job_names = load_workflow_job_names(workflows_glob)
    errors += reconcile(desired_state, names, job_names, aggregated)
    pending = desired_state.get("pending_checks", {})
    return errors, sorted(name for name in pending if name[:1] != "$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desired-state", default=DEFAULT_DESIRED_STATE_PATH)
    parser.add_argument("--constitution", default=DEFAULT_CONSTITUTION_PATH)
    parser.add_argument("--workflows-glob", default=DEFAULT_WORKFLOWS_GLOB)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        errors, pending = reconcile_repo(args.desired_state, args.constitution, args.workflows_glob)
    except ReconciliationError as exc:
        print(f"check-required-check-reconciliation: {exc}", file=sys.stderr)
        return 2
    if pending:
        print(
            f"check-required-check-reconciliation: pending: {', '.join(pending)}", file=sys.stderr
        )

    if not errors:
        if not args.json:
            print("check-required-check-reconciliation: clean")
        else:
            print("[]")
        return 0

    if args.json:
        print(json.dumps([{"code": "GOV-005", "message": e} for e in errors], indent=2))
    else:
        for e in errors:
            print(f"GOV-005 {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
