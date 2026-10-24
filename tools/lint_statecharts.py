#!/usr/bin/env python3
"""tools/lint_statecharts.py — the full standing CV statechart lint set.

E50-T11: consolidates the former per-constraint lint tickets (T13/T17/T21/
T40/T53/T55) into one CI-blocking tool covering the 19 CV-LINT-* rules named
in `docs/plan/29-statechart-adoption-plan.md` §1.6.

Two rule families:
  - JSON rules (tag "J"): walk every `*.machine.json` under a machines
    directory (default `services/api/candleviewer/statechart/machines/`).
  - AST rules (tag "A"): walk every `*.py` file under a source root
    (default `services/api/candleviewer/`).

All rules exit non-zero (`error`) except CV-LINT-INVOKE-CYCLE, which is a
warning (CV-C38, retired to W) and never fails the run on its own.

Usage:
    python tools/lint_statecharts.py \
        [--machines-dir DIR] [--source-root DIR] [--quiet]

Exit code: 0 if only warnings (or nothing) fired, 1 if any error-severity
finding fired, 2 on a usage/IO error (bad path, unparsable JSON/Python).
"""

from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MACHINES_DIR = Path("services/api/candleviewer/statechart/machines")
DEFAULT_SOURCE_ROOT = Path("services/api/candleviewer")

# The pinned statechart runtime package name (CV-LINT-IMPORT, CV-C03). Built
# from parts so this lint module itself never contains the literal import
# statement the CI/repo hook (and CV-LINT-IMPORT itself) scan for.
RUNTIME_MODULE = "xstate" + "_" + "statemachine"

# Modules allowed to import the runtime above.
ALLOWED_IMPORT_MODULES = {"factory.py", "persistence.py"}

# Modules allowed to call from_snapshot( (CV-LINT-RESTORE, CV-C52).
ALLOWED_RESTORE_MODULES = {"persistence.py"}

# Modules allowed to call drain_pending( (CV-LINT-DRAIN, CV-C65').
ALLOWED_DRAIN_MODULES = {"persistence.py"}

# Modules allowed to call re_mint directly (CV-LINT-REMINT, CV-C68); the
# wrapper's own definition site is exempt from the "call only through
# cv_re_mint" rule, and gateway.py is the wrapper's home per 29 §1.
ALLOWED_REMINT_MODULES = {"gateway.py"}

# Hot-path package/module prefixes that must never import the statechart
# package (CV-LINT-HOTPATH, MUSTNOT-01..03, catalogue §3). The replay modules
# on the per-event path (E26-T03) are listed one by one, as in the
# import-linter contract (module-contracts.toml hotpath_statechart): the replay
# session service beside them drives B12 and imports the statechart package.
# `ws.` (E17-T08, ws_statechart): the trailing dot keeps the composition root `ws_wiring.py` out.
# The private stream's row mapping and pairing (E29-T05) are listed as in that contract too.
HOTPATH_MODULE_PREFIXES = (
    "candleviewer.book",
    "candleviewer.bars",
    "candleviewer.orderflow",
    "candleviewer.oms.hotpath",
    "candleviewer.oms.pairing",
    "candleviewer.oms.push_mapping",
    "candleviewer.rules.evaluator",
    "candleviewer.replay.clock",
    "candleviewer.replay.injector",
    "candleviewer.replay.pacing",
    "candleviewer.replay.regroup",
    "candleviewer.replay.runner",
    "candleviewer.ws.",
)

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    rule: str
    file: str
    element: str
    message: str
    severity: str = SEVERITY_ERROR

    def format(self) -> str:
        tag = "WARN" if self.severity == SEVERITY_WARNING else "ERROR"
        return f"[{tag}] {self.rule} {self.file}:{self.element}: {self.message}"


def iter_machine_files(machines_dir: Path) -> Iterator[Path]:
    if not machines_dir.exists():
        return
    yield from sorted(machines_dir.rglob("*.machine.json"))


def iter_python_files(source_root: Path) -> Iterator[Path]:
    if not source_root.exists():
        return
    for path in sorted(source_root.rglob("*.py")):
        if "_generated" in path.parts:
            continue
        yield path


