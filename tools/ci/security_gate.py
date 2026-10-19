#!/usr/bin/env python3
"""E03-T07: security lane severity normalisation and gate policy.

Every scanner in `.github/workflows/_job-security.yml` (CodeQL, Semgrep,
Bandit, pip-audit, npm audit, gitleaks, license-scan, Trivy) reduces its
native output to a single `Finding` shape here, so "what blocks" is defined
exactly once (technical notes, E03-T07 ticket body) instead of per-tool.

Error codes (ticket "Technical notes / design"):
    CI-SEC-001  blocking finding (severity meets/exceeds the tool's policy
                and no unexpired accepted-risk entry covers it: an entry covers
                up to its own severity, and none covers a Critical)
    CI-SEC-002  licence violation (prohibited licence, no exception)
    CI-SEC-003  licence needs approval (LGPL) and no unexpired, correctly
                approved accepted-risk entry covers it
    CI-SEC-004  accepted-risk entry has expired
    CI-SEC-005  scanner infrastructure failure (never silently treated as a
                clean run)

Stdlib + PyYAML only: `scripts/requirements-ci.txt` pins PyYAML for the CI
image, and `tools/ci/requirements-security-gate.txt` pins it by hash for the
codeql job (#3337). No network access performed by this module itself.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from tools.ci.suppressions import (
    COMMENT_ONLY_RE,
    field_problems,
    parse_nosemgrep,
    rule_matches,
)

Severity = str  # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
_SEVERITY_ORDER: dict[Severity, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
_KNOWN_TOOLS = frozenset(
    {
        "codeql",
        "semgrep",
        "bandit",
        "pip-audit",
        "npm-audit",
        "gitleaks",
        "license-scan",
        "trivy",
    }
)

# Per-tool blocking threshold (12.1 gate table / ticket "Technical notes").
# A finding at or above this severity blocks unless an accepted-risk entry
# covers it. gitleaks has no threshold: ANY finding blocks (§12.1, SR-142).
_BLOCKING_THRESHOLD: dict[str, Severity | None] = {
    "codeql": "HIGH",
    "semgrep": "HIGH",  # ERROR-severity Semgrep findings are mapped to HIGH+
    "bandit": "MEDIUM",  # High/Medium confidence+severity blocks (12.1 table)
    "pip-audit": "HIGH",
    "npm-audit": "HIGH",
    "gitleaks": None,  # any finding blocks, handled specially
    "license-scan": None,  # handled by evaluate_licenses(), not severity
    "trivy": "HIGH",
}


GITLEAKS_IR02_HINT = (
    "Treat the secret as compromised: rotate it FIRST per SECURITY.md / runbook IR-02 "
    "(docs/ci-runbook.md, section 'Credential hygiene and full-history sweep'), "
    "then remove it from the branch."
)


class SecurityGateError(Exception):
    """Raised for CI-SEC-* conditions; `code` is the stable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Finding:
    """A normalised finding from any scanner."""

    tool: str
    finding_id: str
    severity: Severity
    package: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.tool not in _KNOWN_TOOLS:
            raise ValueError(f"unknown tool: {self.tool!r}")
        if self.severity not in _SEVERITY_ORDER:
            raise ValueError(f"unknown severity: {self.severity!r}")


@dataclass(frozen=True)
class AcceptedRisk:
    finding_id: str
    tool: str
    severity: Severity
    reason: str
    approver: str
    expires: date
    ticket: str | None = None


def _severity_at_least(sev: Severity, threshold: Severity) -> bool:
    return _SEVERITY_ORDER[sev] >= _SEVERITY_ORDER[threshold]


def load_accepted_risks(path: Path) -> list[AcceptedRisk]:
    """Load and validate `security/accepted-risks.yaml`.

    Raises `SecurityGateError(CI-SEC-005, ...)` on a malformed file — a
    register CI cannot parse is a scanner-infrastructure failure, not a
    clean run.
    """
    if not path.exists():
        raise SecurityGateError("CI-SEC-005", f"accepted-risk register missing: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SecurityGateError(
            "CI-SEC-005", f"accepted-risk register is not valid YAML: {exc}"
        ) from exc

    entries_raw = raw.get("entries", [])
    if not isinstance(entries_raw, list):
        raise SecurityGateError("CI-SEC-005", "accepted-risk register: 'entries' must be a list")

    risks: list[AcceptedRisk] = []
    for i, entry in enumerate(entries_raw):
        try:
            tool = entry["tool"]
            severity = entry["severity"]
            if tool == "gitleaks":
                raise SecurityGateError(
                    "CI-SEC-005",
                    f"accepted-risk entry #{i}: gitleaks findings cannot be accepted "
                    "(SR-142: any finding blocks unconditionally)",
                )
            # evaluate_findings ranks the entry's severity against the finding's (#3558).
            if not isinstance(severity, str) or severity not in _SEVERITY_ORDER:
                raise ValueError(
                    f"severity {severity!r} is not one of {', '.join(_SEVERITY_ORDER)}"
                )
            if severity == "CRITICAL":
                raise SecurityGateError(
                    "CI-SEC-005",
                    f"accepted-risk entry #{i}: Critical-severity findings cannot be "
                    "accepted (30-release-roadmap.md §4.4 R0 threshold)",
                )
            expires_raw = entry["expires"]
            expires = (
                expires_raw
                if isinstance(expires_raw, date) and not isinstance(expires_raw, datetime)
                else datetime.strptime(str(expires_raw), "%Y-%m-%d").replace(tzinfo=UTC).date()
            )
            risks.append(
                AcceptedRisk(
                    finding_id=entry["id"],
                    tool=tool,
                    severity=severity,
                    reason=entry["reason"],
                    approver=entry["approver"],
                    expires=expires,
                    ticket=entry.get("ticket"),
                )
            )
        except SecurityGateError:
            raise
        except (KeyError, ValueError) as exc:
            raise SecurityGateError(
                "CI-SEC-005", f"accepted-risk entry #{i} is malformed: {exc}"
            ) from exc
    return risks


