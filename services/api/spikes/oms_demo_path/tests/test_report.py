"""The report: the budget #4 decision at its boundary, the leak check every output passes before
it is written (the summary goes on a public issue, C-12.2), and how a REST backfill that failed
reads where an empty listing would read zero."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from candleviewer.secrets import Secret
from spikes.oms_demo_path.report import budget_4, build_report, render, write_outputs
from spikes.oms_demo_path.runner import COMPLETED, Config, Harness
from spikes.oms_demo_path.safety import EnvCredentials
from spikes.oms_demo_path.scrub import MASK
from spikes.oms_demo_path.stats import RestExecution

#: Key-shaped values, derived at run time (no secret-shaped literal in the source).
KEY_ID = "k" + hashlib.sha256(b"report key id").hexdigest()[:19]
UNKNOWN = "k" + hashlib.sha256(b"an unknown key-shaped value").hexdigest()[:19]


@pytest.mark.parametrize(
    ("p95", "within", "headroom"),
    [(120.0, True, 180.0), (250.0, True, 50.0), (250.1, False, 49.9), (300.0, False, 0.0)],
)
def test_budget_4_holds_up_to_250_ms_and_leaves_the_rest_of_300_to_the_backend(
    p95: float, within: bool, headroom: float
) -> None:
    assert budget_4(p95) == {
        "create_rtt_p95_ms": p95,
        "within_allocation": within,
        "backend_headroom_ms": headroom,
    }


def test_budget_4_gives_no_verdict_without_creates() -> None:
    assert set(budget_4(None).values()) == {None}


def _harness(tmp_path: Path) -> Harness:
    cfg = Config(
        mode="orders", symbol="ETHUSDT", out=tmp_path / "run", staging=tmp_path / "s", hours=1.0
    )
    return Harness(cfg, EnvCredentials(Secret(KEY_ID), Secret("XXXXXXXXXX")))


async def test_outputs_mask_a_known_value(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    h.notes["probe"] = f"echo [{KEY_ID}]"
    write_outputs(h, build_report(h, {}, COMPLETED), {})
    await h.client.aclose()
    summary = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary["notes"]["probe"] == f"echo [{MASK}]"
    assert KEY_ID not in (tmp_path / "run" / "summary.md").read_text(encoding="utf-8")


async def test_an_output_still_failing_the_leak_check_is_withheld(tmp_path: Path) -> None:
    h = _harness(tmp_path)
    h.notes["probe"] = f"echo [{UNKNOWN}]"
    write_outputs(h, build_report(h, {}, COMPLETED), {})
    await h.client.aclose()
    for name in ("summary.json", "summary.md"):
        text = (tmp_path / "run" / name).read_text(encoding="utf-8")
        assert text == "withheld by the leak check: key-shape\n"
    assert UNKNOWN not in "".join(
        p.read_text(encoding="utf-8") for p in (tmp_path / "run").iterdir()
    )


def _parity_row(summary: str) -> str:
    """The `execution` row of the parity table (other tables have one too)."""
    section = summary.split("## Execution parity")[1].split("## Ordering")[0]
    return next(line for line in section.splitlines() if line.startswith("| execution |"))


async def _summary(h: Harness, rest: dict[str, RestExecution]) -> tuple[dict[str, Any], str]:
    report = build_report(h, rest, COMPLETED)
    await h.client.aclose()
    report |= {"fixtures": [], "ws_capture_withheld": False}  # what `write_outputs` adds
    return report, render(report)


async def test_a_listed_backfill_is_counted_in_the_summary(tmp_path: Path) -> None:
    _, summary = await _summary(_harness(tmp_path), {"e1": RestExecution("Trade", 1_000)})
    assert "the REST backfill listed 1" in summary and "FAILED" not in summary
    assert _parity_row(summary).endswith("| {'Trade': 1} | 0 | 1 | 0 |")


async def test_an_empty_listing_that_succeeded_reads_zero(tmp_path: Path) -> None:
    report, summary = await _summary(_harness(tmp_path), {})
    assert (report["rest_executions"], report["rest_backfill_error"]) == (0, None)
    assert _parity_row(summary).endswith("| 0 | 0 | 0 | 0 |")


async def test_a_failed_backfill_reads_n_a_where_an_empty_listing_would_read_zero(
    tmp_path: Path,
) -> None:
    h = _harness(tmp_path)
    h.backfill_error = "retCode None: TransportError (TRANSPORT_ERROR)"
    report, summary = await _summary(h, {})
    assert (report["rest_executions"], report["rest_backfill_error"]) == (None, h.backfill_error)
    assert f"the REST backfill FAILED ({h.backfill_error})" in summary
    assert "the #843 AC2 number is missing" in summary
    assert _parity_row(summary).endswith("| n/a | n/a | n/a | n/a |")