def load_json(path: Path) -> tuple[dict[str, object] | None, Finding | None]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, Finding(
            rule="CV-LINT-JSON-PARSE",
            file=str(path),
            element="<root>",
            message=f"could not parse machine JSON: {exc}",
        )


def load_ast(path: Path) -> tuple[ast.AST | None, str, Finding | None]:
    try:
        text = path.read_text(encoding="utf-8")
        return ast.parse(text, filename=str(path)), text, None
    except (OSError, SyntaxError) as exc:
        return (
            None,
            "",
            Finding(
                rule="CV-LINT-AST-PARSE",
                file=str(path),
                element="<module>",
                message=f"could not parse Python source: {exc}",
            ),
        )


# --------------------------------------------------------------------------
# JSON rules — walk `*.machine.json` under the machines directory.
# --------------------------------------------------------------------------


def _walk_states(node: dict, path: str = "") -> Iterator[tuple[str, dict]]:
    """Yield (state_path, state_node) for every state in a chart, root included."""
    yield path or "<root>", node
    states = node.get("states")
    if not isinstance(states, dict):
        return
    for name, child in states.items():
        if isinstance(child, dict):
            child_path = f"{path}.{name}" if path else name
            yield from _walk_states(child, child_path)


def _walk_transitions(state: dict) -> Iterator[tuple[str, dict | list | str]]:
    """Yield (event_or_key, transition_value) pairs for `on` and `always`."""
    on = state.get("on")
    if isinstance(on, dict):
        yield from on.items()
    always = state.get("always")
    if always is not None:
        yield "always", always


def _transition_targets(value) -> list[dict]:
    """Normalise a transition value (dict, list of dicts, or bare string) to dicts."""
    if isinstance(value, str):
        return [{"target": value}]
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        out: list[dict] = []
        for item in value:
            out.extend(_transition_targets(item))
        return out
    return []


def rule_policy(file: str, chart: dict) -> list[Finding]:
    """CV-LINT-POLICY (CV-C01, CV-C62): mandatory root keys present and sized."""
    findings: list[Finding] = []
    if chart.get("strictConfig") is not True:
        findings.append(
            Finding(
                "CV-LINT-POLICY",
                file,
                "<root>",
                'chart root must set "strictConfig": true (CV-C01)',
            )
        )
    on_unhandled = chart.get("onUnhandled")
    if on_unhandled != "defer":
        findings.append(
            Finding(
                "CV-LINT-POLICY",
                file,
                "<root>",
                f'chart root "onUnhandled" must be "defer", got {on_unhandled!r} (R13-14)',
            )
        )
    max_iter = chart.get("maxIterations")
    if not isinstance(max_iter, int) or max_iter <= 0:
        findings.append(
            Finding(
                "CV-LINT-POLICY",
                file,
                "<root>",
                'chart root must set a positive integer "maxIterations" (CV-C62)',
            )
        )
    return findings


def rule_fallthrough(file: str, chart: dict) -> list[Finding]:
    """CV-LINT-FALLTHROUGH (C-07b): every guarded-only arm needs an ordered,
    unguarded, auditing fall-through arm for the same event."""
    findings: list[Finding] = []
    for state_path, state in _walk_states(chart):
        for event, value in _walk_transitions(state):
            if event == "always":
                continue
            targets = _transition_targets(value)
            if len(targets) < 2 and not (len(targets) == 1 and "guard" in targets[0]):
                continue
            guarded = [t for t in targets if "guard" in t or "cond" in t]
            unguarded = [t for t in targets if "guard" not in t and "cond" not in t]
            if guarded and not unguarded:
                findings.append(
                    Finding(
                        "CV-LINT-FALLTHROUGH",
                        file,
                        f"{state_path}.on.{event}",
                        "guarded-only transition arm has no ordered, unguarded "
                        "fall-through arm (C-07b)",
                    )
                )
    return findings


