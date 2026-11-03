#!/usr/bin/env python3
"""E47-T05 (#1360): generate the WCAG 2.2 conformance report and check its exception register.

The report `docs/plan/a11y/47-conformance-report.md` is the join of three machine-readable inputs:
the E47-T01 register (`findings.json`), the E47-D02 register (`47-audit-register.json`) and the
limitations register (`47-limitations.json`). It is generated here, never edited. The honest-claims
rule and the evidence-capture contract are E47-D13 spec §3-§4; the design audit
`docs/design/_tools/e47_d13_conformance_audit.py` imports this module (BQ-01) and feeds it its
blob-pinned inputs, so both tools share one model.

Modes (BQ-02):
  --fill      write the report (fails generation on a schema, exception or content problem)
  --check     per PR: schema, exception completeness, content check, and staleness of the report
  --release   RC / GA: everything in --check, plus an open Level A finding (named), an expired
              accepted-risk acceptance (flagged for re-decision) and an unowned limitation

Staleness (BQ-03): the report names the git blob sha of each input; whoever changes a register
regenerates the report in the same PR. Blob shas are computed here, so no git history is needed.
Exception register (BQ-04): the `accepted-risk` rows of the limitations register. Each needs a
criterion, the affected surfaces, a compensating control, the Owner acceptance (name and decision),
an expiry and a remediation ticket; a Level A criterion is never an exception.
Sibling evidence (BQ-09): `docs/plan/a11y/47-evidence.json` (optional) holds resolvable records; an
unresolved reference reads "not yet produced". Content (BQ-10): accessibility gaps only; no hosts,
ids or key material.

Usage (repo root):
  python3 tools/a11y/conformance.py --fill
  python3 tools/a11y/conformance.py --check
  python3 tools/a11y/conformance.py --release [--today YYYY-MM-DD]
Exit 0 = clean; 1 = at least one FAIL line. Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_REL = "tools/a11y/conformance.py"
REPORT_REL = "docs/plan/a11y/47-conformance-report.md"
LIMITS_REL = "docs/plan/a11y/47-limitations.json"
FINDINGS_REL = "docs/plan/a11y/findings.json"
REGISTER_REL = "docs/plan/a11y/47-audit-register.json"
EVIDENCE_REL = "docs/plan/a11y/47-evidence.json"
PLAN14_REL = "docs/plan/14-screens-catalogue.md"

# ---------------------------------------------------------------------------- the criteria

SC: dict[str, tuple[str, str]] = {
    "1.1.1": ("A", "Non-text Content"),
    "1.2.1": ("A", "Audio-only and Video-only (Prerecorded)"),
    "1.2.2": ("A", "Captions (Prerecorded)"),
    "1.2.3": ("A", "Audio Description or Media Alternative (Prerecorded)"),
    "1.2.4": ("AA", "Captions (Live)"),
    "1.2.5": ("AA", "Audio Description (Prerecorded)"),
    "1.3.1": ("A", "Info and Relationships"),
    "1.3.2": ("A", "Meaningful Sequence"),
    "1.3.3": ("A", "Sensory Characteristics"),
    "1.3.4": ("AA", "Orientation"),
    "1.3.5": ("AA", "Identify Input Purpose"),
    "1.4.1": ("A", "Use of Color"),
    "1.4.2": ("A", "Audio Control"),
    "1.4.3": ("AA", "Contrast (Minimum)"),
    "1.4.4": ("AA", "Resize Text"),
    "1.4.5": ("AA", "Images of Text"),
    "1.4.10": ("AA", "Reflow"),
    "1.4.11": ("AA", "Non-text Contrast"),
    "1.4.12": ("AA", "Text Spacing"),
    "1.4.13": ("AA", "Content on Hover or Focus"),
    "2.1.1": ("A", "Keyboard"),
    "2.1.2": ("A", "No Keyboard Trap"),
    "2.1.4": ("A", "Character Key Shortcuts"),
    "2.2.1": ("A", "Timing Adjustable"),
    "2.2.2": ("A", "Pause, Stop, Hide"),
    "2.3.1": ("A", "Three Flashes or Below Threshold"),
    "2.4.1": ("A", "Bypass Blocks"),
    "2.4.2": ("A", "Page Titled"),
    "2.4.3": ("A", "Focus Order"),
    "2.4.4": ("A", "Link Purpose (In Context)"),
    "2.4.5": ("AA", "Multiple Ways"),
    "2.4.6": ("AA", "Headings and Labels"),
    "2.4.7": ("AA", "Focus Visible"),
    "2.4.11": ("AA", "Focus Not Obscured (Minimum)"),
    "2.5.1": ("A", "Pointer Gestures"),
    "2.5.2": ("A", "Pointer Cancellation"),
    "2.5.3": ("A", "Label in Name"),
    "2.5.4": ("A", "Motion Actuation"),
    "2.5.7": ("AA", "Dragging Movements"),
    "2.5.8": ("AA", "Target Size (Minimum)"),
    "3.1.1": ("A", "Language of Page"),
    "3.1.2": ("AA", "Language of Parts"),
    "3.2.1": ("A", "On Focus"),
    "3.2.2": ("A", "On Input"),
    "3.2.3": ("AA", "Consistent Navigation"),
    "3.2.4": ("AA", "Consistent Identification"),
    "3.2.6": ("A", "Consistent Help"),
    "3.3.1": ("A", "Error Identification"),
    "3.3.2": ("A", "Labels or Instructions"),
    "3.3.3": ("AA", "Error Suggestion"),
    "3.3.4": ("AA", "Error Prevention (Legal, Financial, Data)"),
    "3.3.7": ("A", "Redundant Entry"),
    "3.3.8": ("AA", "Accessible Authentication (Minimum)"),
    "4.1.2": ("A", "Name, Role, Value"),
    "4.1.3": ("AA", "Status Messages"),
}
REMOVED = "4.1.1"
LEVEL_WORDS = ("Supports", "Partially Supports", "Does Not Support", "Not Applicable")

# The evidence-capture contract (E47-D13 spec §4): class -> (criteria, required artefact kinds,
# alternative key). Kinds read from the T01 register per screen: automated, keyboard, deep, wcag22.
# The rest are run records the stories produce (pass = a T04 / Q02 pass record, d12 = a D12 verdict,
# q05 = a Q05 appendix row, contrast = an A11Y-C00x run, t03 = a T03 matrix row, flash = an
# A11Y-G005 run); they resolve through `47-evidence.json` or read "not yet produced" (BQ-09).
CONTRACT: dict[str, tuple[tuple[str, ...], tuple[str, ...], str]] = {
    "K-AXE": (
        ("1.1.1", "1.3.1", "1.3.5", "2.4.1", "2.4.2", "2.4.4", "3.1.1", "3.1.2", "3.3.2", "4.1.2"),
        ("automated", "pass"),
        "report",
    ),
    "K-CONTRAST": (("1.4.3", "1.4.11"), ("automated", "contrast", "t03"), "theme"),
    "K-KEY": (("2.1.1", "2.1.2", "2.1.4", "2.4.3", "2.4.7"), ("keyboard", "pass"), "keys"),
    "K-W22": (("2.4.11", "2.5.7", "2.5.8", "3.2.6", "3.3.7", "3.3.8"), ("wcag22", "d12"), "keys"),
    "K-FLASH": (("2.3.1",), ("flash", "q05"), "motion"),
    "K-MOTION": (("2.2.2",), ("q05", "pass"), "motion"),
    "K-MEDIA": (("1.2.1", "1.2.2", "1.2.3", "1.2.4", "1.2.5"), ("pass",), "report"),
    "K-ZOOM": (("1.3.4", "1.4.4", "1.4.10", "1.4.12"), ("deep", "pass"), "scale"),
    "K-SR": (("1.3.2", "2.2.1", "3.2.1", "3.2.2", "3.3.1", "4.1.3"), ("pass", "d12"), "verbosity"),
    "K-MANUAL": (
        (
            "1.3.3",
            "1.4.1",
            "1.4.2",
            "1.4.5",
            "1.4.13",
            "2.4.5",
            "2.4.6",
            "2.5.1",
            "2.5.2",
            "2.5.3",
            "2.5.4",
            "3.2.3",
            "3.2.4",
            "3.3.3",
            "3.3.4",
        ),
        ("pass",),
        "report",
    ),
}
REGISTER_KINDS = ("automated", "keyboard", "deep", "wcag22")
ALT = {
    "report": "report the problem (statement §9)",
    "theme": "high-contrast theme `Ctrl+Shift+H` (SCR-116)",
    "keys": "keyboard equivalents (SCR-013)",
    "motion": "reduced motion `Ctrl+Shift+M` (SCR-117)",
    "scale": "in-app text scale `Ctrl+=` (SCR-116)",
    "verbosity": "announcement verbosity (SCR-117)",
    "table": "`Alt+T` table view",
}
CANVAS = ("1.1.1", "1.3.1", "1.4.11", "2.1.1", "4.1.2", "4.1.3")
CANVAS_REMARK = (
    "canvas: met only through the four layers of `05` §6.1–§6.4 (DOM mirror, live regions, table"
    " alternative, canvas semantics fallback), never by the canvas itself"
)
NA_REASONS = {
    "K-MEDIA": (
        "no prerecorded or live audio or video content: `14` names none",
        re.compile(r"\b(?:video|audio|podcast|transcript|captions)\b", re.IGNORECASE),
    )
}
TRADING_BANDS = range(50, 80)  # SCR-050..079: order flow and trading (`14` §0.2)

# ---------------------------------------------------------------------------- content checks

URL_RE = re.compile(
    r"https?://|www\.|/home/|localhost|\.local\b|\b[a-z0-9-]+\.(?:com|io|org|net)\b"
)
KEYLIKE_RE = re.compile(r"[A-Za-z0-9+/=_-]{24,}")
IMAGE_RE = re.compile(r"!\[|<img|\.png\b|\.svg\b", re.IGNORECASE)
IDLIKE_RE = re.compile(r"\b\d{6,}\b|\bUID\b")
CONTENT_CHECKS = (
    (URL_RE, "a host"),
    (KEYLIKE_RE, "a key-like string"),
    (IMAGE_RE, "an image"),
    (IDLIKE_RE, "an id"),
)
TICKET_RE = re.compile(r"^E\d\d-[A-Z]+\d\d #\d+$")
DATE_RE = re.compile(r"\d{4}-\d\d-\d\d")

Finding = tuple[str, str]  # gate, message


# ---------------------------------------------------------------------------- inputs


def blob_sha(data: bytes) -> str:
    """The git blob sha of a file's bytes (what `git hash-object` prints)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def dicts(value: object) -> list[dict[str, object]]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def text_of(value: object) -> str:
    return value if isinstance(value, str) else ""