def _find_risk(risks: list[AcceptedRisk], finding: Finding) -> AcceptedRisk | None:
    for risk in risks:
        if risk.finding_id == finding.finding_id and risk.tool == finding.tool:
            return risk
    return None


@dataclass(frozen=True)
class GateResult:
    blocked: bool
    code: str | None
    messages: list[str]


def evaluate_findings(
    findings: list[Finding], risks: list[AcceptedRisk], *, run_date: date
) -> GateResult:
    """Apply the single blocking policy described in the ticket's Technical
    notes: every tool reduces to {CRITICAL, HIGH, MEDIUM, LOW}; this is the
    one place "what blocks" is decided.
    """
    messages: list[str] = []
    blocking_code: str | None = None

    for finding in findings:
        threshold = _BLOCKING_THRESHOLD.get(finding.tool)

        # gitleaks: ANY finding blocks, no accepted-risk exception possible
        # (SR-142; load_accepted_risks() already rejects gitleaks entries).
        if finding.tool == "gitleaks":
            messages.append(
                f"CI-SEC-001: gitleaks finding {finding.finding_id} blocks the merge "
                f"({finding.detail}). {GITLEAKS_IR02_HINT}"
            )
            blocking_code = blocking_code or "CI-SEC-001"
            continue

        if threshold is None or not _severity_at_least(finding.severity, threshold):
            continue

        risk = _find_risk(risks, finding)
        if risk is None:
            messages.append(
                f"CI-SEC-001: {finding.tool} finding {finding.finding_id} "
                f"({finding.severity}) has no accepted-risk entry — {finding.detail}"
            )
            blocking_code = blocking_code or "CI-SEC-001"
            continue

        # load_accepted_risks() refuses a CRITICAL entry, but an entry filed under a lower
        # severity can carry a Critical finding's id: it must not cover it either (#3494).
        if finding.severity == "CRITICAL":
            messages.append(
                f"CI-SEC-001: {finding.tool} finding {finding.finding_id} "
                f"({finding.severity}) has an accepted-risk entry, but Critical findings take "
                f"no accepted-risk entry (30-release-roadmap.md §4.4 R0) — {finding.detail}"
            )
            blocking_code = blocking_code or "CI-SEC-001"
            continue

        # An entry accepts up to its own severity: a finding reported above it (an advisory
        # re-scored after the decision, say) needs a new decision, not the old entry (#3558).
        if not _severity_at_least(risk.severity, finding.severity):
            messages.append(
                f"CI-SEC-001: {finding.tool} finding {finding.finding_id} "
                f"({finding.severity}) has an accepted-risk entry for {risk.severity} only, "
                f"so it needs a new decision — {finding.detail}"
            )
            blocking_code = blocking_code or "CI-SEC-001"
            continue

        if risk.expires <= run_date:
            messages.append(
                f"CI-SEC-004: accepted risk expired for {finding.finding_id} "
                f"(expired {risk.expires.isoformat()}, run date {run_date.isoformat()})"
            )
            blocking_code = blocking_code or "CI-SEC-004"
            continue
        # Unexpired, matching accepted-risk entry: does not block, but is always
        # reported so an accepted risk is never silent (C-12.3).
        messages.append(
            f"accepted risk: {finding.tool} finding {finding.finding_id} "
            f"({finding.severity}) until {risk.expires.isoformat()} - {risk.reason}"
        )

    return GateResult(blocked=blocking_code is not None, code=blocking_code, messages=messages)


@dataclass(frozen=True)
class LicenseFinding:
    package: str
    version: str
    license: str


def load_license_allowlist(path: Path) -> dict[str, Any]:
    try:
        doc: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return doc
    except (OSError, json.JSONDecodeError) as exc:
        raise SecurityGateError(
            "CI-SEC-005", f"licence allowlist unreadable/invalid: {path}: {exc}"
        ) from exc


def evaluate_licenses(
    deps: list[LicenseFinding],
    allowlist: dict[str, Any],
    risks: list[AcceptedRisk],
    *,
    run_date: date,
) -> GateResult:
    """SR-136: allowed / needs-approval (LGPL) / prohibited (GPL/AGPL/SSPL/
    BUSL/Commons-Clause/non-commercial) / unknown-license-is-a-failure.
    """
    allowed = set(allowlist.get("allowed", []))
    needs_approval = set(allowlist.get("needs_approval", {}).get("licenses", []))
    prohibited = set(allowlist.get("prohibited", {}).get("licenses", []))
    dev_only = {p for p in allowlist.get("dev_only_exceptions", {}).get("packages", [])}
    unknown_policy = allowlist.get("unknown_license_policy", "fail")

    messages: list[str] = []
    blocking_code: str | None = None

    for dep in deps:
        key = f"{dep.package}@{dep.version}"
        finding_id = f"license:{key}"

        if dep.license in allowed:
            continue

        if key in dev_only:
            continue

        if dep.license in needs_approval:
            risk = next(
                (r for r in risks if r.finding_id == finding_id and r.tool == "license-scan"),
                None,
            )
            if risk is None:
                messages.append(
                    f"CI-SEC-003: {dep.package} {dep.version} is licensed {dep.license!r} "
                    "(LGPL) and needs security + owner approval (SR-136) — no accepted-risk "
                    "entry found"
                )
                blocking_code = blocking_code or "CI-SEC-003"
            elif risk.expires <= run_date:
                messages.append(
                    f"CI-SEC-004: accepted risk for {dep.package} {dep.version} "
                    f"(LGPL approval) expired {risk.expires.isoformat()}"
                )
                blocking_code = blocking_code or "CI-SEC-004"
            continue

        if dep.license in prohibited:
            messages.append(
                f"CI-SEC-002: {dep.package} {dep.version} is licensed {dep.license!r}, "
                "which is prohibited by SR-136 (GPL/AGPL/SSPL/BUSL/Commons-Clause/"
                "non-commercial-only)"
            )
            blocking_code = blocking_code or "CI-SEC-002"
            continue

        # Unknown licence: fail per SR-136 "Unknown licence = fail" (CONSTITUTION §9 #14).
        if unknown_policy == "fail":
            messages.append(
                f"CI-SEC-002: {dep.package} {dep.version} has an unrecognised licence "
                f"{dep.license!r} — not on the allow/needs-approval/prohibited lists "
                "(unknown licence fails the build per SR-136)"
            )
            blocking_code = blocking_code or "CI-SEC-002"

    return GateResult(blocked=blocking_code is not None, code=blocking_code, messages=messages)