def rule_always(file: str, chart: dict) -> list[Finding]:
    """CV-LINT-ALWAYS (CV-C35): no `always` into an invoke-bearing child, and
    no `always` targeting an ancestor of the state that declares it."""
    findings: list[Finding] = []
    invoke_states: set[str] = set()
    for state_path, state in _walk_states(chart):
        if state.get("invoke"):
            invoke_states.add(state_path)
    for state_path, state in _walk_states(chart):
        always = state.get("always")
        if always is None:
            continue
        for target in _transition_targets(always):
            dest = target.get("target")
            if not isinstance(dest, str):
                continue
            dest_norm = dest.lstrip("#").lstrip(".")
            if dest_norm in invoke_states:
                findings.append(
                    Finding(
                        "CV-LINT-ALWAYS",
                        file,
                        f"{state_path}.always",
                        f"always-transition targets invoke-bearing state {dest!r} (CV-C35)",
                    )
                )
            if state_path != "<root>" and (
                state_path.startswith(dest_norm + ".")
                or dest_norm == state_path.rsplit(".", 1)[0]
            ):
                findings.append(
                    Finding(
                        "CV-LINT-ALWAYS",
                        file,
                        f"{state_path}.always",
                        f"always-transition targets ancestor {dest!r} (CV-C35)",
                    )
                )
    return findings


def rule_kill_ancestor(file: str, chart: dict) -> list[Finding]:
    """CV-LINT-KILL-ANCESTOR (C-04): kill/cancel events are declared on an
    ancestor of every invoking state."""
    findings: list[Finding] = []
    kill_events = {"KILL", "CANCEL", "cv.kill", "cv.cancel"}
    ancestors_with_kill: set[str] = set()
    for state_path, state in _walk_states(chart):
        on = state.get("on")
        if isinstance(on, dict) and kill_events & set(on.keys()):
            ancestors_with_kill.add(state_path)
    for state_path, state in _walk_states(chart):
        if not state.get("invoke"):
            continue
        parts = state_path.split(".") if state_path != "<root>" else []
        ancestor_paths = ["<root>"] + [
            ".".join(parts[:i]) for i in range(1, len(parts))
        ]
        if not any(a in ancestors_with_kill for a in ancestor_paths):
            findings.append(
                Finding(
                    "CV-LINT-KILL-ANCESTOR",
                    file,
                    state_path,
                    "invoking state has no ancestor declaring a kill/cancel event (C-04)",
                )
            )
    findings.extend(_kill_frozen_exception(file, chart))
    return findings


#: Catalogue §1.3c SL-protection exception (#1650, owner decision #1778 item X):
#: the only chart-level marker that may satisfy C-04 with a non-terminal KILL target.
SL_PROTECTION_TAG = "cv:slProtection"
#: Explicit allowlist: the tag alone is not enough (review #2133).
SL_PROTECTION_CHART_IDS: frozenset[str] = frozenset({"position_protection"})
#: PENDING COORDINATOR DECISION (#2133 review item 2) — NOT part of the §1.3c
#: exception. Pre-existing charts whose KILL already targets a non-final halted
#: state, surfaced when the KILL-is-final check landed. Exact (chart id, target
#: leaf) pairs only, so no new chart/state can hide here. Delete an entry (or the
#: whole set) to make the rule strict for that chart; never add one silently.
KILL_NONFINAL_PENDING_DECISION: frozenset[tuple[str, str]] = frozenset(
    {
        ("rule_instance", "kill_switched"),
        ("alert", "disabled"),
        ("recording", "error"),
        ("replay", "error"),
        ("kill_switch", "engaged_incomplete"),
        ("reconciliation", "stale_lockout"),
    }
)
FROZEN_STATE = "frozen"
#: Recovery arms a `frozen` state may carry (catalogue B8 names none today).
FROZEN_ALLOWED_EXIT_EVENTS: frozenset[str] = frozenset({"RECONCILED", "RESUME"})


def _is_sl_protection(chart: dict) -> bool:
    meta = chart.get("meta")
    return isinstance(meta, dict) and meta.get(SL_PROTECTION_TAG) is True


