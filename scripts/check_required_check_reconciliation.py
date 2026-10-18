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
# (`<lane>/<job>`) that runs the check, or that run in more than one. Reviewed; an entry
# replaces the same-name match, and a target `ci-required` stops judging fails.
LANE_ALIASES: dict[str, tuple[str, ...]] = {
    "lint": ("js/lint", "py/py-checks"),
    "typecheck": ("js/typecheck", "py/py-checks"),
    "unit-backend": ("py/py-tests",),
    "e2e-smoke": ("e2e/e2e-web",),
    "sast": ("security/codeql", "security/semgrep-bandit"),
    "sca": ("security/read-only-scans",),
    "secrets-scan": ("security/gitleaks", "secret-scan"),
    "container-scan": ("security/trivy",),
    "license-check": ("security/read-only-scans",),
    "generated-code-check": ("gen",),
}

# Matches a row of the §9 table: "| 1 | `lint` | ... |"
CHECK_ROW_RE = re.compile(r"^\|\s*\d+\s*\|\s*`([a-z0-9-]+)`\s*\|")
JOB_NAME_RE = re.compile(r"^\s{0,2}([a-zA-Z0-9_-]+):\s*$")
# A lane of the resolver table in `ci-required`: name, applicability (a literal, or FILTER_*
# variables read by `isTrue` or `!== "false"`, joined by `||`), the env var with its result.
# Nothing else may be in the table.
_VAR = r"process\.env\.FILTER_[A-Z0-9_]+"
_FILTER = rf'(?:isTrue\({_VAR}\)|{_VAR} !== "false")'
LANE_RE = re.compile(
    rf'\s*"?([a-z0-9-]+)"?:\s*\{{\s*applicable:\s*(true|false|{_FILTER}(?:\s*\|\|\s*{_FILTER})*),'
    r"\s*result:\s*process\.env\.(RESULT_[A-Z0-9_]+),?\s*\},?"
)
# The step that decides `ci-required`: a `run:` block that is the resolver call and its argument
# (the lane table), with nothing after it in the block, so its exit is the resolver's whatever the
# shell (`( +)` is the block's indentation: a later line as indented would still be in it).
RESOLVER_RUN_RE = re.compile(
    rf"^\s+run: \|\n( +)node {re.escape(RESOLVER)} \"\$\(node -e '$(.*?)^\s+'\)\""
    r"(?=(?:\n[ \t]*)*(?:\n(?!\1) *\S|\Z))",
    re.M | re.S,
)
# That argument's program: this prelude, the lane table, this epilogue, and nothing else.
PROGRAM_RE = re.compile(
    r'\s*const isTrue = \(v\) => v === "true";\s*const lanes = \{(.*)\n\s*\};'
    r"\s*console\.log\(JSON\.stringify\(lanes\)\);\s*",
    re.S,
)
STEP_ACTION_RE = re.compile(r"actions/(checkout|setup-node)@[0-9a-f]{40}")
# A FILTER_<NAME> variable of the resolver step, set from the `changed-paths` output <name>.
FILTER_ENV_RE = re.compile(
    r"^\s+FILTER_(\w+):\s*\$\{\{\s*needs\.changed-paths\.outputs\.([\w-]+)\s*\}\}\s*(?:#.*)?$",
    re.M,
)
USES_RE = re.compile(r"^    uses:\s*\./\.github/workflows/(\S+)", re.M)
# A called job that never gates its lane: an `if:` that reads no context and calls no status
# function, so a constant (`false`, `False`, `0`, `''`, `null`, ...) or a block scalar (unread), or
# continue-on-error that is not the literal false (its failure would not fail the lane).
_CONTEXT = r"\b(?:github|inputs|needs|vars|env|steps|matrix|strategy|runner|jobs?|secrets)\s*[.\[]"
_STATUS = r"\b(?:always|success|failure|cancelled)\s*\("
NEVER_RE = re.compile(
    rf"^    (if:(?![^\n#]*(?:{_CONTEXT}|{_STATUS})).*"
    r"|continue-on-error:(?!\s*false(?:\s+#.*)?\s*$).*)",
    re.M,
)
# The same at any indentation, `- ` included: a job `ci-required` needs, or one of its steps.
ANY_NEVER_RE = re.compile(NEVER_RE.pattern.replace("^    ", r"^\s*(?:-\s+)?", 1), re.M)
# A YAML anchor, alias or merge key: it hides a node's content from this text-based proof.
ANCHOR_RE = re.compile(r"^\s*(?:- )?(?:[\w\"'-]+\s*:\s+)?[&*]\w|^\s*(?:- )?<<\s*:", re.M)
PATHS_RE = re.compile(r"^\s+paths(-ignore)?:", re.M)
# The only keys `ci-required` and its resolver step may set: no env, defaults, container or
# continue-on-error on the job, no shell, working-directory or if: on the step.
JOB_KEYS = ("name", "if", "needs", "runs-on", "timeout-minutes", "permissions", "steps")
STEP_KEYS = ("name", "id", "env", "run", "timeout-minutes")
# GitHub's default pull_request activity types: a `types` filter that drops one stops a check
# arriving on every pull request.
DEFAULT_TYPES = {"pull_request": {"opened", "synchronize", "reopened"}}


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


