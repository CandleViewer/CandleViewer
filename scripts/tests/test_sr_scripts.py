"""E47-T04: docs-lint for the screen-reader scripts, pins, record template and checklist.

Pure text checks over `docs/qa/a11y/sr/` (G1 to G5 of #1359). It never imports the API package and reads no
network. Cited `file:line` sources must exist and be in range, so a moved builder is caught here.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SR = ROOT / "docs" / "qa" / "a11y" / "sr"
EVID = ROOT / "qa" / "evidence" / "e47" / "sr"
SCRIPTS = sorted((SR / "scripts").glob("[0-9][0-9]-*.md"))
PREFIX = {"XC", "CDC", "FPI", "DOM", "RFE", "RNE", "ORD", "FLT", "LIV", "ADA"}
TEMPLATES = ("_template.md", "_calibration-template.md", "_pass-summary-template.md")
PASS_REF = re.compile(r"pass:[\w.-]+@[0-9a-f]{7,40}")
STOP = {
    "or",
    "the",
    "and",
    "with",
    "then",
    "same",
    "says",
    "not",
    "for",
    "one",
    "each",
    "ends",
    "from",
    "its",
}
HOME_SHAPES = (
    "/home/",
    "/Users/",
    "/root/",
    re.compile(r"[A-Za-z]:[\\/]+(Users|Documents and Settings)[\\/]", re.IGNORECASE),
    re.compile(r"\\\\wsl[.$]", re.IGNORECASE),
    re.compile(
        r"(secret|token|api[_-]?key|password)\s*[:=]\s*[\"']?[A-Za-z0-9+/_-]{16,}", re.IGNORECASE
    ),
)
PF = re.compile(r"\[ \] P / \[ \] F|\[x\] P|\[x\] F")
SRC = re.compile(r"^[\w./-]+\.tsx?:(\d+)$")
HEADER_KEYS = (
    "script_id",
    "title",
    "screens",
    "status",
    "env",
    "fixture",
    "preconditions",
    "last_verified_sha",
    "parents",
    "dry_run",
)


def header(text: str) -> dict:
    m = re.search(r"```yaml\n(.*?)```", text, re.DOTALL)
    assert m, "no YAML header"
    return yaml.safe_load(m.group(1))


def steps(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| ") and re.match(r"^[A-Z]{2,3}-\d\d$", cells[0]):
            rows.append(cells)
    return rows


def anchors(expected: str) -> set[str]:
    """Literal words of the expected text that a cited builder line should carry."""
    words = re.findall(r"[A-Za-z]{3,}", re.sub(r"[{}\[\]]", " ", expected))
    return {w.lower() for w in words if w.lower() not in STOP}


def hits_home_or_secret(text: str) -> bool:
    return any((h in text) if isinstance(h, str) else h.search(text) for h in HOME_SHAPES)


def heuristic_records() -> list[Path]:
    """Evidence records marked `mode: heuristic` in their YAML header, wherever they are named."""
    found = []
    for p in sorted(EVID.glob("**/*.md")):
        text = p.read_text(encoding="utf-8")
        if re.search(r"^mode:\s*heuristic\s*$", text, re.MULTILINE):
            found.append(p)
    return found


def problems(text: str, check_sources: bool = True) -> list[str]:
    out: list[str] = []
    try:
        head = header(text)
    except AssertionError as e:
        return [str(e)]
    for k in HEADER_KEYS:
        if k not in head:
            out.append(f"header lacks {k}")
    if not head.get("preconditions") or not head.get("fixture"):
        out.append("missing preconditions or fixture")
    if head.get("env") != "demo":
        out.append("env must be demo")
    status = str(head.get("status", ""))
    if not status.startswith(("READY", "SURFACE PENDING")):
        out.append("status must start with READY or SURFACE PENDING")
    if head.get("dry_run") not in ("pending", "done"):
        out.append("dry_run must be pending or done")
    if not re.search(r"SCR-\d{3}", " ".join(map(str, head.get("screens", [])))):
        out.append("no screen id")
    rows = steps(text)
    if not rows:
        out.append("no steps")
    seen: set[str] = set()
    for r in rows:
        if len(r) != 8:
            out.append(f"{r[0]}: expected 8 columns")
            continue
        sid, _keys, expected, source, oracle, heur, _lag, pf = r
        if sid in seen:
            out.append(f"duplicate step {sid}")
        seen.add(sid)
        if not expected:
            out.append(f"{sid}: no expected announcement")
        if heur != "heuristic: true":
            out.append(f"{sid}: row must be marked heuristic: true")
        if not oracle:
            out.append(f"{sid}: no oracle")
        elif (oracle == "Source column") != (source != "n/a") or (
            source == "n/a" and not oracle.startswith("05 \u00a7")
        ):
            out.append(f"{sid}: oracle must be Source column or a 05 spec row")
        if not PF.search(pf):
            out.append(f"{sid}: no P/F line")
        m = SRC.match(source)
        if source != "n/a" and not m:
            out.append(f"{sid}: source must be file:line or n/a")
        elif m and check_sources:
            path = ROOT / source.rsplit(":", 1)[0]
            if not path.is_file():
                out.append(f"{sid}: {source} not found")
            else:
                lines = path.read_text(encoding="utf-8").splitlines()
                n = int(m.group(1))
                if n > len(lines):
                    out.append(f"{sid}: {source} out of range")
                elif anchors(expected):
                    window = " ".join(lines[max(0, n - 3) : n + 2]).lower()
                    if not any(a in window for a in anchors(expected)):
                        out.append(f"{sid}: {source} has no anchor token within 2 lines")
        if (
            source == "n/a"
            and "verbatim" not in expected
            and "no scripted text" not in expected
            and "Record" not in expected
        ):
            out.append(f"{sid}: n/a source needs a record-verbatim expectation (never invent copy)")
    return out


def test_scripts_cover_the_ten_surfaces() -> None:
    ids = {header(p.read_text(encoding="utf-8"))["script_id"] for p in SCRIPTS}
    assert ids == PREFIX


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_script_is_usable_by_a_stranger(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert problems(text) == []
    assert all(r[0].startswith(header(text)["script_id"] + "-") for r in steps(text))


@pytest.mark.parametrize(
    "path",
    [p for p in SCRIPTS if p.name[:2] in ("30", "00", "60", "70", "80", "90")],
    ids=lambda p: p.name,
)
def test_environment_badge_is_read_first_and_live_fails(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    first = steps(text)[0]
    assert "Trading environment: Demo" in first[2] and "Live" in first[2]


def test_dom_script_is_demo_only_and_covers_place_cancel_and_readback() -> None:
    text = (SR / "scripts" / "30-dom-ladder.md").read_text(encoding="utf-8")
    assert "NEVER AGAINST LIVE" in text
    rows = {r[0]: r for r in steps(text)}
    assert any("Cancel" in r[1] for r in rows.values())
    assert any("Confirm the DOM-06 order" in r[1] for r in rows.values())
    readback = rows["DOM-06"][2]
    for word in ("buy", "at {price}", "{account}", "{qty}"):
        assert word in readback


def test_record_template_has_all_matrix_rows_signoff_and_pending_approval() -> None:
    text = (SR / "records" / "_template.md").read_text(encoding="utf-8")
    for row in ("NVDA + Electron", "JAWS + Electron", "NVDA + Chromium", "VoiceOver + Electron"):
        assert row in text
    for field in ("build_sha", "os_build", "tester", "approved: pending", "## Sign-off"):
        assert field in text


def test_finding_template_carries_the_routing_fields() -> None:
    text = (SR / "records" / "_template.md").read_text(encoding="utf-8")
    for field in ("at:", "at_version:", "step_id:", "expected:", "routing:", "source: manual"):
        assert field in text


def test_pins_are_dated_owner_owned_and_have_a_next_repin() -> None:
    text = (SR / "regression-checklist.md").read_text(encoding="utf-8")
    assert re.search(r"\| P-\d{4}-\d{2}-\d{2} \|", text)
    assert "OWNER FILL" in text
    assert re.search(r"Next re-pin due \(PROPOSED\):\*\* \d{4}-\d{2}-\d{2}", text)
    assert "Re-pin Chore text" in text
    assert not (SR / "pins.md").exists() and not (SR / "chore-repin-draft.md").exists()


def test_results_live_under_qa_evidence_and_checklist_carries_the_rulings() -> None:
    assert sorted(p.name for p in (SR / "records").glob("*")) == sorted(TEMPLATES)
    assert heuristic_records()
    text = (SR / "regression-checklist.md").read_text(encoding="utf-8")
    for needle in ("Carried rows", "false today", "Deviations (C-4.9)", "scrub checklist"):
        assert needle in text
    for pattern in (
        "apps/web/e2e/**/*screen-reader*",
        "apps/web/e2e/**/*screen_reader*",
        "apps/web/e2e/**/*sr-*",
    ):
        assert not list(ROOT.glob(pattern)), pattern  # no Playwright emulation spec


def test_heuristic_records_are_never_passes() -> None:
    for p in heuristic_records():
        text = p.read_text(encoding="utf-8")
        assert "(heuristic)" in text and "Not a human pass" in text
        assert "approved: pending" in text
        assert "pass:" not in text
        assert not re.search(r"\|\s*P\s*\|", text)


def test_regression_checklist_is_referenced_from_03_and_05() -> None:
    assert "docs/qa/a11y/sr/" in (ROOT / "docs/plan/03-testing-strategy.md").read_text(
        encoding="utf-8"
    )
    assert "docs/qa/a11y/sr/" in (ROOT / "docs/plan/05-accessibility-standard.md").read_text(
        encoding="utf-8"
    )
    assert (SR / "regression-checklist.md").is_file()


def test_no_home_paths_or_secrets_in_the_sr_docs() -> None:
    for p in [*SR.rglob("*.md"), *EVID.rglob("*.md")]:
        assert not hits_home_or_secret(p.read_text(encoding="utf-8")), p


NEW = {"60": "ORD", "70": "FLT", "80": "LIV", "90": "ADA"}
NEW_SCRIPTS = [p for p in SCRIPTS if p.name[:2] in NEW]


def test_new_task_scripts_exist_and_are_surface_pending() -> None:
    assert {p.name[:2] for p in NEW_SCRIPTS} == set(NEW)
    for p in NEW_SCRIPTS:
        text = p.read_text(encoding="utf-8")
        assert header(text)["script_id"] == NEW[p.name[:2]]
        assert str(header(text)["status"]).startswith("SURFACE PENDING")
        assert all("SURFACE PENDING" in r[2] or r[3].endswith(".tsx:47") for r in steps(text))
        assert "NEVER AGAINST LIVE" in text or p.name.startswith("90")


def test_every_new_step_cites_a_screen_and_a_wcag_criterion() -> None:
    for p in NEW_SCRIPTS:
        for r in steps(p.read_text(encoding="utf-8")):
            assert re.match(
                r"^\[SCR-\d{3}( SCR-\d{3})* \u00b7 SC \d\.\d\.\d+( \d\.\d\.\d+)*\]", r[1]
            ), r[0]


def test_order_script_carries_the_streaming_focus_steal_check_and_its_twin() -> None:
    text = (SR / "scripts" / "60-order-ticket.md").read_text(encoding="utf-8")
    rows = {r[0]: r for r in steps(text)}
    assert "P0" in rows["ORD-06"][2] and "focus" in rows["ORD-06"][2].lower()
    assert "SCR-076" in text and "limit" in text.lower()
    assert "E47-TC-205" in text and "E47-Q03" in text


def test_demo_to_live_requires_a_demo_flagged_build_with_a_sandbox_target() -> None:
    text = (SR / "scripts" / "80-demo-to-live.md").read_text(encoding="utf-8")
    pre = " ".join(header(text)["preconditions"])
    assert "demo-flagged" in pre and "sandbox" in pre and "Never Live" in pre


def test_voiceover_launch_flags_are_a_required_record_field() -> None:
    for name in ("_template.md", "_calibration-template.md"):
        head = header((SR / "records" / name).read_text(encoding="utf-8"))
        assert "voiceover_launch_flags" in head
    assert "REQUIRED" in (SR / "records" / "_template.md").read_text(encoding="utf-8")


def test_calibration_template_is_task_3_with_two_independent_testers() -> None:
    text = (SR / "records" / "_calibration-template.md").read_text(encoding="utf-8")
    head = header(text)
    assert head["approved"] == "pending" and "footprint" in head["task"]
    for field in ("tester_a", "tester_b", "resolved_by", "tester_a_ran_independently"):
        assert field in head
    assert "E47-Q01" in text and "Agree" in text


def test_pass_summary_has_the_columns_and_never_a_concrete_pass_ref() -> None:
    text = (SR / "records" / "_pass-summary-template.md").read_text(encoding="utf-8")
    for col in ("Screen", "AT (pinned version)", "Verdict", "Blocking defects", "pass_ref"):
        assert col in text
    assert "pass:<record id>@<sha>" in text and "never written without a human record" in text
    for p in [*SR.rglob("*.md"), *EVID.rglob("*.md")]:
        assert not PASS_REF.search(p.read_text(encoding="utf-8")), p


def test_readme_states_the_split_and_the_results_path() -> None:
    text = (SR / "README.md").read_text(encoding="utf-8")
    assert "qa/evidence/e47/sr/<at>-<date>/" in text and "E47-Q02" in text and "E47-T04" in text


def test_checklist_carries_the_pin_wording_question_and_the_q02_rows() -> None:
    text = (SR / "regression-checklist.md").read_text(encoding="utf-8")
    assert (
        "Pin wording question" in text and "2024.x" in text and "E47-Q02 #1355 human rows" in text
    )
    assert text.count("OWNER FILL") >= 5


GOOD = (SR / "scripts" / "20-footprint-inspection.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda t: t.replace("preconditions:", "pre:"), "lacks preconditions"),
        (lambda t: t.replace("[ ] P / [ ] F", "", 1), "no P/F line"),
        (lambda t: t.replace("| FPI-02 |", "| FPI-01 |"), "duplicate step"),
        (lambda t: t.replace("screens: [SCR-030]", "screens: []"), "no screen id"),
        (lambda t: t.replace("env: demo", "env: live"), "env must be demo"),
        (lambda t: t.replace("| heuristic: true |", "| heuristic: false |", 1), "heuristic: true"),
        (lambda t: t.replace("Source column", "", 1), "no oracle"),
        (lambda t: t.replace("parents:", "kin:"), "lacks parents"),
        (
            lambda t: t.replace("orderflowFormat.ts:63", "orderflowFormat.ts:99999", 1),
            "out of range",
        ),
        (lambda t: t.replace("orderflowFormat.ts:63", "nowhere.ts:1", 1), "not found"),
    ],
)
def test_lint_rejects_a_broken_script(mutate, needle: str) -> None:  # type: ignore[no-untyped-def]
    assert any(needle in p for p in problems(mutate(GOOD)))


def test_lint_rejects_a_step_without_an_expected_announcement() -> None:
    def blank(line: str) -> str:
        if not line.startswith("| FPI-02"):
            return line
        cells = line.split("|")
        cells[3] = " "
        return "|".join(cells)

    bad = "\n".join(blank(line) for line in GOOD.splitlines())
    assert any("FPI-02" in p for p in problems(bad))


def test_lint_rejects_a_cite_with_no_anchor_nearby() -> None:
    far = GOOD.replace("orderflowFormat.ts:63", "orderflowFormat.ts:146", 1)
    assert any("no anchor token" in p for p in problems(far))


def test_heuristic_records_are_found_by_header_not_filename(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "records").mkdir()
    (tmp_path / "records" / "pass-a.md").write_text("mode: heuristic\n", encoding="utf-8")
    (tmp_path / "records" / "2026-heuristic.md").write_text("mode: human\n", encoding="utf-8")
    monkeypatch.setitem(globals(), "EVID", tmp_path)
    assert [p.name for p in heuristic_records()] == ["pass-a.md"]


def test_no_playwright_sr_spec_guard_covers_every_glob(tmp_path: Path) -> None:
    spec = tmp_path / "apps" / "web" / "e2e" / "a11y" / "nvda-screen_reader.spec.ts"
    spec.parent.mkdir(parents=True)
    spec.write_text("", encoding="utf-8")
    assert list(tmp_path.glob("apps/web/e2e/**/*screen_reader*"))


@pytest.mark.parametrize(
    "bad",
    [
        "see /home/someone/x",
        "see /Users/someone/x",
        "see C:\\Users\\someone\\x",
        "see c:/users/someone/x",
        "see \\\\wsl$\\Ubuntu\\x",
        "api" + "_key = " + "x" * 20,
    ],
)
def test_home_and_secret_scan_catches_every_shape(bad: str) -> None:
    assert hits_home_or_secret(bad)
    assert not hits_home_or_secret("plain text, no paths")
