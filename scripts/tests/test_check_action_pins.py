"""Unit tests for tools/ci/check_action_pins.py (SR-132).

Covers: pinned SHA passes, tag fails, pull_request_target fails, comment
lines are ignored, local/docker refs are exempt; and (#3580) the ledger
.github/actions-pins.md compared with every uses: line (CI-PIN-*).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.check_action_pins import check_file, main

PINNED_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_check_file_pinned_sha_passes(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "ok.yml",
        f"""\
jobs:
  build:
    steps:
      - uses: actions/checkout@{PINNED_SHA} # v4.2.2
""",
    )
    assert check_file(wf) == []


def test_check_file_floating_tag_fails(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "bad.yml",
        """\
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
""",
    )
    violations = check_file(wf)
    assert len(violations) == 1
    assert "not a 40-hex commit SHA" in violations[0].reason


def test_check_file_no_ref_at_all_fails(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "noref.yml",
        """\
jobs:
  build:
    steps:
      - uses: actions/checkout
""",
    )
    violations = check_file(wf)
    assert len(violations) == 1
    assert "no @ref" in violations[0].reason


def test_check_file_pull_request_target_fails(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "prt.yml",
        f"""\
on:
  pull_request_target:
jobs:
  build:
    steps:
      - uses: actions/checkout@{PINNED_SHA}
""",
    )
    violations = check_file(wf)
    assert any("pull_request_target" in v.reason for v in violations)


def test_check_file_comment_lines_ignored(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "commented.yml",
        f"""\
jobs:
  build:
    steps:
      # - uses: actions/checkout@v4
      - uses: actions/checkout@{PINNED_SHA}
""",
    )
    assert check_file(wf) == []


def test_check_file_local_ref_exempt(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "local.yml",
        """\
jobs:
  build:
    steps:
      - uses: ./.github/actions/local-thing
""",
    )
    assert check_file(wf) == []


def test_check_file_docker_ref_with_digest_passes(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "docker_ok.yml",
        """\
jobs:
  build:
    steps:
      - uses: docker://alpine@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
""",
    )
    assert check_file(wf) == []


def test_check_file_docker_ref_floating_tag_fails(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "docker_bad.yml",
        """\
jobs:
  build:
    steps:
      - uses: docker://alpine:3.19
""",
    )
    violations = check_file(wf)
    assert len(violations) == 1
    assert "sha256" in violations[0].reason


def test_check_file_pull_request_target_inline_scalar_fails(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "prt_inline.yml",
        f"""\
on: pull_request_target
jobs:
  build:
    steps:
      - uses: actions/checkout@{PINNED_SHA}
""",
    )
    violations = check_file(wf)
    assert any("pull_request_target" in v.reason for v in violations)


def test_check_file_pull_request_target_inline_list_fails(tmp_path: Path) -> None:
    wf = _write(
        tmp_path,
        "prt_list.yml",
        f"""\
on: [push, pull_request_target]
jobs:
  build:
    steps:
      - uses: actions/checkout@{PINNED_SHA}
""",
    )
    violations = check_file(wf)
    assert any("pull_request_target" in v.reason for v in violations)


def test_check_file_pull_request_target_as_substring_not_flagged(tmp_path: Path) -> None:
    # A job step that merely mentions the trigger name in an unrelated
    # `run:` line must not trip the check — only the `on:` trigger block does.
    wf = _write(
        tmp_path,
        "mention.yml",
        f"""\
on:
  push:
jobs:
  build:
    steps:
      - run: echo "not a pull_request_target trigger"
      - uses: actions/checkout@{PINNED_SHA}