def _form_errors(path: str, text: str) -> list[str]:
    """Lines outside the YAML this line-based proof reads: plain `key:` and `- ` lines (and a quoted
    top-level `on`), block scalars, and one-line scalars with no tag, no key inside and no flow
    mapping but `{}`. A loader reads other spellings of the same keys (`"if": false`, `if : false`,
    `? if`, `- {if: false}`, `if: !!str false`, a quoted scalar over lines) that the patterns here
    would not see."""
    errors: list[str] = []
    block = -1  # in a block scalar: the column its lines must pass
    for number, line in enumerate(text.splitlines(), 1):
        if block >= 0 and (not line.strip() or len(line) - len(line.lstrip(" ")) > block):
            continue
        block = -1
        lead, dashes, rest = re.findall(r"^( *)((?:- +)*)(.*)$", line)[0]
        if not rest or rest[0] == "#":
            continue
        key = re.match(r"[\w.-]+:(?:\s+|$)", rest) or (
            None if lead or dashes else re.match(r"([\"'])on\1:(?:\s+|$)", rest)
        )
        value = rest[key.end() :] if key else rest
        plain = re.sub(r"(?:^|\s)#.*", "", value).strip()
        problem = ""
        if not (key or dashes):
            problem = "not a plain `key:` or `- ` line"
        elif value[:1] in ("'", '"'):
            if not re.fullmatch(r"('(?:[^']|'')*'|\"(?:[^\"\\]|\\.)*\")\s*(?:#.*)?", value):
                problem = "a quoted key, or a quoted scalar over lines"
        elif re.fullmatch(r"[|>][1-9+-]*", plain):
            block = len(lead) + (len(dashes) if key else len(dashes.rstrip()) - 1)
        elif plain[:1] in ("!", "?", ":") or re.search(r":(?:\s|$)", plain):
            problem = "a tag, or a key not written `key: value`"
        elif plain[:1] in ("{", "[") and "{" in plain.replace("${{", "") and plain != "{}":
            problem = "a flow mapping"
        if problem:
            errors.append(f"{path}:{number}: {problem}; this proof reads plain block-style YAML")
    return errors


def _check_name(job_id: str, lines: list[str]) -> str | None:
    """A job's check-run name: its literal `name:`, else its id. None when GitHub expands it (an
    expression, or a matrix, which appends its values)."""
    named = [m.group(1) for m in map(re.compile(r"^    name:\s*(.+?)\s*$").match, lines) if m]
    name = named[0].split(" #")[0].strip("\"' ") if named else job_id
    return None if "${{" in name or re.search(r"^      matrix:", "\n".join(lines), re.M) else name


