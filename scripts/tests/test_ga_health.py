"""E49-Q01 (#1335): tools/ga/specs.py (the pack's tag reader) and tools/ga/health.py (the pack's
own health check: tags, quarantine owners and deadlines, egress imports)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ga import health, specs

TODAY = date(2026, 11, 1)
WEB = "apps/web/e2e/x.spec.ts"


def _one(source: str, path: str = WEB, lane: str = "web-chromium") -> specs.SpecTest:
    (test,) = specs.scan_source(source, path, lane)
    return test


def test_scan_reads_title_tags_through_a_semicolon_in_the_title() -> None:
    t = _one(
        'test("a; b @ga-regression @ga-area-admin @story-US-ONB-001", async ({ page }) => {});'
    )
    assert t.in_pack and t.areas == ("admin",) and t.stories == ("US-ONB-001",)
    assert t.line == 1 and t.modifier is None and not t.stub


def test_scan_reads_a_named_tag_const_and_template_titles() -> None:
    source = (
        'const GA = { tag: ["@ga-regression", "@ga-area-shell"] };\n'
        "for (const r of R)\n"
        "  test(`@plan-X ${r.id} @story-US-SET-002`, GA, async () => {});\n"
    )
    t = _one(source)
    assert t.tags == ("@ga-area-shell", "@ga-regression", "@plan-X", "@story-US-SET-002")
    assert t.line == 3


def test_scan_marks_fixme_stubs_and_ignores_other_test_calls() -> None:
    source = (
        'test.fixme("stub @ga-regression @ga-area-replay @story-US-RPL-001", () => {});\n'
        'test.describe("group @ga-regression", () => {});\n'
        "expect(/x/u.test('y')).toBe(true);\n"
        "test.skip(process.env.X === undefined);\n"
        'import { test } from "./fixtures";\n'
    )
    (t,) = specs.scan_source(source, WEB, "web-chromium")
    assert t.stub and t.modifier == "fixme" and t.stories == ("US-RPL-001",)


def test_pack_files_lists_runnable_pack_files_relative_to_the_package() -> None:
    tests = [
        specs.SpecTest("web-chromium", "apps/web/e2e/a.spec.ts", 1, ("@ga-regression",), None),
        specs.SpecTest("web-chromium", "apps/web/e2e/b.spec.ts", 1, ("@ga-regression",), "fixme"),
        specs.SpecTest("web-chromium", "apps/web/e2e/c.spec.ts", 1, (), None),
        specs.SpecTest("electron", "apps/desktop/e2e/d.spec.ts", 1, ("@ga-regression",), None),
    ]
    assert specs.pack_files(tests, "web-chromium") == ["e2e/a.spec.ts"]
    assert specs.pack_files(tests, "electron") == ["e2e/d.spec.ts"]


def test_must_stories_count_must_and_must_should_headings() -> None:
    must = specs.must_stories(ROOT)
    assert len(must) == 184  # `^#### US-.* · Must` in 11-user-stories.md on 2026-11-01
    assert "US-ALRT-005" in must  # a `Must/Should` heading


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ("@ga-regression @ga-area-admin", []),
        ("@ga-regression", ["exactly one @ga-area"]),
        ("@ga-regression @ga-area-admin @ga-area-shell", ["exactly one @ga-area"]),
        ("@ga-regression @ga-area-nowhere", ["exactly one @ga-area"]),
        ("@ga-regression @ga-area-admin @story-US-NOPE-001", ["not a story"]),
        ("@ga-area-admin", ["without @ga-regression"]),
        ("@story-US-ONB-001", ["without @ga-regression"]),
    ],
)
def test_tag_findings(tags: str, expected: list[str]) -> None:
    t = _one(f'test("t {tags}", async () => {{}});')
    found = health.tag_findings([t], set(specs.stories(ROOT)))
    assert len(found) == len(expected)
    for f, e in zip(found, expected, strict=True):
        assert e in f


def test_tag_findings_refuse_test_only_in_the_pack() -> None:
    t = _one('test.only("t @ga-regression @ga-area-admin", async () => {});')
    assert any("test.only" in f for f in health.tag_findings([t], set()))


@pytest.mark.parametrize(
    ("extra", "needle"),
    [
        ("@ticket-4242 @owner-ann @until-2026-11-15", None),
        ("@ticket-4242 @owner-ann @until-2026-11-01", None),  # the last day is still in time
        ("@ticket-4242 @until-2026-11-10", "@owner-"),
        ("@ticket-4242 @owner-ann", "@until-"),
        ("@ticket-4242 @owner-ann @until-2026-13-40", "@until-"),
        ("@ticket-4242 @owner-ann @until-2026-10-31", "has passed"),
        ("@ticket-4242 @owner-ann @until-2026-11-16", "more than 14 days"),
        ("@ticket-4242 @owner-ann @owner-bob @until-2026-11-10", "@owner-"),
        # C-9.3: a quarantine carries its P1 ticket (as the toolchain pack's @flaky does).
        ("@owner-ann @until-2026-11-10", "@ticket-"),
        ("@ticket-abc @owner-ann @until-2026-11-10", "@ticket-"),
    ],
)
def test_a_quarantined_pack_test_needs_an_owner_and_a_near_deadline(
    extra: str, needle: str | None
) -> None:
    t = _one(f'test("t @ga-regression @ga-area-admin @flaky {extra}", async () => {{}});')
    found = health.quarantine_findings([t], TODAY)
    assert (found == []) if needle is None else (len(found) == 1 and needle in found[0])


def test_quarantine_rule_ignores_tests_outside_the_pack() -> None:
    t = _one('test("t @flaky", async () => {});')
    assert health.quarantine_findings([t], TODAY) == []


def _write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("rel", "imports", "ok"),
    [
        ("apps/web/e2e/auth/a.spec.ts", 'import { expect, test } from "../ga/fixtures";', True),
        ("apps/web/e2e/b.spec.ts", 'import { test } from "./ga/fixtures";', True),
        (
            "apps/web/e2e/auth/g.spec.ts",
            'import { expect, packTest as test } from "../ga/fixtures";',
            True,
        ),
        ("apps/web/e2e/ga/c.spec.ts", 'import { badge, test } from "./fixtures";', True),
        ("apps/web/e2e/d.spec.ts", 'import { test, expect } from "@playwright/test";', False),
        ("apps/web/e2e/shell/e.spec.ts", 'import { test } from "./fixtures";', False),
        (
            "apps/web/e2e/f.spec.ts",
            'import { type Page } from "@playwright/test";\n'
            'import { expect, test } from "./ga/fixtures";',
            True,
        ),
    ],
)
def test_a_web_pack_spec_takes_test_from_the_guarded_pack_fixture(
    tmp_path: Path, rel: str, imports: str, ok: bool
) -> None:
    _write(
        tmp_path, rel, f'{imports}\ntest("t @ga-regression @ga-area-admin", async () => {{}});\n'
    )
    tests = specs.scan_source((tmp_path / rel).read_text(), rel, "web-chromium")
    assert (health.egress_findings(tests, tmp_path) == []) is ok


@pytest.mark.parametrize(
    ("imports", "ok"),
    [
        (
            'import { test } from "@playwright/test";\n'
            'import { launchShell } from "./support/shell";',
            True,
        ),
        ('import { _electron as electron, test } from "@playwright/test";', False),
        (
            'import { _electron, test } from "@playwright/test";\n'
            'import { launchShell } from "./support/shell";',
            False,
        ),
    ],
)
def test_an_electron_pack_spec_launches_through_the_guarded_shell(
    tmp_path: Path, imports: str, ok: bool
) -> None:
    rel = "apps/desktop/e2e/x.spec.ts"
    _write(
        tmp_path, rel, f'{imports}\ntest("t @ga-regression @ga-area-shell", async () => {{}});\n'
    )
    tests = specs.scan_source((tmp_path / rel).read_text(), rel, "electron")
    assert (health.egress_findings(tests, tmp_path) == []) is ok


def test_a_file_of_fixme_stubs_only_is_exempt_from_the_egress_import_rule(tmp_path: Path) -> None:
    rel = "apps/desktop/e2e/stubs.spec.ts"
    _write(
        tmp_path,
        rel,
        'import { test } from "@playwright/test";\n'
        'test.fixme("s @ga-regression @ga-area-shell", () => {});\n',
    )
    tests = specs.scan_source((tmp_path / rel).read_text(), rel, "electron")
    assert health.egress_findings(tests, tmp_path) == []


def test_the_repository_pack_is_healthy() -> None:
    assert health.run(ROOT, TODAY) == []


def test_the_repository_pack_spans_both_lanes_and_names_only_known_areas() -> None:
    pack = [t for t in specs.scan(ROOT) if t.in_pack]
    assert {t.lane for t in pack if not t.stub} == {"web-chromium", "electron"}
    assert {a for t in pack for a in t.areas} <= set(specs.AREAS)
    # Every ticket area has at least a carried stub, so it shows in the nightly report.
    assert {a for t in pack for a in t.areas} == set(specs.AREAS)


def test_health_cli_prints_a_summary_and_exits_zero_on_the_repository(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert health.main(["--today", TODAY.isoformat()]) == 0
    assert "ga-regression health:" in capsys.readouterr().out


def test_pack_tags_on_a_describe_title_are_a_finding(tmp_path: Path) -> None:
    rel = "apps/web/e2e/d.spec.ts"
    _write(
        tmp_path,
        rel,
        'test.describe("group @ga-regression @story-US-ONB-001", () => {\n'
        '  test("t", async () => {});\n'
        "});\n"
        'test.describe.serial("plain @plan-X", () => {});\n',
    )
    (found,) = health.describe_findings(tmp_path)
    assert found.startswith(f"{rel}:1:") and "@ga-regression @story-US-ONB-001" in found
    assert specs.describe_tags("test.describe(`ok ${x}`, () => {});") == []


def test_notes_flag_a_provisional_budget_and_unaccepted_gaps(
    capsys: pytest.CaptureFixture[str],
) -> None:
    notes = health.notes(ROOT)
    assert any(n.startswith("electron:") and "provisional" in n for n in notes)
    assert any("pending owner risk acceptance" in n for n in notes)
    assert health.main(["--today", TODAY.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "::warning title=ga-regression health::coverage:" in out


def test_require_accepted_turns_pending_gaps_into_findings() -> None:
    found = health.run(ROOT, TODAY, require_accepted=True)
    assert found and all(f.endswith("gap pending owner acceptance") for f in found)
    assert health.main(["--today", TODAY.isoformat(), "--require-accepted"]) == 1
