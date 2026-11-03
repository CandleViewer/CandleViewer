"""Meta-tests for tools/a11y/motion_audit.py (E47-Q05): known-bad fails, known-good passes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.a11y import motion_audit as ma
from tools.a11y.gates import InfraError

RECT = [0, 0, 341, 256]
VIEWPORT = [1280, 800]


def _capture(**lum: list[float]) -> dict:
    return {
        "fps": 60,
        "viewport": VIEWPORT,
        "regions": {k: {"rect": RECT, "luminance": v} for k, v in lum.items()},
    }


def _fixtures(**extra: list[float]) -> dict:
    base = {
        "synthetic-6hz": ma.synthetic_luminance(6),
        "synthetic-1hz": ma.synthetic_luminance(1),
    }
    return _capture(**base, **extra)


def _row(rows: list[dict], surface: str) -> dict:
    return next(r for r in rows if r["surface"] == surface)


def test_synthetic_six_hz_component_is_measured_and_fails() -> None:
    rows, _ = ma.audit(_fixtures())
    bad = _row(rows, "synthetic-6hz")
    assert bad["measured"] == 6 and bad["result"] == "FAIL (fixture)"


def test_synthetic_one_hz_component_is_measured_and_passes() -> None:
    rows, violations = ma.audit(_fixtures())
    good = _row(rows, "synthetic-1hz")
    assert good["measured"] == 1 and good["result"] == "pass (fixture)"
    assert violations == []  # the intended fixture failure is not a product violation


def test_fixture_that_reads_the_wrong_verdict_is_infra() -> None:
    cap = _fixtures()
    cap["regions"]["synthetic-6hz"]["luminance"] = ma.synthetic_luminance(1)
    with pytest.raises(InfraError, match="synthetic-6hz read pass, expected FAIL"):
        ma.audit(cap)


def test_region_over_the_budget_but_under_g005_still_violates() -> None:
    # 3 pulses per second is G005's trip line; the surface budget (2) is one tighter than WCAG.
    three = ma.synthetic_luminance(3)
    rows, violations = ma.audit(_fixtures(**{"alert-toast": three}))
    assert _row(rows, "alert-toast")["measured"] == 3
    assert len(violations) == 1 and "surface=alert-toast" in violations[0]


def test_region_at_the_budget_passes_and_records_the_rate() -> None:
    rows, violations = ma.audit(_fixtures(**{"alert-toast": ma.synthetic_luminance(2)}))
    assert violations == []
    assert _row(rows, "alert-toast")["measured"] == 2


def test_unbuilt_surface_is_a_pending_row_naming_its_ticket() -> None:
    rows, _ = ma.audit(_fixtures())
    row = _row(rows, "big-trade-bubbles")
    assert row["measured"] is None and row["result"] == "pending E22-S01 #714 (MX-12, MX-14)"
    assert "#5440" in _row(rows, "price-flash-positions")["result"]


def test_built_surface_without_a_capture_is_infra(monkeypatch: pytest.MonkeyPatch) -> None:
    built = ma.Surface("heatmap-live-cell", "SCR-050", 2, "built", "")
    monkeypatch.setattr(ma, "SURFACES", (built, *ma.SURFACES[1:]))
    with pytest.raises(InfraError, match="built surface heatmap-live-cell"):
        ma.audit(_fixtures())


def test_whole_viewport_region_is_rejected() -> None:
    cap = _fixtures()
    cap["regions"]["synthetic-1hz"]["rect"] = [0, 0, 1280, 800]
    with pytest.raises(InfraError, match="whole viewport"):
        ma.audit(cap)


@pytest.mark.parametrize("rect", [None, [0, 0], [0, 0, 0, 10]])
def test_region_without_a_declared_rect_is_infra(rect: object) -> None:
    cap = _fixtures()
    cap["regions"]["synthetic-1hz"]["rect"] = rect
    with pytest.raises(InfraError, match="declared rect"):
        ma.audit(cap)


def test_unregistered_region_and_empty_capture_are_infra() -> None:
    with pytest.raises(InfraError, match="not a registered surface"):
        ma.audit(_capture(mystery=[0.0, 1.0]))
    with pytest.raises(InfraError, match="empty"):
        ma.audit({"fps": 60, "regions": {}})


def test_table_lists_measured_rate_budget_and_result() -> None:
    rows, _ = ma.audit(_fixtures())
    out = ma.table(rows)
    assert "| synthetic-6hz | - | 6 | <= 2 | FAIL (fixture) |" in out
    assert "| alert-toast | SCR-092 | - | <= 2 | pending E40-S02 #1130 |" in out


SAFE = {"running_animations": 4, "script_ms": 120.0, "paint_ms": 80.0, "raf_callbacks": 300}


def test_reduced_motion_that_removes_work_passes() -> None:
    reduced = {"running_animations": 0, "script_ms": 20.0, "paint_ms": 10.0, "raf_callbacks": 30}
    assert ma.check_reduced_work(SAFE, reduced) == []


def test_opacity_only_mutation_with_the_loop_still_running_fails() -> None:
    # Visuals constant, but the animation and its rAF loop still execute: the work is not gone.
    mutated = dict(SAFE)
    msgs = ma.check_reduced_work(SAFE, mutated)
    assert any("running animations" in m for m in msgs)
    assert sum("reduced" in m for m in msgs) == 4  # animations plus all three work keys


def test_running_animation_alone_fails_even_when_work_is_low() -> None:
    reduced = {"running_animations": 1, "script_ms": 1.0, "paint_ms": 1.0, "raf_callbacks": 1}
    assert len(ma.check_reduced_work(SAFE, reduced)) == 1


def test_work_exactly_at_the_fraction_passes_and_just_over_fails() -> None:
    at = {"running_animations": 0, "script_ms": 60.0, "paint_ms": 40.0, "raf_callbacks": 150}
    assert ma.check_reduced_work(SAFE, at) == []
    assert len(ma.check_reduced_work(SAFE, {**at, "script_ms": 60.1})) == 1


def test_vacuous_motion_safe_profile_is_infra() -> None:
    with pytest.raises(InfraError, match="no animation work"):
        ma.check_reduced_work({**SAFE, "running_animations": 0}, {})


def test_cli_flash_prints_table_and_exits_by_verdict(tmp_path: Path, capsys) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_fixtures()))
    assert ma.main(["flash", str(good)]) == 0
    assert "| synthetic-6hz |" in capsys.readouterr().out
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_fixtures(**{"alert-toast": ma.synthetic_luminance(6)})))
    assert ma.main(["flash", str(bad)]) == 1
    assert ma.main(["flash", str(tmp_path / "missing.json")]) == 3


def test_cli_reduce_exit_codes(tmp_path: Path) -> None:
    ok = tmp_path / "ok.json"
    ok.write_text(
        json.dumps(
            {
                "safe": SAFE,
                "reduced": {
                    **SAFE,
                    "running_animations": 0,
                    "script_ms": 1,
                    "paint_ms": 1,
                    "raf_callbacks": 1,
                },
            }
        )
    )
    assert ma.main(["reduce", str(ok)]) == 0
    ko = tmp_path / "ko.json"
    ko.write_text(json.dumps({"safe": SAFE, "reduced": SAFE}))
    assert ma.main(["reduce", str(ko)]) == 1
