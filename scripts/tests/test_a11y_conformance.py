"""E47-T05 (#1360): the conformance report generator and its exception-register checks.

Stdlib + pytest only (the governance lane has no candleviewer package). Cases run on a synthetic
tree under tmp_path; the last ones read the committed report, matrix and the E47-D13 audit.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import astuple
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


conf = _load("a11y_conformance_t", "tools/a11y/conformance.py")
regpy = _load("a11y_register_t", "docs/plan/a11y/_tools/register.py")

D13_DRY_RUN_SHA256 = "cd65248fad221cdfb581e46ffe0754c07483f95a1b7ada488697ef78a963812c"
TODAY = dt.date(2026, 11, 3)
A11Y = "docs/plan/a11y"


def _verdict(v: str) -> dict[str, Any]:
    return {"verdict": v}


def _screen(sid: str) -> dict[str, Any]:
    return {
        "id": sid,
        "name": sid,
        "coverage": "covered",
        "evidence": {
            "automated": _verdict("pass"),
            "keyboard": _verdict("pass"),
            "deep": _verdict("pass"),
            "sr": {"owner": "E47-T04"},
        },
        "wcag22": {
            c: _verdict("pass") for c in ("2.4.11", "2.5.7", "2.5.8", "3.2.6", "3.3.7", "3.3.8")
        },
    }


def _finding(fid: str, sc: str, level: str, status: str = "open") -> dict[str, Any]:
    return {
        "id": fid,
        "screenId": "SCR-001",
        "wcagSc": sc,
        "level": level,
        "status": status,
        "title": f"title of {fid}",
    }


def _row(
    fid: str, sc: str, level: str, disposition: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    return {
        "id": fid,
        "covers": [fid],
        "sc": [sc],
        "level": level,
        "category": "focus",
        "plain": "The keyboard position can jump.",
        "impact": "Keyboard users lose their place.",
        "workaround": "Press Escape and try again.",
        "disposition": disposition,
        "disclosure": "statement",
        **extra,
    }


FIX = {"kind": "fix-ticket", "ticket": "E47-S05 #1319"}
GOOD_RISK: dict[str, Any] = {
    "kind": "accepted-risk",
    "owner": "the Owner",
    "decision": "accepted for GA",
    "expiry": "2027-03-01",
    "compensatingControl": "The high-contrast theme shows the item.",
    "remediationTicket": "E49-T01 #1400",
}


def _write(root: Path, rel: str, data: Any) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data, indent=2), encoding="utf-8")


def _tree(tmp_path: Path, limitations: list[dict[str, Any]] | None = None) -> Path:
    findings = {
        "auditedSha": "a" * 40,
        "screens": [_screen("SCR-001"), _screen("SCR-002")],
        "findings": [_finding("A11Y-F-0001", "2.4.3", "A"), _finding("A11Y-F-0002", "1.4.3", "AA")],
        "patterns": [],
    }
    lims = limitations or [
        _row("A11Y-F-0001", "2.4.3", "A", FIX),
        _row("A11Y-F-0002", "1.4.3", "AA", FIX),
    ]
    _write(tmp_path, f"{A11Y}/findings.json", findings)
    _write(tmp_path, f"{A11Y}/47-audit-register.json", {"findings": [], "unattributed": []})
    _write(tmp_path, "docs/plan/14-screens-catalogue.md", "# 14\nno media here\n")
    _write(
        tmp_path,
        f"{A11Y}/47-limitations.json",
        {"schema": 1, "categories": {}, "limitations": lims},
    )
    return tmp_path


def _run(root: Path, mode: str, today: dt.date = TODAY) -> tuple[list[str], int]:
    return conf.run(root, mode, today)


def _fill(root: Path) -> None:
    lines, rc = _run(root, "fill")
    assert rc == 0, lines


def _edit_limits(root: Path, fn: Any) -> None:
    p = root / f"{A11Y}/47-limitations.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    fn(doc)
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- generation


def test_fill_then_check_is_clean_and_release_names_the_open_level_a(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    _fill(root)
    assert _run(root, "check")[1] == 0
    report = (root / conf.REPORT_REL).read_text(encoding="utf-8")
    assert "## Exception register" in report and "No accepted-risk exceptions" in report
    assert report.count("\n| ") > 55  # the 55 criteria rows plus the limitation rows


def test_stale_report_fails_check_and_names_the_input(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    _fill(root)
    fp = root / f"{A11Y}/findings.json"
    doc = json.loads(fp.read_text(encoding="utf-8"))
    doc["screens"].append(_screen("SCR-003"))
    fp.write_text(json.dumps(doc), encoding="utf-8")
    lines, rc = _run(root, "check")
    assert rc == 1
    assert any(ln.startswith("FAIL G-STALE") and "findings.json" in ln for ln in lines), lines


def test_missing_report_fails_check(tmp_path: Path) -> None:
    lines, rc = _run(_tree(tmp_path), "check")
    assert rc == 1 and any("G-STALE" in ln for ln in lines)


def test_prettier_padding_is_not_stale(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    _fill(root)
    rp = root / conf.REPORT_REL
    rp.write_text(rp.read_text(encoding="utf-8").replace("| Id ", "| Id    "), encoding="utf-8")
    assert _run(root, "check")[1] == 0


def test_open_level_a_fails_release_naming_the_finding_but_not_check(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    _fill(root)
    assert _run(root, "check")[1] == 0
    lines, rc = _run(root, "release")
    assert rc == 1
    assert any(ln.startswith("FAIL G-LEVEL-A") and "A11Y-F-0001" in ln for ln in lines), lines
    assert not any("A11Y-F-0002" in ln and "G-LEVEL-A" in ln for ln in lines)  # AA is not Level A


def test_fixed_level_a_passes_release(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    fp = root / f"{A11Y}/findings.json"
    doc = json.loads(fp.read_text(encoding="utf-8"))
    doc["findings"][0]["status"] = "fixed"
    fp.write_text(json.dumps(doc), encoding="utf-8")
    _edit_limits(root, lambda d: d["limitations"].pop(0))
    _fill(root)
    lines, rc = _run(root, "release")
    assert rc == 0, lines


# --------------------------------------------------------------------------- the exception register


def _risk_tree(tmp_path: Path, risk: dict[str, Any], **row: Any) -> Path:
    rows = [
        _row("A11Y-F-0001", "2.4.3", "A", FIX),
        _row("A11Y-F-0002", "1.4.3", "AA", risk, surfaces=["SCR-001"], **row),
    ]
    return _tree(tmp_path, rows)


def test_complete_exception_is_generated_into_the_register(tmp_path: Path) -> None:
    root = _risk_tree(tmp_path, GOOD_RISK)
    _fill(root)
    report = (root / conf.REPORT_REL).read_text(encoding="utf-8")
    assert "Exceptions: 1; nearest expiry: 2027-03-01." in report
    assert "the Owner: accepted for GA" in report and "E49-T01 #1400" in report
    assert _run(root, "release", TODAY)[1] == 1  # the open Level A, not the exception
    assert not any("G-EXCEPTION" in ln for ln in _run(root, "check")[0])


@pytest.mark.parametrize(
    "missing", ["compensatingControl", "owner", "decision", "expiry", "remediationTicket"]
)
def test_exception_missing_a_disposition_field_fails_generation(
    tmp_path: Path, missing: str
) -> None:
    risk = {k: v for k, v in GOOD_RISK.items() if k != missing}
    root = _risk_tree(tmp_path, risk)
    lines, rc = _run(root, "fill")
    assert rc == 1 and any(ln.startswith("FAIL G-EXCEPTION") for ln in lines), lines
    assert not (root / conf.REPORT_REL).exists()
    assert _run(root, "check")[1] == 1


def test_exception_without_surfaces_or_criterion_fails(tmp_path: Path) -> None:
    root = _risk_tree(tmp_path, GOOD_RISK)
    _edit_limits(root, lambda d: d["limitations"][1].pop("surfaces"))
    lines, rc = _run(root, "fill")
    assert rc == 1 and any("no affected surfaces" in ln for ln in lines)
    _edit_limits(root, lambda d: d["limitations"][1].update(surfaces=["SCR-001"], sc=[]))
    assert any("no success criterion" in ln for ln in _run(root, "fill")[0])


def test_level_a_can_never_be_an_accepted_risk(tmp_path: Path) -> None:
    rows = [
        _row("A11Y-F-0001", "2.4.3", "A", GOOD_RISK, surfaces=["SCR-001"]),
        _row("A11Y-F-0002", "1.4.3", "AA", FIX),
    ]
    lines, rc = _run(_tree(tmp_path, rows), "fill")
    assert rc == 1
    assert any("Level A criterion 2.4.3 can never be an accepted risk" in ln for ln in lines), lines


def test_level_a_criterion_on_an_aa_labelled_row_is_still_refused(tmp_path: Path) -> None:
    root = _risk_tree(tmp_path, GOOD_RISK)
    _edit_limits(root, lambda d: d["limitations"][1].update(sc=["2.4.3"]))
    assert any("can never be an accepted risk" in ln for ln in _run(root, "fill")[0])


def test_expired_acceptance_is_flagged_for_redecision_in_release_and_fill(tmp_path: Path) -> None:
    root = _risk_tree(tmp_path, {**GOOD_RISK, "expiry": "2026-10-01"})
    lines, rc = _run(root, "fill")
    assert rc == 0 and any(ln.startswith("WARN G-EXPIRED") and "A11Y-F-0002" in ln for ln in lines)
    assert _run(root, "check")[1] == 0  # per PR: not an expiry gate (BQ-02)
    rel, rc = _run(root, "release")
    assert rc == 1
    assert any(ln.startswith("FAIL G-EXPIRED") and "re-decide" in ln for ln in rel), rel


def test_acceptance_expiring_today_is_not_yet_expired(tmp_path: Path) -> None:
    root = _risk_tree(tmp_path, {**GOOD_RISK, "expiry": "2026-11-03"})
    assert conf.expired_exceptions((root / f"{A11Y}/47-limitations.json").read_text(), TODAY) == []


# --------------------------------------------------------------------------- content and evidence


@pytest.mark.parametrize(
    "text",
    [
        "see example.com for details",
        "visit https://host/x",
        "key AbCdEfGhIjKlMnOpQrStUvWxYz12",
        "UID 1234567",
    ],
)
def test_content_check_rejects_hosts_ids_and_key_material(tmp_path: Path, text: str) -> None:
    root = _tree(tmp_path)
    _edit_limits(root, lambda d: d["limitations"][1].update(plain=text))
    lines, rc = _run(root, "fill")
    assert rc == 1 and any(ln.startswith("FAIL G-CONTENT") and ".plain" in ln for ln in lines)


def test_content_check_covers_exception_fields(tmp_path: Path) -> None:
    root = _risk_tree(tmp_path, {**GOOD_RISK, "compensatingControl": "ask admin.example.com"})
    assert any("G-CONTENT" in ln and "compensatingControl" in ln for ln in _run(root, "fill")[0])


def test_unresolved_sibling_evidence_reads_not_yet_produced_and_resolves_from_records(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path)
    _fill(root)
    report = (root / conf.REPORT_REL).read_text(encoding="utf-8")
    row = next(ln for ln in report.split("\n") if ln.startswith("| 1.1.1 "))
    assert "not yet produced: pass" in row and row.split("|")[3].strip() != "Supports"
    _write(
        root,
        f"{A11Y}/47-evidence.json",
        {"records": [{"kind": "pass", "sc": ["1.1.1"], "ref": "pass:t04-1@abc1234"}]},
    )
    _fill(root)
    row = next(
        ln
        for ln in (root / conf.REPORT_REL).read_text(encoding="utf-8").split("\n")
        if ln.startswith("| 1.1.1 ")
    )
    assert "pass:t04-1@abc1234" in row and "not yet produced" not in row


@pytest.mark.parametrize(
    ("edit", "needle"),
    [
        (lambda r: r["disposition"].update(ticket="AbCdEfGhIjKlMnOpQrStUvWxYz12"), "ticket"),
        (lambda r: r.update(category="see example.com"), "category"),
        (lambda r: r.update(disclosure="AbCdEfGhIjKlMnOpQrStUvWxYz12"), "disclosure"),
        (lambda r: r.update(disclosure="public"), "disclosure"),
        (lambda r: r["disposition"].update(ticket="not a ticket"), "disposition.ticket"),
    ],
)
def test_every_rendered_field_is_scanned_and_well_formed(
    tmp_path: Path, edit: Any, needle: str
) -> None:
    root = _tree(tmp_path)
    _edit_limits(root, lambda d: edit(d["limitations"][1]))
    lines, rc = _run(root, "fill")
    assert rc == 1 and any(needle in ln for ln in lines), lines
    assert _run(root, "check")[1] == 1


# --------------------------------------------------------------------------- Level A detection


@pytest.mark.parametrize("level", ["A", "AA / A", "A / AA", "A, AA"])
def test_mixed_level_tokens_count_as_level_a(level: str) -> None:
    assert conf.is_level_a(level)
    assert not conf.is_level_a("AA")
    assert conf.is_level_a("AA", ["2.4.3"]) and not conf.is_level_a("AA", ["1.4.3"])


def test_release_names_open_d02_level_a_rows_including_mixed_levels(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    _write(
        root,
        f"{A11Y}/47-audit-register.json",
        {
            "findings": [
                {"id": "A11Y-R-X-F-39", "level": "AA / A", "status": "open", "sc": ["1.4.3"]},
                {"id": "A11Y-R-X-F-40", "level": "AA", "status": "open", "sc": ["2.4.3"]},
                {"id": "A11Y-R-X-F-41", "level": "AA", "status": "open", "sc": ["1.4.3"]},
                {"id": "A11Y-R-X-F-42", "level": "A", "status": "closed", "sc": ["2.4.3"]},
            ],
            "unattributed": [],
        },
    )
    _edit_limits(root, lambda d: None)
    _fill(root)
    lines, rc = _run(root, "release")
    named = [ln for ln in lines if "G-LEVEL-A" in ln]
    assert rc == 1
    assert any("A11Y-R-X-F-39" in ln for ln in named) and any("A11Y-R-X-F-40" in ln for ln in named)
    assert not any("F-41" in ln or "F-42" in ln for ln in named)


# --------------------------------------------------------------------------- BQ-08, the class map


def test_class_map_partitions_the_55_criteria_once() -> None:
    claimed = [sc for scs, _, _ in conf.CONTRACT.values() for sc in scs]
    assert sorted(claimed) == sorted(conf.SC) and len(claimed) == len(set(claimed)) == 55


def test_class_map_matches_the_gates_that_exist() -> None:
    gates = (ROOT / "tools/a11y/gates.py").read_text(encoding="utf-8")
    contrast = (ROOT / "tools/contrast/generate.mjs").read_text(encoding="utf-8")
    # K-FLASH (2.3.1) is A11Y-G005; K-KEY is the keyboard gate G004; K-AXE the axe gate G001.
    assert "A11Y-G005" in gates and "2.3.1" in gates and conf.CONTRACT["K-FLASH"][0] == ("2.3.1",)
    assert "A11Y-G004" in gates and "keyboard" in conf.CONTRACT["K-KEY"][1]
    assert "A11Y-G001" in gates and "automated" in conf.CONTRACT["K-AXE"][1]
    # K-CONTRAST (1.4.3, 1.4.11) is the contrast matrix, A11Y-C001..C003.
    assert "A11Y-C001" in contrast and conf.CONTRACT["K-CONTRAST"][0] == ("1.4.3", "1.4.11")


# --------------------------------------------------------------------------- the real tree


def test_committed_report_matches_the_registers() -> None:
    lines, rc = conf.run(ROOT, "check")
    assert rc == 0, lines


def test_generation_is_deterministic_and_names_its_generator() -> None:
    inp = conf.live_inputs(ROOT)
    limits = (ROOT / conf.LIMITS_REL).read_text(encoding="utf-8")
    assert conf.render_report(limits, inp) == conf.render_report(limits, inp)
    assert conf.render_report(limits, inp).startswith("<!-- generated by tools/a11y/conformance.py")


D13_REL = "docs/design/_tools/e47_d13_conformance_audit.py"


def _d13() -> Any:
    base = subprocess.run(
        ["git", "cat-file", "-t", "4c662fd5b"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if base.returncode != 0:
        pytest.skip("the E47-D13 base commit is not in this clone")
    return _load("a11y_d13_t", D13_REL)


def _git_blob(blob: str) -> str:
    out = subprocess.run(
        ["git", "cat-file", "-p", blob], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return out.stdout


# The limitations register as the D13 dry run was pinned (a git blob, like D13's other inputs), so a
# later register edit never breaks the digest. Repin only with D13's own pins: take the new blob
# (`git hash-object docs/plan/a11y/47-limitations.json`) and the new digest together.
D13_LIMITS_BLOB = "b36dc3b2aaaa1207f3fd07acd33c5f49792690be"


def test_design_audit_model_equals_the_product_model_built_independently() -> None:
    # Not D13's --check: its G-UNTOUCHED gate diffs the whole branch, so it is not a governance test.
    d13 = _d13()
    limits = _git_blob(D13_LIMITS_BLOB)
    inp = conf.Inputs(
        findings=json.loads(_git_blob(d13.FINDINGS_BLOB)),
        register=json.loads(_git_blob(d13.REGISTER_BLOB)),
        plan14=_git_blob(f"{d13.BASE}:{d13.PLAN['14']}"),
        findings_blob=d13.FINDINGS_BLOB,
        register_blob=d13.REGISTER_BLOB,
    )
    # Two loads of one file are two classes, so compare the rows as plain data.
    assert [astuple(r) for r in d13.model(limits)] == [astuple(r) for r in conf.model(limits, inp)]
    assert len(d13.model(limits)) == 55


def test_design_audit_dry_run_is_unchanged() -> None:
    d13 = _d13()
    digest = hashlib.sha256(
        d13.render_report(_git_blob(D13_LIMITS_BLOB)).encode("utf-8")
    ).hexdigest()
    assert digest == D13_DRY_RUN_SHA256


def test_rejected_field_values_never_reach_the_log(tmp_path: Path) -> None:
    secret = "AbCdEfGhIjKlMnOpQrStUvWxYz12"
    root = _tree(tmp_path)
    _edit_limits(root, lambda d: d["limitations"][1]["disposition"].update(ticket=secret))
    _edit_limits(root, lambda d: d["limitations"][0].update(disclosure=secret))
    lines, rc = _run(root, "fill")
    assert rc == 1 and lines
    assert not any(secret in ln for ln in lines), lines


def test_numeric_leaves_are_content_scanned(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    _edit_limits(root, lambda d: d["limitations"][1].update(count=1234567))
    lines, rc = _run(root, "fill")
    assert rc == 1 and any("G-CONTENT" in ln and "count" in ln for ln in lines), lines


# --------------------------------------------------------------------------- the matrix sign-off (BQ-05)


def _register_doc() -> dict[str, Any]:
    return json.loads((ROOT / A11Y / "findings.json").read_text(encoding="utf-8"))


def test_matrix_sign_off_column_reads_the_register() -> None:
    doc = _register_doc()
    assert "| Sign-off" in regpy.render(doc)
    assert "not signed off" in regpy.render(doc)
    signed = copy.deepcopy(doc)
    signed["screens"][0]["signOff"] = {"verdict": "signed", "by": "the Owner", "date": "2026-11-03"}
    assert regpy.validate(signed) == []
    assert "signed (the Owner, 2026-11-03)" in regpy.render(signed)


@pytest.mark.parametrize(
    "extra",
    [{"extra": "x"}, {"by": "ask admin.example.com"}, {"by": "AbCdEfGhIjKlMnOpQrStUvWxYz12"}],
)
def test_matrix_rejects_unknown_sign_off_keys_and_leaky_names(extra: dict[str, str]) -> None:
    bad = _register_doc()
    bad["screens"][0]["signOff"] = {
        "verdict": "signed",
        "by": "the Owner",
        "date": "2026-11-03",
        **extra,
    }
    assert any("signOff" in e for e in regpy.validate(bad))


def test_matrix_rejects_a_malformed_sign_off() -> None:
    bad = _register_doc()
    bad["screens"][0]["signOff"] = {"verdict": "maybe", "by": "", "date": "soon"}
    assert any("signOff" in e for e in regpy.validate(bad))


def test_committed_matrix_is_current() -> None:
    assert regpy.main(["--check"]) == 0


# --------------------------------------------------------------------------- per-PR Level A ban, plain language


def test_level_a_entry_ban_fires_under_per_pr_check_not_only_release(tmp_path: Path) -> None:
    rows = [
        _row("A11Y-F-0001", "2.4.3", "A", GOOD_RISK, surfaces=["SCR-001"]),
        _row("A11Y-F-0002", "1.4.3", "AA", FIX),
    ]
    root = _tree(tmp_path, rows)
    lines, rc = _run(root, "check")
    assert rc == 1
    assert any("G-EXCEPTION" in ln and "can never be an accepted risk" in ln for ln in lines), lines


def test_open_level_a_findings_are_not_a_per_pr_gate(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    _fill(root)
    assert _run(root, "check")[1] == 0 and _run(root, "release")[1] == 1


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("Focus moves to the page behind it", "full stop"),
        ("The focus moves. It is lost.", "more than one sentence"),
        ("Words " * 31 + "end.", "30 words"),
        ("Fails 2.4.3 on this page.", "criterion number"),
        ("The ARIA label is missing.", "banned word"),
        ("The viewport is too small.", "banned word"),
        ("The role=button is wrong.", "banned word"),
    ],
)
@pytest.mark.parametrize("field", ["plain", "impact", "workaround"])
def test_plain_language_rule_is_a_generator_check(
    tmp_path: Path, field: str, text: str, why: str
) -> None:
    root = _tree(tmp_path)
    _edit_limits(root, lambda d: d["limitations"][1].update({field: text}))
    lines, rc = _run(root, "check")
    assert rc == 1, lines
    assert any(f"G-PLAIN: limitations[1].{field}: " in ln and why in ln for ln in lines), lines
    assert not any(text in ln for ln in lines)


def test_plain_language_is_not_applied_to_internal_rows(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    _edit_limits(root, lambda d: d["categories"].update(focus="A sentence."))
    _edit_limits(
        root,
        lambda d: d["limitations"][1].update(disclosure="internal", plain="Raw text 2.4.3 ARIA"),
    )
    assert not any("G-PLAIN" in ln for ln in _run(root, "check")[0])


def test_fill_notes_the_internal_row_review_without_gating(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    _edit_limits(root, lambda d: d["limitations"][1].update(disclosure="internal"))
    lines, rc = _run(root, "fill")
    assert rc == 0 and any("E47-X04 (#1389)" in ln for ln in lines), lines
    quiet, _ = _run(_tree(tmp_path / "b"), "fill")
    assert not any("E47-X04" in ln for ln in quiet)


def test_class_map_is_the_one_d13_proposed() -> None:
    # BQ-08: class-map changes are co-decided with the owner; this pins the proposal as it stands.
    pinned = {k: (len(v[0]), v[1], v[2]) for k, v in conf.CONTRACT.items()}
    assert pinned == {
        "K-AXE": (10, ("automated", "pass"), "report"),
        "K-CONTRAST": (2, ("automated", "contrast", "t03"), "theme"),
        "K-KEY": (5, ("keyboard", "pass"), "keys"),
        "K-W22": (6, ("wcag22", "d12"), "keys"),
        "K-FLASH": (1, ("flash", "q05"), "motion"),
        "K-MOTION": (1, ("q05", "pass"), "motion"),
        "K-MEDIA": (5, ("pass",), "report"),
        "K-ZOOM": (4, ("deep", "pass"), "scale"),
        "K-SR": (6, ("pass", "d12"), "verbosity"),
        "K-MANUAL": (15, ("pass",), "report"),
    }