@dataclass(frozen=True)
class Inputs:
    """The three registers and the one plan text the model reads (live, or blob-pinned)."""

    findings: dict[str, object]
    register: dict[str, object]
    plan14: str
    findings_blob: str = ""
    register_blob: str = ""
    evidence: tuple[dict[str, object], ...] = field(default_factory=tuple)

    def screens(self) -> list[dict[str, object]]:
        return dicts(self.findings.get("screens"))

    def t01_findings(self) -> list[dict[str, object]]:
        return dicts(self.findings.get("findings"))

    def patterns(self) -> list[dict[str, object]]:
        return dicts(self.findings.get("patterns"))

    def audited_sha(self) -> str:
        return text_of(self.findings.get("auditedSha"))[:9]

    def live_screens(self) -> list[dict[str, object]]:
        return [s for s in self.screens() if not text_of(s.get("coverage")).startswith("reserved")]

    def open_t01(self, sc: str) -> list[str]:
        return sorted(
            text_of(f.get("id"))
            for f in self.t01_findings()
            if f.get("wcagSc") == sc and f.get("status") != "fixed"
        )

    def d02_rows(self) -> list[dict[str, object]]:
        return dicts(self.register.get("findings")) + dicts(self.register.get("unattributed"))

    def d02_open(self, sc: str) -> list[dict[str, object]]:
        out = []
        for f in self.d02_rows():
            scs = f.get("sc")
            if (
                isinstance(scs, list)
                and sc in scs
                and text_of(f.get("status")).startswith("open")
                and not text_of(f.get("id")).startswith("A11Y-F-")
            ):
                out.append(f)
        return out

    def trading_blocker(self, sc: str) -> bool:
        for f in self.d02_open(sc):
            screens = f.get("screens")
            nums = (
                [int(s[4:]) for s in screens if isinstance(s, str) and s[4:].isdigit()]
                if isinstance(screens, list)
                else []
            )
            if f.get("severity") == "blocker" and any(n in TRADING_BANDS for n in nums):
                return True
        return False

    def resolved(self, kind: str, sc: str) -> str:
        """The sibling evidence reference for a (kind, criterion), or '' (not produced)."""
        for rec in self.evidence:
            scs = rec.get("sc")
            if rec.get("kind") == kind and isinstance(scs, list) and sc in scs:
                return text_of(rec.get("ref"))
        return ""


