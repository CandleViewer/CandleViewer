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