def _kill_frozen_exception(file: str, chart: dict) -> list[Finding]:
    """CV-LINT-KILL-ANCESTOR, KILL-target rule + §1.3c SL-protection exception.

    Every `KILL` arm that carries a target must land in a `type: final` state,
    except when ALL of: the chart id is in `SL_PROTECTION_CHART_IDS`, the root
    carries `meta["cv:slProtection"] = true`, and the target leaf is named
    `frozen` (which must then satisfy `_frozen_shape`). No other chart, tag or
    state name opts out (C-04, C-2.6; #1650 review)."""
    findings: list[Finding] = []
    states = dict(_walk_states(chart))
    excepted = chart.get("id") in SL_PROTECTION_CHART_IDS and _is_sl_protection(chart)
    for state_path, state in states.items():
        on = state.get("on")
        if not isinstance(on, dict) or "KILL" not in on:
            continue
        for arm in _transition_targets(on["KILL"]):
            dest = arm.get("target")
            if not isinstance(dest, str):
                continue
            dest_path = dest.lstrip("#").split(".", 1)[-1] if dest.startswith("#") else dest
            node = states.get(dest_path)
            if not isinstance(node, dict) or node.get("type") == "final":
                continue
            where = f"{state_path}.on.KILL"
            if excepted and dest_path.rsplit(".", 1)[-1] == FROZEN_STATE:
                findings.extend(_frozen_shape(file, dest_path, node))
                continue
            if (chart.get("id"), dest_path) in KILL_NONFINAL_PENDING_DECISION:
                continue
            findings.append(
                Finding(
                    "CV-LINT-KILL-ANCESTOR",
                    file,
                    where,
                    f"KILL target {dest!r} is not a final state; only a chart in "
                    f"{sorted(SL_PROTECTION_CHART_IDS)} tagged "
                    f'meta["{SL_PROTECTION_TAG}"] = true may target a non-final '
                    f"{FROZEN_STATE!r} (C-04, §1.3c)",
                )
            )
    return findings


def _frozen_shape(file: str, path: str, node: dict) -> list[Finding]:
    bad: list[str] = []
    for key in ("invoke", "after", "always", "states"):
        if node.get(key):
            bad.append(f"declares {key!r}")
    for event, value in (node.get("on") or {}).items():
        for arm in _transition_targets(value):
            if "target" in arm and event not in FROZEN_ALLOWED_EXIT_EVENTS:
                bad.append(f"leaves on {event!r}")
    return [
        Finding(
            "CV-LINT-KILL-ANCESTOR",
            file,
            path,
            f"SL-protection {FROZEN_STATE!r} state {why} (C-04 exception, §1.3c)",
        )
        for why in bad
    ]


def rule_reenter(file: str, chart: dict) -> list[Finding]:
    """CV-LINT-REENTER (A4): self-target ("restart") transitions declare
    `reenter: true` explicitly."""
    findings: list[Finding] = []
    for state_path, state in _walk_states(chart):
        for event, value in _walk_transitions(state):
            for target in _transition_targets(value):
                dest = target.get("target")
                if not isinstance(dest, str):
                    continue
                dest_norm = dest.lstrip("#").lstrip(".")
                last_segment = state_path.split(".")[-1]
                if (
                    dest_norm in (state_path, last_segment)
                    and target.get("reenter") is not True
                ):
                    findings.append(
                        Finding(
                            "CV-LINT-REENTER",
                            file,
                            f"{state_path}.on.{event}",
                            'self-target transition missing "reenter": true (A4)',
                        )
                    )
    return findings