def _json(raw: bytes) -> dict[str, object]:
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def live_inputs(root: Path = ROOT) -> Inputs:
    """The working-tree inputs (BQ-03: the report is stale when any of them changed)."""

    def rd(rel: str) -> bytes:
        p = root / rel
        return p.read_bytes() if p.is_file() else b""

    f, r, e = rd(FINDINGS_REL), rd(REGISTER_REL), rd(EVIDENCE_REL)
    return Inputs(
        findings=_json(f),
        register=_json(r),
        plan14=rd(PLAN14_REL).decode("utf-8", "replace"),
        findings_blob=blob_sha(f),
        register_blob=blob_sha(r),
        evidence=tuple(dicts(_json(e).get("records"))) if e else (),
    )


# ---------------------------------------------------------------------------- the model


def cell_verdict(screen: dict[str, object], kind: str, sc: str) -> str:
    """The recorded verdict of a register kind on a screen: '' when none was recorded."""
    if kind == "wcag22":
        cells_ = screen.get("wcag22")
        cell = cells_.get(sc) if isinstance(cells_, dict) else None
    else:
        ev = screen.get("evidence")
        cell = ev.get(kind) if isinstance(ev, dict) else None
    v = text_of(cell.get("verdict")) if isinstance(cell, dict) else ""
    if v.startswith(("pass", "fail")) or (kind == "wcag22" and v.startswith("n/a (not applicable")):
        return v
    return ""