""",
    )
    assert check_file(wf) == []


def test_main_exits_1_on_violation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wf = _write(tmp_path, "bad.yml", "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v4\n")
    rc = main([str(wf)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "CI-GATE-003" in captured.err


def test_main_exits_0_on_clean_dir(tmp_path: Path) -> None:
    _write(tmp_path, "ok.yml", f"jobs:\n  build:\n    steps:\n      - uses: actions/checkout@{PINNED_SHA}\n")
    rc = main([str(tmp_path)])
    assert rc == 0


def test_main_exits_2_on_missing_path() -> None:
    rc = main(["/no/such/path/at/all"])
    assert rc == 2


# --- The ledger against every uses: line (#3580) ------------------------------------------------

LEDGER = ".github/actions-pins.md"
CACHE_SHA = "55cc8345863c7cc4c66a329aec7e433d2d1c52a9"
F40 = "f" * 40
HEADER = "| Action | Pinned SHA | Upstream tag | Used in | Last |\n|---|---|---|---|---|\n"
CHECKOUT_ROW = f"| `actions/checkout` | `{PINNED_SHA}` | `v4.2.2` | `a.yml`, `b.yml` | x |\n"
SETUP = ".github/actions/setup/action.yml"
CACHE_ROW = f"| `actions/cache` | `{CACHE_SHA}` | `v6.1.0` | `{SETUP}` | x |\n"
# a.yml line 4 and b.yml line 6 use checkout; the composite action's line 4 uses cache. A local
# `./` reference and a `docker://` image pinned by digest need no row.
WORKFLOW_A = f"jobs:\n  j:\n    steps:\n      - uses: actions/checkout@{PINNED_SHA} # v4.2.2\n"
WORKFLOW_B = (
    "jobs:\n  j:\n    uses: ./.github/workflows/a.yml\n  k:\n    steps:\n"
    f"      - uses: actions/checkout@{PINNED_SHA} # v4.2.2\n"
    f"      - uses: docker://alpine@sha256:{'0' * 64}\n"
)
ACTION = f"runs:\n  using: composite\n  steps:\n    - uses: actions/cache@{CACHE_SHA} # v6.1.0\n"
A_YML, B_YML = ".github/workflows/a.yml:4", ".github/workflows/b.yml:6"
ACTION_YML = f"{SETUP}:4"


def _repo(tmp_path: Path, rows: str = CHECKOUT_ROW + CACHE_ROW, a: str = WORKFLOW_A) -> Path:
    # The ledger's header is line 3, so the first row is line 5 and the second line 6.
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "actions" / "setup").mkdir(parents=True)
    _write(tmp_path, ".github/workflows/a.yml", a)
    _write(tmp_path, ".github/workflows/b.yml", WORKFLOW_B)
    _write(tmp_path, SETUP, ACTION)
    _write(tmp_path, LEDGER, "# Ledger\n\n" + HEADER + rows)
    return tmp_path


def _run(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    rc = main(["--root", str(root)])
    return rc, capsys.readouterr().err


def _fails_with(root: Path, capsys: pytest.CaptureFixture[str], finding: str) -> bool:
    return _run(root, capsys) == (1, f"{LEDGER} disagrees with the uses: lines:\n  {finding}\n")


def test_ledger_matching_every_uses_line_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(_repo(tmp_path), capsys) == (0, "")


MISMATCHES = {  # id -> (the ledger's rows, the one finding, which names both sides)
    "stale-sha": (
        CHECKOUT_ROW + CACHE_ROW.replace(CACHE_SHA, F40),
        f"CI-PIN-004 {ACTION_YML}: actions/cache is pinned at {CACHE_SHA}; {LEDGER}:6 has {F40}",
    ),
    "stale-tag": (
        CHECKOUT_ROW + CACHE_ROW.replace("v6.1.0", "v6.0.0"),
        f"CI-PIN-005 {ACTION_YML}: actions/cache is tagged v6.1.0; {LEDGER}:6 has v6.0.0",
    ),
    "missing-row": (
        CHECKOUT_ROW,
        f"CI-PIN-002 {ACTION_YML}: actions/cache@{CACHE_SHA} has no row in {LEDGER}",
    ),
    "duplicate-row": (
        CHECKOUT_ROW + CACHE_ROW + CHECKOUT_ROW,
        f"CI-PIN-003 {LEDGER}:5, {LEDGER}:7: actions/checkout has 2 rows; keep one",
    ),
    "unused-row": (
        CHECKOUT_ROW + CACHE_ROW + CACHE_ROW.replace("actions/cache", "actions/setup-node"),
        f"CI-PIN-006 {LEDGER}:7: no uses: line names actions/setup-node",
    ),
    "used-in-missing": (
        CHECKOUT_ROW.replace(", `b.yml`", "") + CACHE_ROW,
        f"CI-PIN-007 {B_YML}: uses actions/checkout; {LEDGER}:5 'Used in' does not list b.yml",
    ),
    "used-in-extra": (
        CHECKOUT_ROW.replace("`b.yml`", "`b.yml`, `c.yml`") + CACHE_ROW,
        f"CI-PIN-008 {LEDGER}:5: 'Used in' lists c.yml, which does not use actions/checkout",
    ),
}


@pytest.mark.parametrize(("rows", "finding"), MISMATCHES.values(), ids=MISMATCHES.keys())
def test_ledger_mismatch_fails_naming_both_sides(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rows: str, finding: str
) -> None:
    assert _fails_with(_repo(tmp_path, rows), capsys, finding)


def test_ledger_uses_line_without_tag_comment_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _repo(tmp_path, a=WORKFLOW_A.replace(" # v4.2.2", ""))
    tagged = "actions/checkout has no `# <tag>` comment"
    assert _fails_with(root, capsys, f"CI-PIN-005 {A_YML}: {tagged}; {LEDGER}:5 has v4.2.2")


UNREADABLE = {  # id -> the ledger's text past its title (None: no ledger file)
    "no-file": None,
    "no-table": "No table.\n",
    "no-tag-column": "| Action | Pinned SHA | Used in |\n| --- | --- | --- |\n",
    "short-row": HEADER + CHECKOUT_ROW.replace(" x |", ""),
    "bare-value": HEADER + CHECKOUT_ROW.replace(f"`{PINNED_SHA}`", PINNED_SHA),
    "short-sha": HEADER + CHECKOUT_ROW.replace(PINNED_SHA, PINNED_SHA[:12]),
    "unseparated": HEADER + CHECKOUT_ROW.replace("`a.yml`, ", "`a.yml` "),
    "listed-twice": HEADER + CHECKOUT_ROW.replace("`b.yml`", "`a.yml`"),
    "second-table": HEADER + CHECKOUT_ROW + "\nprose\n\n" + HEADER + CACHE_ROW,
}


@pytest.mark.parametrize("text", UNREADABLE.values(), ids=UNREADABLE.keys())
def test_ledger_unreadable_table_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str | None
) -> None:
    ledger = _repo(tmp_path) / LEDGER
    if text is None:
        ledger.unlink()
    else:
        ledger.write_text(f"# Ledger\n\n{text}", encoding="utf-8")
    rc, err = _run(tmp_path, capsys)
    assert rc == 1 and f"CI-PIN-001 {LEDGER}" in err, err


def test_repo_run_checks_composite_actions_for_sr132(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(_repo(tmp_path), SETUP, ACTION.replace(CACHE_SHA, "v6"))
    rc, err = _run(tmp_path, capsys)
    assert rc == 1 and "CI-GATE-003" in err and f"{ACTION_YML}: unpinned" in err
    assert "CI-PIN" not in err  # an unpinned line still counts as a use of the row


def test_main_root_with_paths_exits_2(tmp_path: Path) -> None:
    assert main(["--root", str(tmp_path), str(tmp_path)]) == 2