def _on_every(trigger: str, event: str) -> bool:
    """Whether an `on:` block (comments stripped) runs `event` for every pull request to `main`: no
    `paths` filter anywhere, no `branches-ignore`, a `branches` filter only if it lists `main`, and
    a `types` filter only if it keeps GitHub's defaults (DEFAULT_TYPES)."""
    if not re.search(rf"(?<![\w-]){event}(?![\w-])", trigger) or PATHS_RE.search(trigger):
        return False
    block = re.search(rf"^  {event}:.*\n((?:    .*\n|\s*\n)*)", trigger, re.M)
    keys = re.findall(r"^    ([a-z-]+):(.*(?:\n\s+- .*)*)", block.group(1) if block else "", re.M)
    filters = {key: set(re.findall(r"[\w*./-]+", values)) for key, values in keys}
    types = DEFAULT_TYPES.get(event, set())
    return (
        "branches-ignore" not in filters
        and "main" in filters.get("branches", {"main"})
        and types <= filters.get("types", types)
    )


def load_workflow_job_names(workflows_glob: str, event: str = "pull_request") -> set[str]:
    """Check-run names reported on every `event` (stdlib only): a job's literal `name:`, else its
    id, and `<caller> / <job>` for each job of a reusable workflow a job calls (the caller's own
    name reports only as a skipped placeholder); see `_check_name`. A workflow whose trigger
    filters narrow `event` (`_on_every`) reports nothing here: on other pull requests its checks
    never arrive. Empty when none runs."""
    names: set[str] = set()
    for wf_path in sorted(glob.glob(workflows_glob)):
        text = _read(wf_path)
        on = re.search(r"^[\"']?on[\"']?:(.*?)^[^\s#]", text + "\nend", re.M | re.S)
        if not _on_every(re.sub("#.*", "", on.group(1)) if on else "", event):
            continue
        for job_id, lines in _job_blocks(text).items():
            name, uses = _check_name(job_id, lines), USES_RE.search("\n".join(lines))
            if uses:
                called = _job_blocks(_read(os.path.join(os.path.dirname(wf_path), uses.group(1))))
                subs = [_check_name(*job) for job in called.items()]
                names.update(f"{name} / {sub}" for sub in subs if name and sub)
            elif name:
                names.add(name)
    return names