# --------------------------------------------------------------------------
# Adapters: reduce each tool's native output to Finding / LicenseFinding.
# Each is deliberately small and defensive — a tool output that fails to
# parse is a scanner-infrastructure failure (CI-SEC-005), never treated as
# "no findings" (ticket: "a scanner that silently errors is indistinguishable
# from a clean repository").
# --------------------------------------------------------------------------

_SARIF_LEVEL_TO_SEVERITY: dict[str, Severity] = {
    "error": "HIGH",
    "warning": "MEDIUM",
    "note": "LOW",
    "none": "LOW",
}


def _sarif_rule_index(
    run: dict[str, Any],
) -> tuple[dict[str, Any], list[list[dict[str, Any]]]]:
    """Index a run's rule descriptors by id, plus positional tables.

    Returns `(by_id, components)` where `components[0]` is the driver's rule
    list and `components[i]` the i-th extension's — the layout SARIF uses to
    resolve `result.rule.{toolComponent.index, index}` / `result.ruleIndex`.
    """
    tool = run.get("tool", {})
    components: list[list[dict[str, Any]]] = [list(tool.get("driver", {}).get("rules", []))]
    for ext in tool.get("extensions", []):
        components.append(list(ext.get("rules", [])))
    by_id: dict[str, Any] = {}
    for rules in components:
        for rule in rules:
            if isinstance(rule, dict) and "id" in rule:
                by_id.setdefault(rule["id"], rule)
    return by_id, components


def _rule_severity(rule: dict[str, Any], result: dict[str, Any] | None = None) -> Severity:
    """Bucket from `security-severity` (result first, then rule), else SARIF level.

    No severity anywhere defaults to `warning` -> MEDIUM (below the semgrep HIGH
    threshold, so unscored SAST noise does not block; fail-closed adapters such
    as pip-audit treat unscored advisories as HIGH on their own).
    """
    res = result or {}
    sec_sev = res.get("properties", {}).get("security-severity")
    if sec_sev is None:
        sec_sev = rule.get("properties", {}).get("security-severity")
    score: float | None = None
    if sec_sev is not None:
        try:
            score = float(sec_sev)
        except (TypeError, ValueError):
            score = None
    if score is not None:
        if score >= 9.0:
            return "CRITICAL"
        if score >= 7.0:
            return "HIGH"
        if score >= 4.0:
            return "MEDIUM"
        return "LOW"
    level = res.get("level") or rule.get("defaultConfiguration", {}).get("level", "warning")
    return _SARIF_LEVEL_TO_SEVERITY.get(level, "MEDIUM")