def class_of(sc: str) -> str:
    for k, (scs, _, _) in CONTRACT.items():
        if sc in scs:
            return k
    return ""


@dataclass(frozen=True)
class Row:
    sc: str
    level: str
    name: str
    conformance: str
    remarks: str
    evidence: str
    alternative: str


def overrides(limits: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for o in dicts(limits_data(limits).get("overrides")):
        out[text_of(o.get("sc"))] = text_of(o.get("to"))
    return out


def determine(sc: str, limits: str, inp: Inputs) -> tuple[Row, bool]:
    """The row by the honest-claims rule (spec §3); bool = a reviewer override tried to raise it."""
    level, name = SC[sc]
    k = class_of(sc)
    _, kinds, alt_key = CONTRACT[k]
    reg_kinds = [x for x in kinds if x in REGISTER_KINDS]
    screens = inp.live_screens()
    sha = inp.audited_sha()
    remarks: list[str] = []
    evidence: list[str] = []
    if k in NA_REASONS:
        reason, probe = NA_REASONS[k]
        if not probe.search(inp.plan14):
            row = Row(sc, level, name, "Not Applicable", f"not applicable: {reason}", "n/a", "")
            return row, False
    produced = {x: sum(1 for s in screens if cell_verdict(s, x, sc)) for x in reg_kinds}
    for x in reg_kinds:
        if produced[x]:
            verdicts = [cell_verdict(s, x, sc) for s in screens]
            n_pass = sum(1 for v in verdicts if v.startswith("pass"))
            n_fail = sum(1 for v in verdicts if v.startswith("fail"))
            n_na = produced[x] - n_pass - n_fail
            tally = f"{n_pass} pass, {n_fail} fail" + (f", {n_na} n/a" if n_na else "")
            evidence.append(f"t01:{x}@{sha} ({produced[x]} screens: {tally})")
    missing_kinds = []
    for x in kinds:
        if x in REGISTER_KINDS:
            continue
        ref = inp.resolved(x, sc)
        if ref:
            evidence.append(ref)
        else:
            missing_kinds.append(x)
    passing = sum(
        1
        for s in screens
        if reg_kinds and all(cell_verdict(s, x, sc).startswith(("pass", "n/a")) for x in reg_kinds)
    )
    gap = len(screens) - passing
    opens = inp.open_t01(sc)
    d02n = len(inp.d02_open(sc))
    if not evidence:
        conf = "Does Not Support"
        remarks.append("evidence not produced on any screen")
    else:
        full = gap == 0 and not missing_kinds
        conf = "Supports" if full and not opens and not d02n else "Partially Supports"
        if gap:
            remarks.append(f"evidence not produced for {gap} of {len(screens)} screens")
    if inp.trading_blocker(sc):
        conf = "Does Not Support"
        remarks.append("an open blocker on a trading path")
    if missing_kinds:
        remarks.append("not yet produced: " + ", ".join(missing_kinds))
    if opens:
        remarks.append("open findings: " + ", ".join(opens))
    if d02n:
        remarks.append(f"open design findings: {d02n} (E47-D02)")
    if sc in CANVAS:
        remarks.append(CANVAS_REMARK)
    raised = False
    want = overrides(limits).get(sc)
    rank = {"Supports": 3, "Partially Supports": 2, "Does Not Support": 1}
    if want:
        if rank.get(want, 9) > rank[conf]:
            raised = True
        elif want != conf:
            conf = want
            remarks.append("lowered by a reviewer")
    alt = ALT["table"] if sc in CANVAS and sc != "4.1.3" else ALT[alt_key]
    row = Row(
        sc,
        level,
        name,
        conf,
        "; ".join(remarks) or "-",
        "; ".join(evidence) or "none produced",
        alt if conf in ("Partially Supports", "Does Not Support") else "",
    )
    return row, raised


def sc_key(sc: str) -> tuple[int, ...]:
    return tuple(int(x) for x in sc.split("."))


def model(limits: str, inp: Inputs) -> list[Row]:
    return [determine(sc, limits, inp)[0] for sc in sorted(SC, key=sc_key)]


# ---------------------------------------------------------------------------- limitations


def limits_data(limits: str) -> dict[str, object]:
    return _json(limits.encode("utf-8"))


def limit_rows(limits: str) -> list[dict[str, object]]:
    return dicts(limits_data(limits).get("limitations"))


def disposition_ok(row: dict[str, object]) -> bool:
    d = row.get("disposition")
    if not isinstance(d, dict):
        return False
    kind = d.get("kind")
    if kind == "fix-ticket":
        t = text_of(d.get("ticket"))
        return bool(TICKET_RE.match(t)) and not t.startswith("E47-T01")
    if kind == "accepted-risk":
        return bool(text_of(d.get("owner")) and DATE_RE.fullmatch(text_of(d.get("expiry"))))
    return False


def unowned(limits: str) -> list[str]:
    return [text_of(r.get("id")) for r in limit_rows(limits) if not disposition_ok(r)]


def limits_problems(limits: str, inp: Inputs) -> list[str]:
    """The limitations register's join with the T01 register (E47-D13 G-LIMIT)."""
    bad: list[str] = []
    rows = limit_rows(limits)
    if not rows:
        return ["the register has no rows or is not JSON"]
    pat_of = {text_of(p.get("id")): p for p in inp.patterns()}
    covered: dict[str, int] = {}
    t01 = inp.t01_findings()
    level_of = {text_of(f.get("id")): text_of(f.get("level")) for f in t01}
    sc_of = {text_of(f.get("id")): text_of(f.get("wcagSc")) for f in t01}
    open_ids = {text_of(f.get("id")) for f in t01 if f.get("status") != "fixed"}
    for r in rows:
        rid = text_of(r.get("id"))
        if not re.fullmatch(r"A11Y-F-\d{4}|A11Y-P-\d\d|MX-\d\d", rid):
            bad.append(f"{rid!r} is not an A11Y-F, A11Y-P or MX id")
        members: list[str] = []
        if rid.startswith("A11Y-P-"):
            fs = pat_of.get(rid, {}).get("findings")
            members = [x for x in fs if isinstance(x, str)] if isinstance(fs, list) else []
        elif rid.startswith("A11Y-F-"):
            members = [rid]
        members = [m for m in members if m in open_ids]
        cov = r.get("covers")
        if rid.startswith("A11Y-") and cov != members:
            bad.append(f"{rid} covers {cov}, the register says {members}")
        for m in members:
            covered[m] = covered.get(m, 0) + 1
        scs = r.get("sc")
        want_scs = sorted({sc_of[m] for m in members}, key=sc_key)
        if rid.startswith("A11Y-") and scs != want_scs:
            bad.append(f"{rid}'s criteria {scs} are not {want_scs}")
        lvl = "A" if any(level_of.get(m) == "A" for m in members) else "AA"
        if rid.startswith("A11Y-") and r.get("level") != lvl:
            bad.append(f"{rid}'s level is not {lvl}")
        d = r.get("disposition")
        dd = d if isinstance(d, dict) else {}
        if dd.get("kind") == "accepted-risk" and r.get("level") == "A":
            bad.append(f"{rid} accepts a Level A risk")
        if dd.get("kind") not in ("fix-ticket", "accepted-risk", "none"):
            bad.append(f"{rid}'s disposition kind is not one of the three")
        if dd.get("kind") == "fix-ticket" and text_of(dd.get("ticket")).startswith("E47-T01"):
            bad.append(f"{rid} names the audit as its fix ticket")
        closed = text_of(dd.get("closedTicket"))
        if closed and (dd.get("kind") != "none" or not TICKET_RE.match(closed)):
            bad.append(f"{rid}'s closed fix ticket is not a ticket on a 'none' disposition")
        for fld in ("plain", "impact", "workaround", "category", "disclosure"):
            if not text_of(r.get(fld)):
                bad.append(f"{rid} has no {fld}")
    for m in sorted(open_ids):
        if covered.get(m, 0) != 1:
            bad.append(f"{m} is covered {covered.get(m, 0)} times")
    return bad


# ---------------------------------------------------------------------------- the exception register


def disposition_of(row: dict[str, object]) -> dict[str, object]:
    d = row.get("disposition")
    return d if isinstance(d, dict) else {}


def exception_rows(limits: str) -> list[dict[str, object]]:
    return [r for r in limit_rows(limits) if disposition_of(r).get("kind") == "accepted-risk"]


def exception_problems(limits: str) -> list[str]:
    """BQ-04: an accepted-risk row is a complete exception, or it is not an exception."""
    bad: list[str] = []
    for r in exception_rows(limits):
        rid = text_of(r.get("id"))
        dd = disposition_of(r)
        scs = r.get("sc")
        sc_list = [x for x in scs if isinstance(x, str)] if isinstance(scs, list) else []
        if not sc_list:
            bad.append(f"{rid}: exception has no success criterion")
        for sc in sc_list:
            if sc not in SC:
                bad.append(f"{rid}: {sc} is not a WCAG 2.2 A or AA criterion")
            elif SC[sc][0] == "A":
                bad.append(f"{rid}: Level A criterion {sc} can never be an accepted risk")
        if r.get("level") == "A":
            bad.append(f"{rid}: a Level A row can never be an accepted risk")
        surf = r.get("surfaces")
        if not (
            isinstance(surf, list)
            and surf
            and all(re.fullmatch(r"SCR-\d{3}", str(s)) for s in surf)
        ):
            bad.append(f"{rid}: exception has no affected surfaces (SCR ids)")
        if not text_of(dd.get("compensatingControl")):
            bad.append(f"{rid}: exception has no compensating control")
        if not text_of(dd.get("owner")):
            bad.append(f"{rid}: exception has no named Owner acceptance")
        if not text_of(dd.get("decision")):
            bad.append(f"{rid}: exception has no Owner decision")
        exp = text_of(dd.get("expiry"))
        if not _valid_date(exp):
            bad.append(f"{rid}: exception has no valid expiry date")
        rem = text_of(dd.get("remediationTicket"))
        if not TICKET_RE.match(rem) or rem.startswith("E47-T01"):
            bad.append(f"{rid}: exception has no remediation ticket")
    return bad


def _today() -> dt.date:
    return dt.datetime.now(tz=dt.UTC).date()


def _valid_date(s: str) -> bool:
    if not DATE_RE.fullmatch(s):
        return False
    try:
        dt.date.fromisoformat(s)
    except ValueError:
        return False
    return True


def expired_exceptions(limits: str, today: dt.date) -> list[str]:
    out = []
    for r in exception_rows(limits):
        exp = text_of(disposition_of(r).get("expiry"))
        if _valid_date(exp) and dt.date.fromisoformat(exp) < today:
            out.append(f"{text_of(r.get('id'))} expired {exp}: re-decide, do not extend silently")
    return out


def is_level_a(level: object, scs: object = None) -> bool:
    """Level A when any level token is A ('AA / A' too), or any criterion is Level A in `SC`."""
    if "A" in re.findall(r"[A-Za-z]+", text_of(level)):
        return True
    return isinstance(scs, list) and any(SC.get(x, ("", ""))[0] == "A" for x in scs)


def open_level_a(inp: Inputs) -> list[str]:
    """Every open Level A finding, named (E47-T01 register, then E47-D02 rows not in it)."""
    out = [
        f"{text_of(f.get('id'))} (SC {text_of(f.get('wcagSc'))}): {text_of(f.get('title'))[:80]}"
        for f in inp.t01_findings()
        if is_level_a(f.get("level"), [f.get("wcagSc")]) and f.get("status") != "fixed"
    ]
    for f in inp.d02_rows():
        if (
            is_level_a(f.get("level"), f.get("sc"))
            and text_of(f.get("status")).startswith("open")
            and not text_of(f.get("id")).startswith("A11Y-F-")
        ):
            out.append(f"{text_of(f.get('id'))}: {text_of(f.get('title'))[:80]}")
    return sorted(out)


def _leaves(value: object, path: str) -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [(path, str(value))]
    if isinstance(value, dict):
        return [x for k, v in value.items() for x in _leaves(v, f"{path}.{k}" if path else str(k))]
    if isinstance(value, list):
        return [x for i, v in enumerate(value) for x in _leaves(v, f"{path}[{i}]")]
    return []


def content_problems(limits: str, report: str = "") -> list[str]:
    """BQ-10 (D13 §6.5): accessibility gaps only; no host, id, image or key material.

    Every string leaf of the limitations register is scanned, so no rendered field escapes.
    """
    out = []
    for where, s in _leaves(limits_data(limits), ""):
        for rx, what in CONTENT_CHECKS:
            if rx.search(s):
                out.append(f"{where}: {what}")
    for ln_no, ln in enumerate(report.split("\n"), 1):
        for rx, what in ((URL_RE, "a host"), (IMAGE_RE, "an image")):
            if rx.search(ln):
                out.append(f"report line {ln_no}: {what}")
    return out


def field_problems(limits: str) -> list[str]:
    """Rendered fields that must be well formed (E47-T05; the D13 gates cover them separately).

    Messages carry the JSON path only, never the rejected value (it may be key-like).
    """
    bad = []
    for i, r in enumerate(limit_rows(limits)):
        at = f"limitations[{i}]"
        dd = disposition_of(r)
        if dd.get("kind") == "fix-ticket" and not TICKET_RE.match(text_of(dd.get("ticket"))):
            bad.append(f"{at}.disposition.ticket is not 'Exx-Yzz #n'")
        if r.get("disclosure") not in ("statement", "internal"):
            bad.append(f"{at}.disclosure must be statement or internal")
        if not text_of(r.get("category")):
            bad.append(f"{at}.category is empty")
    return bad


# ---------------------------------------------------------------------------- the report


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    """A Markdown table padded the way Prettier pads it (register.py's rendering)."""
    body_ = [[x.replace("|", "\\|").strip() for x in r] for r in [header, *rows]]
    widths = [max(3, *(len(r[i]) for r in body_)) for i in range(len(header))]
    out = ["| " + " | ".join(x.ljust(w) for x, w in zip(body_[0], widths, strict=True)) + " |"]
    out.append("| " + " | ".join("-" * w for w in widths) + " |")
    for r in body_[1:]:
        out.append("| " + " | ".join(x.ljust(w) for x, w in zip(r, widths, strict=True)) + " |")
    return out


def counts(rows: list[Row]) -> dict[str, int]:
    return {w: sum(1 for r in rows if r.conformance == w) for w in LEVEL_WORDS}


def status_words(rows: list[Row]) -> str:
    full = all(r.conformance in ("Supports", "Not Applicable") for r in rows)
    return "Fully conforms" if full else "Partially conforms"


def _join(value: object) -> str:
    return ", ".join(x for x in value if isinstance(x, str)) if isinstance(value, list) else ""


def exception_section(limits: str, inp: Inputs) -> list[str]:
    ex = exception_rows(limits)
    exps = sorted(text_of(disposition_of(r).get("expiry")) for r in ex)
    open_a = sum(
        1 for f in inp.t01_findings() if f.get("level") == "A" and f.get("status") != "fixed"
    )
    open_aa = sum(
        1 for f in inp.t01_findings() if f.get("level") == "AA" and f.get("status") != "fixed"
    )
    out = [
        "",
        "## Exception register",
        "",
        (
            f"The accepted-risk rows of `{LIMITS_REL}`: a complete exception or no exception. A"
            " Level A criterion is never an exception; an expiry that passes is re-decided at the"
            " next release check, never extended silently."
        ),
        "",
        f"- Open findings (E47-T01): Level A {open_a}, Level AA {open_aa}.",
        f"- Exceptions: {len(ex)}; nearest expiry: {exps[0] if exps else 'none'}.",
        "",
    ]
    if not ex:
        out.append("No accepted-risk exceptions are registered.")
        return out
    rows = []
    for r in ex:
        dd = disposition_of(r)
        rows.append(
            [
                text_of(r.get("id")),
                _join(r.get("sc")),
                text_of(r.get("level")),
                _join(r.get("surfaces")),
                text_of(dd.get("compensatingControl")),
                f"{text_of(dd.get('owner'))}: {text_of(dd.get('decision'))}",
                text_of(dd.get("expiry")),
                text_of(dd.get("remediationTicket")),
            ]
        )
    out += table(
        [
            "Id",
            "Criteria",
            "Level",
            "Surfaces",
            "Compensating control",
            "Owner acceptance",
            "Expiry",
            "Remediation ticket",
        ],
        rows,
    )
    return out


def render_report(
    limits: str,
    inp: Inputs,
    *,
    generator: str = TOOL_REL,
    ref: str = "",
    note: str | None = None,
    exceptions: bool = True,
) -> str:
    rows = model(limits, inp)
    c = counts(rows)
    lim = limit_rows(limits)
    blocked = unowned(limits)
    n_a = sum(1 for r in rows if r.level == "A")
    ref = ref or inp.audited_sha()
    note = (
        note
        if note is not None
        else f"Generator: `{TOOL_REL}` (E47-T05); the format is frozen by E47-D13 §3-§4."
    )
    out = [
        f"<!-- generated by {generator} --fill from the E47-T01 and E47-D02 registers; do not edit -->",
        "",
        "# Accessibility conformance report (WCAG 2.2 Level A and AA): dry run",
        "",
        (
            f"**Dry run at `{ref}`, not a conformance claim.** Generated from `{FINDINGS_REL}` (blob"
            f" `{inp.findings_blob[:9]}`) and `{REGISTER_REL}` (blob `{inp.register_blob[:9]}`) under"
            " the honest-claims rule and the evidence-capture contract of"
            f" `docs/design/E47/E47-D13.md` §3-§4. {note}"
        ),
        "",
        (
            "- Product: CandleViewer, the web app in its desktop shell. Target: WCAG 2.2 Level AA."
            " Shape: VPAT-shaped; nothing is filed."
        ),
        (
            f"- Criteria: {len(rows)} rows (Level A {n_a}, Level AA {len(rows) - n_a}). Supports"
            f" {c['Supports']}, Partially Supports {c['Partially Supports']}, Does Not Support"
            f" {c['Does Not Support']}, Not Applicable {c['Not Applicable']}."
        ),
        f"- Status in words: {status_words(rows)}.",
        (
            f"- Screens: {len(inp.live_screens())} non-reserved; register evidence audited at"
            f" `{inp.audited_sha()}`."
        ),
        (
            f"- Known limitations: {len(lim)} rows in `{LIMITS_REL}`; {len(blocked)} without a"
            " disposition, so sign-off is blocked"
            + (f" ({', '.join(blocked)})." if blocked else ".")
        ),
        "",
        "## Criteria",
        "",
    ]
    out += table(
        ["Criterion", "Level", "Conformance level", "Remarks", "Evidence", "Alternative"],
        [
            [f"{r.sc} {r.name}", r.level, r.conformance, r.remarks, r.evidence, r.alternative]
            for r in rows
        ],
    )
    out += [
        "",
        "## Not claimed",
        "",
        f"- {REMOVED} Parsing: removed from WCAG 2.2, so it is not a row.",
        (
            "- Level AAA, including the `05` §1 extras (non-text contrast 7:1 for buy and sell state,"
            " no timing limits): not claimed."
        ),
        "- Section 508 and EN 301 549: not claimed.",
        "",
        "## Known limitations",
        "",
    ]
    lrows: list[list[str]] = []
    for r in lim:
        d = r.get("disposition")
        dd = d if isinstance(d, dict) else {}
        kind = text_of(dd.get("kind")) or "none"
        closed = text_of(dd.get("closedTicket"))
        what = (
            text_of(dd.get("ticket"))
            or text_of(dd.get("owner"))
            or (f"fix ticket {closed} closed, finding open" if closed else "-")
        )
        ok = "yes" if disposition_ok(r) else "no: blocks sign-off"
        lrows.append(
            [
                text_of(r.get("id")),
                _join(r.get("covers")),
                _join(r.get("sc")),
                f"{kind}: {what}",
                ok,
                text_of(r.get("disclosure")),
            ]
        )
    out += table(["Id", "Covers", "Criteria", "Disposition", "Owned", "Disclosure"], lrows)
    if exceptions:
        out += exception_section(limits, inp)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------- staleness


def normalise(text: str) -> list[str]:
    """Lines modulo Markdown table padding and trailing space (Prettier-stable comparison)."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if line.startswith("|") and line.endswith("|"):
            cells = [x.strip() for x in line[1:-1].split(" | ")]
            cells = ["---" if x and set(x) <= {"-", ":"} else x for x in cells]
            line = "| " + " | ".join(cells) + " |"
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return out


def stale_reason(committed: str, want: str) -> str:
    """'' when the committed report equals the generated one; else what changed."""
    if normalise(committed) == normalise(want):
        return ""
    pin = re.compile(r"`docs/plan/a11y/([a-z0-9.-]+)` \(blob `([0-9a-f]{9})`\)")
    have, now = dict(pin.findall(committed)), dict(pin.findall(want))
    moved = [f"{k} (blob {have.get(k, '?')} -> {v})" for k, v in now.items() if have.get(k) != v]
    if moved:
        return "the report is stale: " + ", ".join(moved) + " changed; run --fill"
    return "the report is stale (it differs from the generated one); run --fill"


# ---------------------------------------------------------------------------- the checks


def generation_problems(limits: str, inp: Inputs, report: str) -> list[Finding]:
    out: list[Finding] = []
    if not limits.strip() or not limit_rows(limits):
        out.append(("G-SCHEMA", f"{LIMITS_REL} is missing, not JSON or has no rows"))
        return out
    out += [("G-SCHEMA", m) for m in limits_problems(limits, inp)]
    out += [("G-SCHEMA", m) for m in field_problems(limits)]
    out += [("G-EXCEPTION", m) for m in exception_problems(limits)]
    out += [("G-CONTENT", m) for m in content_problems(limits, report)]
    return out


def run(root: Path, mode: str, today: dt.date | None = None) -> tuple[list[str], int]:
    """One of 'fill', 'check', 'release'; returns (output lines, exit code)."""
    inp = live_inputs(root)
    lp = root / LIMITS_REL
    limits = lp.read_text(encoding="utf-8") if lp.is_file() else ""
    want = render_report(limits, inp) if limit_rows(limits) else ""
    findings = generation_problems(limits, inp, want)
    lines: list[str] = []
    if mode == "fill":
        if findings:
            return _fmt(findings), 1
        (root / REPORT_REL).write_text(want, encoding="utf-8", newline="\n")
        lines.append(f"conformance: wrote {REPORT_REL}")
        for m in expired_exceptions(limits, today or _today()):
            lines.append(f"WARN G-EXPIRED: {m}")
        return lines, 0
    rp = root / REPORT_REL
    committed = rp.read_text(encoding="utf-8") if rp.is_file() else ""
    if not findings:
        why = stale_reason(committed, want) if committed else f"{REPORT_REL} is missing; run --fill"
        if why:
            findings.append(("G-STALE", why))
    if mode == "release":
        findings += [("G-LEVEL-A", f"open Level A finding {m}") for m in open_level_a(inp)]
        findings += [("G-EXPIRED", m) for m in expired_exceptions(limits, today or _today())]
        findings += [
            ("G-OWNER", f"{i} has no valid disposition: blocks sign-off") for i in unowned(limits)
        ]
    lines = _fmt(findings)
    lines.append(f"conformance --{mode}: {len(findings)} FAIL")
    return lines, 1 if findings else 0


def _fmt(findings: list[Finding]) -> list[str]:
    return [f"FAIL {g}: {m}" for g, m in findings]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fill", action="store_true", help="write the report")
    mode.add_argument("--check", action="store_true", help="per PR: schema and staleness")
    mode.add_argument("--release", action="store_true", help="RC: also Level A and expiry")
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    ap.add_argument("--today", type=dt.date.fromisoformat, default=None, help="YYYY-MM-DD")
    args = ap.parse_args(argv)
    m = "fill" if args.fill else "check" if args.check else "release"
    lines, rc = run(args.root, m, args.today)
    for ln in lines:
        print(ln)
    return rc


if __name__ == "__main__":
    sys.exit(main())
