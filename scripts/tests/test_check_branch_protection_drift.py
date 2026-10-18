"""Unit tests for scripts/check_branch_protection_drift.py (GOV-005)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import check_branch_protection_drift as drift
from apply_branch_protection import ApplyError, Diff, compare_view, load_desired_state
from check_branch_protection_drift import render_findings

FILE = str(SCRIPTS_DIR.parent / ".github/branch-protection.json")


# Regression: encodes E01-Q01 case 1.10 (originating case id) -- drift between
# live and desired branch-protection state must be detected and reported.
def test_render_findings_text_reports_all_kinds() -> None:
    diff = Diff(added={"a": 1}, removed={"b": 2}, changed={"c": (3, 4)})
    text = render_findings(diff, as_json=False)
    assert "GOV-005" in text
    assert "+ a" in text
    assert "- b" in text
    assert "~ c" in text


def test_render_findings_json_shapes_each_kind() -> None:
    diff = Diff(added={"a": 1}, removed={"b": 2}, changed={"c": (3, 4)})
    payload = json.loads(render_findings(diff, as_json=True))
    kinds = {item["kind"] for item in payload}
    assert kinds == {"missing_on_live", "unexpected_on_live", "changed"}
    for item in payload:
        assert item["code"] == "GOV-005"


def test_render_findings_json_empty_diff_is_empty_list() -> None:
    diff = Diff(added={}, removed={}, changed={})
    payload = json.loads(render_findings(diff, as_json=True))
    assert payload == []


def _raise(*_args: object) -> dict:
    raise ApplyError("GET failed: 502")


@pytest.mark.parametrize(
    "live_change,desired_change,token,code,kind",
    [
        (lambda live: None, None, "t", 0, None),
        (lambda live: live.update(lock_branch=True), None, "t", 1, "changed"),
        (lambda live: live.update(new_setting=True), None, "t", 1, "unexpected_on_live"),
        (lambda live: None, lambda d: d.pop("pending_checks"), "t", 1, "c9_1_not_enforced"),
        (lambda live: None, None, "", 2, None),  # no token: fail closed
        (_raise, None, "t", 2, None),  # API error: fail closed
    ],
)
def test_main_compares_every_setting_and_proves_c91(
    tmp_path, monkeypatch, capsys, live_change, desired_change, token, code, kind
) -> None:
    desired = load_desired_state(FILE)
    if desired_change:
        desired_change(desired)
    path = tmp_path / "desired.json"
    path.write_text(json.dumps(desired), encoding="utf-8")
    live = compare_view(desired)
    if live_change is _raise:
        monkeypatch.setattr(drift, "fetch_live_state", _raise)
    else:
        live_change(live)
        monkeypatch.setattr(drift, "fetch_live_state", lambda *a: live)
    monkeypatch.setenv("CV_TEST_TOKEN", token)
    root = SCRIPTS_DIR.parent
    argv = ["--repo", "o/r", "--token-env", "CV_TEST_TOKEN", "--desired-state", str(path), "--json"]
    argv += ["--constitution", str(root / "CONSTITUTION.md")]
    argv += ["--workflows-glob", str(root / ".github/workflows/*.yml")]
    assert drift.main(argv) == code
    if code < 2:
        findings = json.loads(capsys.readouterr().out)
        assert [f["kind"] for f in findings][:1] == ([kind] if kind else [])