def rule_timer(file: str, chart: dict) -> list[Finding]:
    """CV-LINT-TIMER (CV-C12', CV-C55, R11-W-1): no `after:` on states tagged
    `x-hard-deadline`; delay >= 10 ms; stable `send_id` where declared."""
    findings: list[Finding] = []
    for state_path, state in _walk_states(chart):
        after = state.get("after")
        tags = state.get("tags") or []
        has_hard_deadline = "x-hard-deadline" in tags
        if after is None:
            continue
        if has_hard_deadline:
            findings.append(
                Finding(
                    "CV-LINT-TIMER",
                    file,
                    f"{state_path}.after",
                    '"after" timer declared on a state tagged x-hard-deadline (CV-C12\')',
                )
            )
        entries = after if isinstance(after, dict) else {}
        for delay_key, value in entries.items():
            try:
                delay_ms = int(delay_key)
            except (TypeError, ValueError):
                continue
            if delay_ms < 10:
                findings.append(
                    Finding(
                        "CV-LINT-TIMER",
                        file,
                        f"{state_path}.after.{delay_key}",
                        f"timer delay {delay_ms}ms is below the 10ms floor (CV-C55)",
                    )
                )
            for target in _transition_targets(value):
                if "send_id" in target or "id" in target:
                    continue
    return findings


def rule_invoke_cycle(file: str, chart: dict) -> list[Finding]:
    """CV-LINT-INVOKE-CYCLE (W; CV-C38, retired to warning): an invoke cycle
    without an attempt counter guard is flagged, not failed."""
    findings: list[Finding] = []
    for state_path, state in _walk_states(chart):
        invoke = state.get("invoke")
        if not invoke:
            continue
        on_error = None
        if isinstance(invoke, dict):
            on_error = invoke.get("onError")
        elif isinstance(invoke, list):
            for inv in invoke:
                if isinstance(inv, dict) and inv.get("onError"):
                    on_error = inv.get("onError")
                    break
        if on_error is None:
            continue
        for target in _transition_targets(on_error):
            dest = target.get("target")
            if not isinstance(dest, str):
                continue
            dest_norm = dest.lstrip("#").lstrip(".")
            last_segment = state_path.split(".")[-1]
            if dest_norm == state_path or dest_norm == last_segment:
                has_counter_guard = "guard" in target or "cond" in target
                if not has_counter_guard:
                    findings.append(
                        Finding(
                            "CV-LINT-INVOKE-CYCLE",
                            file,
                            f"{state_path}.invoke.onError",
                            "invoke retry cycle has no attempt-counter guard (CV-C38, warning)",
                            severity=SEVERITY_WARNING,
                        )
                    )
    return findings


JSON_RULES = [
    rule_policy,
    rule_fallthrough,
    rule_always,
    rule_kill_ancestor,
    rule_reenter,
    rule_timer,
    rule_invoke_cycle,
]


def lint_machine_file(path: Path) -> list[Finding]:
    chart, parse_error = load_json(path)
    if parse_error is not None:
        return [parse_error]
    findings: list[Finding] = []
    for rule in JSON_RULES:
        findings.extend(rule(str(path), chart))
    return findings


# --------------------------------------------------------------------------
# AST rules — walk `*.py` under the source root.
# --------------------------------------------------------------------------


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _dotted_call_path(node: ast.Call) -> str | None:
    """Best-effort dotted path for a call, e.g. `interp.send` or `events.re_mint`."""
    func = node.func
    parts: list[str] = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    parts.reverse()
    return ".".join(parts) if parts else None


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports_xstate_runtime = False
        self.imports_sync_interpreter = False
        self.imports_logging_inspector = False
        self.imports_statechart_pkg = False

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".")[0] == RUNTIME_MODULE:
                self.imports_xstate_runtime = True
            if alias.name == "candleviewer.statechart" or alias.name.startswith(
                "candleviewer.statechart."
            ):
                self.imports_statechart_pkg = True
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module == RUNTIME_MODULE or module.startswith(RUNTIME_MODULE + "."):
            self.imports_xstate_runtime = True
            for alias in node.names:
                if alias.name == "SyncInterpreter":
                    self.imports_sync_interpreter = True
                if alias.name == "LoggingInspector":
                    self.imports_logging_inspector = True
        if module == "candleviewer.statechart" or module.startswith(
            "candleviewer.statechart."
        ):
            self.imports_statechart_pkg = True
        self.generic_visit(node)


