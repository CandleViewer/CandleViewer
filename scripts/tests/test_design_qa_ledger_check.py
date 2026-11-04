"""E49-D01 (#1330): the design-QA ledger self-check, its fixture ledgers and its pack gates.

Stdlib + pytest only. The fixture cases read `tests/fixtures/design_qa/`; the pack cases read the
plan documents at the tool's pinned base (the governance checkout has the full history).
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "design_qa_ledger_check", ROOT / "scripts" / "design_qa_ledger_check.py"
)
assert _spec and _spec.loader
dq = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = dq
_spec.loader.exec_module(dq)

FX = ROOT / "tests" / "fixtures" / "design_qa"
HEADER = ",".join(dq.SCREEN_HEADER)


def _fx(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


def _run(screens: str, findings: str | None = None) -> frozenset[str]:
    reg = json.loads(_fx("register.json"))
    fnd = _fx("findings.csv") if findings is None else findings
    got: frozenset[str] = dq.codes(
        dq.check_ledger(screens, fnd, _fx("catalogue.md"), reg, dq.FIXTURE_KEYS)
    )
    return got


def _swap(old: str, new: str) -> str:
    text = _fx("complete.csv")
    assert old in text
    return text.replace(old, new, 1)


@pytest.mark.parametrize("name", sorted(dq.FIXTURES))
def test_fixture_ledger_gives_its_expected_codes(name: str) -> None:
    assert _run(_fx(name)) == dq.FIXTURES[name]


def test_exception_without_followup_key_fails() -> None:
    assert _run(_swap("DQA-0002;E49-D05,", "DQA-0002,")) == {"E_EXCEPTION"}


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ("SCR-010,App shell", "SCR-009,App shell", "E_RESERVED"),
        ("SCR-010,App shell", "SCR-006,App shell", "E_EXTRA"),
        ("SCR-001,Login,E09", "SCR-001,Sign in,E09", "E_NAME"),
        ("SCR-001,Login,E09,", "SCR-001,Login,E9,", "E_EPIC"),
        ("pass,0,0,0,0,,,findings,", "pass,0,0,0,0,,,no findings at sha,", "E_E47"),
        ("SCR-001,Login,E09,agent-run,2026-11-04", "SCR-001,Login,E09,agent-run,4 Nov", "E_AUDIT"),
        ("(global chrome),E05,,", "(global chrome),E05,agent-run,", "E_AUDIT"),
        ("pass,0,0,0,0,", "pass,0,0,x,0,", "E_COUNTS"),
        ("pass,0,0,0,0,,", "pass,0,0,0,0,X-1,", "E_BUGKEY"),
        ("DQA-0002;E49-D05", "DQA-0002;E99-Z99", "E_BUGKEY"),
        ("reason: no visual surface of its own", "no visual surface of its own", "E_NA"),
        ("findings,0,0,1,0,DQA-0001", "findings,0,0,1,0,DQA-0009", "E_CROSS"),
    ],
)
def test_one_broken_rule_gives_its_code(old: str, new: str, code: str) -> None:
    assert code in _run(_swap(old, new))


def test_a11y_exception_needs_a_compensating_control() -> None:
    a11y = "owner: the owner; reason: DQ-AX-5 dense cells"
    old = "owner: the owner; reason: deferred to the post-GA polish pass"
    assert _run(_swap(old, a11y)) == {"E_EXCEPTION"}
    assert _run(_swap(old, a11y + "; control: the table view")) == frozenset()


def test_pass_with_a_finding_and_findings_with_none_fail() -> None:
    assert "E_COUNTS" in _run(_swap("pass,0,0,0,0,", "pass,0,0,1,0,"))
    assert "E_COUNTS" in _run(_swap("findings,0,0,1,0,", "findings,0,0,0,0,"))


def test_counts_must_match_the_finding_rows() -> None:
    assert _run(_swap("findings,0,0,1,0,", "findings,0,1,0,0,")) >= {"E_CROSS"}


def test_duplicate_row_fails() -> None:
    text = _fx("complete.csv")
    assert "E_DUP" in _run(text + text.splitlines()[1] + "\n")


def test_headers_and_malformed_rows_fail() -> None:
    assert _run("screen,name\n") == {"E_HEADER"}
    assert "E_HEADER" in _run(HEADER + "\nSCR-001,Login\n")
    assert "E_FINDINGS" in _run(_fx("complete.csv"), "id,severity\n")
    bad = "finding_id,severity,status,component,opened\nDQA-0001,P9,open,SCR-002,2026-11-04\n"
    assert "E_FINDINGS" in _run(_fx("complete.csv"), bad)
    odd = bad.replace("P9,open", "P2,parked")
    assert "E_FINDINGS" in _run(_fx("complete.csv"), odd)
    for row in ("DQA-0001,P2,wontfix", "DQA-0001,P1,open", "X-1,P2,open"):  # BQ-1, BQ-2 riders
        assert "E_FINDINGS" in _run(_fx("complete.csv"), f"{bad[:44]}{row},SCR-002,2026-11-04\n")
    assert "E_FINDINGS" not in _run(
        _fx("complete.csv"), f"{bad[:44]}#42,P1,open,SCR-002,2026-11-04\n"
    )


def test_order_puts_the_first_tier_then_weight_then_id() -> None:
    matrix = (
        "| **US-A-001** a | Must | SCR-002, SCR-003 |\n"
        "| **US-A-002** b | Must | SCR-003 |\n"
        "| **US-A-003** c | Must/Should | SCR-001 |\n"
        "## 3. Screens\n| **US-A-004** d | Must | SCR-001 |\n"
    )
    weights = dq.must_weights(matrix)
    assert weights == {"SCR-002": 1, "SCR-003": 2}
    cat = [("SCR-001", "a"), ("SCR-002", "b"), ("SCR-003", "c"), ("SCR-030", "d")]
    assert dq.audit_order(cat, weights) == ["SCR-030", "SCR-003", "SCR-002", "SCR-001"]


def test_pack_gates_pass_and_every_mutation_trips_its_own_gate() -> None:
    tree = dq.read_tree(changed=())
    assert [r.gate for r in dq.L.run_gates(dq.GATES, tree) if not r.ok] == []
    assert dq.self_test(changed=()) == 0


def test_ledger_mode_reports_and_exits_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    code = dq.main(["--ledger", str(FX / "complete.csv"), str(FX / "findings.csv")])
    assert code == 1
    assert "E_MISSING" in capsys.readouterr().out


def test_order_mode_prints_every_screen(capsys: pytest.CaptureFixture[str]) -> None:
    assert dq.main(["--order"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 149
    assert lines[0].split()[1] == "SCR-030"
