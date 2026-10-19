"""The report: the budget #4 decision at its boundary, and the leak check every output passes
before it is written (the summary goes on a public issue, C-12.2)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from candleviewer.secrets import Secret
from spikes.oms_demo_path.report import budget_4, build_report, write_outputs
from spikes.oms_demo_path.runner import COMPLETED, Config, Harness
from spikes.oms_demo_path.safety import EnvCredentials
from spikes.oms_demo_path.scrub import MASK

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