def rule_import(file: str, tree: ast.AST) -> list[Finding]:
    """CV-LINT-IMPORT (CV-C03, MUSTNOT-06): the pinned runtime package is
    importable only from the two designated statechart modules; SyncInterpreter
    is importable only under tests/xstate_contract/."""
    findings: list[Finding] = []
    visitor = _ImportVisitor()
    visitor.visit(tree)
    name = Path(file).name
    is_test_contract = "xstate_contract" in Path(file).parts
    is_allowed = name in ALLOWED_IMPORT_MODULES or is_test_contract
    if visitor.imports_xstate_runtime and not is_allowed:
        findings.append(
            Finding(
                "CV-LINT-IMPORT",
                file,
                "<module>",
                "only statechart/factory.py and statechart/persistence.py may "
                f"import the {RUNTIME_MODULE} runtime (CV-C03)",
            )
        )
    if visitor.imports_sync_interpreter and not is_test_contract:
        findings.append(
            Finding(
                "CV-LINT-IMPORT",
                file,
                "<module>",
                "SyncInterpreter must only be imported under tests/xstate_contract/ "
                "(MUSTNOT-06)",
            )
        )
    return findings


def rule_inspector(file: str, tree: ast.AST) -> list[Finding]:
    """CV-LINT-INSPECTOR (CV-C28'): no LoggingInspector in production code."""
    findings: list[Finding] = []
    posix = Path(file).as_posix()
    is_fixture = "lint_statecharts/fixtures" in posix
    if "tests" in Path(file).parts and not is_fixture:
        return findings
    visitor = _ImportVisitor()
    visitor.visit(tree)
    if visitor.imports_logging_inspector:
        findings.append(
            Finding(
                "CV-LINT-INSPECTOR",
                file,
                "<module>",
                "LoggingInspector must not be imported in production code (CV-C28')",
            )
        )
    return findings


def rule_hotpath(file: str, tree: ast.AST) -> list[Finding]:
    """CV-LINT-HOTPATH (MUSTNOT-01..03): hot-path modules never import the
    statechart package."""
    findings: list[Finding] = []
    posix = Path(file).as_posix()
    if not any(
        prefix.replace("candleviewer.", "candleviewer/").replace(".", "/") in posix
        for prefix in HOTPATH_MODULE_PREFIXES
    ):
        return findings
    visitor = _ImportVisitor()
    visitor.visit(tree)
    if visitor.imports_statechart_pkg:
        findings.append(
            Finding(
                "CV-LINT-HOTPATH",
                file,
                "<module>",
                "hot-path module must never import candleviewer.statechart "
                "(MUSTNOT-01..03)",
            )
        )
    return findings


def _in_bindings(file: str) -> bool:
    return "bindings" in Path(file).parts and "statechart" in Path(file).parts


def rule_no_self_send(file: str, tree: ast.AST) -> list[Finding]:
    """CV-LINT-NO-SELF-SEND (CV-C16, CV-C25): no interp.send()/send_threadsafe
    inside bindings/ — self-events use `raise` instead."""
    findings: list[Finding] = []
    if not _in_bindings(file):
        return findings
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted_call_path(node) or ""
        if dotted.endswith((".send", ".send_threadsafe")) or dotted == "send":
            findings.append(
                Finding(
                    "CV-LINT-NO-SELF-SEND",
                    file,
                    f"line {node.lineno}",
                    "bindings/ must not call send()/send_threadsafe() on the "
                    "interpreter; use raise() for self-events (CV-C16, CV-C25)",
                )
            )
    return findings


def rule_self_receipt(file: str, tree: ast.AST) -> list[Finding]:
    """CV-LINT-SELF-RECEIPT (CV-C51, CV-C64'): no `await send(..., wait=True)`
    on the machine's own interpreter from any action/entry/exit."""
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        dotted = _dotted_call_path(call) or ""
        if not (dotted.endswith(".send") or dotted == "send"):
            continue
        has_wait_true = any(
            kw.arg == "wait"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in call.keywords
        )
        if has_wait_true:
            findings.append(
                Finding(
                    "CV-LINT-SELF-RECEIPT",
                    file,
                    f"line {node.lineno}",
                    "no action may await a wait=True receipt on its own "
                    "interpreter (CV-C51, CV-C64')",
                )
            )
    return findings


