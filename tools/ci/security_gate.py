#!/usr/bin/env python3
"""E03-T07: security lane severity normalisation and gate policy.

Every scanner in `.github/workflows/_job-security.yml` (CodeQL, Semgrep,
Bandit, pip-audit, npm audit, gitleaks, license-scan, Trivy) reduces its
native output to a single `Finding` shape here, so "what blocks" is defined
exactly once (technical notes, E03-T07 ticket body) instead of per-tool.

Error codes (ticket "Technical notes / design"):
    CI-SEC-001  blocking finding (severity meets/exceeds the tool's policy
                and no unexpired accepted-risk entry covers it)
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
import sys
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


def _sarif_runs(runs: object, path: Path, tool: str) -> list[dict[str, Any]]:
    """Return the document's runs once each one names its `tool.driver` (#3337).

    Every scanner that reaches this gate (CodeQL, Semgrep, Bandit, Trivy) writes
    one run per scan, clean or not, and SARIF requires `tool.driver.name`. A
    document with no run records no scan, and a run with no driver is malformed:
    both are CI-SEC-005, never a clean scan or findings without a severity.
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
        if not isinstance(name, str) or not name:
            raise malformed(
                f"run {i} has no tool.driver with a name (a malformed run, "
                "not findings without a severity)"
            )
    return runs


def parse_sarif(
    path: Path,
    tool: str,
    *,
    source_root: Path | None = None,
    today: date | None = None,
) -> list[Finding]:
    """Parse a SARIF 2.1.0 file into normalised findings.

    Used for CodeQL, Semgrep and Trivy (all three can emit SARIF). Severity
    is read from `security-severity` (CVSS-like float, mapped to buckets)
    when the result *or its rule descriptor* provides it, else falls back to
    the SARIF `level` (error/warning/note) of the result, then of the rule's
    `defaultConfiguration`.

    CodeQL in particular carries both `security-severity` and the level only
    on the rule (`tool.driver.rules[]` / `tool.extensions[].rules[]`) and
    omits `level` on results that match the default — reading the result
    alone silently downgraded every CodeQL High to MEDIUM (never blocking),
    which is how PRs with a GitHub-reported High CodeQL alert passed this
    gate (CI-SEC-001 regression, fixed under ci/e03-codeql-job-fix).

    A document without runs, or with a run that names no `tool.driver`, is a
    scanner-infrastructure failure (CI-SEC-005, `_sarif_runs`), for every tool.
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
    for run in _sarif_runs(doc["runs"], path, tool):
        by_id, components = _sarif_rule_index(run)
        for result in run.get("results", []):
            rule_id = result.get("ruleId", "unknown-rule")
            rule = _sarif_result_rule(result, by_id, components)
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


def _npm_advisory_id(via: dict[str, Any], pkg_name: str) -> str:
    """Prefer the GHSA id (last segment of the advisory `url`) over npm's
    numeric `source`, so accepted-risks entries can use stable GHSA ids."""
    url = str(via.get("url", ""))
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    if tail.startswith("GHSA-"):
        return tail
    return str(via.get("source", pkg_name))


def parse_npm_audit(path: Path) -> list[Finding]:
    """`npm audit --json` (v8+/v10 schema: `vulnerabilities` map) -> Findings."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecurityGateError(
            "CI-SEC-005", f"npm-audit: unreadable/invalid {path}: {exc}"
        ) from exc

    findings: list[Finding] = []
    vulns = doc.get("vulnerabilities", {})
    for pkg_name, info in vulns.items():
        severity = str(info.get("severity", "high")).upper()
        if severity not in _SEVERITY_ORDER:
            severity = "HIGH"
        via = info.get("via", [])
        ids = [_npm_advisory_id(v, pkg_name) for v in via if isinstance(v, dict)] or [pkg_name]
        for finding_id in ids:
            findings.append(
                Finding(
                    tool="npm-audit",
                    finding_id=str(finding_id),
                    severity=severity,
                    package=pkg_name,
                    detail=f"npm audit advisory for {pkg_name}",
                )
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
    parser.add_argument("--tool", required=True, choices=sorted(_PARSERS) + ["license-scan"])
    parser.add_argument("--report", required=True, type=Path, help="tool's native report file")
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
    args = parser.parse_args(argv)

    run_date = (
        datetime.strptime(args.run_date, "%Y-%m-%d").replace(tzinfo=UTC).date()
        if args.run_date
        else datetime.now(UTC).date()
    )

    try:
        risks = load_accepted_risks(args.accepted_risks)
        if args.tool == "license-scan":
            deps = parse_license_report(args.report)
            allowlist = load_license_allowlist(args.allowlist)
            result = evaluate_licenses(deps, allowlist, risks, run_date=run_date)
        else:
            if args.tool == "semgrep":
                findings = parse_sarif(args.report, "semgrep", today=run_date)
            else:
                findings = _PARSERS[args.tool](args.report)
            result = evaluate_findings(findings, risks, run_date=run_date)
    except SecurityGateError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1

    for msg in result.messages:
        print(msg, file=sys.stderr if result.blocked else sys.stdout)

    if result.blocked:
        print(f"security_gate[{args.tool}]: BLOCKED ({result.code})", file=sys.stderr)
        return 1

    print(f"security_gate[{args.tool}]: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
