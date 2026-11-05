# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""The sample schema and its two files (the scout's §5): a strict row, a lossless round trip
through Parquet and its JSON Lines twin, 0600 files, and the scrub that refuses a leak."""

from __future__ import annotations

import stat
from pathlib import Path

import pydantic
import pytest

from spike.oms_demo_path.scrub import LeakDetected, Scrubber
from spike.sl_attach.results import JSONL, PARQUET, Sample, read_jsonl, read_parquet, write_samples


def sample(**fields: object) -> Sample:
    base: dict[str, object] = {
        "run_id": "run#1",
        "sample_id": 0,
        "arm": "b",
        "symbol": "BTCUSDT",
        "side": "buy",
        "position_idx": 0,
        "qty": "0.002",
        "order_ref": "link#1",
        "outcome": "ok",
    }
    return Sample.model_validate(base | fields)


def test_a_row_refuses_an_unknown_field_and_an_unknown_arm() -> None:
    with pytest.raises(pydantic.ValidationError):
        sample(order_id="x")
    with pytest.raises(pydantic.ValidationError):
        sample(arm="c")


def test_parquet_and_its_twin_round_trip(tmp_path: Path) -> None:
    rows = [
        sample(
            exposure_ms=138.5,
            exposure_venue_ms=90.0,
            exec_time_ms=1_793_000_000_000,
            ingest_us=1_793_000_000_040_000,
            stage="trading_stop",
            ret_code=0,
            ret_msg_class="ok",
            requests_order_class=1,
            requests_position_class=1,
            taxonomy_divergent=False,
        ),
        sample(
            sample_id=1,
            arm="a",
            outcome="discarded",
            discard_reason="skew",
            skew_ms=501.0,
            retryable=True,
        ),
    ]
    write_samples(tmp_path, rows, Scrubber())
    assert read_parquet(tmp_path) == rows
    assert read_jsonl(tmp_path) == rows
    for name in (PARQUET, JSONL):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600


def test_a_row_carrying_a_registered_value_is_refused_and_nothing_written(tmp_path: Path) -> None:
    scrubber = Scrubber()
    scrubber.secret("a1b2c3d4e5f6-key-id")
    leaky = sample(order_ref="a1b2c3d4e5f6-key-id")
    with pytest.raises(LeakDetected):
        write_samples(tmp_path / "run", [sample(), leaky], scrubber)
    assert not (tmp_path / "run").exists()