def prove_lanes(workflows_dir: str) -> tuple[set[str], list[str]]:
    """The lanes pr.yml's `ci-required` judges: each lane's name, and `<lane>/<job>` for every job
    of the reusable workflow it calls that can fail it (keys at 4 spaces, not NEVER_RE).
    `ci-required` must run `if: always()`, with only JOB_KEYS (pr.yml sets no env or defaults),
    its steps checkout, setup-node and one `run:` step, with only STEP_KEYS, that is the resolver
    call alone (RESOLVER_RUN_RE) on PROGRAM_RE's program, and the only place that sets a FILTER_
    or RESULT_ name. A lane counts when its applicability is not the literal `false` and reads
    only FILTER_<NAME> set from the `changed-paths` output <name>, and the table, with no key twice
    and nothing but lanes, takes its result from the needed job of the lane's own name, or from the
    `gates` output of that name, which the step of that id backs. Every job `ci-required` needs
    must fail when its work fails: no ANY_NEVER_RE, on the job or on a step, but continue-on-error
    on a `gates` step whose outcome is a lane. These files are plain block-style YAML
    (`_form_errors`), with no anchor, alias or merge key (ANCHOR_RE). Returns (lanes, errors)."""
    path = os.path.join(workflows_dir, "pr.yml")
    text = _read(path)
    if ANCHOR_RE.search(text):
        return set(), [f"{path}: a YAML anchor, alias or merge key hides content from this proof"]
    form = _form_errors(path, text)
    if form:
        return set(), form
    jobs = _job_blocks(text)
    body = "\n".join(jobs.get(AGGREGATE_CONTEXT, []))
    run = RESOLVER_RUN_RE.search(body)
    steps = re.split(r"^      - ", body.split("\n    steps:\n", 1)[-1], flags=re.M)[1:]
    decider = [f"      - {step}" for step in steps if RESOLVER in step]
    step_keys = re.findall(r"^(?:      - |        )([\w-]+):", "".join(decider[:1]), re.M)
    actions = re.findall(r"^\s+(?:- )?uses:\s*(\S+)", body, re.M)
    if (
        not re.search(r"^    if:\s*(\$\{\{\s*)?always\(\)\s*(\}\})?\s*$", body, re.M)
        or not set(re.findall(r"^    ([\w-]+):", body, re.M)) <= set(JOB_KEYS)
        or re.search(r"^\s+(?:- )?(continue-on-error|defaults|shell)\s*:", body, re.M)
        or re.search(r"^(?:defaults|env):", text, re.M)
        or not run
        or len(re.findall(r"^\s+(?:- )?run:", body, re.M)) != 1
        or len(decider) != 1
        or not set(step_keys) <= set(STEP_KEYS)
        or re.search(r"^\s*if:", decider[0], re.M)
        or not all(map(STEP_ACTION_RE.fullmatch, actions))
    ):
        return set(), [
            f"{path}: `{AGGREGATE_CONTEXT}` must run `if: always()` with no job keys but "
            f"{', '.join(JOB_KEYS)} (pr.yml may set no env or defaults), with steps checkout, "
            "setup-node and one step with no `if:`, continue-on-error or shell: (no keys but "
            f"{', '.join(STEP_KEYS)}) that is the {RESOLVER} call alone, whose exit is the "
            "resolver's"
        ]
    env_block = re.search(r"^        env:\n((?:          .*\n)*)", decider[0] + "\n", re.M)
    env_text = env_block[1] if env_block else ""
    named = re.findall(r"^\s+(?:- +)?((?:FILTER|RESULT)_\w+)\s*:", body, re.M)
    if sorted(named) != sorted(set(re.findall(r"^          (\w+):", env_text, re.M))):
        return set(), [
            f"{path}: the resolver step's env must set each FILTER_ and RESULT_ name once and "
            f"nothing else, and no other part of `{AGGREGATE_CONTEXT}` may set one (a step's own "
            "env wins over the job's)"
        ]
    program = PROGRAM_RE.fullmatch(run.group(2))
    if not program:
        return set(), [
            f"{path}: the `{AGGREGATE_CONTEXT}` program must be the isTrue line, the lane table "
            "and `console.log(JSON.stringify(lanes));`, nothing else"
        ]
    needs = set(re.findall(r"^      - ([A-Za-z0-9_-]+)\s*$", body.split("\n    steps:")[0], re.M))
    env = dict(re.findall(r"^\s+(RESULT_[A-Z0-9_]+):\s*\$\{\{\s*(\S+)\s*\}\}\s*$", env_text, re.M))
    pairs = FILTER_ENV_RE.findall(env_text) if "changed-paths" in needs else []
    filters = {f"FILTER_{var}" for var, out in pairs if var.lower().replace("_", "-") == out}
    gates = "\n".join(jobs.get("gates", []))
    step_ids = set(re.findall(r"^\s+id:\s*([A-Za-z0-9_-]+)\s*$", gates, re.M))
    outputs = re.findall(
        r"^      ([a-z0-9-]+):\s*\$\{\{\s*steps\.([\w-]+)\.outcome\s*\}\}", gates, re.M
    )
    exported = {key for key, step in outputs if key == step and step in step_ids}
    found = LANE_RE.findall(program.group(1))
    rest = LANE_RE.sub("", program.group(1)).strip()
    keys = [lane for lane, _, _ in found]
    errors = [f"{path}: lane '{k}' repeats" for k in sorted(set(keys)) if keys.count(k) > 1]
    errors += [f"{path}: the lane table holds more than lanes: {rest[:80]!r}"] if rest else []
    lanes: set[str] = set()
    outcomes: set[str] = set()  # lanes judged by a `gates` step's outcome
    for lane, applicable, var in found:
        source = env.get(var, "")
        unset = sorted(set(re.findall(r"FILTER_\w+", applicable)) - filters)
        if unset:
            errors.append(f"{path}: lane '{lane}' reads {unset}, not set from changed-paths")
        if applicable == "false" or unset:
            continue
        if source == f"needs.{lane}.result" and lane in needs and lane in jobs:
            lanes.add(lane)
            uses = USES_RE.search("\n".join(jobs[lane]))
            if uses:
                called_path = os.path.join(workflows_dir, uses.group(1))
                called_text = _read(called_path)
                if ANCHOR_RE.search(called_text):
                    errors.append(f"{called_path}: a YAML anchor, alias or merge key hides content")
                errors += _form_errors(called_path, called_text)
                called = _job_blocks(called_text)
                skip = {
                    job
                    for job, block in called.items()
                    if NEVER_RE.search(job_text := "\n".join(block))
                    or not re.match(r"(?:[ \t]*(?:#.*)?\n)*    [^\s#]", job_text)
                }
                lanes.update(f"{lane}/{job}" for job in set(called) - skip)
        elif source == f"needs.gates.outputs.{lane}" and "gates" in needs and lane in exported:
            lanes.add(lane)
            outcomes.add(lane)
    for job in sorted(needs):
        head, _, tail = ("\n" + "\n".join(jobs.get(job, []))).partition("\n    steps:\n")
        for i, chunk in enumerate([head, *re.split(r"(?=^      - )", tail, flags=re.M)]):
            step_id = re.search(r"^      (?:- |  )id:\s*([\w-]+)\s*$", chunk, re.M)
            judged = i > 0 and job == "gates" and step_id is not None and step_id[1] in outcomes
            errors += [
                f"{path}: job '{job}' must fail `{AGGREGATE_CONTEXT}` when its work fails, but "
                f"sets {m.group(1)!r}"
                for m in ANY_NEVER_RE.finditer(chunk)
                if not (judged and m.group(1).startswith("continue-on-error"))
            ]
    return lanes, errors + ([] if lanes else [f"{path}: no lane table in `{AGGREGATE_CONTEXT}`"])


