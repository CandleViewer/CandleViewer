"""E42-Q06 (C1, C2): scripts/verify_deferred_must.py on the real backlog and on mutated copies.

The real E42, E43 and E44 backlogs pass today. Each mutated copy stands for one way a deferral
decays (an owner descoped, missing, retired, off R4, a design ticket late, SCR-137 dropped, E42 no
longer stating the deferral) and must fail with exit 1, naming the ticket. The record is written
only on a pass, the same bytes each time, and the committed one is dated and names every owner.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import verify_deferred_must as mod  # after the path shim above, as the sibling tests do

REAL = Path(__file__).resolve().parents[2] / "docs" / "plan" / "backlog"
RECORD = REAL / "verification" / "E42-deferred-must.md"
OWNERS = ("E43-D01", "E43-S02", "E43-S01", "E44-S01", "E44-T04")


def _copy(tmp_path: Path, *, ledger: bool = False) -> Path:
    """The three epic files (and the ledger, when asked) in a directory of their own."""
    backlog = tmp_path / "backlog"
    (backlog / "_tools").mkdir(parents=True)
    for epic in ("E42", "E43", "E44"):
        shutil.copyfile(REAL / f"{epic}.json", backlog / f"{epic}.json")
    if ledger:
        shutil.copyfile(REAL / mod.LEDGER, backlog / mod.LEDGER)
    return backlog


def _tickets(backlog: Path, epic: str) -> list[dict[str, object]]:
    tickets: list[dict[str, object]] = json.loads((backlog / f"{epic}.json").read_text("utf-8"))
    return tickets


def _edit(backlog: Path, key: str, **fields: object) -> None:
    epic = key.split("-")[0]
    tickets = _tickets(backlog, epic)
    (ticket,) = [t for t in tickets if t["key"] == key]
    ticket.update(fields)
    (backlog / f"{epic}.json").write_text(json.dumps(tickets), encoding="utf-8")


def _body(backlog: Path, key: str) -> str:
    (ticket,) = [t for t in _tickets(backlog, key.split("-")[0]) if t["key"] == key]
    return str(ticket["body"])


def _gaps(backlog: Path) -> list[mod.Gap]:
    return mod.check(mod.load_backlog(backlog))


def test_the_real_backlog_passes_today(capsys: pytest.CaptureFixture[str]) -> None:
    assert _gaps(REAL) == []
    assert mod.main([]) == 0
    assert capsys.readouterr().out == "PASS: 5 owner tickets hold the deferred Musts\n"


def test_us_admin_012_removed_from_e44_fails_naming_each_ticket(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The Gherkin failure: a re-scope removed US-ADMIN-012 from E44 without reassigning it."""
    backlog = _copy(tmp_path)
    for key in ("E44-T04", "E44-S01"):
        _edit(backlog, key, body=_body(backlog, key).replace("US-ADMIN-012", "US-ADMIN-099"))
    names = "its body names US-ADMIN-012"
    assert _gaps(backlog) == [
        mod.Gap("E44-S01", "owns US-ADMIN-012", names, "none"),
        mod.Gap("E44-T04", "owns US-ADMIN-012", names, "none"),
    ]
    assert mod.main(["--backlog", str(backlog)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"GAP E44-S01: owns US-ADMIN-012: expected {names}; found none"
    assert out[-1] == "E42 cannot be signed off; escalate to the Owner as an R4 Must-coverage risk."


def test_a_missing_owner_or_one_in_another_epic_file_fails(tmp_path: Path) -> None:
    backlog = _copy(tmp_path)
    e44 = [t for t in _tickets(backlog, "E44") if t["key"] != "E44-S01"]
    (moved,) = [t for t in _tickets(backlog, "E43") if t["key"] == "E43-S01"]
    (backlog / "E44.json").write_text(json.dumps([*e44, moved]), encoding="utf-8")
    e43 = [t for t in _tickets(backlog, "E43") if t["key"] != "E43-S01"]
    (backlog / "E43.json").write_text(json.dumps(e43), encoding="utf-8")
    assert _gaps(backlog) == [
        mod.Gap("E43-S01", "owns US-ADMIN-012", "the ticket in E43.json", "none"),
        mod.Gap("E44-S01", "owns US-ADMIN-012", "the ticket in E44.json", "none"),
    ]


@pytest.mark.parametrize(
    ("key", "fields", "gap"),
    [
        ("E43-S02", {"labels": ["retired"]}, ("not retired", "no `retired` label", "retired")),
        ("E44-T04", {"milestone": "R5"}, ("milestone", mod.MILESTONE, "R5")),
        ("E44-S01", {"milestone": None}, ("milestone", mod.MILESTONE, "none")),
        ("E44-S01", {"sprint": "Sprint 23"}, ("R4 window", "Sprint 20 to Sprint 22", "Sprint 23")),
        ("E43-S01", {"sprint": "Sprint 19"}, ("R4 window", "Sprint 20 to Sprint 22", "Sprint 19")),
        ("E44-T04", {"sprint": "next"}, ("R4 window", "Sprint 20 to Sprint 22", "next")),
    ],
)
def test_an_owner_retired_or_off_r4_fails_naming_it(
    tmp_path: Path, key: str, fields: dict[str, object], gap: tuple[str, str, str]
) -> None:
    backlog = _copy(tmp_path)
    _edit(backlog, key, **fields)
    assert _gaps(backlog) == [mod.Gap(key, *gap)]


def test_a_design_ticket_one_sprint_ahead_of_its_story_fails(tmp_path: Path) -> None:
    backlog = _copy(tmp_path)
    _edit(backlog, "E43-D01", sprint="Sprint 19")
    expected = "at least 2 sprints before E43-S02 (Sprint 20): Sprint 18 or earlier"
    assert _gaps(backlog) == [mod.Gap("E43-D01", "design ahead", expected, "Sprint 19")]
    _edit(backlog, "E43-D01", sprint="Sprint 18")
    _edit(backlog, "E43-S02", sprint="")  # the story it serves has no sprint: both are named
    assert _gaps(backlog) == [
        mod.Gap("E43-D01", "design ahead", "at least 2 sprints before E43-S02", "Sprint 18"),
        mod.Gap("E43-S02", "R4 window", "Sprint 20 to Sprint 22", "none"),
    ]


def test_scr_137_removed_from_an_e43_ticket_fails(tmp_path: Path) -> None:
    backlog = _copy(tmp_path)
    _edit(backlog, "E43-S01", body=_body(backlog, "E43-S01").replace("SCR-137", "SCR-999"))
    assert _gaps(backlog) == [mod.Gap("E43-S01", "screen", "its body names SCR-137", "none")]


def test_e42_no_longer_stating_the_deferral_fails(tmp_path: Path) -> None:
    backlog = _copy(tmp_path)
    lines = _body(backlog, "E42-S05").splitlines()
    _edit(backlog, "E42-S05", body="\n".join(x for x in lines if "US-ADMIN-012" not in x))
    check = "states the deferral of US-ADMIN-012"
    assert _gaps(backlog) == [
        mod.Gap("E42-S05", check, f"its body names {word}", "none")
        for word in ("E43-S01", "E44-S01", "E44-T04", "US-ADMIN-012")
    ]
    e42 = [t for t in _tickets(backlog, "E42") if t["key"] != "E42-S01"]
    (backlog / "E42.json").write_text(json.dumps(e42), encoding="utf-8")
    assert mod.Gap("E42-S01", "states the deferral", "the ticket", "none") in _gaps(backlog)


def test_an_owner_epic_not_blocked_by_e42_fails(tmp_path: Path) -> None:
    backlog = _copy(tmp_path)
    _edit(backlog, "E44", blocked_by=["E38", "E43"])
    _edit(backlog, "E43", blocked_by=None)
    assert _gaps(backlog) == [
        mod.Gap("E43", "blocked by E42", "E42 in blocked_by", "none"),
        mod.Gap("E44", "blocked by E42", "E42 in blocked_by", "E38, E43"),
    ]


def _board(**changes: Mapping[str, object]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = [
        {"title": f"[{key}] t", "state": "OPEN", "status": "Ready", "labels": []} for key in OWNERS
    ]
    items.append({"title": "no key", "state": "CLOSED", "status": None})
    for item in items:
        item.update(changes.get(str(item["title"])[1:8], {}))
    return [i for i in items if i.get("title") != "gone"]


def test_the_board_snapshot_needs_each_owner_open_or_closed_as_done(tmp_path: Path) -> None:
    assert mod.snapshot_gaps(_board(**{"E44-T04": {"state": "CLOSED", "status": "Done"}})) == []
    changes: dict[str, Mapping[str, object]] = {
        "E43-S02": {"state": "CLOSED", "status": "Backlog"},
        "E43-D01": {"labels": ["retired"]},
        "E44-S01": {"title": "gone"},
    }
    board = _board(**changes)
    closed = "CLOSED, status Backlog"
    assert mod.snapshot_gaps(board) == [
        mod.Gap("E43-D01", "not retired on the board", "no `retired` label", "retired"),
        mod.Gap("E43-S02", "open on the board", "open, or closed as Done", closed),
        mod.Gap("E44-S01", "on the board", "an issue titled [E44-S01]", "none"),
    ]
    snapshot = tmp_path / "board.json"
    snapshot.write_text(json.dumps(board), encoding="utf-8")
    assert mod.main(["--snapshot", str(snapshot)]) == 1
    snapshot.write_text(json.dumps(_board()), encoding="utf-8")
    assert mod.main(["--snapshot", str(snapshot)]) == 0


@pytest.mark.parametrize(("content", "code"), [("{not json", 2), ('{"a": 1}', 2), ("[1, 2]", 1)])
def test_an_unreadable_input_is_exit_2_and_an_empty_epic_a_gap(
    tmp_path: Path, content: str, code: int
) -> None:
    """Never a pass: an unreadable file is exit 2, and a list holding no tickets loses every
    owner in that epic, exit 1."""
    assert mod.main(["--backlog", str(tmp_path / "absent")]) == 2
    broken = _copy(tmp_path)
    (broken / "E43.json").write_text(content, encoding="utf-8")
    assert mod.main(["--backlog", str(broken)]) == code
    snapshot = tmp_path / "board.json"
    snapshot.write_text(content, encoding="utf-8")
    assert mod.main(["--snapshot", str(snapshot)]) == 2


def _record(backlog: Path, path: Path, *extra: str) -> int:
    argv = ["--backlog", str(backlog), "--write-record", str(path), *extra]
    return mod.main([*argv, "--reviewer", "QA", "--date", "2026-11-03"])


def test_the_record_is_written_on_a_pass_the_same_bytes_each_time(tmp_path: Path) -> None:
    backlog = _copy(tmp_path, ledger=True)
    first, second = tmp_path / "out" / "a.md", tmp_path / "b.md"
    assert _record(backlog, first) == 0 and _record(backlog, second) == 0
    text = first.read_text(encoding="utf-8")
    assert second.read_bytes() == first.read_bytes() and "\r" not in text
    assert "- **Date:** 2026-11-03\n- **Reviewer:** QA\n- **Result:** PASS\n" in text
    row = r"^\| US-ADMIN-012 +\| E44 +\| E44-T04 +\| #1247 +\| Task +\| S20 +\| R4 Live enablement"
    assert re.search(row + r" +\| yes +\| none +\|$", text, re.MULTILINE)
    design = r"\| S18 +\| R4 Live enablement +\| yes +\| design, 2 sprints before E43-S02; "
    assert re.search(design + r"names SCR-137 \|$", text, re.MULTILINE)
    assert "\n".join(mod._wrap(mod.EXCEPTION)) in text
    digests = re.findall(r"^  - `([\w.]+)`: `[0-9a-f]{64}`$", text, re.MULTILINE)
    assert digests == ["E42.json", "E43.json", "E44.json", "verify_deferred_must.py"]


def test_no_record_is_written_on_a_gap(tmp_path: Path) -> None:
    backlog = _copy(tmp_path)
    _edit(backlog, "E44-T04", labels=["retired"])
    assert _record(backlog, tmp_path / "record.md") == 1
    assert not (tmp_path / "record.md").exists()


def test_the_issue_column_reads_the_ledger_or_says_none(tmp_path: Path) -> None:
    backlog = _copy(tmp_path)
    tickets = mod.load_backlog(backlog)
    assert {row.issue for row in mod.rows(tickets, mod._issues(backlog))} == {"none"}
    for ledger in ('["E44-T04"]', '{"E44-T04": 1247, "E44-S01": {"number": "1266"}}'):
        (backlog / mod.LEDGER).write_text(ledger, encoding="utf-8")
        assert mod._issues(backlog) == {}
    assert mod.rows({}, {})[0] == mod.Row(
        "US-ADMIN-010", "E43", "E43-D01", "none", "none", "none", "none", False, "names SCR-137"
    )


def test_the_table_is_padded_as_prettier_pads_one() -> None:
    assert mod._table(["A", "Bb"], [["x", "yyyy"]]) == [
        "| A   | Bb   |",
        "| --- | ---- |",
        "| x   | yyyy |",
    ]
    assert mod._wrap("a bb ccc", 4) == ["a bb", "ccc"]


@pytest.mark.parametrize(
    "extra",
    [
        ["--reviewer", "QA"],
        ["--date", "2026-11-03"],
        ["--reviewer", "Q|A", "--date", "2026-11-03"],
        ["--reviewer", " ", "--date", "2026-11-03"],
        ["--reviewer", "QA", "--date", "2026-02-30"],
        ["--reviewer", "QA", "--date", "03/11/2026"],
    ],
)
def test_write_record_needs_a_one_line_reviewer_and_a_real_date(
    tmp_path: Path, extra: list[str]
) -> None:
    with pytest.raises(SystemExit) as exited:
        mod.main(["--write-record", str(tmp_path / "record.md"), *extra])
    assert exited.value.code == 2 and not (tmp_path / "record.md").exists()


def test_json_names_each_gap_and_the_escalation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert mod.main(["--json"]) == 0
    passed = json.loads(capsys.readouterr().out)
    assert (passed["result"], passed["gaps"], len(passed["rows"])) == ("PASS", [], 5)
    assert "escalation" not in passed
    backlog = _copy(tmp_path)
    _edit(backlog, "E44-T04", milestone="R5")
    assert mod.main(["--backlog", str(backlog), "--json"]) == 1
    failed = json.loads(capsys.readouterr().out)
    assert (failed["result"], failed["escalation"]) == ("FAIL", mod.ESCALATION)
    gap = {"check": "milestone", "expected": mod.MILESTONE, "found": "R5", "ticket": "E44-T04"}
    assert failed["gaps"] == [gap]


def test_the_committed_record_is_dated_and_names_every_owner() -> None:
    """C2: checked in, dated, with a reviewer, every owner ticket in its table and the one
    stated exception as the script words it; a snapshot, so it is not compared with today's
    backlog."""
    text = RECORD.read_text(encoding="utf-8")
    assert re.search(r"^- \*\*Date:\*\* \d{4}-\d{2}-\d{2}$", text, re.MULTILINE)
    assert re.search(r"^- \*\*Reviewer:\*\* \S.*$", text, re.MULTILINE)
    assert "\n- **Result:** PASS\n" in text
    for key in OWNERS:
        assert re.search(rf"^\| US-ADMIN-01[02] +\| E4[34] +\| {key} +\|", text, re.MULTILINE)
    assert "\n".join(mod._wrap(mod.EXCEPTION)) in text
    assert text.endswith("E42-Q04 attaches this record to the E42 QA sign-off.\n")


def test_a_word_is_named_only_on_a_word_boundary() -> None:
    assert mod._names("the design names SCR-137 here", "SCR-137")
    assert mod._names("names SCR-137.", "SCR-137")
    assert not mod._names("names SCR-1370 only", "SCR-137")
    assert not mod._names("names XSCR-137 only", "SCR-137")


def test_the_record_states_what_the_static_checks_cover(tmp_path: Path) -> None:
    backlog = _copy(tmp_path, ledger=True)
    out = tmp_path / "record.md"
    assert _record(backlog, out) == 0
    assert "\n".join(mod._wrap(mod.SCOPE)) in out.read_text(encoding="utf-8")
    assert "\n".join(mod._wrap(mod.SCOPE)) in RECORD.read_text(encoding="utf-8")
