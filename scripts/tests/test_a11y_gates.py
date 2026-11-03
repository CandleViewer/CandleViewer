"""Meta-tests for tools/a11y/gates.py (E47-T02): injected defect fails, clean passes."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.a11y import gates

ROOT = Path(__file__).resolve().parents[2]


def _report(impact: str = "serious") -> dict:
    return {
        "screens": {
            "SCR-060": {
                "violations": [
                    {
                        "id": "color-contrast",
                        "impact": impact,
                        "nodes": [{"target": ["#buy"]}],
                    }
                ]
            }
        }
    }


def test_axe_new_serious_violation_names_screen_rule_node() -> None:
    msgs = gates.check_axe(_report(), {"entries": []})
    assert len(msgs) == 1
    assert "SCR-060" in msgs[0] and "color-contrast" in msgs[0] and "#buy" in msgs[0]


def test_axe_moderate_ignored_and_baselined_allowed() -> None:
    assert gates.check_axe(_report("moderate"), {"entries": []}) == []
    base = {
        "entries": [
            {"fingerprint": "SCR-060|color-contrast|#buy", "finding": "A11Y-F001"}
        ]
    }
    assert gates.check_axe(_report(), base) == []


def test_baseline_entry_without_finding_id_is_rejected() -> None:
    assert gates.check_baseline_entries({"entries": [{"fingerprint": "x"}]})
    assert not gates.check_baseline_entries(
        {"entries": [{"fingerprint": "x", "finding": "A11Y-F2"}]}
    )


def test_lighthouse_below_floor_is_violation_but_missing_is_infra() -> None:
    assert gates.check_lighthouse({"SCR-020": 0.97}) == []
    assert "SCR-063" in gates.check_lighthouse({"SCR-063": 0.9})[0]
    with pytest.raises(gates.InfraError):
        gates.check_lighthouse({})
    with pytest.raises(gates.InfraError):
        gates.check_lighthouse({"SCR-020": None})


def test_flash_five_hz_fails_and_names_component() -> None:
    fps = 30
    strobe = [1.0 if (i // 3) % 2 == 0 else 0.0 for i in range(fps)]  # 5 Hz
    calm = [0.5] * fps
    msgs = gates.check_flash(
        {"fps": fps, "components": {"heatmap": calm, "bubbles": strobe}}
    )
    assert len(msgs) == 1 and "bubbles" in msgs[0]


def test_flash_five_hz_message_names_component_and_rate() -> None:
    fps = 60
    strobe = [1.0 if (i // 6) % 2 == 0 else 0.0 for i in range(fps)]  # 5 Hz
    rate = gates.count_flashes(strobe, fps)
    assert rate >= 3
    msg = gates.check_flash({"fps": fps, "components": {"liquidation-flash": strobe}})[
        0
    ]
    assert "component=liquidation-flash" in msg and f"{rate} flashes/s" in msg


def test_flash_two_per_second_passes_with_margin() -> None:
    fps = 60  # a 100 ms flash every 500 ms: the coalescer's worst case
    lum = [1.0 if i % 30 < 6 else 0.0 for i in range(fps * 3)]
    assert gates.count_flashes(lum, fps) == 2
    assert gates.check_flash({"fps": fps, "components": {"c": lum}}) == []


def test_flash_table_lists_rate_limit_and_result() -> None:
    fps = 60
    strobe = [1.0 if (i // 6) % 2 == 0 else 0.0 for i in range(fps)]
    table = gates.flash_table(
        {"fps": fps, "components": {"b": strobe, "a": [0.5] * fps}}
    )
    assert table.splitlines() == [
        "| component | max flashes/s | limit | result |",
        "|---|---|---|---|",
        "| a | 0 | < 3 | pass |",
        f"| b | {gates.count_flashes(strobe, fps)} | < 3 | FAIL |",
    ]


def test_flash_cli_table_flag_prints_table(tmp_path, capsys) -> None:
    cap = tmp_path / "c.json"
    cap.write_text('{"fps": 60, "components": {"a": [0.5, 0.5]}}')
    assert gates.main(["flash", str(cap), "--table"]) == 0
    assert "| a | 0 | < 3 | pass |" in capsys.readouterr().out


def test_flash_empty_capture_is_infra() -> None:
    with pytest.raises(gates.InfraError):
        gates.check_flash({"fps": 30, "components": {}})


def test_keyboard_trap_and_mouse_events_fail() -> None:
    ok = {"mouseEvents": 0, "steps": [{"name": "submit order", "ok": True}]}
    assert gates.check_keyboard(ok) == []
    bad = {"mouseEvents": 2, "steps": [{"name": "switch symbol", "ok": False}]}
    assert len(gates.check_keyboard(bad)) == 2


def test_keyboard_gate_names_screens_with_mouse_events() -> None:
    steps = [{"name": "SCR-020 tab-traversal-no-trap", "ok": True}]
    bad = {
        "mouseEvents": 3,
        "perScreen": {"SCR-010": 0, "SCR-020": 3},
        "steps": steps,
    }
    msgs = gates.check_keyboard(bad)
    assert len(msgs) == 1
    assert "SCR-020" in msgs[0] and "SCR-010" not in msgs[0]


def test_keyboard_collector_counts_clicks_not_mousemove() -> None:
    # A synthetic click (even untrusted, e.g. Radix .click()) must still count; a
    # browser-synthesised mousemove must not (#2063).
    src = (ROOT / "apps/web/e2e/a11y/keyboard.collect.ts").read_text(encoding="utf-8")
    assert '["mousedown", "mouseup", "click"]' in src
    assert "mousemove" not in src.replace("mousemove is", "").split("addInitScript")[
        1
    ].split("const steps")[0].replace("browser-synthesised mousemove", "")
    assert "isTrusted" not in src


def test_tree_snapshot_diff_reports_change(tmp_path: Path) -> None:
    snap, act = tmp_path / "s", tmp_path / "a"
    snap.mkdir()
    act.mkdir()
    (snap / "SCR-020.txt").write_text("main\n  heading 'Chart'\n", encoding="utf-8")
    (act / "SCR-020.txt").write_text("main\n", encoding="utf-8")
    msgs = gates.check_tree(str(snap), str(act))
    assert "SCR-020" in msgs[0] and "heading" in msgs[0]
    (act / "SCR-020.txt").write_text("main\n  heading 'Chart'\n", encoding="utf-8")
    assert gates.check_tree(str(snap), str(act)) == []


def test_cli_exit_codes_distinguish_violation_from_infra(tmp_path: Path) -> None:
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps(_report()), encoding="utf-8")
    base = tmp_path / "b.json"
    base.write_text('{"entries": []}', encoding="utf-8")
    assert (
        gates.main(["axe", str(rep), "--baseline", str(base)]) == gates.EXIT_VIOLATION
    )
    assert (
        gates.main(["axe", str(tmp_path / "nope.json"), "--baseline", str(base)])
        == gates.EXIT_INFRA
    )
    rep.write_text(json.dumps({"screens": {}}), encoding="utf-8")
    assert gates.main(["axe", str(rep), "--baseline", str(base)]) == gates.EXIT_OK


def test_break_glass_waives_infra_only_and_is_time_limited() -> None:
    now = dt.datetime(2026, 10, 4, tzinfo=dt.timezone.utc)
    soon = (now + dt.timedelta(hours=2)).isoformat()
    far = (now + dt.timedelta(days=3)).isoformat()
    assert gates.infra_waiver_active({"CV_A11Y_INFRA_WAIVER_UNTIL": soon}, now)
    assert not gates.infra_waiver_active({"CV_A11Y_INFRA_WAIVER_UNTIL": far}, now)
    assert not gates.infra_waiver_active({}, now)


def test_waiver_does_not_hide_violation(tmp_path: Path, monkeypatch) -> None:
    until = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
    monkeypatch.setenv("CV_A11Y_INFRA_WAIVER_UNTIL", until)
    rep, base = tmp_path / "r.json", tmp_path / "b.json"
    rep.write_text(json.dumps(_report()), encoding="utf-8")
    base.write_text('{"entries": []}', encoding="utf-8")
    assert (
        gates.main(["axe", str(rep), "--baseline", str(base)]) == gates.EXIT_VIOLATION
    )
    assert (
        gates.main(["axe", str(tmp_path / "x.json"), "--baseline", str(base)])
        == gates.EXIT_OK
    )


def test_runtime_budget_over_limit_fails() -> None:
    assert gates.check_budget(600, 720) == []
    assert "A11Y-G007" in gates.check_budget(721, 720)[0]


def test_missing_collector_output_is_infra_not_green(tmp_path: Path) -> None:
    """A collector that produced nothing must exit 3, never pass vacuously."""
    missing = str(tmp_path / "axe.json")
    assert gates.main(["axe", missing]) == gates.EXIT_INFRA
    assert gates.main(["keyboard", missing]) == gates.EXIT_INFRA
    assert gates.main(["tree", "--snapshots", str(tmp_path), str(tmp_path / "t")]) == (
        gates.EXIT_INFRA
    )


def test_baseline_change_requires_finding_id_in_pr_body() -> None:
    base = {"entries": []}
    head = {"entries": [{"fingerprint": "fp1", "finding": "A11Y-F012"}]}
    assert gates.check_baseline_pr_ids(base, head, "no id here")
    assert not gates.check_baseline_pr_ids(base, head, "Justified by A11Y-F012")
    assert not gates.check_baseline_pr_ids(head, head, "")


def test_flash_high_rate_strobe_trips_and_calm_canvas_passes() -> None:
    strobe = [
        0.0 if (i // 4) % 2 == 0 else 1.0 for i in range(360)
    ]  # 60 Hz sampling, ~7.5 Hz strobe
    assert gates.check_flash({"fps": 60, "components": {"canvas:strobe": strobe}})
    calm = [0.05 + 0.01 * ((i * 7) % 5) for i in range(360)]
    assert gates.check_flash({"fps": 60, "components": {"canvas:heatmap": calm}}) == []


def _pulses(
    per_second: int, fps: int = 60, seconds: int = 3, width: int = 6
) -> list[float]:
    """Dark field with `per_second` evenly spaced 100 ms bright pulses."""
    period = fps // per_second
    return [1.0 if i % period < width else 0.0 for i in range(fps * seconds)]


@pytest.mark.parametrize(("per_second", "expected"), [(2, 2), (3, 3), (4, 4)])
def test_flash_counts_each_pulse_as_one_flash(per_second: int, expected: int) -> None:
    assert gates.count_flashes(_pulses(per_second), 60) == expected


def test_flash_three_pulses_per_second_fails_the_gate() -> None:
    assert gates.check_flash({"fps": 60, "components": {"price-flash": _pulses(3)}})


def test_flash_two_pulses_per_second_passes_the_gate() -> None:
    assert (
        gates.check_flash({"fps": 60, "components": {"price-flash": _pulses(2)}}) == []
    )


def test_flash_series_starting_bright_counts_the_first_fall() -> None:
    # Bright at frame 0, so the first qualifying change is a fall; 3 pulses still fail.
    series = [1.0 if i % 20 < 6 else 0.0 for i in range(180)]
    assert gates.count_flashes(series, 60) == 3


def test_flash_cli_table_flag_keeps_the_failing_exit(tmp_path) -> None:
    cap = tmp_path / "f.json"
    cap.write_text(json.dumps({"fps": 60, "components": {"x": _pulses(4)}}))
    assert gates.main(["flash", str(cap), "--table"]) == 1


def test_flash_first_change_of_a_capture_counts() -> None:
    # One second, dark at frame 0, three pulses: the window must include the very first
    # rise. Counting reversals only (dropping the first change) scored this 2 and passed.
    series = [1.0 if (i % 20) in range(10, 16) else 0.0 for i in range(60)]
    assert gates.count_flashes(series, 60) == 3
    assert gates.check_flash({"fps": 60, "components": {"price-flash": series}})


def test_flash_rise_then_fall_counts_exactly_one() -> None:
    assert gates.count_flashes([0.0] * 5 + [1.0] * 5 + [0.0] * 5, 60) == 1


def test_flash_rise_fall_rise_counts_one_and_ignores_the_dangling_half() -> None:
    assert gates.count_flashes([0.0] * 5 + [1.0] * 5 + [0.0] * 5 + [1.0] * 5, 60) == 1


def test_flash_window_slides_across_a_wall_second_boundary() -> None:
    # Three pulses straddling frame 60: wall-second buckets would split them 1 + 2 and pass.
    series = [0.0] * 120
    for start in (40, 60, 80):
        series[start : start + 6] = [1.0] * 6
    assert gates.count_flashes(series, 60) == 3


# --- E47-Q04: moderate/minor baseline, schema, expiry, Lighthouse metadata -------------

NOW = dt.datetime(2026, 11, 3, 12, tzinfo=dt.timezone.utc)


def _entry(**kw: str) -> dict:
    base = {
        "fingerprint": "region|main > div",
        "finding": "A11Y-F-0007",
        "justification": "the third-party widget renders this label; fix ships with the vendor bump",
        "owner": "alice",
        "ticket": "#1400",
        "target": "2026-12-01",
        "expiry": "2026-12-15",
    }
    return {**base, **kw}


def test_moderate_above_baseline_fails_and_baselined_passes() -> None:
    rep = _report("moderate")
    msgs = gates.check_axe_minor(rep, {"minor_entries": []})
    assert len(msgs) == 1 and "color-contrast" in msgs[0] and "#buy" in msgs[0]
    base = {"minor_entries": [_entry(fingerprint="color-contrast|#buy")]}
    assert gates.check_axe_minor(rep, base) == []
    assert gates.check_axe_minor(_report("serious"), {}) == []  # serious is G001 proper


def test_minor_key_ignores_react_use_id_segments() -> None:
    rep = {"screens": {"S": {"violations": [{"id": "label", "impact": "minor", "nodes": [{"target": ["#:r1a:"]}]}]}}}
    assert "label|#:r*:" in gates.axe_minor_fingerprints(rep)
    rep["screens"]["S"]["violations"][0]["nodes"][0]["target"] = ["#:r9z:"]
    assert gates.check_axe_minor(rep, {"minor_entries": [_entry(fingerprint="label|#:r*:")]}) == []


def test_expired_suppression_fails_naming_owner_and_ticket() -> None:
    for section in ("entries", "minor_entries", "pa11y_entries"):
        msgs = gates.check_baseline_schema({section: [_entry(expiry="2026-11-02")]}, NOW)
        assert len(msgs) == 1, section
        assert "expired" in msgs[0] and "owner=alice" in msgs[0] and "ticket=#1400" in msgs[0]


def test_baseline_entry_valid_through_its_expiry_day() -> None:
    assert gates.check_baseline_schema({"entries": [_entry(expiry="2026-11-03", target="2026-11-03")]}, NOW) == []


@pytest.mark.parametrize("field", ["justification", "owner", "ticket", "target", "expiry"])
def test_baseline_entry_missing_schema_field_fails(field: str) -> None:
    msgs = gates.check_baseline_schema({"minor_entries": [_entry(**{field: ""})]}, NOW)
    assert msgs and field in msgs[0]


def test_baseline_entry_bad_date_and_target_after_expiry_fail() -> None:
    assert "invalid date" in gates.check_baseline_schema({"entries": [_entry(expiry="soon")]}, NOW)[0]
    assert "after its expiry" in gates.check_baseline_schema(
        {"entries": [_entry(target="2027-01-01")]}, NOW
    )[0]


def test_baseline_pr_ids_cover_every_section() -> None:
    head = {
        "entries": [_entry(fingerprint="a|b|c")],
        "minor_entries": [_entry()],
        "pa11y_entries": [_entry(fingerprint="x|y")],
    }
    assert len(gates.check_baseline_pr_ids({}, head, "no id")) == 3
    assert not gates.check_baseline_pr_ids({}, head, "A11Y-F-0007")


def test_repo_baseline_has_every_section_and_passes_its_own_schema() -> None:
    base = json.loads((ROOT / "tools/a11y/axe-baseline.json").read_text(encoding="utf-8"))
    assert base["schemaVersion"] == 2
    assert all(isinstance(base[s], list) for s in gates.BASELINE_SECTIONS)
    assert gates.check_baseline_schema(base, NOW) == []


def test_lighthouse_new_shape_pending_passes_and_low_score_fails() -> None:
    doc = {
        "lighthouse": "12.2.1",
        "chromium": "141.0.0.0",
        "runnerClass": "github-hosted Ubuntu24 1 X64",
        "scores": {"SCR-001": 0.98},
        "pending": {"SCR-030": "pending E11 (epic) #38"},
    }
    assert gates.check_lighthouse(doc) == []
    line = gates.lighthouse_line(doc)
    assert "141.0.0.0" in line and "github-hosted" in line and "1 pending" in line
    doc["scores"]["SCR-001"] = 0.9
    assert "SCR-001" in gates.check_lighthouse(doc)[0]
    with pytest.raises(gates.InfraError):
        gates.check_lighthouse({"scores": {}, "pending": {"SCR-030": "x"}})


def test_cli_axe_fails_on_expired_entry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rep, base = tmp_path / "axe.json", tmp_path / "b.json"
    rep.write_text(json.dumps({"screens": {}}), encoding="utf-8")
    base.write_text(json.dumps({"minor_entries": [_entry(expiry="2020-01-01", target="2020-01-01")]}), encoding="utf-8")
    assert gates.main(["axe", str(rep), "--baseline", str(base)]) == 1
    assert "owner=alice" in capsys.readouterr().out


def test_baseline_expiry_beyond_the_ninety_day_horizon_fails() -> None:
    ok = _entry(expiry="2027-02-01", target="2027-01-01")  # 90 days from 2026-11-03
    assert gates.check_baseline_schema({"minor_entries": [ok]}, NOW) == []
    far = _entry(expiry="2027-02-02", target="2027-01-01")
    msgs = gates.check_baseline_schema({"minor_entries": [far]}, NOW)
    assert len(msgs) == 1 and "90 days" in msgs[0] and "owner=alice" in msgs[0]


def test_minor_entry_needs_an_a11y_f_finding_id() -> None:
    msgs = gates.check_baseline_schema({"minor_entries": [_entry(finding="BUG-7")]}, NOW)
    assert len(msgs) == 1 and "finding id" in msgs[0]


# --- pa11y-ci (A11Y-G009): real output shapes --------------------------------------------------

URL = "http://127.0.0.1:4173/login"
CFG = {"urls": [{"url": URL, "_route": "R-001"}]}


def _p11(*issues: dict, url: str = URL) -> dict:
    return {"total": 1, "passes": 0, "errors": len(issues), "results": {url: list(issues)}}


ERR = {"code": "WCAG2AA.Principle1.Guideline1_4.1_4_3.G18", "type": "error", "typeCode": 1,
       "message": "contrast", "context": "<a>", "selector": "html > body > a", "runner": "htmlcs"}


def test_pa11y_error_fails_naming_url_code_and_node() -> None:
    msgs = gates.check_pa11y(_p11(ERR), {}, CFG)
    assert len(msgs) == 1 and "A11Y-G009" in msgs[0]
    assert URL in msgs[0] and "1_4_3" in msgs[0] and "html > body > a" in msgs[0]


def test_pa11y_notice_warning_and_clean_pass_and_baselined_error_passes() -> None:
    assert gates.check_pa11y(_p11({**ERR, "type": "notice"}, {**ERR, "type": "warning"}), {}, CFG) == []
    assert gates.check_pa11y(_p11(), {}, CFG) == []
    fp = f"{ERR['code']}|html > body > a"
    assert gates.check_pa11y(_p11(ERR), {"pa11y_entries": [_entry(fingerprint=fp)]}, CFG) == []


def test_pa11y_unscannable_page_in_its_real_shape_is_infra_not_a_pass() -> None:
    # pa11y-ci reports a page it could not load as [{"message": "..."}]: no type, no code
    broken = {"results": {URL: [{"message": "Failed to launch the browser process"}]}}
    with pytest.raises(gates.InfraError, match="could not scan"):
        gates.check_pa11y(broken, {}, CFG)


@pytest.mark.parametrize("issue", [{"message": "x", "type": "error"}, {"code": "C", "message": "x"}, "oops"])
def test_pa11y_issue_without_type_or_code_is_infra(issue: object) -> None:
    with pytest.raises(gates.InfraError):
        gates.check_pa11y({"results": {URL: [issue]}}, {}, CFG)


def test_pa11y_empty_results_or_missing_configured_url_is_infra() -> None:
    for res in ({}, {"results": {}}, {"results": None}):
        with pytest.raises(gates.InfraError, match="no results"):
            gates.check_pa11y(res, {}, CFG)
    with pytest.raises(gates.InfraError, match="no result for"):
        gates.check_pa11y(_p11(url="http://127.0.0.1:4173/other"), {}, CFG)
    with pytest.raises(gates.InfraError):
        gates.check_pa11y({"results": {URL: "Error: net::ERR_CONNECTION_REFUSED"}}, {}, CFG)


def test_cli_pa11y_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg, bad, ok = tmp_path / "cfg.json", tmp_path / "bad.json", tmp_path / "ok.json"
    cfg.write_text(json.dumps(CFG), encoding="utf-8")
    bad.write_text(json.dumps(_p11(ERR)), encoding="utf-8")
    ok.write_text(json.dumps(_p11()), encoding="utf-8")
    base = ["--config", str(cfg)]
    assert gates.main(["pa11y", str(ok), *base]) == 0
    assert gates.main(["pa11y", str(bad), *base]) == 1
    assert gates.main(["pa11y", str(tmp_path / "absent.json"), *base]) == 3


def test_pa11y_gate_lines_neutralise_control_characters_from_the_page() -> None:
    payload = "x\n::add-mask::topsecret\r::error::boom\x00"
    evil = {**ERR, "code": f"C{payload}", "selector": f"#a{payload}"}
    msgs = gates.check_pa11y(_p11(evil, url=f"{URL}{payload}"), {}, {"urls": []})
    assert len(msgs) == 1
    assert not any(c in msgs[0] for c in "\n\r\x00") and "\n::" not in msgs[0]
    broken = {"results": {URL: [{"message": f"boom{payload}"}]}}
    with pytest.raises(gates.InfraError) as exc:
        gates.check_pa11y(broken, {}, CFG)
    assert "\n" not in str(exc.value) and "\r" not in str(exc.value)