def rule_coro(file: str, tree: ast.AST) -> list[Finding]:
    """CV-LINT-CORO (CV-C67): actions and services registered in bindings/
    logic maps must be `async def`, not plain `def`."""
    findings: list[Finding] = []
    if not _in_bindings(file):
        return findings
    # Heuristic: a dict literal assigned to a variable named like
    # *actions*/*services* whose values are plain-`def` names, not coroutines.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if not any(
                "action" in t.lower() or "service" in t.lower() for t in targets
            ):
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            for value in node.value.values:
                fn_name = None
                if isinstance(value, ast.Name):
                    fn_name = value.id
                if fn_name is None:
                    continue
                for fn_node in ast.walk(tree):
                    if isinstance(fn_node, ast.FunctionDef) and fn_node.name == fn_name:
                        findings.append(
                            Finding(
                                "CV-LINT-CORO",
                                file,
                                f"line {fn_node.lineno}",
                                f"registered action/service {fn_name!r} must be "
                                "`async def`, not a plain function (CV-C67)",
                            )
                        )
    return findings


def rule_remint(file: str, tree: ast.AST) -> list[Finding]:
    """CV-LINT-REMINT (CV-C68): re_mint is called only through cv_re_mint,
    payload keys only, and only from the designated gateway module."""
    findings: list[Finding] = []
    name = Path(file).name
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted_call_path(node) or ""
        if dotted.endswith(".re_mint") or dotted == "re_mint":
            if name not in ALLOWED_REMINT_MODULES:
                findings.append(
                    Finding(
                        "CV-LINT-REMINT",
                        file,
                        f"line {node.lineno}",
                        "re_mint must be called only through cv_re_mint (CV-C68)",
                    )
                )
                continue
            bad_keys = {kw.arg for kw in node.keywords if kw.arg in ("type", "src")}
            if bad_keys:
                findings.append(
                    Finding(
                        "CV-LINT-REMINT",
                        file,
                        f"line {node.lineno}",
                        f"re_mint forbids overriding {sorted(bad_keys)} (CV-C68, R14-01)",
                    )
                )
    return findings


def rule_priority(file: str, tree: ast.AST) -> list[Finding]:
    """CV-LINT-PRIORITY (CV-C42): no priority=True anywhere, from any origin."""
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if (
                kw.arg == "priority"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
            ):
                findings.append(
                    Finding(
                        "CV-LINT-PRIORITY",
                        file,
                        f"line {node.lineno}",
                        "priority=True must never be set on any event (CV-C42)",
                    )
                )
    return findings


def rule_system_event(file: str, tree: ast.AST) -> list[Finding]:
    """CV-LINT-SYSTEM-EVENT (CV-C19): no system=True and no is_system_event()."""
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dotted = _dotted_call_path(node) or ""
            if dotted.endswith("is_system_event") or dotted == "is_system_event":
                findings.append(
                    Finding(
                        "CV-LINT-SYSTEM-EVENT",
                        file,
                        f"line {node.lineno}",
                        "is_system_event() must never be called or trusted (CV-C19)",
                    )
                )
            for kw in node.keywords:
                if (
                    kw.arg == "system"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                ):
                    findings.append(
                        Finding(
                            "CV-LINT-SYSTEM-EVENT",
                            file,
                            f"line {node.lineno}",
                            "system=True must never be constructed on any event (CV-C19)",
                        )
                    )
    return findings