def _sarif_result_rule(
    result: dict[str, Any],
    by_id: dict[str, Any],
    components: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    """Resolve a result's rule descriptor, preferring `ruleId`.

    If the positional reference (`rule.index` / `ruleIndex`) points at a
    different rule than `ruleId`, the descriptor with the HIGHER severity wins
    (fail-closed) and a warning is logged: a mismatched index never downgrades.
    """
    ref = result.get("rule", {})
    comp_idx = ref.get("toolComponent", {}).get("index", 0)
    rule_idx = ref.get("index", result.get("ruleIndex"))
    by_index: dict[str, Any] = {}
    if isinstance(rule_idx, int) and 0 <= comp_idx < len(components):
        rules = components[comp_idx]
        if 0 <= rule_idx < len(rules):
            by_index = rules[rule_idx]
    rid = result.get("ruleId") or ref.get("id")
    by_rule_id: dict[str, Any] = by_id.get(rid, {}) if rid else {}
    if not by_rule_id:
        return by_index
    if not by_index or by_index.get("id") == by_rule_id.get("id"):
        return by_rule_id
    print(
        f"security_gate: warning: ruleId {rid!r} and ruleIndex {rule_idx} "
        f"({by_index.get('id')!r}) disagree; using the higher severity",
        file=sys.stderr,
    )
    sev_id = _SEVERITY_ORDER[_rule_severity(by_rule_id)]
    sev_ix = _SEVERITY_ORDER[_rule_severity(by_index)]
    return by_index if sev_ix > sev_id else by_rule_id


def _justification_texts(result: dict[str, Any], source_root: Path) -> list[str]:
    """The finding line, plus the line above only when that line is comment-only
    and the finding line itself is not a comment. Never a code line."""
    locs = result.get("locations") or []
    phys = locs[0].get("physicalLocation", {}) if locs else {}
    uri = phys.get("artifactLocation", {}).get("uri", "")
    start = phys.get("region", {}).get("startLine")
    if not uri or not isinstance(start, int) or start < 1:
        return []
    try:
        lines = (source_root / uri).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    if start > len(lines):
        return []
    own = lines[start - 1]
    texts = [own]
    if start >= 2 and not COMMENT_ONLY_RE.match(own) and COMMENT_ONLY_RE.match(lines[start - 2]):
        texts.append(lines[start - 2])
    return texts


def _suppression_problem(
    result: dict[str, Any], rule_id: str, source_root: Path, today: date
) -> str | None:
    """Return None if the result carries a justified, unexpired in-source
    suppression (so it may be skipped), else the reason it still blocks.
    Returns "" if the result has no in-source suppression at all.

    Grammar, exact rule-id matching and the review-date cap are owned by
    `tools/ci/suppressions.py`, shared with `check_auth_semgrep.py`.
    """
    sups = result.get("suppressions") or []
    inline = [s for s in sups if isinstance(s, dict) and s.get("kind") == "inSource"]
    if not inline:
        return ""
    texts = [str(s["justification"]) for s in inline if s.get("justification")]
    if not texts:
        texts = _justification_texts(result, source_root)
    last = "needs 'nosemgrep: <rule-id>[,<rule-id>] reason=<r> owner=@<who> review=YYYY-MM-DD'"
    for text in texts:
        for marker in parse_nosemgrep(text):
            if not rule_matches(rule_id, marker.rules):
                continue
            problems = field_problems(marker.rest, today)
            if not problems:
                return None
            last = "; ".join(problems)
    return last


def _incomplete_scan(invocations: object) -> str | None:
    """Why a run's `invocations` show the scan did not complete, or None (#3372).

    An invocation must report `executionSuccessful: true`. An error-level
    `toolConfigurationNotifications` entry also means part of the scan did not
    happen: Bandit lists each file it could not scan there and still reports
    success. `toolExecutionNotifications` are not read: CodeQL reports per-file
    extraction diagnostics there, and Semgrep's fatal errors already fail its step.
    Semgrep's per-file parse errors are judged from its JSON report instead
    (`check_semgrep_coverage`, #3549): its notifications carry no line spans.
    """
    if not isinstance(invocations, list):
        return "'invocations' is not a list"
    for j, invocation in enumerate(invocations):
        if not isinstance(invocation, dict):
            return f"invocation {j} is not an object"
        if invocation.get("executionSuccessful") is not True:
            return f"invocation {j} does not report executionSuccessful: true"
        notes = invocation.get("toolConfigurationNotifications", [])
        if not isinstance(notes, list) or not all(isinstance(n, dict) for n in notes):
            return f"invocation {j} 'toolConfigurationNotifications' is not a list of objects"
        errors = [note for note in notes if note.get("level") == "error"]
        if errors:
            first = json.dumps(errors[0])  # escaped: no line breaks reach the log
            first = first if len(first) <= 300 else first[:297] + "..."
            return f"invocation {j} reports {len(errors)} configuration error(s), first: {first}"
    return None


def _sarif_runs(runs: object, path: Path, tool: str) -> list[dict[str, Any]]:
    """Return the document's runs once each one records a completed scan (#3337, #3372).

    Every scanner that reaches this gate (CodeQL, Semgrep, Bandit, Trivy) writes
    one run per scan, clean or not, with a named `tool.driver` (SARIF requires
    `tool.driver.name`) and a `results` list, `[]` when clean. A document with no
    run records no scan, and a run with no driver is malformed. `results` absent
    or null means the analysis was not performed (SARIF 2.1.0 §3.14.23), and an
    invocation can say the scan did not complete (`_incomplete_scan`). Each case
    is CI-SEC-005, never a clean scan or findings without a severity.
    """

    def malformed(reason: str) -> SecurityGateError:
        return SecurityGateError("CI-SEC-005", f"{tool}: {path} {reason}")

    if not isinstance(runs, list):
        raise malformed("is not a SARIF document ('runs' is not a list)")
    if not runs:
        raise malformed("has no runs, so it records no scan")
    for i, run in enumerate(runs):
        if not isinstance(run, dict):
            raise malformed(f"run {i} is not an object")
        component = run.get("tool")
        driver = component.get("driver") if isinstance(component, dict) else None
        name = driver.get("name") if isinstance(driver, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise malformed(
                f"run {i} has no tool.driver with a name (a malformed run, "
                "not findings without a severity)"
            )
        results = run.get("results")
        if results is None:
            raise malformed(f"run {i} has no 'results' list (absent or null: not computed)")
        if not isinstance(results, list):
            raise malformed(f"run {i} 'results' is not a list")
        for k, result in enumerate(results):
            if not isinstance(result, dict):
                raise malformed(f"run {i} result {k} is not an object")
        problem = _incomplete_scan(run.get("invocations", []))
        if problem:
            raise malformed(f"run {i} records no completed scan: {problem}")
    return runs


def parse_sarif(
    path: Path,
    tool: str,
    *,
    source_root: Path | None = None,
    today: date | None = None,
) -> list[Finding]:
    """Parse a SARIF 2.1.0 file into normalised findings.

    Used for CodeQL, Semgrep, Bandit and Trivy (every SARIF tool in
    `_PARSERS`). Severity is read from `security-severity` (CVSS-like float,
    mapped to buckets) when the result *or its rule descriptor* provides it,
    else falls back to the SARIF `level` (error/warning/note) of the result,
    then of the rule's `defaultConfiguration`.

    CodeQL in particular carries both `security-severity` and the level only
    on the rule (`tool.driver.rules[]` / `tool.extensions[].rules[]`) and
    omits `level` on results that match the default — reading the result
    alone silently downgraded every CodeQL High to MEDIUM (never blocking),
    which is how PRs with a GitHub-reported High CodeQL alert passed this
    gate (CI-SEC-001 regression, fixed under ci/e03-codeql-job-fix).

    A SARIF with no run, or with a run that names no `tool.driver`, has no
    `results` list or records an incomplete scan, is a scanner-infrastructure
    failure (CI-SEC-005, `_sarif_runs`), for every tool. So is a CodeQL result
    with no SARIF `level` whose rule descriptor is on neither the driver nor an
    extension (#3372): CodeQL describes every rule it reports, so the result is
    malformed, not the default MEDIUM (which the codeql policy never blocks).
    CI-SEC-005 rather than a guessed HIGH: its real severity is unknown, and an
    accepted-risk entry can clear a HIGH but never a malformed SARIF.
    """
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecurityGateError(
            "CI-SEC-005", f"{tool}: unreadable/invalid SARIF {path}: {exc}"
        ) from exc

    if not isinstance(doc, dict) or "runs" not in doc:
        raise SecurityGateError("CI-SEC-005", f"{tool}: {path} is not a SARIF document (no 'runs')")

    findings: list[Finding] = []
    for i, run in enumerate(_sarif_runs(doc["runs"], path, tool)):
        by_id, components = _sarif_rule_index(run)
        for k, result in enumerate(run["results"]):
            rule_id = result.get("ruleId", "unknown-rule")
            rule = _sarif_result_rule(result, by_id, components)
            level = result.get("level")
            scored = isinstance(level, str) and level in _SARIF_LEVEL_TO_SEVERITY
            if tool == "codeql" and not rule and not scored:
                raise SecurityGateError(
                    "CI-SEC-005",
                    f"{tool}: {path} run {i} result {k} ({rule_id!r}) has no level and no rule "
                    "descriptor on tool.driver or tool.extensions (a malformed CodeQL result)",
                )
            if rule_id == "unknown-rule" and "id" in rule:
                rule_id = rule["id"]
            locations = result.get("locations", [])
            loc = ""
            if locations:
                phys = locations[0].get("physicalLocation", {})
                uri = phys.get("artifactLocation", {}).get("uri", "").replace("\\", "/")
                line = phys.get("region", {}).get("startLine", "")
                loc = f"{uri}:{line}" if uri else ""
            finding_id = f"{rule_id}:{loc}" if loc else rule_id

            suppression_note = ""
            if tool == "semgrep":
                problem = _suppression_problem(
                    result,
                    rule_id,
                    source_root or Path.cwd(),
                    today or datetime.now(UTC).date(),
                )
                if problem is None:
                    continue
                if problem:
                    suppression_note = f"CI-SEC-006: unjustified in-source suppression ({problem}) "

            severity = _rule_severity(rule, result)

            message = result.get("message", {}).get("text", "")
            findings.append(
                Finding(
                    tool=tool,
                    finding_id=finding_id,
                    severity=severity,
                    detail=suppression_note + (f"{message} ({loc})" if loc else message),
                )
            )
    return findings


# How Semgrep's JSON report (`--json-output`) shows a target a rule did not analyse (#3549).
# Only two error kinds leave the other rules' findings on a target intact, so only they are
# notes: a rule `Timeout` on a file, and a `PartialParsing` error in a snippet a rule embeds in a
# YAML file (a workflow's `run:` script read as Bash, say; the YAML itself parsed). Either one
# fails the scan when it comes from one of the repo's own rules, whose findings are its
# invariants: a cv-* rule (`.semgrep/`, named `semgrep.cv-*` in CI) or an auth pack rule.
# `Too many matches` drops every rule's findings on the file, so it fails like any other error.
SEMGREP_TIMEOUT_THRESHOLD = 3  # Semgrep's default --timeout-threshold, which CI keeps
_SEMGREP_SNIPPET = re.compile(
    r"When parsing a snippet as .+? for metavariable-pattern in rule '([^'\n]+)'"
)
_YAML_SUFFIXES = (".yml", ".yaml")
# Why Semgrep skipped a target, as `--verbose` lists it in `paths.skipped`. An ignore file or a
# CLI include/exclude is configuration that review sees. A target whose analysis failed is judged
# by its entry in `errors`. Any other reason, such as a size above `--max-target-bytes`, means no
# rule analysed the target, so the scan fails.
_CONFIGURED_SKIPS = frozenset(
    {
        "Gitignore_patterns_match",  # Semgrep's spelling (semgrep_output_v1)
        "semgrepignore_patterns_match",
        "cli_include_flags_do_not_match",
        "cli_exclude_flags_match",
    }
)
_FAILED_ANALYSIS = "analysis_failed_parser_or_internal_error"


def _is_cv_rule(rule_id: str) -> bool:
    """A `.semgrep/cv-*.yml` rule: `semgrep.cv-obs-no-print` as CI names it, or `cv-...`."""
    return rule_id.rsplit(".", 1)[-1].startswith("cv-")


def _every_rule(_rule_id: str) -> bool:
    """The auth pack's rules (`security/semgrep/auth`): each one guards RBAC or audit."""
    return True


def _line(point: object) -> int | None:
    line = point.get("line") if isinstance(point, dict) else None
    return line if isinstance(line, int) and not isinstance(line, bool) and line > 0 else None


def _span_lines(error: dict[str, Any]) -> set[int] | None:
    """The lines a `PartialParsing` error's spans cover, or None without a valid span."""
    spans = error.get("spans")
    kind = error.get("type")
    if spans is None and isinstance(kind, list) and len(kind) == 2:
        spans = kind[1]  # Semgrep writes the spans in both places
    if not isinstance(spans, list) or not spans:
        return None
    lines: set[int] = set()
    for span in spans:
        if not isinstance(span, dict):
            return None
        start, end = _line(span.get("start")), _line(span.get("end"))
        if start is None or end is None or end < start:
            return None
        lines.update(range(start, end + 1))
    return lines


def _ranges(lines: set[int]) -> str:
    """`{3, 10, 11, 12}` as `3, 10-12`."""
    runs: list[list[int]] = []
    for number in sorted(lines):
        if runs and number == runs[-1][1] + 1:
            runs[-1][1] = number
        else:
            runs.append([number, number])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def _escape(text: str) -> str:
    """`text` escaped as the Actions toolkit escapes a command's data: no CR or LF survives."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _annotate(note: str, target: str, line: int | None = None) -> str:
    """`note` as a GitHub Actions warning on `target`, so the checks UI shows it as well.

    Escaped as the Actions toolkit escapes a command, so no path or text can end it early.
    """
    where = "file=" + _escape(target).replace(":", "%3A").replace(",", "%2C")
    return f"::warning {where}" + (f",line={line}" if line else "") + f"::{_escape(note)}"


def check_semgrep_coverage(path: Path, own_rule: Callable[[str], bool] = _is_cv_rule) -> list[str]:
    """Raise CI-SEC-005 when Semgrep's JSON report shows a target a rule did not analyse (#3549).

    Semgrep's SARIF lists such an error only as a `toolExecutionNotifications` entry with no
    line span, and its summary still calls the scan complete, so the step also writes its
    `--json-output` for this check. Semgrep 1.99 read files with PEP 695 generics in part or not
    at all and reported no finding there; a part it skipped can hide a cv-* rule's match too.

    Every error fails the scan except two, which come back as GitHub warnings for the log and
    the checks UI: a `Timeout` of a rule that is not `own_rule` on a file with fewer than
    `SEMGREP_TIMEOUT_THRESHOLD` of them (at that count Semgrep runs no further rule on the
    file), and a `PartialParsing` error in a snippet that such a rule embeds in a YAML file.
    The scan also fails on a target `--verbose` lists as skipped for a reason other than
    configuration (`_CONFIGURED_SKIPS`) or an error above, and on a rule Semgrep skipped.
    """

    def lost_scan(reason: str) -> SecurityGateError:
        return SecurityGateError("CI-SEC-005", f"semgrep: {path} {reason}")

    def clipped(error: dict[str, Any]) -> str:
        text = json.dumps(error)  # escaped: no line breaks reach the log
        return text if len(text) <= 300 else text[:297] + "..."

    def objects(value: object) -> list[dict[str, Any]] | None:
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value
        return None

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise lost_scan(f"is not a readable JSON report: {exc}") from exc
    if not isinstance(doc, dict):
        doc = {}
    errors = objects(doc.get("errors"))
    if errors is None:
        raise lost_scan("has no 'errors' list of objects (not a semgrep --json-output report)")
    paths = doc.get("paths")
    skipped = objects(paths.get("skipped") if isinstance(paths, dict) else None)
    if skipped is None:
        raise lost_scan(
            "has no 'paths.skipped' list of objects (semgrep writes it with --verbose), so the "
            "targets it skipped are unknown"
        )
    skipped_rules = objects(doc.get("skipped_rules"))
    if skipped_rules is None:
        raise lost_scan(
            "has no 'skipped_rules' list of objects, so the rules it skipped are unknown"
        )
    lost: list[str] = []
    timeouts: dict[str, list[str]] = {}  # target -> the rules that timed out on it
    snippets: dict[str, tuple[set[int], set[str]]] = {}  # YAML target -> lines, rules
    for error in errors:
        kind = error.get("type")
        name = kind[0] if isinstance(kind, list) and kind else kind
        if not isinstance(name, str):
            raise lost_scan(f"has an error with no type name: {clipped(error)}")
        target = error.get("path") if isinstance(error.get("path"), str) else None
        rule = error.get("rule_id") if isinstance(error.get("rule_id"), str) else None
        if name == "PartialParsing":
            lines = _span_lines(error)
            if not target or lines is None:
                no_span = "has a PartialParsing error with no target or line span"
                raise lost_scan(f"{no_span}: {clipped(error)}")
            message = error.get("message")
            snippet = _SEMGREP_SNIPPET.search(message) if isinstance(message, str) else None
            parser = snippet.group(1) if snippet else rule
            own = any(own_rule(r) for r in (rule, parser) if r)
            if snippet and not own and target.endswith(_YAML_SUFFIXES):
                gap = snippets.setdefault(target, (set(), set()))
                gap[0].update(lines)
                gap[1].add(snippet.group(1))
            else:
                by = f" in {parser}" if parser else ""
                lost.append(f"{target} (PartialParsing{by}, line(s) {_ranges(lines)})")
            continue
        if name == "Timeout" and target:
            timeouts.setdefault(target, []).append(rule or "an unnamed rule")
            if rule and not own_rule(rule):
                continue
        by = f" in {rule}" if rule else ""
        lost.append(f"{target or 'an unnamed target'} ({name}{by})")
    notes: list[str] = []
    for target, rules in timeouts.items():
        if len(rules) >= SEMGREP_TIMEOUT_THRESHOLD:
            lost.append(f"{target} ({len(rules)} rule timeouts, so Semgrep skipped the rules left)")
        else:
            note = f"semgrep: {', '.join(rules)} timed out on {target}; the other rules analysed it"
            notes.append(_annotate(note + ", not failing", target))
    for target, (lines, parsers) in snippets.items():
        note = f"semgrep: {target}: {', '.join(sorted(parsers))} could not parse the snippet on "
        note += f"line(s) {_ranges(lines)}; the rest was analysed, not failing"
        notes.append(_annotate(note, target, min(lines)))
    failed = {error["path"] for error in errors if isinstance(error.get("path"), str)}
    for entry in skipped:
        target = entry["path"] if isinstance(entry.get("path"), str) else None
        reason = entry["reason"] if isinstance(entry.get("reason"), str) else "no reason given"
        configured = reason in _CONFIGURED_SKIPS
        judged = reason == _FAILED_ANALYSIS and target in failed  # by its entry in errors
        if target and (configured or judged):
            continue
        lost.append(f"{target or 'an unnamed target'} (skipped: {reason})")
    lost.extend(f"a rule Semgrep skipped: {clipped(entry)}" for entry in skipped_rules)
    if lost:
        raise lost_scan(
            f"shows {len(lost)} target(s) a rule did not analyse, so their clean result means "
            "nothing: " + "; ".join(_escape(entry) for entry in lost)
        )
    return sorted(notes)


def parse_pip_audit(path: Path) -> list[Finding]:
    """`pip-audit -f json` output -> Findings. Severity is not always
    reported by pip-audit; advisories without an explicit severity are
    treated as HIGH (fail-closed — never silently downgrade an unscored
    advisory).
    """
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecurityGateError(
            "CI-SEC-005", f"pip-audit: unreadable/invalid {path}: {exc}"
        ) from exc

    findings: list[Finding] = []
    deps = doc if isinstance(doc, list) else doc.get("dependencies", [])
    for dep in deps:
        name = dep.get("name", "unknown")
        version = dep.get("version", "")
        for vuln in dep.get("vulns", []):
            vuln_id = vuln.get("id", "UNKNOWN")
            severity = str(vuln.get("severity") or "HIGH").upper()
            if severity not in _SEVERITY_ORDER:
                severity = "HIGH"
            findings.append(
                Finding(
                    tool="pip-audit",
                    finding_id=vuln_id,
                    severity=severity,
                    package=f"{name}=={version}",
                    detail=vuln.get("description", ""),
                )
            )
    return findings


# `pnpm audit --json` as pnpm 12.5.1 writes it (scripts/tests/fixtures/pnpm-audit/README.md):
# `advisories` maps npm's numeric advisory id to one GHSA advisory on one module, and
# `metadata.vulnerabilities` counts those advisories per severity.
_PNPM_SEVERITY: dict[str, Severity] = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "moderate": "MEDIUM",
    "low": "LOW",
    "info": "LOW",
}
_GHSA_ID = re.compile(r"GHSA(?:-[0-9a-z]{4}){3}")


def _pnpm_ghsa(advisory: dict[str, Any]) -> str | None:
    """The advisory's GHSA id, which accepted-risk entries use: `github_advisory_id`, else the
    last segment of its `url`."""
    url = advisory.get("url")
    tail = url.rstrip("/").rsplit("/", 1)[-1] if isinstance(url, str) else None
    for candidate in (advisory.get("github_advisory_id"), tail):
        if isinstance(candidate, str) and _GHSA_ID.fullmatch(candidate):
            return candidate
    return None


def _pnpm_installed(advisory: dict[str, Any]) -> tuple[list[str], list[str]] | None:
    """The versions (in pnpm's order, once each) and all dependency paths in the advisory's
    `findings`; None unless that is a non-empty list of objects, each with a string `version`
    and a non-empty list of string `paths`."""
    entries = advisory.get("findings")
    if not isinstance(entries, list) or not entries:
        return None
    versions: list[str] = []
    paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        version, entry_paths = entry.get("version"), entry.get("paths")
        if not isinstance(version, str) or not isinstance(entry_paths, list) or not entry_paths:
            return None
        if not all(isinstance(dep_path, str) for dep_path in entry_paths):
            return None
        versions.append(version)
        paths.extend(entry_paths)
    return list(dict.fromkeys(versions)), paths


def _pnpm_counts(counts: dict[str, Any]) -> str:
    """Per-severity advisory counts as text, e.g. "1 high, 2 moderate"; "" when all are 0."""
    return ", ".join(f"{counts[sev]} {sev}" for sev in _PNPM_SEVERITY if counts[sev])


def parse_npm_audit(path: Path) -> list[Finding]:
    """`pnpm audit --json` (pnpm 12.5.1, which CI and `make security` run) -> Findings.

    pnpm's report is not npm's (#3494): `advisories`, keyed by npm's advisory id, and
    `metadata`. Each advisory is one module's exposure to one GHSA, and its `findings` list
    every installed vulnerable version with all its dependency paths. The gate judges the
    advisory, so it is one Finding however many versions and paths it has (they go into
    `package` and `detail`). Two modules exposed to one GHSA stay two Findings, which one
    accepted-risk entry covers. `finding_id` is the GHSA id, the id the register uses.

    Fails closed (CI-SEC-005), never zero findings: on an empty file (pnpm writes nothing to
    stdout when it cannot reach the registry), on any other schema (npm's own `npm audit
    --json` too: nothing here runs it), on a missing or mistyped key or an unknown severity,
    and on advisories that disagree with the per-severity counts in `metadata.vulnerabilities`
    (pnpm counts, but leaves out of `advisories`, one on its auditConfig ignore list: the
    register is the only exception path, C-12.3). A clean run is an empty `advisories` with
    zero counts.
    """

    def malformed(reason: str) -> SecurityGateError:
        return SecurityGateError("CI-SEC-005", f"npm-audit: {path} {reason}")

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise malformed(f"is unreadable: {exc}") from exc
    if not text.strip():
        raise malformed("is empty: pnpm audit wrote no report (its stderr in the log says why)")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise malformed(f"is not JSON: {exc}") from exc
    if not (
        isinstance(doc, dict)
        and isinstance(doc.get("advisories"), dict)
        and isinstance(doc.get("metadata"), dict)
    ):
        raise malformed(
            "is not a `pnpm audit --json` report "
            "(an object with an 'advisories' object and a 'metadata' object)"
        )
    counts = doc["metadata"].get("vulnerabilities")
    if not (
        isinstance(counts, dict)
        and set(counts) == set(_PNPM_SEVERITY)
        and all(type(n) is int and n >= 0 for n in counts.values())
    ):
        raise malformed("has no counts per severity in 'metadata.vulnerabilities'")

    findings: list[Finding] = []
    listed = dict.fromkeys(_PNPM_SEVERITY, 0)
    for key, advisory in doc["advisories"].items():
        if not isinstance(advisory, dict):
            raise malformed(f"advisory {key} is not an object")
        severity, module, title = (advisory.get(k) for k in ("severity", "module_name", "title"))
        if not isinstance(severity, str) or severity not in _PNPM_SEVERITY:
            raise malformed(
                f"advisory {key} has no known severity (critical, high, moderate, low or info)"
            )
        if not isinstance(module, str) or not module:
            raise malformed(f"advisory {key} has no module_name")
        if not isinstance(title, str):
            raise malformed(f"advisory {key} has no title")
        ghsa = _pnpm_ghsa(advisory)
        if ghsa is None:
            raise malformed(
                f"advisory {key} has no GHSA id (github_advisory_id, or the last segment of url)"
            )
        installed = _pnpm_installed(advisory)
        if installed is None:
            raise malformed(
                f"advisory {key} has no findings (a non-empty list of objects with a version "
                "and a non-empty paths list)"
            )
        versions, paths = installed
        listed[severity] += 1
        package = f"{module}@{','.join(versions)}"
        n_paths = f"{len(paths)} dependency path{'' if len(paths) == 1 else 's'}"
        findings.append(
            Finding(
                tool="npm-audit",
                finding_id=ghsa,
                severity=_PNPM_SEVERITY[severity],
                package=package,
                detail=f"{package}: {title} ({n_paths}, e.g. {paths[0]})",
            )
        )
    if listed != counts:
        raise malformed(
            f"lists {_pnpm_counts(listed) or 'no'} advisories but its metadata counts "
            f"{_pnpm_counts(counts) or 'none'}: every advisory pnpm counts must reach the gate"
        )
    return findings


def parse_gitleaks(path: Path) -> list[Finding]:
    """`gitleaks detect --report-format json --redact` output -> Findings.

    `--redact` means the secret value itself is never present in the
    report (SR-146); we only ever surface rule id + location, never a
    secret value, in any message this module produces.
    """
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecurityGateError(
            "CI-SEC-005", f"gitleaks: unreadable/invalid {path}: {exc}"
        ) from exc

    findings: list[Finding] = []
    for item in doc if isinstance(doc, list) else []:
        rule = item.get("RuleID", "unknown-rule")
        file_ = item.get("File", "")
        line = item.get("StartLine", "")
        findings.append(
            Finding(
                tool="gitleaks",
                finding_id=f"{rule}:{file_}:{line}",
                severity="CRITICAL",
                detail=f"redacted secret match ({rule}) at {file_}:{line}",
            )
        )
    return findings


def parse_license_report(path: Path) -> list[LicenseFinding]:
    """Normalised license report: a JSON array of {package, version, license}.

    Produced by `tools/ci/collect_licenses.py` (wraps `pip-licenses` +
    `license-checker` output into one shape) before this module evaluates it.
    """
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecurityGateError(
            "CI-SEC-005", f"license-scan: unreadable/invalid {path}: {exc}"
        ) from exc

    if not isinstance(doc, list):
        raise SecurityGateError("CI-SEC-005", f"license-scan: {path} must be a JSON array")

    return [
        LicenseFinding(
            package=entry["package"],
            version=entry.get("version", ""),
            license=entry["license"],
        )
        for entry in doc
    ]


_PARSERS: dict[str, Any] = {
    "codeql": lambda p: parse_sarif(p, "codeql"),
    "semgrep": lambda p: parse_sarif(p, "semgrep"),
    "bandit": lambda p: parse_sarif(p, "bandit"),
    "trivy": lambda p: parse_sarif(p, "trivy"),
    "pip-audit": parse_pip_audit,
    "npm-audit": parse_npm_audit,
    "gitleaks": parse_gitleaks,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tool", required=True, choices=sorted(_PARSERS) + ["license-scan", "semgrep-auth"]
    )
    parser.add_argument(
        "--report",
        required=True,
        type=Path,
        help="tool's native report file; for semgrep-auth, the auth pack scan's --json-output",
    )
    parser.add_argument(
        "--accepted-risks",
        type=Path,
        default=Path("security/accepted-risks.yaml"),
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=Path("tools/ci/licenses-allowlist.json"),
        help="only used when --tool license-scan",
    )
    parser.add_argument(
        "--run-date",
        default=None,
        help="ISO date override for tests; default: today (UTC)",
    )
    parser.add_argument(
        "--semgrep-json",
        type=Path,
        default=None,
        help="required with --tool semgrep: its --json-output report, the one that says which "
        "targets a rule did not analyse (#3549)",
    )
    args = parser.parse_args(argv)

    run_date = (
        datetime.strptime(args.run_date, "%Y-%m-%d").replace(tzinfo=UTC).date()
        if args.run_date
        else datetime.now(UTC).date()
    )

    notes: list[str] = []
    lost: SecurityGateError | None = None  # a Semgrep scan's gap, reported after its findings
    try:
        risks = load_accepted_risks(args.accepted_risks)
        if args.tool == "license-scan":
            deps = parse_license_report(args.report)
            allowlist = load_license_allowlist(args.allowlist)
            result = evaluate_licenses(deps, allowlist, risks, run_date=run_date)
        elif args.tool == "semgrep-auth":
            # The auth pack's scan (`--error`) fails on any finding itself; this judges what it
            # did not analyse, every rule counted as the repo's own (#3549).
            notes = check_semgrep_coverage(args.report, _every_rule)
            result = evaluate_findings([], risks, run_date=run_date)
        else:
            if args.tool == "semgrep":
                findings = parse_sarif(args.report, "semgrep", today=run_date)
                if args.semgrep_json is None:
                    raise SecurityGateError(
                        "CI-SEC-005",
                        "semgrep: no --semgrep-json report, so the files it did not parse are "
                        "unknown",
                    )
                try:
                    notes = check_semgrep_coverage(args.semgrep_json)
                except SecurityGateError as exc:
                    lost = exc  # the findings still print, so one run shows both
            else:
                findings = _PARSERS[args.tool](args.report)
            result = evaluate_findings(findings, risks, run_date=run_date)
    except SecurityGateError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1

    for note in notes:
        print(note)
    for msg in result.messages:
        print(msg, file=sys.stderr if result.blocked else sys.stdout)

    if result.blocked:
        print(f"security_gate[{args.tool}]: BLOCKED ({result.code})", file=sys.stderr)
    if lost is not None:
        print(f"{lost.code}: {lost.message}", file=sys.stderr)
    if result.blocked or lost is not None:
        return 1

    print(f"security_gate[{args.tool}]: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