def duplicate_check_names(workflows_glob: str, contexts: set[str]) -> list[str]:
    """Each required check that more than one job, in any workflow, reports by name (its literal
    `name:`, else its id): GitHub matches a required check by name and app, and every Actions job
    is the same app, so another job could pass it."""
    names = [
        _check_name(*job)
        for wf_path in sorted(glob.glob(workflows_glob))
        for job in _job_blocks(_read(wf_path)).items()
    ]
    return [
        f"'{name}' is required on main and the check-run name of {names.count(name)} jobs"
        for name in sorted(contexts)
        if names.count(name) > 1
    ]


def aggregated_checks(names: list[str], lanes: set[str]) -> tuple[set[str], list[str]]:
    """The §9 checks a judged lane runs: when the name has a LANE_ALIASES entry, every one of
    its targets, else a lane or lane job of that name. Returns (checks, errors for aliases that
    are stale or unknown)."""
    jobs = {entry.split("/", 1)[1] for entry in lanes if "/" in entry}
    errors = [
        f"LANE_ALIASES['{n}'] is not a §9 check" for n in sorted(set(LANE_ALIASES) - set(names))
    ]
    covered: set[str] = set()
    for name in names:
        missing = [target for target in LANE_ALIASES.get(name, ()) if target not in lanes]
        if missing:
            errors.append(f"LANE_ALIASES['{name}'] is stale: no judged {', '.join(missing)}")
        elif name in LANE_ALIASES or name in lanes or name in jobs:
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
    reasons = desired_state.get("pending_checks", {})
    if not isinstance(reasons, dict):
        raise ReconciliationError("pending_checks must be an object: check name -> reason")
    listed = {name for name in reasons if name[:1] != "$"}
    pending = {name for name in listed if str(reasons[name]).strip()}
    enforced = contexts | (set(aggregated) if AGGREGATE_CONTEXT in contexts else set())

    for name in sorted(contexts | listed):
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
                f"'{name}' is required on main but no check run named '{name}' arrives on every "
                "pull_request (a reusable workflow's jobs report as `<caller> / <job>`)"
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
    errors += duplicate_check_names(workflows_glob, required_contexts(desired_state))
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