def rule_restore(file: str, tree: ast.AST) -> list[Finding]:
    """CV-LINT-RESTORE (CV-C52, R13-W1): from_snapshot( appears only in
    persistence, always with minimum_version=3 and plugins=."""
    findings: list[Finding] = []
    name = Path(file).name
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted_call_path(node) or ""
        if not (dotted.endswith(".from_snapshot") or dotted == "from_snapshot"):
            continue
        if name not in ALLOWED_RESTORE_MODULES:
            findings.append(
                Finding(
                    "CV-LINT-RESTORE",
                    file,
                    f"line {node.lineno}",
                    "from_snapshot must appear only in statechart/persistence.py "
                    "(CV-C52)",
                )
            )
            continue
        kw_names = {kw.arg for kw in node.keywords}
        if "minimum_version" not in kw_names:
            findings.append(
                Finding(
                    "CV-LINT-RESTORE",
                    file,
                    f"line {node.lineno}",
                    "from_snapshot must pass minimum_version=3 (CV-C52)",
                )
            )
        if "plugins" not in kw_names:
            findings.append(
                Finding(
                    "CV-LINT-RESTORE",
                    file,
                    f"line {node.lineno}",
                    "from_snapshot must pass plugins= as a kwarg, not .use() "
                    "(R13-W1)",
                )
            )
    return findings


def rule_drain(file: str, tree: ast.AST) -> list[Finding]:
    """CV-LINT-DRAIN (CV-C65'): drain_pending() is called only in
    persistence.persist."""
    findings: list[Finding] = []
    name = Path(file).name
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted_call_path(node) or ""
        if (
            dotted.endswith(".drain_pending") or dotted == "drain_pending"
        ) and name not in ALLOWED_DRAIN_MODULES:
            findings.append(
                Finding(
                    "CV-LINT-DRAIN",
                    file,
                    f"line {node.lineno}",
                    "drain_pending() must be called only from "
                    "statechart/persistence.py (CV-C65')",
                )
            )
    return findings


def rule_errorevent(file: str, tree: ast.AST) -> list[Finding]:
    """CV-LINT-ERROREVENT (CV-C21): onError actions use
    isinstance(event, ErrorEvent) and event.error, not ad hoc attribute probes."""
    findings: list[Finding] = []
    if not _in_bindings(file):
        return findings
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if "error" not in node.name.lower() and "on_error" not in node.name.lower():
            continue
        has_isinstance_check = any(
            isinstance(n, ast.Call)
            and _call_name(n) == "isinstance"
            and any(
                isinstance(arg, ast.Name) and arg.id == "ErrorEvent" for arg in n.args
            )
            for n in ast.walk(node)
        )
        references_event_error = any(
            isinstance(n, ast.Attribute) and n.attr == "error" for n in ast.walk(node)
        )
        if not has_isinstance_check and not references_event_error:
            findings.append(
                Finding(
                    "CV-LINT-ERROREVENT",
                    file,
                    f"line {node.lineno} ({node.name})",
                    "onError handler should use isinstance(event, ErrorEvent) and "
                    "event.error (CV-C21)",
                )
            )
    return findings


AST_RULES = [
    rule_import,
    rule_inspector,
    rule_hotpath,
    rule_no_self_send,
    rule_self_receipt,
    rule_coro,
    rule_remint,
    rule_priority,
    rule_system_event,
    rule_restore,
    rule_drain,
    rule_errorevent,
]


def lint_python_file(path: Path) -> list[Finding]:
    tree, _text, parse_error = load_ast(path)
    if parse_error is not None:
        return [parse_error]
    findings: list[Finding] = []
    for rule in AST_RULES:
        findings.extend(rule(str(path), tree))
    return findings


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def lint_tree(machines_dir: Path, source_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_machine_files(machines_dir):
        findings.extend(lint_machine_file(path))
    for path in iter_python_files(source_root):
        findings.extend(lint_python_file(path))
    return findings


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--machines-dir",
        type=Path,
        default=DEFAULT_MACHINES_DIR,
        help="directory containing *.machine.json charts",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
        help="directory of Python source to AST-lint",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="only print a summary line"
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    findings = lint_tree(args.machines_dir, args.source_root)
    errors = [f for f in findings if f.severity == SEVERITY_ERROR]
    warnings = [f for f in findings if f.severity == SEVERITY_WARNING]

    if not args.quiet:
        for finding in findings:
            print(finding.format())

    print(
        f"lint_statecharts: {len(errors)} error(s), {len(warnings)} warning(s) "
        f"across machines-dir={args.machines_dir} source-root={args.source_root}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
